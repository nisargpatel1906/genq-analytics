import os
import sys
import asyncio
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

# Set up environment variables to make the client load correctly
os.environ["LLM_PROVIDER"] = "openrouter"
os.environ["OPENROUTER_API_KEY"] = "mock_openrouter_key"
os.environ["LLM_FALLBACK_PROVIDER"] = "nvidia"
os.environ["NVIDIA_API_KEY"] = "mock_nvidia_key"

from services.llm import chat_completion, chat_completion_stream

# Custom mock classes for AsyncClient
class MockResponseStream:
    def raise_for_status(self):
        pass
    async def aiter_lines(self):
        yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
        yield 'data: {"choices": [{"delta": {"content": " Async"}}]}'
        yield 'data: {"choices": [{"delta": {"content": " Stream!"}}]}'
        yield 'data: [DONE]'

class MockStreamContext:
    async def __aenter__(self):
        return MockResponseStream()
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class MockAsyncClientStream:
    def __init__(self, *args, **kwargs):
        pass
    def stream(self, method, url, **kwargs):
        return MockStreamContext()
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

async def test_async_llm_stream():
    with patch("httpx.AsyncClient", new=MockAsyncClientStream):
        chunks = []
        async for chunk in chat_completion_stream([{"role": "user", "content": "hi"}], task="chat"):
            chunks.append(chunk)
            
        print("Streamed chunks:", chunks)
        assert chunks == ["Hello", " Async", " Stream!"]
        print("Async stream verification passed.")

# Custom mock classes for standard post
class MockResponsePost:
    def raise_for_status(self):
        pass
    def json(self):
        return {
            "choices": [{"message": {"content": "Hello Sync Wrapper!"}}]
        }

class MockAsyncClientPost:
    def __init__(self, *args, **kwargs):
        pass
    async def post(self, url, **kwargs):
        return MockResponsePost()
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

def test_async_llm_completion_sync_wrapper():
    with patch("httpx.AsyncClient", new=MockAsyncClientPost):
        res = chat_completion([{"role": "user", "content": "hi"}], task="chat")
        print("Completion response:", res)
        assert res == "Hello Sync Wrapper!"
        print("Sync completion wrapper verification passed.")

# Custom mock classes for fallback
class MockAsyncClientFallback:
    def __init__(self, *args, **kwargs):
        self.call_count = 0
    async def post(self, url, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            import httpx
            raise httpx.ConnectTimeout("Connection timed out")
        
        # Fallback success response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={
            "choices": [{"message": {"content": "Fallback NIM Output!"}}]
        })
        return mock_response

    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

async def test_completion_fallback():
    # Instantiate fallback client once and patch
    fallback_client = MockAsyncClientFallback()
    with patch("httpx.AsyncClient", return_value=fallback_client):
        from services.llm import chat_completion_async
        res = await chat_completion_async([{"role": "user", "content": "hi"}], task="chat")
        print("Fallback response:", res)
        assert res == "Fallback NIM Output!"
        print("Fallback provider verification passed.")

if __name__ == "__main__":
    # Run async tests
    asyncio.run(test_async_llm_stream())
    asyncio.run(test_completion_fallback())
    # Run sync test
    test_async_llm_completion_sync_wrapper()
    print("\nALL ASYNC LLM CLIENT VERIFICATIONS PASSED SUCCESSFULLY!")
