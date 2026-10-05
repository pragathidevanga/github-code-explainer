"""Repository inventory, tree generation, and static file metadata extraction."""

from __future__ import annotations

import ast
import os
import re
from collections import Counter
from pathlib import Path

from backend.code_extractor import _priority
from backend.file_inspector import (
    CONFIGURATION_NAMES,
    DOCUMENTATION_NAMES,
    classify_file,
    inspect_file,
    is_sensitive_file,
    iter_repository_files,
)
from backend.models import FileAnalysis
from backend.utils import IGNORED_DIRS, SOURCE_EXTENSIONS, env_int, language_for_path

DOC_NAMES = DOCUMENTATION_NAMES
CONFIG_NAMES = CONFIGURATION_NAMES
ENTRY_NAMES = {"main.py", "app.py", "server.py", "manage.py", "main.js", "main.ts", "index.js", "index.ts", "index.jsx", "index.tsx"}
IMPORTANT_FOLDER_NAMES = {
    "src", "app", "apps", "backend", "frontend", "routes", "controllers",
    "services", "models", "components", "pages", "views", "hooks", "utils",
    "config", "test", "tests", "__tests__",
}


def _walk(root: Path):
    yield from iter_repository_files(root)


def _tree(root: Path, files: list[Path], max_nodes: int = 1200, root_name: str | None = None) -> str:
    children: dict[Path, list[Path]] = {}
    for path in files:
        parent = path.parent.relative_to(root)
        parts = path.relative_to(root).parts
        for index in range(len(parts) - 1):
            folder = Path(*parts[:index + 1])
            children.setdefault(folder.parent, [])
            if folder not in children[folder.parent]:
                children[folder.parent].append(folder)
        children.setdefault(parent, []).append(path)

    lines = [f"📦 {root_name or root.name}"]
    count = 0

    def add_children(parent: Path, prefix: str, depth: int = 0) -> None:
        nonlocal count
        entries = children.get(parent, [])
        entries.sort(key=lambda entry: (entry not in children, entry.name.lower()))
        for index, entry in enumerate(entries):
            if count >= max_nodes:
                lines.append(f"{prefix}└── … (tree shortened at {max_nodes} entries)")
                return
            count += 1
            last = index == len(entries) - 1
            connector = "└── " if last else "├── "
            is_dir = entry in children
            label = f"📁 {entry.name}" if is_dir else f"📄 {entry.name}"
            lines.append(prefix + connector + label)
            if is_dir:
                if depth >= 39:
                    lines.append(prefix + ("    " if last else "│   ") + "└── … (maximum display depth reached)")
                else:
                    add_children(entry, prefix + ("    " if last else "│   "), depth + 1)

    add_children(Path("."), "")
    return "\n".join(lines)


def _python_symbols(text: str) -> tuple[list[str], list[str], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], [], _regex_imports(text)
    functions, classes, imports = [], [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or ".")
    return sorted(set(functions)), sorted(set(classes)), sorted(set(imports))


def _regex_imports(text: str) -> list[str]:
    patterns = (
        r"^\s*import\s+(.+)",
        r"^\s*from\s+([.\w]+)\s+import",
        r"^\s*(?:const|let|var)\s+.+?\s*=\s*require\(['\"]([^'\"]+)",
        r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)",
        r"^\s*import\s+['\"]([^'\"]+)",
        r"^\s*#include\s+[<\"]([^>\"]+)",
        r"^\s*using\s+([\w.]+)",
        r"^\s*(?:use|require)\s+([^;(\s]+)",
    )
    found = []
    for line in text.splitlines():
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                found.append(match.group(1).strip())
                break
    return sorted(set(found))[:40]


