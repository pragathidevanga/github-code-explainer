import unittest
from unittest.mock import patch

from backend.llm_service import LLMService, OllamaConfigurationError


class LocalOllamaTests(unittest.TestCase):
    def test_remote_llm_endpoint_is_rejected_before_network_access(self):
        with patch.dict("os.environ", {"OLLAMA_BASE_URL": "https://llm.example.com"}):
            service = LLMService()
            with patch.object(service._session, "request") as request:
                with self.assertRaises(OllamaConfigurationError):
                    service._request("GET", "/api/tags")
                request.assert_not_called()

    def test_malformed_endpoint_fails_with_configuration_error(self):
        with patch.dict("os.environ", {"OLLAMA_BASE_URL": "http://[invalid"}):
            service = LLMService()
            with self.assertRaises(OllamaConfigurationError):
                service._request("GET", "/api/tags")

    def test_loopback_endpoint_is_allowed_without_environment_proxy(self):
        with patch.dict("os.environ", {"OLLAMA_BASE_URL": "http://127.0.0.1:11434"}):
            service = LLMService()
            self.assertFalse(service._session.trust_env)


if __name__ == "__main__":
    unittest.main()
