import logging
import os
import time
import json
import asyncio
import httpx
from typing import Any
from dotenv import load_dotenv

logger = logging.getLogger("genq_api.llm")

_backend_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_backend_env):
    load_dotenv(_backend_env, override=True)
else:
    load_dotenv(override=True)

# Exclusive OpenRouter Configuration
OPENROUTER_DEFAULT_MODEL = "qwen/qwen3.8-27b:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Active API key rotation index
_CURRENT_KEY_INDEX = 0


def _get_api_keys() -> list[str]:
    """Returns a deduplicated list of available OpenRouter API keys."""
    keys: list[str] = []
    # Check comma-separated pool
    keys_csv = os.environ.get("OPENROUTER_API_KEYS", "")
    if keys_csv:
        for k in keys_csv.split(","):
            cleaned = k.strip()
            if cleaned and cleaned not in keys:
                keys.append(cleaned)

    # Check primary key
    primary = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if primary and primary not in keys:
        keys.append(primary)

    # Check fallback key
    fallback = os.environ.get("OPENROUTER_FALLBACK_API_KEY", "").strip()
    if fallback and fallback not in keys:
        keys.append(fallback)

    return keys


def _get_current_key() -> str:
    global _CURRENT_KEY_INDEX
    keys = _get_api_keys()
    if not keys:
        raise RuntimeError("OPENROUTER_API_KEY is not configured in backend/.env")
    return keys[_CURRENT_KEY_INDEX % len(keys)]


def _rotate_to_next_key() -> str | None:
    """Rotates to the next available OpenRouter key if multiple exist."""
    global _CURRENT_KEY_INDEX
    keys = _get_api_keys()
    if len(keys) <= 1:
        return None
    _CURRENT_KEY_INDEX = (_CURRENT_KEY_INDEX + 1) % len(keys)
    new_key = keys[_CURRENT_KEY_INDEX]
    masked = new_key[:8] + "..." + new_key[-4:] if len(new_key) > 12 else "***"
    logger.info("Rotated to alternate OpenRouter API key: %s (Key #%d of %d)", masked, _CURRENT_KEY_INDEX + 1, len(keys))
    return new_key


NVIDIA_DEFAULT_MODEL = "moonshotai/kimi-k3"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _get_nvidia_api_key() -> str:
    return os.environ.get("NVIDIA_API_KEY", "").strip()


def _normalize_nvidia_model(model_name: str) -> str:
    """Normalizes model names, handling common build.nvidia.com URL slugs."""
    name = model_name.strip()
    # Web catalog URLs often use dashes where the NIM API expects dots
    name = name.replace("glm-5-3", "glm-5.3")
    return name


def _get_nvidia_candidate_models(primary_model: str) -> list[str]:
    """Returns the ordered list of candidate models starting with the primary model."""
    candidates = [_normalize_nvidia_model(primary_model)]

    raw_fallbacks = os.environ.get("NVIDIA_FALLBACK_MODELS", "").strip()
    if not raw_fallbacks:
        raw_fallbacks = os.environ.get("NVIDIA_FALLBACK_MODEL", "").strip()

    if raw_fallbacks:
        for m in raw_fallbacks.split(","):
            norm = _normalize_nvidia_model(m)
            if norm and norm not in candidates:
                candidates.append(norm)

    return candidates


def _model_for(task: str = "chat", provider_override: str | None = None) -> str:
    provider = (provider_override or os.environ.get("LLM_PROVIDER", "openrouter")).lower()
    if provider == "nvidia":
        task_key = task.upper()
        raw_m = (
            os.environ.get(f"NVIDIA_{task_key}_MODEL")
            or os.environ.get("NVIDIA_MODEL")
            or os.environ.get(f"LLM_{task_key}_MODEL")
            or NVIDIA_DEFAULT_MODEL
        )
        return _normalize_nvidia_model(raw_m)
    task_key = task.upper()
    return (
        os.environ.get(f"OPENROUTER_{task_key}_MODEL")
        or os.environ.get("OPENROUTER_MODEL")
        or os.environ.get(f"LLM_{task_key}_MODEL")
        or OPENROUTER_DEFAULT_MODEL
    )


def _openrouter_models_to_try(task: str = "chat") -> list[str]:
    candidates = []
    primary = _model_for(task, provider_override="openrouter")
    if primary:
        candidates.append(primary)
    raw_fallbacks = os.environ.get("OPENROUTER_FALLBACK_MODELS", "").strip()
    if raw_fallbacks:
        for m in raw_fallbacks.split(","):
            m = m.strip()
            if m and m not in candidates:
                candidates.append(m)
    return candidates


def provider_label(task: str = "chat") -> str:
    prov, model = _require_model(task)
    return f"{prov}:{model}"