def _symbols_and_imports(path: Path, text: str) -> tuple[list[str], list[str], list[str]]:
    if path.suffix.lower() == ".py":
        return _python_symbols(text)
    function_patterns = (
        r"\b(?:function\s+|(?:async\s+)?def\s+)([A-Za-z_$][\w$]*)\s*\(",
        r"^\s*(?:(?:public|private|protected|static|async|export|virtual|override|final|inline|constexpr)\s+)*(?:[\w:<>,\[\]*&?]+\s+)+([A-Za-z_$][\w$]*)\s*\(",
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
    )
    functions = [
        name
        for pattern in function_patterns
        for name in re.findall(pattern, text, re.MULTILINE)
    ]
    classes = re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", text)
    return sorted(set(functions))[:80], sorted(set(classes))[:60], _regex_imports(text)


def _purpose(
    path: Path,
    text: str,
    entry_points: set[str],
    root: Path,
    file_type: str,
) -> str:
    nonempty_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if file_type == "Documentation":
        heading = next((line.lstrip("# ").strip() for line in nonempty_lines if line.startswith("#")), "")
        if heading:
            return f"Documentation; its first detected heading is “{heading[:180]}”."
        if nonempty_lines:
            return f"Documentation; opening text: {nonempty_lines[0][:180]}"
        return "Documentation file; no readable text was available."
    if file_type == "Configuration":
        if path.name.lower() in CONFIG_NAMES:
            return "Project configuration or dependency manifest, identified by its filename."
        if nonempty_lines:
            return f"Configuration content begins with: {nonempty_lines[0][:180]}"
        return "Configuration file; no readable text was available."
    if file_type == "Data / schema":
        if nonempty_lines:
            return f"Structured data or schema; first content line: {nonempty_lines[0][:180]}"
        return "Structured data or schema file; no readable text was available."
    if file_type == "Deployment":
        return "Deployment or build configuration, identified by its filename or repository location."
    if file_type == "Markup":
        return "HTML markup file; its document structure is inspected without rendering it."
    if file_type == "Stylesheet":
        return "Stylesheet file containing presentation rules; it is inspected as text."
    if file_type == "Jupyter notebook":
        return next((line for line in nonempty_lines if line.startswith("Jupyter notebook.")), "Jupyter notebook with cells extracted from its JSON content.")
    if file_type == "Other readable text":
        if nonempty_lines:
            return f"Readable text file; opening content: {nonempty_lines[0][:180]}"
    first_doc = re.search(r'^\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')', text, re.DOTALL)
    if first_doc:
        description = (first_doc.group(1) or first_doc.group(2) or "").strip().splitlines()[0].strip()
        if description:
            return description[:240]
    if path.relative_to(root).as_posix() in entry_points:
        return "Potential application entry point based on its filename; runtime behavior was not executed."
    return "Purpose could not be clearly determined from the analyzed repository."


def _relationships(imports: list[str], indexed_paths: set[str]) -> list[str]:
    relationships = set()
    for imported in imports:
        normalized = imported.replace(".", "/").lstrip("./")
        if not normalized or not (imported.startswith(".") or "/" in imported):
            continue
        matches = [path for path in indexed_paths if path.endswith(normalized) or path.endswith(normalized + ".py") or path.endswith(normalized + ".js") or path.endswith(normalized + ".ts") or path.endswith(normalized + "/index.js") or path.endswith(normalized + "/index.ts")]
        relationships.update(matches[:3])
    return sorted(relationships)[:12]


