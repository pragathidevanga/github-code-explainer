import tempfile
import unittest
from pathlib import Path

from backend.code_extractor import extract_code
from backend.repository_analyzer import analyze_repository
from backend.technology_detector import detect_languages, detect_technologies


class RepositoryAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_ignores_generated_directories_and_binary_files(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        (self.root / "src" / "photo.png").write_bytes(b"\x89PNG")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "ignored.js").write_text("ignored()", encoding="utf-8")

        result = extract_code(self.root)
        self.assertIn("src/main.py", result.analyzed_paths)
        self.assertNotIn("src/photo.png", result.analyzed_paths)
        self.assertNotIn("node_modules/ignored.js", result.analyzed_paths)

    def test_detects_language_counts_from_extensions(self):
        (self.root / "main.py").write_text("pass\n", encoding="utf-8")
        (self.root / "app.js").write_text("export const value = 1;\n", encoding="utf-8")

        self.assertEqual(detect_languages(self.root), {"JavaScript": 1, "Python": 1})

    def test_tree_and_file_analysis_reflect_repository_contents(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text(
            '"""Runs the app entry point."""\nfrom fastapi import FastAPI\n\n'
            "class Service:\n    pass\n\ndef run():\n    return Service()\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text("# Example project\n", encoding="utf-8")

        report = analyze_repository(self.root)
        self.assertIn("src", report["folder_tree"])
        self.assertIn("main.py", report["folder_tree"])
        self.assertEqual(report["total_files"], 2)
        main = next(item for item in report["file_analysis"] if item.path == "src/main.py")
        self.assertIn("Service", main.classes)
        self.assertIn("run", main.functions)
        self.assertEqual(main.purpose, "Runs the app entry point.")
        self.assertEqual(report["entry_points"], ["src/main.py"])

    def test_reports_nested_important_folder_purpose_from_contents(self):
        components = self.root / "src" / "components"
        components.mkdir(parents=True)
        (components / "Button.jsx").write_text("export function Button() { return null; }\n", encoding="utf-8")

        report = analyze_repository(self.root)
        component_folder = next(folder for folder in report["important_folders"] if folder["path"] == "src/components")
        self.assertIn("1 supported source file", component_folder["purpose"])

    def test_technology_detection_requires_repository_evidence(self):
        (self.root / "service.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
        )
        self.assertEqual(detect_technologies(self.root), ["FastAPI", "Python"])

    def test_readme_documentation_can_provide_technology_evidence(self):
        (self.root / "README.md").write_text(
            "Uses Microsoft Power BI, Power Query, DAX, and Microsoft Excel.\n",
            encoding="utf-8",
        )
        self.assertEqual(
            detect_technologies(self.root),
            ["DAX", "Microsoft Excel", "Power BI", "Power Query"],
        )

    def test_javascript_node_repository_uses_manifest_and_source_evidence(self):
        (self.root / "package.json").write_text(
            '{"engines":{"node":">=20"},"dependencies":{"react":"^18.0.0"}}\n',
            encoding="utf-8",
        )
        (self.root / "app.js").write_text(
            "import React from 'react';\nexport const App = () => null;\n",
            encoding="utf-8",
        )
        self.assertEqual(detect_languages(self.root), {"JavaScript": 1})
        self.assertEqual(detect_technologies(self.root), ["Node.js", "React"])

    def test_configuration_heavy_repository_counts_manifest_types(self):
        (self.root / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("[project]\nname = 'sample'\n", encoding="utf-8")
        (self.root / "settings.yaml").write_text("service:\n  enabled: true\n", encoding="utf-8")
        report = analyze_repository(self.root)
        self.assertEqual(report["source_files"], 0)
        self.assertEqual(report["configuration_files"], 3)

    def test_extraction_respects_total_context_limit(self):
        (self.root / "README.md").write_text("# Project\n", encoding="utf-8")
        (self.root / "main.py").write_text("x" * 500, encoding="utf-8")

        result = extract_code_with_limits(self.root, 120)
        self.assertLessEqual(result.context_size, 120)


def extract_code_with_limits(root: Path, maximum: int):
    from unittest.mock import patch

    with patch.dict("os.environ", {"MAX_TOTAL_CONTEXT": str(maximum), "MAX_FILE_SIZE": "1000", "MAX_FILES": "80"}):
        return extract_code(root)


if __name__ == "__main__":
    unittest.main()