def _require_model(task: str = "chat", provider_override: str | None = None) -> tuple[str, str]:
    provider = (provider_override or os.environ.get("LLM_PROVIDER", "openrouter")).lower()
    return provider, _model_for(task, provider_override=provider)


class EmptyLLMResponseError(Exception):
    """Raised when the LLM provider returns a successful HTTP code but an empty string body."""
    pass


class OpenRouterRateLimitError(Exception):
    """Raised when OpenRouter rate limit is exhausted across all available keys."""
    pass


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (EmptyLLMResponseError, OpenRouterRateLimitError)):
        return True
    exc_str = str(exc).lower()
    return any(term in exc_str for term in ["429", "500", "502", "503", "504", "rate limit", "too many requests", "server error"])


async def _retry_with_backoff_async(func, max_retries: int = 5, base_delay: float = 6.0):
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
                # Try rotating key if it was a rate limit
                if "429" in str(exc) or "rate limit" in str(exc).lower():
                    rotated = _rotate_to_next_key()
                    if rotated:
                        logger.info("Attempting retry with newly rotated OpenRouter key...")
                        await asyncio.sleep(1.0)
                        continue

                delay = base_delay * (1.8 ** attempt)
                if hasattr(exc, "response") and exc.response is not None:
                    retry_after = exc.response.headers.get("retry-after")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after) + 1.0)
                        except ValueError:
                            pass
                    reset_tokens = exc.response.headers.get("x-ratelimit-reset-tokens")
                    if reset_tokens:
                        try:
                            val = float(str(reset_tokens).rstrip("s"))
                            delay = max(delay, val + 1.0)
                        except ValueError:
                            pass

                logger.warning(
                    "OpenRouter transient error (attempt %d/%d): %s. Backing off for %.1fs...",
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                raise
    raise last_exc


async def _call_openrouter_async(
    messages: list[dict[str, str]],
    model: str,
    *,
    task: str = "chat",
    json_mode: bool = False,
    timeout: int = 300,
) -> str:
    base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
    api_key = _get_current_key()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "http://localhost:8000"),
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "GenQ Analytics"),
    }

    max_tok = int(os.environ.get("OPENROUTER_MAX_TOKENS", "4096"))
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "max_tokens": max_tok,
    }

    # Ling model supports standard prompting for JSON
    # When json_mode is requested, we prompt via system instructions
    if json_mode and not any(term in model.lower() for term in ["ling", "free"]):
        payload["response_format"] = {"type": "json_object"}

    masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
    t0 = time.time()
    print(f"\n[{time.strftime('%H:%M:%S')}] [OpenRouter] -> Task '{task}' calling {model} (Key: {masked_key})...", flush=True)
    logger.info("Sending prompt to OpenRouter API (model: %s, key: %s)...", model, masked_key)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )

        if response.status_code == 429:
            err_msg = ""
            try:
                err_data = response.json()
                err_msg = err_data.get("error", {}).get("message", "")
            except Exception:
                err_msg = response.text[:200]

            print(f"[{time.strftime('%H:%M:%S')}] [OpenRouter] ⚠️ 429 Rate Limit on key {masked_key}: {err_msg}", flush=True)
            logger.warning("OpenRouter returned 429 Too Many Requests: %s", err_msg)
            
            # Rotate key if available
            rotated_key = _rotate_to_next_key()
            if rotated_key:
                masked_rotated = rotated_key[:6] + "..." + rotated_key[-4:] if len(rotated_key) > 10 else "***"
                print(f"[{time.strftime('%H:%M:%S')}] [OpenRouter] 🔄 Seamlessly rotating to alternate key: {masked_rotated}...", flush=True)
                logger.info("Retrying with rotated OpenRouter fallback key...")
                headers["Authorization"] = f"Bearer {rotated_key}"
                await asyncio.sleep(1.0)
                response = await client.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

        if response.status_code == 429:
            err_body = ""
            try:
                err_body = response.json().get("error", {}).get("message", "")
            except Exception:
                err_body = response.text[:200]
            print(f"[{time.strftime('%H:%M:%S')}] [OpenRouter] ❌ 429 Rate Limit exhausted across keys.", flush=True)
            raise OpenRouterRateLimitError(
                f"OpenRouter 429 Rate Limit on model '{model}': {err_body or 'Too Many Requests'}. "
                f"If using the free tier, consider adding an additional key or rotating keys in backend/.env."
            )

        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(f"OpenRouter API returned unexpected response type: {type(data)}")
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise RuntimeError(f"OpenRouter API response has no choices: {data}")
    message = choices[0].get("message")
    if not message or not isinstance(message, dict):
        raise RuntimeError(f"OpenRouter API response choice has invalid message: {data}")
    content = message.get("content")
    if not content:
        # Fallback to reasoning field if content is empty
        content = message.get("reasoning") or ""
    result = str(content).strip()
    if not result:
        raise EmptyLLMResponseError("OpenRouter API returned an empty completion string.")

    elapsed = time.time() - t0
    print(f"[{time.strftime('%H:%M:%S')}] [OpenRouter] ✅ Task '{task}' completed in {elapsed:.2f}s ({len(result)} chars)", flush=True)
    return result