def analyze_repository(
    root: Path,
    analyzed_paths: list[str] | None = None,
    repository_name: str | None = None,
    inspections: dict | None = None,
) -> dict:
    """Create repository-wide stats and static metadata for prioritized files."""
    root = root.resolve()
    all_paths = list(_walk(root))
    relative_paths = [path.relative_to(root).as_posix() for path in all_paths]
    total_folders = 0
    for current, directories, _ in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = [name for name in directories if name not in IGNORED_DIRS and not (current_path / name).is_symlink()]
        total_folders += len(directories)

    classifications = {path.relative_to(root).as_posix(): classify_file(path) for path in all_paths}
    source_paths = [
        path for path in all_paths
        if path.suffix.lower() in SOURCE_EXTENSIONS
        and not classifications[path.relative_to(root).as_posix()][2]
    ]
    source_count = len(source_paths)
    languages: dict[str, int] = {}
    for path in source_paths:
        language = language_for_path(path)
        languages[language] = languages.get(language, 0) + 1
    notebook_language_map = {
        "python": "Python", "python3": "Python", "javascript": "JavaScript",
        "typescript": "TypeScript", "julia": "Julia", "r": "R",
        "java": "Java", "c": "C", "cpp": "C++", "rust": "Rust",
    }
    notebooks_inspected = 0
    for path in all_paths:
        if path.suffix.lower() != ".ipynb":
            continue
        if notebooks_inspected >= env_int("MAX_FILES", 80):
            break
        relative = path.relative_to(root).as_posix()
        inspected = (inspections or {}).get(relative)
        if inspected is None:
            if inspections is not None:
                continue
            inspected = inspect_file(path, 4096)
        notebooks_inspected += 1
        normalized = notebook_language_map.get(inspected.language.lower())
        if normalized:
            languages[normalized] = languages.get(normalized, 0) + 1
    languages = dict(sorted(languages.items(), key=lambda item: (-item[1], item[0])))
    entry_points = {
        path.relative_to(root).as_posix()
        for path in all_paths
        if path.name.lower() in ENTRY_NAMES
    }
    important_paths = sorted(
        [
            path for path in all_paths
            if not classifications[path.relative_to(root).as_posix()][2]
            and classifications[path.relative_to(root).as_posix()][0] != "Unreadable"
        ],
        key=lambda path: _priority(path.relative_to(root)),
    )
    if analyzed_paths is not None:
        analyzed_set = set(analyzed_paths)
        chosen = [path for path in important_paths if path.relative_to(root).as_posix() in analyzed_set]
    else:
        chosen = important_paths[:80]

    file_analysis = []
    indexed_paths = set(relative_paths)
    for path in chosen:
        relative = path.relative_to(root).as_posix()
        inspected = (inspections or {}).get(relative)
        if inspected is None:
            inspected = inspect_file(path, env_int("MAX_FILE_SIZE", 100_000))
        if inspected.is_binary:
            continue
        text = inspected.analysis_content if inspected.file_type == "Jupyter notebook" else inspected.content
        analysis_path = path.with_suffix(".py") if inspected.language.lower() in {"python", "python3"} else path
        if inspected.file_type in {"Source code", "Jupyter notebook"}:
            functions, classes, imports = _symbols_and_imports(analysis_path, text)
        else:
            functions, classes, imports = [], [], []
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        file_analysis.append(FileAnalysis(
            filename=path.name,
            path=relative,
            language=inspected.language if inspected.file_type == "Jupyter notebook" else language_for_path(path),
            file_type=inspected.file_type,
            size_bytes=size_bytes,
            purpose=_purpose(path, inspected.content, entry_points, root, inspected.file_type),
            notes=inspected.note,
            notebook_code_cells=inspected.notebook_code_cells,
            notebook_markdown_cells=inspected.notebook_markdown_cells,
            functions=functions,
            classes=classes,
            imports=imports,
            relationships=_relationships(imports, indexed_paths),
        ))

    folder_tree = _tree(root, all_paths, root_name=repository_name)
    folder_paths: set[str] = set()
    for path in relative_paths:
        parts = Path(path).parts[:-1]
        for index, part in enumerate(parts):
            relative_folder = Path(*parts[:index + 1]).as_posix()
            if index == 0 or part.lower() in IMPORTANT_FOLDER_NAMES:
                folder_paths.add(relative_folder)
    important_folders = []
    ordered_folders = sorted(
        folder_paths,
        key=lambda folder: (
            Path(folder).name.lower() not in IMPORTANT_FOLDER_NAMES,
            len(Path(folder).parts),
            folder.lower(),
        ),
    )
    for folder in ordered_folders[:40]:
        members = [path for path in relative_paths if path.startswith(folder + "/")]
        source_members = sum(
            Path(path).suffix.lower() in SOURCE_EXTENSIONS
            and not classifications[path][2]
            for path in members
        )
        if Path(folder).name.lower() in {"test", "tests", "__tests__"}:
            purpose = "Contains files grouped under a test-oriented folder name; individual test behavior was not executed."
        elif source_members:
            languages_in_folder = sorted({
                language_for_path(path) for path in members
                if Path(path).suffix.lower() in SOURCE_EXTENSIONS
                and not classifications[path][2]
            })
            purpose = f"Contains {source_members} supported source file(s), including {', '.join(languages_in_folder)}."
        elif members:
            member_types = Counter(classifications[path][0] for path in members)
            represented = [
                f"{count} {file_type.lower()}"
                for file_type, count in member_types.most_common(3)
                if file_type not in {"Binary", "Unreadable"}
            ]
            purpose = (
                f"Contains {', '.join(represented)} file(s)."
                if represented
                else "Purpose could not be clearly determined from the analyzed repository."
            )
        else:
            purpose = "Purpose could not be clearly determined from the analyzed repository."
        important_folders.append({"path": folder, "purpose": purpose})

    important_files = [
        {"path": path.relative_to(root).as_posix(), "filename": path.name, "reason": _importance_reason(path)}
        for path in important_paths[:40]
    ]
    extensions = Counter(path.suffix.lower() or "[no extension]" for path in all_paths)
    return {
        "repository_name": repository_name or root.name,
        "total_files": len(all_paths),
        "total_folders": total_folders,
        "source_files": source_count,
        "readable_files": sum(not inspected[2] and inspected[0] != "Unreadable" for inspected in classifications.values()),
        "binary_files": sum(inspected[2] for inspected in classifications.values()),
        "sensitive_files": sum(is_sensitive_file(path) for path in all_paths),
        "notebook_files": sum(inspected[0] == "Jupyter notebook" for inspected in classifications.values()),
        "data_files": sum(inspected[0] == "Data / schema" for inspected in classifications.values()),
        "unknown_readable_files": sum(
            inspected[0] == "Other readable text" for inspected in classifications.values()
        ),
        "file_types": dict(Counter(inspected[0] for inspected in classifications.values()).most_common()),
        "binary_file_samples": [
            {"path": relative, "extension": Path(relative).suffix.lower(), "size_bytes": (root / relative).stat().st_size}
            for relative, inspected in classifications.items()
            if inspected[2]
        ][:50],
        "languages": languages,
        "folder_tree": folder_tree,
        "important_folders": important_folders,
        "important_files": important_files,
        "file_analysis": file_analysis,
        "entry_points": sorted(entry_points),
        "extensions": dict(extensions.most_common()),
        "documentation_files": sum(inspected[0] == "Documentation" for inspected in classifications.values()),
        "configuration_files": sum(inspected[0] == "Configuration" for inspected in classifications.values()),
        "test_files": sum(
            any(part.lower() in {"test", "tests", "__tests__"} for part in path.parts)
            or path.name.lower().startswith(("test_", "test."))
            or ".test." in path.name.lower()
            for path in all_paths
        ),
    }


def _importance_reason(path: Path) -> str:
    inspected_type, _, _ = classify_file(path)
    if inspected_type == "Documentation":
        return "Documentation file selected for repository context."
    if inspected_type == "Configuration":
        return "Project configuration or dependency manifest."
    if inspected_type == "Jupyter notebook":
        return "Notebook cell sources selected; stored outputs are excluded."
    if inspected_type == "Data / schema":
        return "Structured data/schema content selected for repository context."
    if path.name.lower() in ENTRY_NAMES:
        return "Potential application entry point based on filename."
    return f"{inspected_type} selected by repository analysis priority."
