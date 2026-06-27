# scratch/verify_fallback.py

import sys
sys.path.insert(0, '.')

import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import httpx

from services.llm import chat_completion, _call_provider_async


class TestLLMFallbackAndResilience(unittest.TestCase):

    @patch('httpx.AsyncClient.post')
    def test_call_nvidia_null_content(self, mock_post):
        # Mock successful API call returning null content in choice message
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call nvidia
        res = asyncio.run(_call_provider_async("nvidia", [{"role": "user", "content": "hello"}], "nvidia/llama-3.3-nemotron-super-49b-v1.5", json_mode=False, timeout=10))
        self.assertEqual(res, "")

    @patch('httpx.AsyncClient.post')
    def test_call_openrouter_null_content(self, mock_post):
        # Mock successful API call returning null content in choice message
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call openrouter
        res = asyncio.run(_call_provider_async("openrouter", [{"role": "user", "content": "hello"}], "nvidia/nemotron-3-super-120b-a12b:free", json_mode=False, timeout=10))
        self.assertEqual(res, "")

    @patch('httpx.AsyncClient.post')
    @patch('services.llm._get_env')
    def test_chat_completion_fallback_to_nvidia(self, mock_get_env, mock_post):
        # Configure fallback env vars
        mock_get_env.side_effect = lambda key, default="": {
            "LLM_PROVIDER": "openrouter",
            "LLM_FALLBACK_PROVIDER": "nvidia",
            "OPENROUTER_API_KEY": "sk-or-v1-test",
            "NVIDIA_API_KEY": "nvapi-test",
        }.get(key, default)

        # Mock calls
        # 1st call: OpenRouter fails with 429
        # 2nd call: Nvidia succeeds with valid content
        mock_resp_openrouter = MagicMock()
        mock_resp_openrouter.status_code = 429
        mock_resp_openrouter.raise_for_status.side_effect = httpx.HTTPStatusError("429 Too Many Requests", request=MagicMock(), response=mock_resp_openrouter)

        mock_resp_nvidia = MagicMock()
        mock_resp_nvidia.status_code = 200
        mock_resp_nvidia.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "NVIDIA Response text"
                    }
                }
            ]
        }

        # Mock the consecutive post requests
        # _retry_with_backoff_async will try openrouter 6 times (1 initial + 5 retries).
        # We can mock it returning 429 for all of them.
        responses = [mock_resp_openrouter] * 6 + [mock_resp_nvidia]
        mock_post.side_effect = responses

        # We also need to patch asyncio.sleep to avoid waiting during test retries
        with patch('asyncio.sleep') as mock_sleep:
            res = chat_completion([{"role": "user", "content": "hello"}], task="chat")
            self.assertEqual(res, "NVIDIA Response text")
            self.assertEqual(mock_post.call_count, 7)  # 6 openrouter attempts + 1 nvidia fallback attempt


if __name__ == "__main__":
    unittest.main()