async def _call_openrouter_stream_async(messages: list[dict[str, str]], model: str, *, timeout: int):
    base_url = os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL).rstrip("/")
    api_key = _get_current_key()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": os.environ.get("OPENROUTER_SITE_URL", "http://localhost:8000"),
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "GenQ Analytics"),
    }

    max_tok = int(os.environ.get("OPENROUTER_MAX_TOKENS", "4096"))
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "max_tokens": max_tok,
        "stream": True,
    }

    logger.info("Streaming from OpenRouter API (model: %s)...", model)

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
                    if not content and "reasoning" in delta:
                        content = delta.get("reasoning", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


async def _call_nvidia_async(
    messages: list[dict[str, str]],
    model: str,
    *,
    task: str = "chat",
    json_mode: bool = False,
    timeout: int = 60,
) -> str:
    base_url = os.environ.get("NVIDIA_BASE_URL", NVIDIA_BASE_URL).rstrip("/")
    api_key = _get_nvidia_api_key()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not configured in backend/.env")

    model = _normalize_nvidia_model(model)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    max_tok = int(os.environ.get("NVIDIA_MAX_TOKENS", "4096"))
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "max_tokens": max_tok,
    }

    masked_key = api_key[:6] + "..." + api_key[-4:] if len(api_key) > 10 else "***"
    t0 = time.time()
    print(f"\n[{time.strftime('%H:%M:%S')}] [NVIDIA NIM] -> Task '{task}' calling {model} (Key: {masked_key})...", flush=True)
    logger.info("Sending prompt to NVIDIA NIM API (model: %s)...", model)

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices", [])
    if not choices or not isinstance(choices, list):
        raise RuntimeError(f"NVIDIA API response has no choices: {data}")
    message = choices[0].get("message", {})
    content = message.get("content") or message.get("reasoning_content") or message.get("reasoning") or ""
    result = str(content).strip()
    if not result:
        raise EmptyLLMResponseError("NVIDIA NIM API returned an empty completion string.")

    elapsed = time.time() - t0
    print(f"[{time.strftime('%H:%M:%S')}] [NVIDIA NIM] ✅ Task '{task}' completed in {elapsed:.2f}s ({len(result)} chars)", flush=True)
    return result


async def _call_nvidia_stream_async(
    messages: list[dict[str, str]],
    model: str,
    *,
    timeout: int = 60,
):
    base_url = os.environ.get("NVIDIA_BASE_URL", NVIDIA_BASE_URL).rstrip("/")
    api_key = _get_nvidia_api_key()
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not configured in backend/.env")

    model = _normalize_nvidia_model(model)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
    }

    max_tok = int(os.environ.get("NVIDIA_MAX_TOKENS", "4096"))
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.2")),
        "max_tokens": max_tok,
        "stream": True,
    }

    logger.info("Streaming from NVIDIA NIM API (model: %s)...", model)

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
                    if not content:
                        content = delta.get("reasoning_content") or delta.get("reasoning") or ""
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
    prov, model = _require_model(task, provider_override=provider)
    if prov == "nvidia":
        candidates = _get_nvidia_candidate_models(model)
        nvidia_timeout = int(os.environ.get("NVIDIA_TIMEOUT", str(timeout)))
        fallback_timeout = int(os.environ.get("NVIDIA_FALLBACK_TIMEOUT", "300"))

        stream_started = False
        for idx, candidate in enumerate(candidates):
            cur_timeout = nvidia_timeout if idx == 0 else fallback_timeout
            try:
                async for chunk in _call_nvidia_stream_async(messages, candidate, timeout=cur_timeout):
                    stream_started = True
                    yield chunk
                if stream_started:
                    return
            except Exception as stream_err:
                logger.warning("[NVIDIA NIM] Streaming error with model '%s': %s", candidate, stream_err)
                if stream_started:
                    return

        # Fallback to OpenRouter stream if configured
        fallback_provider = os.environ.get("LLM_FALLBACK_PROVIDER", "").strip().lower()
        if fallback_provider == "openrouter":
            for or_model in _openrouter_models_to_try(task):
                try:
                    async for chunk in _call_openrouter_stream_async(messages, or_model, timeout=timeout):
                        yield chunk
                    return
                except Exception as stream_err:
                    logger.warning("[OpenRouter] Streaming error with model '%s': %s", or_model, stream_err)
    else:
        for or_model in _openrouter_models_to_try(task):
            try:
                async for chunk in _call_openrouter_stream_async(messages, or_model, timeout=timeout):
                    yield chunk
                return
            except Exception as stream_err:
                logger.warning("[OpenRouter] Streaming error with model '%s': %s", or_model, stream_err)


