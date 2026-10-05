"""Professional Streamlit interface for the repository explainer API."""

from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st

if __package__:
    from .styles import apply_styles
else:
    frontend_directory = str(Path(__file__).resolve().parent)
    if frontend_directory not in sys.path:
        sys.path.insert(0, frontend_directory)
    from styles import apply_styles

st.set_page_config(
    page_title="Local GitHub Repository Code Explainer",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_styles(st)

API_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/analyze"
PROGRESS_STEPS = [
    "Validating repository",
    "Cloning repository",
    "Scanning folders",
    "Analyzing source files",
    "Detecting technologies",
    "Preparing AI context",
    "Generating explanation",
    "Finalizing report",
]


def _valid_github_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or hostname != "github.com"
        or port is not None
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return False
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        return False
    repository = parts[1][:-4] if parts[1].lower().endswith(".git") else parts[1]
    return (
        all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (parts[0], repository))
        and parts[0] not in {".", ".."}
        and repository not in {".", ".."}
    )


def _section(explanation: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?im)^\s{{0,3}}(?:#+\s*)?{re.escape(heading)}\s*:?\s*$"
    )
    match = pattern.search(explanation)
    if not match:
        return ""
    remainder = explanation[match.end():]
    next_heading = re.search(r"(?m)^\s{0,3}#{1,6}\s+\S|^\s{0,3}[A-Z][A-Z /-]{4,}\s*$", remainder)
    return remainder[: next_heading.start()].strip() if next_heading else remainder.strip()


