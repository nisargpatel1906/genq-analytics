import math
import json
import logging
import re
import pandas as pd

logger = logging.getLogger("genq_api.utils")

def sanitize_json(obj):
    """
    Recursively walk through a dictionary/list and replace 
    NaN, Inf, -Inf with None (null in JSON).
    """
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj

def coerce_numeric_series(series: pd.Series) -> pd.Series:
    """Coerces a pandas Series to numeric values, removing common currency symbols and formatting."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = (
        series.astype(str)
        .str.replace(r"[,₹$€£]", "", regex=True)
        .str.replace(r"%", "", regex=True)
        .str.extract(r"(-?\d+(?:\.\d+)?)", expand=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")

def are_braces_balanced(text: str) -> bool:
    """Checks if top-level braces { } are balanced in text, respecting strings."""
    in_string = False
    escape = False
    depth = 0
    found_brace = False
    for char in text:
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == '{':
                depth += 1
                found_brace = True
            elif char == '}':
                depth -= 1
                if depth == 0 and found_brace:
                    return True
    return False


def try_repair_json(content: str) -> str:
    """Attempts to auto-repair simple JSON errors like trailing commas or missing closing structures."""
    content = content.strip()
    if "{" not in content:
        return content

    first_brace = content.find("{")
    last_brace = content.rfind("}")

    # Check if slicing between first_brace and last_brace produces a balanced root object
    if last_brace > first_brace and are_braces_balanced(content[first_brace:last_brace + 1]):
        content = content[first_brace:last_brace + 1]
    else:
        # The root object was NOT closed! Do not cut off before the end!
        content = content[first_brace:]

    # Clean up trailing commas before closing braces/brackets
    content = re.sub(r',\s*([\]}])', r'\1', content)

    # Scan characters to find unbalanced brackets or quotes
    in_string = False
    escape = False
    stack = []

    for char in content:
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == '{' or char == '[':
                stack.append(char)
            elif char == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif char == ']':
                if stack and stack[-1] == '[':
                    stack.pop()

    # If the response was cut off mid-string, terminate the string first
    if in_string:
        content += '"'

    # If the content ends with an uncompleted key or colon (e.g. '"key": ' or ',"key"'), strip it
    content = re.sub(r',\s*"[^"]*"\s*:\s*$', '', content)
    content = re.sub(r',\s*"[^"]*"\s*$', '', content)
    content = re.sub(r',\s*$', '', content)

    # Re-calculate stack for closing
    stack = []
    in_string = False
    escape = False
    for char in content:
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == '{' or char == '[':
                stack.append(char)
            elif char == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif char == ']':
                if stack and stack[-1] == '[':
                    stack.pop()

    # Append missing closing brackets/braces in reverse order
    while stack:
        open_char = stack.pop()
        if open_char == '{':
            content += '}'
        elif open_char == '[':
            content += ']'

    return content


def _raw_decode_root_object(text: str) -> dict | None:
    """
    Uses json.JSONDecoder(strict=False).raw_decode to parse the ROOT JSON object
    starting at the first '{' in `text`, ignoring any trailing content.
    Returns None if the root object cannot be parsed.
    """
    decoder = json.JSONDecoder(strict=False)
    idx = text.find("{")
    if idx == -1:
        return None
    try:
        obj, _ = decoder.raw_decode(text, idx)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    return None


def parse_json_safely(content: str) -> dict:
    """Extracts and parses JSON from LLM response.

    Handles:
    - <think>...</think> reasoning blocks (DeepSeek-R1, Gemma)
    - Markdown code fences (```json ... ``` or unclosed fences)
    - Trailing text / extra JSON blocks after the root object
    - Truncated / unbalanced JSON (smart auto-repair of root object)
    - LaTeX math formatting
    - Inline // comments
    """
    original_content = content
    content = content.strip()

    # ── 1. Strip <think>...</think> reasoning blocks ──────────────────────────
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    if content.startswith('<think>'):
        end = content.find('</think>')
        content = content[end + 8:].strip() if end != -1 else ''

    if not content:
        logger.error("LLM response was empty after stripping think-tags.")
        return {"error": "Empty response", "raw": original_content}

    # ── 2. Strip markdown code fences ─────────────────────────────────────────
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    if fence_match:
        content = fence_match.group(1).strip()
    else:
        # Strip open fence if unclosed
        fence_open = re.search(r'```(?:json)?\s*', content)
        if fence_open:
            content = content[fence_open.end():].strip()
        if content.endswith("```"):
            content = content[:-3].strip()

    # ── 3. Strip LaTeX and inline // comments ─────────────────────────────────
    content = re.sub(r'\$\\text\{([a-zA-Z]+)\}\s*=\s*([0-9\.]+)\$', r'\1 = \2', content)
    content = content.replace('$', '')
    content = re.sub(r'//[^\n]*', '', content)

    first_brace = content.find("{")
    if first_brace == -1:
        logger.error("No JSON object found in LLM response.")
        return {"error": "No JSON object found", "raw": original_content}

    root_text = content[first_brace:].strip()

    # ── 4. Fast path: raw_decode on root object ──────────────────────────────
    result = _raw_decode_root_object(root_text)
    if result is not None:
        return result

    # ── 5. Balanced slice path ───────────────────────────────────────────────
    last_brace = root_text.rfind("}")
    if last_brace != -1 and are_braces_balanced(root_text[:last_brace + 1]):
        try:
            result = json.loads(root_text[:last_brace + 1], strict=False)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # ── 6. Repair path: auto-repair truncated root object ─────────────────────
    repaired = try_repair_json(root_text)
    try:
        result = json.loads(repaired, strict=False)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    result = _raw_decode_root_object(repaired)
    if result is not None:
        return result

    # Final fallback: standard loads
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse and repair JSON output: {e}. Raw sample: {original_content[:300]}")
        return {"error": "Failed to parse JSON", "raw": original_content}