async def chat_completion_async(
    messages: list[dict[str, str]],
    *,
    task: str = "chat",
    json_mode: bool = False,
    timeout: int = 300,
    provider: str | None = None,
) -> str:
    prov, model = _require_model(task, provider_override=provider)

    if prov == "nvidia":
        candidates = _get_nvidia_candidate_models(model)
        nvidia_timeout = int(os.environ.get("NVIDIA_TIMEOUT", str(timeout)))
        fallback_timeout = int(os.environ.get("NVIDIA_FALLBACK_TIMEOUT", "300"))

        last_error = None
        for idx, candidate in enumerate(candidates):
            is_primary = (idx == 0)
            cur_timeout = nvidia_timeout if is_primary else fallback_timeout

            if not is_primary:
                print(
                    f"[{time.strftime('%H:%M:%S')}] [NVIDIA NIM] 🔄 Fallback ({idx}/{len(candidates)-1}) -> Attempting model '{candidate}' (Timeout: {cur_timeout}s)...",
                    flush=True,
                )
                logger.info("[NVIDIA NIM] Cascading fallback (%d/%d) to model '%s'...", idx, len(candidates) - 1, candidate)

            try:
                result = await _call_nvidia_async(
                    messages, candidate, task=task, json_mode=json_mode, timeout=cur_timeout
                )
                if not is_primary:
                    print(
                        f"[{time.strftime('%H:%M:%S')}] [NVIDIA NIM] ✅ Fallback model '{candidate}' succeeded for task '{task}'!",
                        flush=True,
                    )
                return result
            except Exception as n_err:
                last_error = n_err
                err_detail = str(n_err) or f"Read timed out after {cur_timeout}s with 0 bytes received"
                err_desc = f"{type(n_err).__name__}: {err_detail}"
                logger.warning(
                    "[NVIDIA NIM] Candidate '%s' failed: %s", candidate, err_desc
                )
                print(
                    f"[{time.strftime('%H:%M:%S')}] [NVIDIA NIM] ⚠️ Model '{candidate}' failed: {err_desc}",
                    flush=True,
                )
                continue

        # If all NVIDIA candidate models failed, check if OpenRouter fallback is permitted
        fallback_provider = os.environ.get("LLM_FALLBACK_PROVIDER", "").strip().lower()
        if fallback_provider == "openrouter":
            print(
                f"[{time.strftime('%H:%M:%S')}] [NVIDIA NIM] ⚠️ All configured NVIDIA NIM models exhausted ({candidates}). Falling back to OpenRouter...",
                flush=True,
            )
            or_candidates = _openrouter_models_to_try(task)
            last_or_err = None
            for or_model in or_candidates:
                try:
                    return await _retry_with_backoff_async(
                        lambda: _call_openrouter_async(messages, or_model, task=task, json_mode=json_mode, timeout=timeout),
                        max_retries=2,
                        base_delay=2.0,
                    )
                except Exception as or_err:
                    last_or_err = or_err
                    logger.warning("[OpenRouter] Model '%s' failed: %s", or_model, or_err)
                    print(f"[{time.strftime('%H:%M:%S')}] [OpenRouter] ⚠️ Model '{or_model}' failed, attempting fallback...", flush=True)
                    continue
            if last_or_err:
                raise last_or_err

        # If fallback exhausted and no alternate provider, raise informative error
        if last_error:
            if not str(last_error):
                raise RuntimeError(
                    f"All configured NVIDIA NIM models {candidates} timed out with 0 bytes received from NVIDIA cloud workers."
                ) from last_error
            raise last_error

    or_candidates = _openrouter_models_to_try(task)
    last_or_err = None
    for or_model in or_candidates:
        try:
            return await _retry_with_backoff_async(
                lambda: _call_openrouter_async(messages, or_model, task=task, json_mode=json_mode, timeout=timeout),
                max_retries=2,
                base_delay=2.0,
            )
        except Exception as or_err:
            last_or_err = or_err
            logger.warning("[OpenRouter] Model '%s' failed: %s", or_model, or_err)
            print(f"[{time.strftime('%H:%M:%S')}] [OpenRouter] ⚠️ Model '{or_model}' failed, attempting fallback...", flush=True)
            continue
    if last_or_err:
        raise last_or_err


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