def _error_message(response: requests.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if response.status_code == 422:
        return "❌ Invalid GitHub repository URL. Enter a public repository such as `https://github.com/username/repository`."
    if response.status_code == 413:
        return f"❌ Repository is too large. {detail or 'The repository exceeds the configured size limit.'}"
    if response.status_code == 502 and detail and "clone" in str(detail).lower():
        return f"❌ Unable to clone repository. {detail}"
    if response.status_code == 503 and detail and "model" in str(detail).lower():
        return "⚠️ The configured Qwen model is not installed. Run the Ollama pull command shown in the setup instructions."
    if response.status_code == 503:
        return "⚠️ Local AI is unavailable. Please make sure Ollama is running."
    return f"❌ Analysis could not be completed. {detail or 'Check that the backend is running and try again.'}"


def _metric(label: str, value: str | int) -> None:
    st.markdown(
        f'<div class="metric"><div class="metric-label">{html.escape(label)}</div>'
        f'<div class="metric-value">{html.escape(str(value))}</div></div>',
        unsafe_allow_html=True,
    )


def _render_file_analysis(item: dict) -> None:
    title = f"{item.get('filename', 'File')} · {item.get('path', '')}"
    with st.expander(title):
        first, second = st.columns(2)
        first.markdown(f"**Language:** {item.get('language', 'Unknown')}")
        first.markdown(f"**File type:** {item.get('file_type', 'Unknown')}")
        first.markdown(f"**Approximate size:** {item.get('size_bytes', 0):,} bytes")
        second.markdown(f"**Purpose:** {item.get('purpose', 'Purpose could not be clearly determined from the analyzed repository.')}")
        if item.get("notebook_code_cells") or item.get("notebook_markdown_cells"):
            st.markdown(
                f"**Notebook cells:** {item.get('notebook_code_cells', 0)} code, "
                f"{item.get('notebook_markdown_cells', 0)} markdown (outputs excluded)"
            )
        if item.get("notes"):
            st.caption(item["notes"])
        if item.get("functions"):
            st.markdown("**Detected functions**")
            st.write(", ".join(item["functions"]))
        if item.get("classes"):
            st.markdown("**Detected classes**")
            st.write(", ".join(item["classes"]))
        if item.get("imports"):
            st.markdown("**Imports / dependencies**")
            st.write(", ".join(item["imports"]))
        if item.get("relationships"):
            st.markdown("**Related repository files (matched import paths)**")
            st.write(", ".join(item["relationships"]))


def _render_results(data: dict) -> None:
    st.markdown(
        f'<div class="panel"><div class="section-kicker">Analyzed repository</div>'
        f'<h2 style="margin:.2rem 0">{html.escape(data["repository_name"])}</h2>'
        f'<a href="{html.escape(data["github_url"], quote=True)}" target="_blank" '
        f'style="color:#9d91ff">{html.escape(data["github_url"])}</a></div>',
        unsafe_allow_html=True,
    )
    overview_tab, tree_tab, files_tab, ai_tab, details_tab = st.tabs(
        ["📊 Overview", "🌳 Repository Structure", "📁 Files & Folders", "🧠 AI Explanation", "⚙️ Technical Details"]
    )

    with overview_tab:
        metrics = st.columns(4)
        values = [
            ("Total Files", data["total_files"]),
            ("Total Folders", data["total_folders"]),
            ("Source Files", data["source_files"]),
            ("Languages", len(data["languages"])),
        ]
        for column, (label, value) in zip(metrics, values):
            with column:
                _metric(label, value)
        st.markdown('<div class="section-kicker">Detected technologies</div>', unsafe_allow_html=True)
        if data["technologies"]:
            st.markdown(" ".join(f"`{html.escape(item)}`" for item in data["technologies"]))
        else:
            st.info("No listed technology was confirmed from the inspected repository evidence.")
        st.markdown('<div class="section-kicker">Programming languages</div>', unsafe_allow_html=True)
        if data["languages"]:
            language_columns = st.columns(min(4, len(data["languages"])))
            for index, (language, count) in enumerate(data["languages"].items()):
                with language_columns[index % len(language_columns)]:
                    _metric(language, count)
        elif data.get("total_files", 0) > 0:
            st.info(
                "This repository contains no conventional source-code files, but documentation, "
                "configuration, data, notebooks, or other readable files are available for analysis."
            )
        else:
            st.warning("⚠️ No readable repository files were available for analysis.")
        overview = _section(data["ai_explanation"], "PROJECT OVERVIEW")
        features = _section(data["ai_explanation"], "MAIN FEATURES")
        st.markdown('<div class="section-kicker">Project overview</div>', unsafe_allow_html=True)
        st.markdown(overview or "See the AI Explanation tab for the evidence-based repository report.")
        st.markdown('<div class="section-kicker">Main features</div>', unsafe_allow_html=True)
        st.markdown(features or "The model did not provide a separate main-features section.")

    with tree_tab:
        st.caption("The tree includes readable source and project files; ignored build, cache, and media content is omitted.")
        with st.expander("Expand repository tree", expanded=True):
            st.code(data["folder_tree"], language="text")

    with files_tab:
        st.markdown("### File-type inventory")
        st.markdown(
            " · ".join(
                f"**{kind}:** {count}"
                for kind, count in data.get("file_types", {}).items()
            ) or "No files were classified."
        )
        if data.get("binary_file_samples"):
            with st.expander(f"Binary files classified but not read ({data.get('binary_files', 0)})"):
                for binary in data["binary_file_samples"]:
                    st.write(
                        f"`{binary['path']}` · {binary.get('extension') or 'no extension'} · "
                        f"{binary['size_bytes']:,} bytes"
                    )
        st.markdown("### Important folders")
        if data.get("important_folders"):
            for folder in data["important_folders"]:
                with st.expander(f"📁 {folder['path']}"):
                    st.write(folder["purpose"])
        else:
            st.write("No meaningful top-level folders were detected.")
        st.markdown("### Important files")
        for file in data.get("important_files", []):
            st.markdown(f"- `{file['path']}` — {file['reason']}")
        st.markdown("### File analysis")
        if data.get("file_analysis"):
            for item in data["file_analysis"]:
                _render_file_analysis(item)
        else:
            st.info("No prioritized readable files were available for file-by-file analysis.")

    with ai_tab:
        st.markdown("## 🧠 AI Generated Repository Explanation")
        st.markdown(data["ai_explanation"])

    with details_tab:
        detail_rows = [
            ("LLM model", data.get("llm_model", "Not reported")),
            ("Ollama URL", data.get("ollama_base_url", "Not reported")),
            ("Files analyzed", data.get("files_analyzed", 0)),
            ("Files skipped by limits", data.get("files_skipped", 0)),
            ("Readable files", data.get("readable_files", 0)),
            ("Binary files (not sent as text)", data.get("binary_files", 0)),
            ("Sensitive files withheld", data.get("sensitive_files", 0)),
            ("Jupyter notebooks", data.get("notebook_files", 0)),
            ("Data / schema files", data.get("data_files", 0)),
            ("Unknown readable text files", data.get("unknown_readable_files", 0)),
            ("Files skipped including binary assets", data.get("skipped_files", data.get("files_skipped", 0))),
            ("Context size", f'{data.get("context_size", 0):,} characters'),
            ("Languages detected", ", ".join(data.get("languages", {}).keys()) or "None"),
            ("Technologies detected", ", ".join(data.get("technologies", [])) or "None"),
            ("File types", ", ".join(f"{kind}: {count}" for kind, count in data.get("file_types", {}).items()) or "None"),
            ("Binary file examples", ", ".join(item["path"] for item in data.get("binary_file_samples", [])[:10]) or "None"),
            ("Potential entry points", ", ".join(data.get("entry_points", [])) or "None detected"),
            ("Documentation / configuration / test files", f'{data.get("documentation_files", 0)} / {data.get("configuration_files", 0)} / {data.get("test_files", 0)}'),
            ("File extensions", ", ".join(f"{extension or '[no extension]'}: {count}" for extension, count in data.get("file_extensions", {}).items()) or "None"),
            ("Processing", "Static file inspection; repository code was not executed."),
        ]
        for label, value in detail_rows:
            st.markdown(f"**{label}:** {value}")


with st.sidebar:
    st.markdown("## 🧠 About This Project")
    st.write(
        "This application analyzes public GitHub repositories and uses a locally running Qwen model through Ollama to generate a detailed explanation of the repository."
    )
    st.markdown("**Technology stack**")
    st.markdown(" ".join(f"`{tag}`" for tag in ("Python", "FastAPI", "GitPython", "Ollama", "Qwen", "Streamlit")))
    st.divider()
    st.markdown("### 🔒 Local AI")
    st.caption("Repository analysis and AI generation are performed locally. Public GitHub content is cloned locally; no GitHub credentials are requested.")
    st.caption("The application only reads repository files and never runs their code.")

st.markdown(
    '<section class="hero"><span class="badge">● LOCAL AI &nbsp;•&nbsp; OLLAMA &nbsp;•&nbsp; QWEN</span>'
    '<div class="eyebrow">🧠 LOCAL GITHUB</div><h1>REPOSITORY CODE EXPLAINER</h1>'
    '<p>Understand any public GitHub repository with AI-powered code analysis running entirely on your machine.</p></section>',
    unsafe_allow_html=True,
)

st.markdown("### GitHub Repository URL")
st.caption("Enter a public repository URL. No GitHub credentials are needed.")
with st.form("repository_form"):
    repository_url = st.text_input(
        "Enter a public GitHub repository URL",
        placeholder="https://github.com/username/repository",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("🚀 Analyze Repository", use_container_width=True)
if submitted:
    st.session_state.pop("analysis_result", None)
    if not _valid_github_url(repository_url):
        st.error("❌ Invalid GitHub repository URL. Use `https://github.com/username/repository`.")
    else:
        try:
            with st.status("Analyzing repository with the local AI pipeline…", expanded=True) as status:
                progress = st.progress(10, text="Repository analysis is running locally")
                step_display = st.empty()
                step_display.markdown(
                    "\n".join(
                        f"{index:02d} {'✓' if index == 1 else '◌'} {step}"
                        for index, step in enumerate(PROGRESS_STEPS, start=1)
                    )
                )
                response = requests.post(
                    API_URL,
                    json={"github_url": repository_url.strip()},
                    timeout=(10, 900),
                )
                if not response.ok:
                    status.update(label="Analysis could not be completed", state="error")
                    st.error(_error_message(response))
                    st.stop()
                result = response.json()
                progress.progress(100, text="Analysis complete")
                step_display.markdown(
                    "\n".join(
                        f"{index:02d} ✓ {step}"
                        for index, step in enumerate(PROGRESS_STEPS, start=1)
                    )
                )
                status.update(label="Repository analysis complete", state="complete", expanded=True)
                st.session_state["analysis_result"] = result
        except requests.Timeout:
            st.error("⏱️ The analysis took too long. Check the backend and Ollama, then try again.")
        except requests.ConnectionError:
            st.error("❌ Cannot reach the FastAPI backend. Start the backend and retry.")
        except (requests.RequestException, ValueError) as exc:
            st.error(f"❌ Could not read the analysis response: {exc}")

if "analysis_result" in st.session_state:
    result = st.session_state["analysis_result"]
    if result["source_files"] == 0 and result.get("total_files", 0) > 0:
        st.info(
            "This repository contains no conventional source-code files, but documentation, "
            "configuration, data, notebooks, or other readable files are available for analysis. "
            "The AI report is based on that evidence."
        )
    elif result.get("total_files", 0) == 0:
        st.warning("⚠️ No readable repository files were available for analysis.")
    _render_results(result)
