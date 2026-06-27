import logging
import os
import time
import json
import asyncio
import httpx
from typing import Any
from dotenv import load_dotenv

logger = logging.getLogger("genq_api.llm")

load_dotenv()

NVIDIA_DEFAULT_ANALYSIS_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
NVIDIA_DEFAULT_CHAT_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
NVIDIA_DEFAULT_DOMAIN_MODEL = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
NVIDIA_DEFAULT_REVIEW_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
NVIDIA_DEFAULT_VISUAL_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
NVIDIA_DEFAULT_REPORT_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

OPENROUTER_DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _get_env(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val is None:
        return default
    return str(val)


def _configured_provider(provider_override: str | None = None) -> str:
    provider = provider_override or _get_env("LLM_PROVIDER")
    if provider:
        return provider.strip().lower()
    if _get_env("GEMINI_API_KEY"):
        return "gemini"
    return "openrouter" if _get_env("OPENROUTER_API_KEY") else "nvidia"


def _model_for(task: str, provider_override: str | None = None) -> str | None:
    task_key = task.upper()
    provider = _configured_provider(provider_override)

    if provider == "nvidia":
        explicit_model = _get_env(f"LLM_{task_key}_MODEL")
        if explicit_model:
            return explicit_model.strip()

        shared_model = _get_env("LLM_MODEL")
        if shared_model:
            return shared_model.strip()

        if task == "domain":
            return _get_env("NVIDIA_DOMAIN_MODEL", NVIDIA_DEFAULT_DOMAIN_MODEL).strip()
        if task == "analysis":
            return _get_env("NVIDIA_MODEL", NVIDIA_DEFAULT_ANALYSIS_MODEL).strip()
        if task == "visual":
            return _get_env("NVIDIA_VISUAL_MODEL", NVIDIA_DEFAULT_VISUAL_MODEL).strip()
        if task == "report":
            return _get_env("NVIDIA_REPORT_MODEL", NVIDIA_DEFAULT_REPORT_MODEL).strip()
        if task == "review":
            return _get_env("NVIDIA_REVIEW_MODEL", NVIDIA_DEFAULT_REVIEW_MODEL).strip()
        return _get_env("NVIDIA_CHAT_MODEL", NVIDIA_DEFAULT_CHAT_MODEL).strip()

    if provider == "openrouter":
        val = _get_env(f"OPENROUTER_{task_key}_MODEL") or _get_env("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL)
        return val

    if provider == "gemini":
        val = _get_env(f"GEMINI_{task_key}_MODEL") or _get_env("GEMINI_MODEL", "gemini-2.5-flash")
        return val.strip()

    if provider == "ollama":
        val = _get_env(f"OLLAMA_{task_key}_MODEL") or _get_env("OLLAMA_MODEL") or _get_env("LLM_MODEL") or "gemma4:12b"
        return val.strip()

    return _get_env(f"LLM_{task_key}_MODEL") or _get_env("LLM_MODEL")


def provider_label(task: str = "chat") -> str:
    provider = _configured_provider()
    model = _model_for(task) or "unconfigured"
    return f"{provider}:{model}"


def _require_model(task: str, provider_override: str | None = None) -> tuple[str, str]:
    provider = _configured_provider(provider_override)
    model = _model_for(task, provider_override)
    if not model:
        raise RuntimeError(
            "No LLM model configured. Set NVIDIA_API_KEY for NVIDIA NIM, "
            "OPENROUTER_API_KEY for OpenRouter, GEMINI_API_KEY for Gemini, "
            "or LLM_PROVIDER=ollama for local Ollama."
        )
    return provider, model


async def _call_provider_async(provider: str, messages: list[dict[str, str]], model: str, *, task: str = "chat", json_mode: bool, timeout: int) -> str:
    # Determine base url and headers
    headers = {"Content-Type": "application/json"}
    if provider == "nvidia":
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            raise RuntimeError("NVIDIA_API_KEY is not configured in backend/.env")
        base_url = os.environ.get("NVIDIA_BASE_URL", NVIDIA_DEFAULT_BASE_URL).rstrip("/")
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured in backend/.env")
        base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured in backend/.env")
        base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    else:
        raise RuntimeError(f"Unsupported LLM provider: {provider}")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "max_tokens": 4096,
        "stream": False,
    }
    if provider == "ollama":
        # Use configurable context lengths (lower default to prevent 8B model OOMs)
        if task in ("analysis", "visual", "report"):
            num_ctx = int(os.environ.get("LLM_OLLAMA_NUM_CTX_ANALYSIS", "16384"))
            payload["options"] = {"num_ctx": num_ctx}
        else:
            num_ctx = int(os.environ.get("LLM_OLLAMA_NUM_CTX_DEFAULT", "8192"))
            payload["options"] = {"num_ctx": num_ctx}

    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    logger.info("Sending prompt to %s API (model: %s)...", provider.title(), model)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        if json_mode and response.status_code in {400, 422}:
            logger.info("%s model rejected response_format; retrying without JSON mode.", provider.title())
            payload.pop("response_format", None)
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"{provider.title()} API returned unexpected response type: {type(data)}")
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise RuntimeError(f"{provider.title()} API response has no choices: {data}")
    message = choices[0].get("message")
    if not message or not isinstance(message, dict):
        raise RuntimeError(f"{provider.title()} API response choice has invalid message: {data}")
    content = message.get("content")
    if content is None:
        content = ""
    result = str(content).strip()
    if not result:
        raise EmptyLLMResponseError(f"{provider.title()} API returned an empty completion string.")
    return result


