"""Evidence-based programming language and technology detection."""

from __future__ import annotations

import re
from pathlib import Path

from backend.file_inspector import classify_file, inspect_file, iter_repository_files
from backend.utils import LANGUAGE_BY_EXTENSION, SOURCE_EXTENSIONS

TECHNOLOGY_EVIDENCE = {
    "React": (r'"react"\s*:', r"from\s+['\"]react['\"]", r"require\(['\"]react['\"]\)"),
    "Node.js": (r'"node"\s*:', r"\bprocess\.versions\.node\b"),
    "FastAPI": (r"\bfastapi\b", r"from\s+fastapi\b", r"import\s+fastapi\b"),
    "Flask": (r"\bflask\b", r"from\s+flask\b"),
    "Django": (r"\bdjango\b", r"from\s+django\b"),
    "Express": (r'"express"\s*:', r"require\(['\"]express['\"]\)", r"from\s+['\"]express['\"]"),
    "MongoDB": (r"\bmongodb\b", r"\bpymongo\b", r"\bmongoose\b"),
    "MySQL": (r"\bmysql\b", r"\bpymysql\b"),
    "PostgreSQL": (r"\bpostgres(?:ql)?\b", r"\bpsycopg(?:2)?\b"),
    "TensorFlow": (r"\btensorflow\b", r"\bkeras\b"),
    "PyTorch": (r"\btorch\b", r"\bpytorch\b"),
    "Scikit-learn": (r"\bscikit[-_]learn\b", r"\bsklearn\b"),
    "Docker": (r"\bdockerfile\b", r"\bdocker-compose\b"),
    "Streamlit": (r"\bstreamlit\b", r"import\s+streamlit"),
    "Vue": (r'"vue"\s*:', r"from\s+['\"]vue['\"]"),
    "Angular": (r'"@angular/core"\s*:', r"angular\.json"),
    "Next.js": (r'"next"\s*:', r"next\.config\.(?:js|ts)"),
    "Vite": (r'"vite"\s*:', r"vite\.config\.(?:js|ts)"),
    "Spring Boot": (r"spring-boot", r"org\.springframework\.boot"),
    "Svelte": (r'"svelte"\s*:', r"\.svelte\b"),
    "Power BI": (r"\bmicrosoft\s+power\s*bi\b", r"\bpowerbi\b"),
    "Power Query": (r"\bpower\s*query\b",),
    "DAX": (r"\bdax\b",),
    "Microsoft Excel": (r"\bmicrosoft\s+excel\b",),
}


def detect_languages(root: Path) -> dict[str, int]:
    """Count supported source files by detected language."""
    counts: dict[str, int] = {}
    for path in iter_repository_files(root):
        extension = path.suffix.lower()
        if extension in SOURCE_EXTENSIONS:
            if classify_file(path)[2]:
                continue
            language = LANGUAGE_BY_EXTENSION[extension]
            counts[language] = counts.get(language, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def detect_technologies(root: Path) -> list[str]:
    """Find technologies only when readable repository content provides evidence."""
    evidence_text = []
    candidates = list(iter_repository_files(root))
    candidates.sort(
        key=lambda path: (
            classify_file(path)[0] not in {"Configuration", "Source code", "Jupyter notebook"},
            path.as_posix().lower(),
        )
    )
    evidence_size = 0
    has_python = False
    for path in candidates:
        if evidence_size >= 2_000_000:
            break
        file_type, _, is_binary = classify_file(path)
        if is_binary or file_type == "Unreadable":
            continue
        remaining = min(200_000, 2_000_000 - evidence_size)
        inspected = inspect_file(path, remaining)
        content = inspected.analysis_content or inspected.content
        evidence_text.append(content)
        evidence_size += len(content)
        if path.suffix.lower() == ".py":
            has_python = True
        elif path.suffix.lower() == ".ipynb" and inspected.language.lower() in {"python", "python3"}:
            has_python = True
        if path.name.lower() == "dockerfile":
            evidence_text.append("dockerfile")

    searchable = "\n".join(evidence_text)
    detected = []
    for technology, patterns in TECHNOLOGY_EVIDENCE.items():
        if any(re.search(pattern, searchable, re.IGNORECASE) for pattern in patterns):
            detected.append(technology)

    if has_python:
        detected.append("Python")
    return sorted(set(detected))
