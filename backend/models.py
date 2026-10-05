"""Pydantic API models."""

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    github_url: str = Field(min_length=1, max_length=500)


class FileAnalysis(BaseModel):
    filename: str
    path: str
    language: str
    file_type: str
    size_bytes: int
    purpose: str
    notes: str = ""
    notebook_code_cells: int = 0
    notebook_markdown_cells: int = 0
    functions: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    success: bool
    repository_name: str
    github_url: str
    total_files: int
    total_folders: int
    source_files: int
    readable_files: int
    binary_files: int
    sensitive_files: int
    notebook_files: int
    data_files: int
    unknown_readable_files: int
    file_types: dict[str, int]
    binary_file_samples: list[dict[str, str | int]]
    documentation_files: int
    configuration_files: int
    test_files: int
    file_extensions: dict[str, int]
    languages: dict[str, int]
    technologies: list[str]
    entry_points: list[str]
    folder_tree: str
    important_folders: list[dict[str, str]]
    important_files: list[dict[str, str]]
    file_analysis: list[FileAnalysis]
    ai_explanation: str
    files_analyzed: int
    files_skipped: int
    skipped_files: int
    context_size: int
    llm_model: str
    ollama_base_url: str
