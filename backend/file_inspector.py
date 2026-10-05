"""Classify repository files and safely extract bounded readable evidence."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from backend.utils import BINARY_EXTENSIONS, IGNORED_DIRS, SOURCE_EXTENSIONS, env_int, language_for_path

NOTEBOOK_EXTENSIONS = {".ipynb"}
DOCUMENTATION_EXTENSIONS = {".adoc", ".markdown", ".md", ".rst"}
CONFIGURATION_EXTENSIONS = {".cfg", ".conf", ".ini", ".properties", ".toml", ".yaml", ".yml"}
DATA_SCHEMA_EXTENSIONS = {
    ".avro", ".csv", ".dbml", ".dtd", ".gql", ".graphql", ".jsonl",
    ".json", ".ndjson", ".parquet", ".proto", ".prisma", ".tsv", ".xml", ".xsd",
}
DEPLOYMENT_NAMES = {
    "docker-compose.yaml", "docker-compose.yml", "dockerfile", "makefile",
    "procfile", "vercel.json", "netlify.toml",
}
DEPLOYMENT_DIRS = {"deploy", "deployment", "deployments", "helm", "k8s", "kubernetes", "manifests"}
CONFIGURATION_NAMES = {
    ".dockerignore", ".editorconfig", ".env", ".env.example", ".gitignore",
    "appsettings.json", "config.json", "settings.json", "angular.json",
    "build.gradle", "cargo.toml", "docker-compose.yml",
    "dockerfile", "go.mod", "package-lock.json", "package.json", "pipfile",
    "pom.xml", "pyproject.toml", "requirements.txt", "tsconfig.json",
    "vite.config.js", "vite.config.ts", "next.config.js",
}
DOCUMENTATION_NAMES = {
    "readme", "readme.md", "readme.rst", "readme.txt", "contributing.md",
    "changelog.md", "license", "license.md", "license.txt",
}
TEXT_MAGIC_PREFIXES = (
    b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a",
    b"RIFF", b"PK\x03\x04", b"\x1f\x8b", b"%PDF-", b"MZ",
    b"\x7fELF", b"SQLite format 3\x00", b"\xd0\xcf\x11\xe0",
)
TRUNCATION_MARKER = "[File truncated because it exceeds analysis limit]"
SENSITIVE_KEY_PATTERN = (
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"password|passwd|secret(?:[_-]?key)?|private[_-]?key"
)
QUOTED_SECRET = re.compile(
    rf"""(?im)(["']?(?:{SENSITIVE_KEY_PATTERN})["']?\s*[:=]\s*)(["'])([^"'\r\n]{{8,}})(\2)"""
)
UNQUOTED_SECRET = re.compile(
    rf"(?im)(\b(?:{SENSITIVE_KEY_PATTERN})\b\s*[:=]\s*)([A-Za-z0-9_./+=-]{{20,}})"
)
BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{12,}")


@dataclass(frozen=True)
class FileInspection:
    file_type: str
    language: str
    is_binary: bool
    content: str
    analysis_content: str
    note: str = ""
    notebook_code_cells: int = 0
    notebook_markdown_cells: int = 0


def is_sensitive_file(path: Path) -> bool:
    """Identify common secret/config credential files by name before reading their contents."""
    name = path.name.lower()
    if name in {".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json", "service-account.json"}:
        return name not in {".env.example", ".env.sample", ".env.template"}
    if name.startswith(".env.") and name not in {".env.example", ".env.sample", ".env.template"}:
        return True
    return any(term in name for term in ("secret", "credential", "private_key"))


def _redact_secrets(text: str) -> tuple[str, bool]:
    """Redact common literal secret assignments before text is stored in LLM context."""
    redacted = QUOTED_SECRET.sub(r"\1\2[REDACTED]\4", text)
    redacted = UNQUOTED_SECRET.sub(r"\1[REDACTED]", redacted)
    redacted = BEARER_TOKEN.sub(r"\1[REDACTED]", redacted)
    return redacted, redacted != text


def iter_repository_files(root: Path):
    """Yield regular files beneath root, pruning ignored directories and symlinks."""
    root = root.resolve()
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in IGNORED_DIRS and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                continue
            try:
                resolved = path.resolve()
                if root not in resolved.parents or not path.is_file():
                    continue
            except OSError:
                continue
            yield path


def _looks_binary(sample: bytes, suffix: str) -> bool:
    if suffix in BINARY_EXTENSIONS:
        return True
    if not sample:
        return False
    if any(sample.startswith(signature) for signature in TEXT_MAGIC_PREFIXES):
        return True
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    if b"\x00" in sample:
        return True
    try:
        decoded = sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            decoded = sample.decode("cp1252")
        except UnicodeDecodeError:
            return True
    controls = sum(
        ord(char) < 32 and char not in "\t\n\r\f\b"
        for char in decoded
    )
    return controls / max(len(decoded), 1) > 0.02


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _classify_text(path: Path) -> tuple[str, str]:
    name = path.name.lower()
    suffix = path.suffix.lower()
    path_parts = {part.lower() for part in path.parts[:-1]}
    if name in DEPLOYMENT_NAMES or path_parts & DEPLOYMENT_DIRS:
        return "Deployment", "Deployment configuration"
    if suffix == ".html":
        return "Markup", "HTML"
    if suffix in {".css", ".scss"}:
        return "Stylesheet", "Stylesheet"
    if suffix in SOURCE_EXTENSIONS:
        if suffix == ".sql" and ({"schema", "schemas", "migrations", "data"} & path_parts):
            return "Data / schema", "SQL schema / data"
        return "Source code", _language(path)
    if suffix in NOTEBOOK_EXTENSIONS:
        return "Jupyter notebook", "Notebook language from metadata"
    if (
        name in CONFIGURATION_NAMES
        or name.startswith(".env.")
        or name.startswith("requirements")
        or suffix in CONFIGURATION_EXTENSIONS
    ):
        return "Configuration", "Configuration / data format"
    if suffix in DOCUMENTATION_EXTENSIONS or name in DOCUMENTATION_NAMES:
        return "Documentation", "Documentation"
    if suffix in DATA_SCHEMA_EXTENSIONS or suffix in {".json", ".xml"}:
        return "Data / schema", "Structured data / schema"
    if "docs" in path_parts or "documentation" in path_parts:
        return "Documentation", "Documentation"
    return "Other readable text", "Text"


def _language(path: Path) -> str:
    return language_for_path(path)


def classify_file(path: Path) -> tuple[str, str, bool]:
    """Classify a file using its name, extension, and a small binary-detection sample."""
    if is_sensitive_file(path):
        file_type, language = _classify_text(path)
        return file_type, language, False
    try:
        with path.open("rb") as source:
            sample = source.read(8192)
    except OSError:
        return "Unreadable", "Unknown", False
    if _looks_binary(sample, path.suffix.lower()):
        return "Binary", "Binary", True
    file_type, language = _classify_text(path)
    return file_type, language, False


def _notebook_inspection(path: Path, max_chars: int) -> FileInspection:
    read_limit = env_int("MAX_NOTEBOOK_SIZE", 10_000_000)
    try:
        with path.open("rb") as source:
            data = source.read(read_limit + 1)
    except OSError:
        return FileInspection("Jupyter notebook", "Unknown", False, "", "", "Notebook could not be read.")
    if len(data) > read_limit:
        message = f"Notebook exceeds the {read_limit:,}-byte notebook parsing limit; cell content was not extracted."
        return FileInspection("Jupyter notebook", "Unknown", False, message, message, message)
    try:
        notebook = json.loads(_decode_text(data))
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        message = "Notebook is not valid readable Jupyter JSON; cell content could not be extracted."
        return FileInspection("Jupyter notebook", "Unknown", False, message, message, message)
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        message = "Notebook has no valid cells collection."
        return FileInspection("Jupyter notebook", "Unknown", False, message, message, message)

    metadata = notebook.get("metadata", {})
    kernelspec = metadata.get("kernelspec", {}) if isinstance(metadata, dict) else {}
    language = (
        (metadata.get("language_info", {}) or {}).get("name")
        if isinstance(metadata, dict) and isinstance(metadata.get("language_info", {}), dict)
        else None
    )
    if not language and isinstance(kernelspec, dict):
        language = kernelspec.get("language") or kernelspec.get("name")
    language = str(language or "Not specified in notebook metadata")

    code_sections: list[str] = []
    code_sources: list[str] = []
    markdown_sections: list[str] = []
    cell_sections: list[str] = []
    for index, cell in enumerate(notebook["cells"][:500], start=1):
        if not isinstance(cell, dict):
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(item for item in source if isinstance(item, str))
        if not isinstance(source, str) or not source.strip():
            continue
        cell_type = cell.get("cell_type")
        if cell_type == "code":
            section = f"[CODE CELL {index}]\n{source}"
            code_sections.append(section)
            code_sources.append(source)
        elif cell_type == "markdown":
            section = f"[MARKDOWN CELL {index}]\n{source}"
            markdown_sections.append(section)
        else:
            continue
        cell_sections.append(section)

    intro = (
        f"Jupyter notebook. Kernel language: {language}. "
        f"Code cells: {len(code_sections)}. Markdown cells: {len(markdown_sections)}. "
        "Stored cell outputs are intentionally excluded."
    )
    combined = "\n\n".join([intro, *cell_sections])
    truncated = len(combined) > max_chars
    if truncated:
        combined = combined[:max_chars]
        if max_chars >= len(TRUNCATION_MARKER):
            combined = combined[:-len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    note = "Notebook cell outputs and execution metadata were not included."
    if len(notebook["cells"]) > 500:
        note += " Only the first 500 cells were inspected."
    combined, content_redacted = _redact_secrets(combined)
    analysis_content, analysis_redacted = _redact_secrets("\n\n".join(code_sources)[:max_chars])
    if content_redacted or analysis_redacted:
        note += " Common literal secrets were redacted."
    return FileInspection(
        "Jupyter notebook",
        language,
        False,
        combined,
        analysis_content,
        note,
        len(code_sections),
        len(markdown_sections),
    )


def inspect_file(path: Path, max_chars: int | None = None) -> FileInspection:
    """Read bounded text evidence; notebook outputs and binary bytes are never sent to the LLM."""
    character_limit = max_chars or env_int("MAX_FILE_SIZE", 100_000)
    file_type, language, is_binary = classify_file(path)
    if is_binary:
        return FileInspection(file_type, language, True, "", "")
    if is_sensitive_file(path):
        message = "Sensitive file identified by filename; contents were withheld from analysis."
        return FileInspection(file_type, language, False, message, "", message)
    if path.suffix.lower() in NOTEBOOK_EXTENSIONS:
        return _notebook_inspection(path, character_limit)
    byte_limit = character_limit * 4 + 4
    try:
        with path.open("rb") as source:
            data = source.read(byte_limit + 1)
    except OSError:
        return FileInspection("Unreadable", "Unknown", False, "", "", "File could not be read as text.")
    if _looks_binary(data[:8192], path.suffix.lower()):
        return FileInspection("Binary", "Binary", True, "", "")
    truncated = len(data) > byte_limit
    text = _decode_text(data[:byte_limit])
    if len(text) > character_limit:
        text = text[:character_limit]
        truncated = True
    if truncated and len(text) >= len(TRUNCATION_MARKER):
        text = text[:-len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    text, redacted = _redact_secrets(text)
    note = "Common literal secrets were redacted." if redacted else ""
    return FileInspection(file_type, language, False, text, text, note)