class EmptyLLMResponseError(Exception):
    """Raised when the LLM provider returns a successful HTTP code but an empty string body."""
    pass


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, EmptyLLMResponseError):
        return True
    exc_str = str(exc).lower()
    return any(term in exc_str for term in ["429", "500", "502", "503", "504", "rate limit", "too many requests", "server error"])


def _is_worst_case_error(exc: Exception) -> bool:
    exc_str = str(exc).lower()
    return any(term in exc_str for term in ["timeout", "timed out", "connection refused", "connection reset"])


async def _retry_with_backoff_async(func, max_retries: int = 2, base_delay: float = 5.0):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            res = func()
            if asyncio.iscoroutine(res):
                return await res
            return res
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries and _is_transient_error(exc):
                delay = base_delay * (2 ** attempt)
                logger.warning("Transient error (attempt %d/%d): %s. Retrying in %.1fs...",
                               attempt + 1, max_retries + 1, exc, delay)
                await asyncio.sleep(delay)
            else:
                raise
    raise last_exc


async def _call_provider_stream_async(provider: str, messages: list[dict[str, str]], model: str, *, timeout: int):
    # Determine base url and headers
    headers = {"Content-Type": "application/json"}
    if provider == "nvidia":
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            raise RuntimeError("NVIDIA_API_KEY is not configured in backend/.env")
        base_url = os.environ.get("NVIDIA_BASE_URL", NVIDIA_DEFAULT_BASE_URL).rstrip("/")
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured in backend/.env")
        base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured in backend/.env")
        base_url = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    else:
        raise RuntimeError(f"Unsupported LLM provider: {provider}")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "max_tokens": 4096,
        "stream": True,
    }
    if provider == "ollama":
        payload["options"] = {"num_ctx": 16384}

    logger.info("Streaming from %s API (model: %s)...", provider.title(), model)
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                if line.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


async def chat_completion_stream(
    messages: list[dict[str, str]],
    *,
    task: str = "chat",
    timeout: int = 300,
    provider: str | None = None,
):
    selected_provider, model = _require_model(task, provider)
    async for chunk in _call_provider_stream_async(selected_provider, messages, model, timeout=timeout):
        yield chunk


async def chat_completion_async(
    messages: list[dict[str, str]],
    *,
    task: str = "chat",
    json_mode: bool = False,
    timeout: int = 300,
    provider: str | None = None,
) -> str:
    selected_provider, model = _require_model(task, provider)

    max_retries = 3 if selected_provider == "ollama" else 5
    base_delay = 3.0 if selected_provider == "ollama" else 8.0

    try:
        return await _retry_with_backoff_async(
            lambda: _call_provider_async(selected_provider, messages, model, task=task, json_mode=json_mode, timeout=timeout),
            max_retries=max_retries,
            base_delay=base_delay
        )
    except Exception as exc:
        fallback_provider = _get_env("LLM_FALLBACK_PROVIDER", "").strip().lower()
        if fallback_provider and fallback_provider != selected_provider:
            logger.warning(
                "%s provider failed for task '%s'; retrying with fallback '%s': %s",
                selected_provider,
                task,
                fallback_provider,
                exc,
            )
            fallback_model = _model_for(task, fallback_provider)
            if not fallback_model:
                raise
            try:
                return await _call_provider_async(fallback_provider, messages, fallback_model, task=task, json_mode=json_mode, timeout=timeout)
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Primary {selected_provider} failed: {exc}. "
                    f"Fallback {fallback_provider} also failed: {fallback_exc}"
                ) from fallback_exc
        raise

    raise RuntimeError(f"Unsupported LLM_PROVIDER '{selected_provider}'. Use 'nvidia', 'openrouter', 'gemini', or 'ollama'.")


def chat_completion(
    messages: list[dict[str, str]],
    *,
    task: str = "chat",
    json_mode: bool = False,
    timeout: int = 300,
    provider: str | None = None,
) -> str:
    coro = chat_completion_async(messages, task=task, json_mode=json_mode, timeout=timeout, provider=provider)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
        
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)
