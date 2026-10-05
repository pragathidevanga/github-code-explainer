"""Safe public GitHub repository cloning and cache management."""

from __future__ import annotations

import os
import re
import shutil
import threading
from pathlib import Path

from git import GitCommandError, Repo
from git.exc import InvalidGitRepositoryError

from backend.utils import (
    IGNORED_DIRS,
    PROJECT_ROOT,
    canonicalize_github_url,
    env_int,
    repository_cache_path,
    safe_child_path,
)


class RepositoryError(RuntimeError):
    """Base exception for repository processing failures."""


class CloneError(RepositoryError):
    """Raised when the public repository cannot be cloned."""


class RepositoryTooLarge(RepositoryError):
    """Raised when a cloned repository exceeds the configured size limit."""


class EmptyRepository(RepositoryError):
    """Raised when a repository contains no files to analyze."""


class GitHubProcessor:
    """Clone repositories into a local cache; never execute repository files."""

    def __init__(self) -> None:
        self._cache_lock = threading.Lock()

    def clone_repository(self, github_url: str) -> tuple[Path, str, str]:
        canonical_url, owner, repository = canonicalize_github_url(github_url)
        with self._cache_lock:
            return self._clone_validated(canonical_url, owner, repository)

    def _clone_validated(self, canonical_url: str, owner: str, repository: str) -> tuple[Path, str, str]:
        destination = repository_cache_path(owner, repository)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            try:
                cached = Repo(destination)
                origin = cached.remotes.origin.url
                if origin.rstrip("/").removesuffix(".git").lower() == canonical_url.rstrip("/").removesuffix(".git").lower():
                    try:
                        self._materialize_repository_files(cached, destination)
                    finally:
                        cached.close()
                    self._check_repository_size(destination)
                    self._check_nonempty(destination)
                    return destination, repository, canonical_url
                cached.close()
            except (GitCommandError, InvalidGitRepositoryError, AttributeError, OSError):
                pass
            raise CloneError("A cached repository could not be verified. Remove its cache folder and retry.")

        try:
            cloned = Repo.clone_from(
                canonical_url,
                destination,
                depth=1,
                no_checkout=True,
            )
            self._materialize_repository_files(cloned, destination)
            cloned.close()
        except GitCommandError as exc:
            self._remove_partial_clone(destination)
            message = str(exc).lower()
            if "not found" in message or "repository not found" in message:
                raise CloneError("The repository was not found or is not publicly accessible.") from exc
            if "timed out" in message or "timeout" in message:
                raise CloneError("Cloning timed out. Check your network and try again.") from exc
            raise CloneError("Unable to clone the public repository. Check the URL and network connection.") from exc
        except (OSError, ValueError) as exc:
            self._remove_partial_clone(destination)
            raise CloneError("Unable to clone the public repository. Check the URL and network connection.") from exc

        try:
            self._check_repository_size(destination)
            self._check_nonempty(destination)
        except RepositoryError:
            self._remove_partial_clone(destination)
            raise
        except ValueError:
            self._remove_partial_clone(destination)
            raise
        except OSError as exc:
            self._remove_partial_clone(destination)
            raise CloneError("Unable to inspect the cloned repository in the local cache.") from exc
        return destination, repository, canonical_url

    @staticmethod
    def _is_portable_git_path(path: str) -> bool:
        """Reject paths unsafe or unrepresentable on Windows before materializing blobs."""
        parts = path.split("/")
        if not parts or any(
            not part
            or part in {".", ".."}
            or any(ord(character) < 32 or character in '<>:"\\|?*' for character in part)
            or part.endswith((" ", "."))
            or re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.IGNORECASE)
            for part in parts
        ):
            return False
        return not any(part.lower() in IGNORED_DIRS for part in parts[:-1])

    @classmethod
    def _materialize_repository_files(cls, repository: Repo, destination: Path) -> int:
        """Write safe committed blobs into the worktree without invoking checkout filters."""
        if not repository.head.is_valid():
            return 0
        try:
            commit = repository.head.commit
            entries = [
                item for item in commit.tree.traverse()
                if item.type == "blob"
                and item.mode != 0o120000
                and cls._is_portable_git_path(item.path)
            ]
        except (GitCommandError, ValueError, IndexError) as exc:
            raise CloneError("The repository's committed file tree could not be inspected.") from exc

        maximum_bytes = env_int("MAX_REPOSITORY_SIZE_MB", 500) * 1024 * 1024
        if sum(item.size for item in entries) > maximum_bytes:
            raise RepositoryTooLarge(
                f"Repository exceeds the configured {maximum_bytes // (1024 * 1024)} MB analysis size limit."
            )

        cache_root = (PROJECT_ROOT / "repositories").resolve()
        safe_child_path(cache_root, destination)
        if destination.is_symlink():
            raise CloneError("The repository cache path must not be a symbolic link.")
        root = destination.resolve()
        written = 0
        for item in entries:
            target = root.joinpath(*item.path.split("/"))
            current = root
            safe = True
            for part in item.path.split("/")[:-1]:
                current = current / part
                if current.exists() and (current.is_symlink() or not current.is_dir()):
                    safe = False
                    break
                current.mkdir(exist_ok=True)
            if not safe or (target.exists() and (target.is_symlink() or not target.is_file())):
                continue
            try:
                safe_child_path(root, target)
                with target.open("wb") as destination_file:
                    shutil.copyfileobj(item.data_stream, destination_file, length=64 * 1024)
            except (OSError, ValueError):
                continue
            written += 1
        return written

    @staticmethod
    def _remove_partial_clone(path: Path) -> None:
        if not path.exists():
            return
        cache_root = (PROJECT_ROOT / "repositories").resolve()
        safe_child_path(cache_root, path)
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise CloneError(
                "An incomplete repository cache could not be removed. Close programs using the cache folder and retry."
            ) from exc

    @staticmethod
    def _check_nonempty(repository_path: Path) -> None:
        from backend.file_inspector import classify_file, iter_repository_files

        for path in iter_repository_files(repository_path):
            file_type, _, _ = classify_file(path)
            if file_type != "Unreadable":
                return
        raise EmptyRepository(
            "The public repository contains no files available for analysis after excluding unusable or generated content."
        )

    @staticmethod
    def _check_repository_size(repository_path: Path) -> None:
        maximum_mb = env_int("MAX_REPOSITORY_SIZE_MB", 500)
        total_bytes = 0
        for current, directories, filenames in os.walk(repository_path, followlinks=False):
            directories[:] = [name for name in directories if name != ".git"]
            for filename in filenames:
                file_path = Path(current) / filename
                if file_path.is_symlink():
                    continue
                try:
                    total_bytes += file_path.stat().st_size
                except OSError:
                    continue
                if total_bytes > maximum_mb * 1024 * 1024:
                    raise RepositoryTooLarge(
                        f"Repository exceeds the configured {maximum_mb} MB analysis size limit."
                    )


_processor = GitHubProcessor()


def clone_repository(github_url: str) -> tuple[Path, str, str]:
    """Module-level entry point used by the API and tests."""
    if not (PROJECT_ROOT / "repositories").exists():
        (PROJECT_ROOT / "repositories").mkdir(parents=True, exist_ok=True)
    return _processor.clone_repository(github_url)
