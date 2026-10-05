import tempfile
import unittest
from pathlib import Path

from git import Repo

from backend.github_processor import EmptyRepository, GitHubProcessor
from backend.utils import InvalidGitHubURL, PROJECT_ROOT, canonicalize_github_url, repository_cache_path


class GitHubURLTests(unittest.TestCase):
    def test_accepts_supported_public_url_variants(self):
        variants = (
            "https://github.com/example/project",
            "https://github.com/example/project/",
            "https://github.com/example/project.git",
        )
        for url in variants:
            with self.subTest(url=url):
                canonical, owner, repository = canonicalize_github_url(url)
                self.assertEqual(canonical, "https://github.com/example/project.git")
                self.assertEqual((owner, repository), ("example", "project"))

    def test_rejects_non_github_and_non_repository_urls(self):
        invalid_urls = (
            "http://github.com/example/project",
            "https://github.com/example/project/issues",
            "https://github.com.evil.test/example/project",
            "https://user:secret@github.com/example/project",
            "https://github.com/example/../secret",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(InvalidGitHubURL):
                canonicalize_github_url(url)

    def test_cache_path_is_scoped_to_repository_cache(self):
        from backend.utils import PROJECT_ROOT

        cache = repository_cache_path("owner", "repo")
        self.assertEqual(cache.parent, (PROJECT_ROOT / "repositories").resolve())

    def test_processor_exposes_a_local_clone_entry_point(self):
        self.assertTrue(callable(GitHubProcessor().clone_repository))

    def test_readme_only_repository_is_not_empty_and_git_tree_restores_checkout(self):
        cache_root = PROJECT_ROOT / "repositories"
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache_root) as temporary_directory:
            root = Path(temporary_directory)
            repository = Repo.init(root)
            with repository.config_writer() as config:
                config.set_value("user", "name", "Test")
                config.set_value("user", "email", "test@example.invalid")
            readme = root / "README.md"
            readme.write_text("# Documentation-only project\n", encoding="utf-8")
            repository.index.add([str(readme)])
            repository.index.commit("Add README")
            readme.unlink()

            GitHubProcessor._materialize_repository_files(repository, root)
            GitHubProcessor._check_nonempty(root)

            self.assertIn("Documentation-only project", readme.read_text(encoding="utf-8"))
            self.assertTrue(GitHubProcessor._is_portable_git_path("README.md"))
            repository.close()

    def test_empty_repository_is_rejected_but_unrepresentable_tree_paths_are_skipped(self):
        cache_root = PROJECT_ROOT / "repositories"
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache_root) as temporary_directory:
            root = Path(temporary_directory)
            repository = Repo.init(root)
            self.assertEqual(GitHubProcessor._materialize_repository_files(repository, root), 0)
            repository.close()
            with self.assertRaises(EmptyRepository):
                GitHubProcessor._check_nonempty(root)

        self.assertFalse(GitHubProcessor._is_portable_git_path("Experiment No:2/README.md"))
        self.assertFalse(GitHubProcessor._is_portable_git_path("CON.txt"))


if __name__ == "__main__":
    unittest.main()
