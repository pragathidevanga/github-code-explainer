import json
import tempfile
import unittest
from pathlib import Path

from backend.code_extractor import extract_code
from backend.file_inspector import classify_file, inspect_file
from backend.repository_analyzer import analyze_repository


class GeneralFileAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_notebook_extracts_code_and_markdown_without_saved_outputs(self):
        notebook = {
            "metadata": {
                "kernelspec": {"language": "python", "name": "python3"},
                "language_info": {"name": "python"},
            },
            "cells": [
                {"cell_type": "markdown", "source": ["# Dataset overview\n", "Input explanation."]},
                {
                    "cell_type": "code",
                    "source": ["def summarize(values):\n", "    return len(values)\n"],
                    "outputs": [{"output_type": "stream", "text": ["PRIVATE_SAVED_OUTPUT"]}],
                    "execution_count": 1,
                },
            ],
        }
        path = self.root / "exploration.ipynb"
        path.write_text(json.dumps(notebook), encoding="utf-8")

        inspected = inspect_file(path)
        extracted = extract_code(self.root)
        report = analyze_repository(self.root, extracted.analyzed_paths, inspections=extracted.inspections)
        item = report["file_analysis"][0]

        self.assertEqual(inspected.file_type, "Jupyter notebook")
        self.assertEqual((inspected.notebook_code_cells, inspected.notebook_markdown_cells), (1, 1))
        self.assertIn("Input explanation.", extracted.context)
        self.assertIn("def summarize", extracted.context)
        self.assertNotIn("PRIVATE_SAVED_OUTPUT", extracted.context)
        self.assertEqual(item.functions, ["summarize"])
        self.assertEqual(item.language, "python")
        self.assertEqual(report["languages"]["Python"], 1)

    def test_classifies_documents_configuration_data_and_unknown_text(self):
        files = {
            "README.md": ("# Getting Started\nProject documentation.", "Documentation"),
            "settings.yaml": ("service:\n  enabled: true\n", "Configuration"),
            "records.csv": ("name,value\nalpha,3\n", "Data / schema"),
            "payload.custom": ("This readable text has an unfamiliar extension.\n", "Other readable text"),
        }
        for name, (content, _) in files.items():
            (self.root / name).write_text(content, encoding="utf-8")

        for name, (_, expected_type) in files.items():
            with self.subTest(name=name):
                inspected = inspect_file(self.root / name)
                self.assertEqual(inspected.file_type, expected_type)

        extracted = extract_code(self.root)
        for content, _ in files.values():
            self.assertIn(content.splitlines()[0], extracted.context)
        report = analyze_repository(self.root, extracted.analyzed_paths, inspections=extracted.inspections)
        self.assertEqual(report["documentation_files"], 1)
        self.assertEqual(report["configuration_files"], 1)
        self.assertEqual(report["file_types"]["Data / schema"], 1)
        self.assertEqual(report["file_types"]["Other readable text"], 1)
        self.assertEqual(report["data_files"], 1)
        self.assertEqual(report["unknown_readable_files"], 1)

    def test_readme_only_and_binary_plus_readable_repositories_have_inspectable_files(self):
        readme = self.root / "README.md"
        readme.write_text("# Documentation-only project\nUsage details.\n", encoding="utf-8")
        extraction = extract_code(self.root)
        report = analyze_repository(self.root, extraction.analyzed_paths, inspections=extraction.inspections)

        self.assertEqual(report["source_files"], 0)
        self.assertEqual(report["documentation_files"], 1)
        self.assertIn("Usage details.", extraction.context)
        self.assertEqual(report["total_files"], 1)

        (self.root / "brand.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        report_with_asset = analyze_repository(self.root)
        self.assertEqual(report_with_asset["total_files"], 2)
        self.assertEqual(report_with_asset["binary_files"], 1)
        self.assertEqual(report_with_asset["documentation_files"], 1)

    def test_classifies_deployment_markup_and_stylesheet_files(self):
        samples = {
            "Dockerfile": ("FROM python:3.12\n", "Deployment"),
            "index.html": ("<main>Hello</main>\n", "Markup"),
            "site.css": ("body { color: navy; }\n", "Stylesheet"),
        }
        for filename, (content, expected_type) in samples.items():
            path = self.root / filename
            path.write_text(content, encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertEqual(inspect_file(path).file_type, expected_type)

    def test_binary_files_are_counted_and_never_extracted_as_text(self):
        (self.root / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        (self.root / "unknown.payload").write_bytes(b"PK\x03\x04" + b"\x00" * 32)
        (self.root / "notes.readable").write_text("These words are readable.\n", encoding="utf-8")

        self.assertEqual(classify_file(self.root / "diagram.png")[0], "Binary")
        self.assertTrue(classify_file(self.root / "unknown.payload")[2])
        extracted = extract_code(self.root)
        report = analyze_repository(self.root, extracted.analyzed_paths, inspections=extracted.inspections)

        self.assertEqual(report["binary_files"], 2)
        self.assertEqual(report["readable_files"], 1)
        self.assertEqual(report["total_files"], 3)
        self.assertEqual(len(report["binary_file_samples"]), 2)
        self.assertNotIn("PK", extracted.context)
        self.assertIn("These words are readable.", extracted.context)

    def test_sensitive_files_are_withheld_and_common_literals_are_redacted(self):
        (self.root / ".env").write_text("API_KEY=very-secret-api-token\n", encoding="utf-8")
        source = self.root / "settings.py"
        source.write_text(
            'API_KEY = "ghp_testSecretValueThatMustNotEscape"\n'
            'DEFAULT_TIMEOUT = 12\n',
            encoding="utf-8",
        )

        extracted = extract_code(self.root)
        report = analyze_repository(self.root, extracted.analyzed_paths, inspections=extracted.inspections)

        self.assertNotIn("very-secret-api-token", extracted.context)
        self.assertNotIn("ghp_testSecretValueThatMustNotEscape", extracted.context)
        self.assertIn("[REDACTED]", extracted.context)
        self.assertIn("Sensitive file identified", extracted.context)
        self.assertEqual(report["sensitive_files"], 1)

    def test_repository_source_is_never_executed(self):
        sentinel = self.root / "must_not_exist.txt"
        (self.root / "danger.py").write_text(
            f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n",
            encoding="utf-8",
        )

        extracted = extract_code(self.root)
        report = analyze_repository(self.root, extracted.analyzed_paths, inspections=extracted.inspections)

        self.assertIn("Path(", extracted.context)
        self.assertEqual(report["source_files"], 1)
        self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
