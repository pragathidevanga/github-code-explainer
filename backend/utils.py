"""Validation, path-safety, and shared configuration helpers."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

IGNORED_DIRS = {
    ".git", ".github", "node_modules", "__pycache__", ".venv", "venv",
    "env", "dist", "build", "coverage", ".idea", ".vscode", ".pytest_cache",
    ".tox", ".mypy_cache", ".ruff_cache", "target",
}
BINARY_EXTENSIONS = {
    ".3gp", ".7z", ".aac", ".avi", ".bin", ".bmp", ".bz2", ".class",
    ".dll", ".dylib", ".eot", ".exe", ".flac", ".gif", ".gz", ".ico",
    ".jar", ".jpeg", ".jpg", ".lockb", ".m4a", ".mkv", ".mov", ".mp3",
    ".mp4", ".mpeg", ".mpg", ".o", ".obj", ".pdf", ".png", ".rar",
    ".p12", ".pfx", ".pem", ".key", ".so", ".tar", ".tif", ".tiff",
    ".ttf", ".wav", ".webm", ".webp",
    ".woff", ".woff2", ".xz", ".zip",
}
IGNORED_EXTENSIONS = BINARY_EXTENSIONS
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".go", ".rs", ".php", ".rb", ".kt", ".swift",
    ".html", ".css", ".scss", ".sql", ".sh",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript (JSX)",
    ".mjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript (TSX)",
    ".java": "Java", ".c": "C", ".h": "C/C++ header", ".cpp": "C++",
    ".hpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".php": "PHP",
    ".rb": "Ruby", ".kt": "Kotlin", ".swift": "Swift", ".html": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sql": "SQL", ".sh": "Shell",
}


class InvalidGitHubURL(ValueError):
    """Raised when an input is not a supported public GitHub URL."""


def canonicalize_github_url(value: str) -> tuple[str, str, str]:
    """Return canonical HTTPS URL, owner, and repository name."""
    candidate = value.strip()
    try:
        parsed = urlparse(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise InvalidGitHubURL("The GitHub URL is malformed.") from exc
    if (
        parsed.scheme.lower() != "https"
        or hostname is None
        or hostname.lower() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise InvalidGitHubURL("Enter a public repository URL on https://github.com.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise InvalidGitHubURL("Use a repository URL such as https://github.com/owner/repository.")
    owner, repository = parts
    if repository.lower().endswith(".git"):
        repository = repository[:-4]
    if not owner or owner in {".", ".."} or not repository or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner):
        raise InvalidGitHubURL("The GitHub owner or repository name is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", repository) or repository in {".", ".."}:
        raise InvalidGitHubURL("The GitHub owner or repository name is invalid.")

    return f"https://github.com/{owner}/{repository}.git", owner, repository


def safe_child_path(parent: Path, child: Path) -> Path:
    """Resolve a child and ensure it remains inside the expected directory."""
    resolved_parent = parent.resolve()
    resolved_child = child.resolve()
    if resolved_child == resolved_parent or resolved_parent not in resolved_child.parents:
        raise ValueError("Resolved path is outside the repository directory.")
    return resolved_child


def repository_cache_path(owner: str, repository: str) -> Path:
    """Build a stable, filesystem-safe cache path for a validated repository."""
    cache_root = (PROJECT_ROOT / "repositories").resolve()
    slug = re.sub(r"[^A-Za-z0-9_.-]", "-", f"{owner}-{repository}").strip(".-")
    digest = hashlib.sha256(f"{owner}/{repository}".lower().encode("utf-8")).hexdigest()[:12]
    path = cache_root / f"{slug[:80]}-{digest}"
    safe_child_path(cache_root, path)
    return path


def env_int(name: str, default: int, minimum: int = 1) -> int:
    """Read a positive integer from the environment with explicit validation."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def language_for_path(path: str | Path) -> str:
    """Return the detected language or a descriptive fallback."""
    return LANGUAGE_BY_EXTENSION.get(Path(path).suffix.lower(), "Other")
