"""FastAPI application for local GitHub repository analysis."""

from __future__ import annotations

import json
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.code_extractor import extract_code
from backend.github_processor import CloneError, EmptyRepository, RepositoryTooLarge, clone_repository
from backend.llm_service import (
    ModelUnavailable,
    OllamaConfigurationError,
    OllamaError,
    OllamaUnavailable,
    explain_repository,
    get_public_ollama_url,
)
from backend.models import AnalyzeRequest, AnalyzeResponse
from backend.repository_analyzer import analyze_repository
from backend.technology_detector import detect_technologies
from backend.utils import InvalidGitHubURL, env_int

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Local GitHub Repository Code Explainer",
    description="Analyze public GitHub repositories and explain them using a local Ollama model.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/")
def health_check() -> dict[str, str]:
    return {"status": "running", "message": "Local GitHub Repository Code Explainer API"}


def _build_context(
    github_url: str,
    analysis: dict,
    technologies: list[str],
    extraction,
) -> str:
    max_context = env_int("MAX_TOTAL_CONTEXT", 300_000)
    core = (
        f"Repository URL: {github_url}\n"
        f"Repository name: {analysis['repository_name']}\n"
        f"Statistics: {json.dumps({key: analysis[key] for key in ('total_files', 'total_folders', 'source_files', 'readable_files', 'binary_files', 'sensitive_files', 'notebook_files', 'documentation_files', 'configuration_files', 'data_files', 'test_files', 'unknown_readable_files')})}\n"
        f"File categories: {json.dumps(analysis['file_types'])}\n"
        f"Binary file examples (classified only, not read as text): {json.dumps(analysis['binary_file_samples'][:20])}\n"
        f"Languages and file counts: {json.dumps(analysis['languages'])}\n"
        f"Technologies with repository evidence: {json.dumps(technologies)}\n"
        f"Potential entry points (filename evidence only): {json.dumps(analysis['entry_points'])}\n"
    )
    file_rows = [
        {
            "path": item.path,
            "language": item.language,
            "file_type": item.file_type,
            "size_bytes": item.size_bytes,
            "purpose": item.purpose,
            "notes": item.notes,
            "notebook_code_cells": item.notebook_code_cells,
            "notebook_markdown_cells": item.notebook_markdown_cells,
            "functions": item.functions[:20],
            "classes": item.classes[:12],
            "imports": item.imports[:20],
            "relationships": item.relationships[:12],
        }
        for item in analysis["file_analysis"][:50]
    ]
    details = (
        f"Important folders: {json.dumps(analysis['important_folders'][:40])}\n"
        f"Important files: {json.dumps(analysis['important_files'][:40])}\n"
        f"Static file analysis: {json.dumps(file_rows)}\n"
        f"Repository tree:\n{analysis['folder_tree'][:20_000]}\n"
        f"Files omitted by configured analysis limits: {extraction.skipped_files}."
    )
    metadata_budget = min(len(core) + len(details), max_context // 3)
    if len(core) >= metadata_budget:
        metadata = core[:metadata_budget]
    else:
        detail_budget = metadata_budget - len(core)
        marker = "\n[Repository metadata shortened because of context limits]"
        if len(details) > detail_budget and detail_budget >= len(marker):
            details = details[:detail_budget - len(marker)] + marker
        else:
            details = details[:detail_budget]
        metadata = core + details

    source_budget = max_context - len(metadata)
    source_context = extraction.context
    if len(source_context) > source_budget:
        marker = "\n[Additional repository source omitted because of total context limits]"
        if source_budget >= len(marker):
            source_context = source_context[:source_budget - len(marker)] + marker
        else:
            source_context = source_context[:source_budget]
    return metadata + source_context


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        repository_path, repository_name, canonical_url = clone_repository(request.github_url)
    except InvalidGitHubURL as exc:
        raise HTTPException(status_code=422, detail=f"Invalid GitHub repository URL: {exc}") from exc
    except RepositoryTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except EmptyRepository as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CloneError as exc:
        raise HTTPException(status_code=502, detail=f"Unable to clone repository: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        extraction = extract_code(repository_path)
        analysis = analyze_repository(
            repository_path,
            extraction.analyzed_paths,
            repository_name,
            extraction.inspections,
        )
        technologies = detect_technologies(repository_path)
        context = _build_context(canonical_url, analysis, technologies, extraction)
        explanation = explain_repository(context)
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Local AI is unavailable. Please make sure Ollama is running. {exc}") from exc
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"The configured Qwen model is not installed. {exc}") from exc
    except OllamaConfigurationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=f"Local AI could not generate an explanation: {exc}") from exc
    except (OSError, ValueError) as exc:
        logger.exception("Repository analysis failed for %s", canonical_url)
        raise HTTPException(status_code=500, detail="Repository analysis failed while reading repository contents.") from exc

    return AnalyzeResponse(
        success=True,
        repository_name=analysis["repository_name"],
        github_url=canonical_url.removesuffix(".git"),
        total_files=analysis["total_files"],
        total_folders=analysis["total_folders"],
        source_files=analysis["source_files"],
        readable_files=analysis["readable_files"],
        binary_files=analysis["binary_files"],
        sensitive_files=analysis["sensitive_files"],
        notebook_files=analysis["notebook_files"],
        data_files=analysis["data_files"],
        unknown_readable_files=analysis["unknown_readable_files"],
        file_types=analysis["file_types"],
        binary_file_samples=analysis["binary_file_samples"],
        documentation_files=analysis["documentation_files"],
        configuration_files=analysis["configuration_files"],
        test_files=analysis["test_files"],
        file_extensions=analysis["extensions"],
        languages=analysis["languages"],
        technologies=technologies,
        entry_points=analysis["entry_points"],
        folder_tree=analysis["folder_tree"],
        important_folders=analysis["important_folders"],
        important_files=analysis["important_files"],
        file_analysis=analysis["file_analysis"],
        ai_explanation=explanation,
        files_analyzed=len(extraction.analyzed_paths),
        files_skipped=extraction.skipped_files,
        skipped_files=(
            extraction.skipped_files
            + analysis["binary_files"]
            + analysis["file_types"].get("Unreadable", 0)
        ),
        context_size=len(context),
        llm_model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        ollama_base_url=get_public_ollama_url(),
    )
