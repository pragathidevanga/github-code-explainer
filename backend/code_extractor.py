"""Prioritize and safely extract bounded source context without executing files."""

from __future__ import annotations

from pathlib import Path

from backend.file_inspector import (
    CONFIGURATION_NAMES,
    CONFIGURATION_EXTENSIONS,
    DATA_SCHEMA_EXTENSIONS,
    DOCUMENTATION_EXTENSIONS,
    DOCUMENTATION_NAMES,
    FileInspection,
    NOTEBOOK_EXTENSIONS,
    classify_file,
    inspect_file,
    iter_repository_files,
)
from backend.utils import SOURCE_EXTENSIONS, env_int

IMPORTANT_DIRS = {"src", "app", "backend", "frontend", "routes", "controllers", "services", "models", "components"}


class ExtractionResult:
    def __init__(
        self,
        context: str,
        analyzed_paths: list[str],
        skipped_files: int,
        context_size: int,
        inspections: dict[str, FileInspection],
    ):
        self.context = context
        self.analyzed_paths = analyzed_paths
        self.skipped_files = skipped_files
        self.context_size = context_size
        self.inspections = inspections


def _is_candidate(path: Path) -> bool:
    file_type, _, is_binary = classify_file(path)
    return not is_binary and file_type != "Unreadable"


def _priority(relative: Path) -> tuple[int, str]:
    name = relative.name.lower()
    parts = {part.lower() for part in relative.parts[:-1]}
    if name in DOCUMENTATION_NAMES or name.startswith("readme"):
        score = 0
    elif name in CONFIGURATION_NAMES or relative.suffix.lower() in CONFIGURATION_EXTENSIONS:
        score = 1
    elif name.startswith(("main.", "app.", "server.", "index.")) or name == "manage.py":
        score = 2
    elif relative.suffix.lower() in SOURCE_EXTENSIONS and parts & IMPORTANT_DIRS:
        score = 3
    elif relative.suffix.lower() in SOURCE_EXTENSIONS:
        score = 4
    elif relative.suffix.lower() in NOTEBOOK_EXTENSIONS:
        score = 5
    elif relative.suffix.lower() in DATA_SCHEMA_EXTENSIONS:
        score = 6
    elif relative.suffix.lower() in DOCUMENTATION_EXTENSIONS:
        score = 7
    else:
        score = 8
    if any(part in {"test", "tests", "__tests__"} for part in parts):
        score += 2
    return score, relative.as_posix().lower()


def extract_code(root: Path) -> ExtractionResult:
    """Collect prioritized text with per-file and total character limits."""
    max_files = env_int("MAX_FILES", 80)
    max_file_size = env_int("MAX_FILE_SIZE", 100_000)
    max_total_context = env_int("MAX_TOTAL_CONTEXT", 300_000)
    root = root.resolve()
    candidates: list[Path] = []
    for path in iter_repository_files(root):
        try:
            if path.stat().st_size > 0 and _is_candidate(path):
                candidates.append(path)
        except OSError:
            continue

    candidates.sort(key=lambda path: _priority(path.relative_to(root)))
    selected = candidates[:max_files]
    omitted = len(candidates) - len(selected)
    chunks: list[str] = []
    analyzed_paths: list[str] = []
    inspections: dict[str, FileInspection] = {}
    used = 0

    for path in selected:
        relative = path.relative_to(root).as_posix()
        try:
            inspected = inspect_file(path, max_file_size)
        except (OSError, UnicodeError):
            omitted += 1
            continue
        if inspected.is_binary or not inspected.content:
            omitted += 1
            continue
        text = inspected.content[:max_file_size]
        remaining = max_total_context - used
        if remaining <= 0:
            omitted += len(selected) - len(analyzed_paths)
            break
        header = f"\n--- {relative} [{inspected.file_type}; {inspected.language}] ---\n"
        content_budget = remaining - len(header)
        if content_budget <= 0:
            omitted += 1
            continue
        marker = "\n[File truncated because it exceeds analysis limit]"
        truncated = len(inspected.content) > max_file_size or len(text) > content_budget
        if truncated:
            if content_budget < len(marker):
                omitted += 1
                continue
            text = text[:content_budget - len(marker)] + marker
        chunk = header + text
        chunks.append(chunk)
        used += len(chunk)
        analyzed_paths.append(relative)
        inspections[relative] = inspected
        if used >= max_total_context:
            break

    omitted = max(omitted, len(candidates) - len(analyzed_paths))
    return ExtractionResult("".join(chunks), analyzed_paths, omitted, used, inspections)
