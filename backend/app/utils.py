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

def try_repair_json(content: str) -> str:
    """Attempts to auto-repair simple JSON errors like trailing commas or missing closing structures."""
    content = content.strip()
    
    # Extract JSON substring if possible
    if "{" in content:
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if last_brace > first_brace:
            content = content[first_brace:last_brace + 1]
        else:
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
        
    # Append missing closing brackets/braces in reverse order
    while stack:
        open_char = stack.pop()
        if open_char == '{':
            content += '}'
        elif open_char == '[':
            content += ']'
            
    return content

def _raw_decode_first_object(text: str) -> dict | None:
    """
    Uses json.JSONDecoder.raw_decode to parse the FIRST complete JSON object
    in `text`, ignoring any trailing content (extra text, extra JSON blocks, etc.).
    Returns None if no valid JSON object can be found.
    """
    decoder = json.JSONDecoder()
    # Scan forward to the first '{' and try decoding from there
    idx = text.find("{")
    while idx != -1:
        try:
            obj, _ = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = text.find("{", idx + 1)
    return None


def parse_json_safely(content: str) -> dict:
    """Extracts and parses JSON from LLM response.

    Handles:
    - <think>...</think> reasoning blocks (DeepSeek-R1, Gemma)
    - Markdown code fences (```json ... ```)
    - Trailing text / extra JSON blocks after the main object  ← "Extra data" fix
    - Truncated / unbalanced JSON (auto-repair)
    - LaTeX math formatting
    - Inline // comments
    """
    original_content = content
    content = content.strip()

    # ── 1. Strip <think>...</think> reasoning blocks ──────────────────────────
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    # Also handle partial/unclosed think blocks at the very start
    if content.startswith('<think>'):
        end = content.find('</think>')
        content = content[end + 8:].strip() if end != -1 else ''

    if not content:
        logger.error("LLM response was empty after stripping think-tags.")
        return {"error": "Empty response", "raw": original_content}

    # ── 2. Strip markdown code fences ─────────────────────────────────────────
    # Handle both ```json\n...\n``` and ```\n...\n``` forms, possibly with
    # trailing text after the closing fence.
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    if fence_match:
        content = fence_match.group(1).strip()
    else:
        # No fences — strip any leading/trailing ``` in case they're unclosed
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    # ── 3. Strip LaTeX and inline // comments ─────────────────────────────────
    content = re.sub(r'\$\\text\{([a-zA-Z]+)\}\s*=\s*([0-9\.]+)\$', r'\1 = \2', content)
    content = content.replace('$', '')
    # Remove JS-style inline comments that some models add (// ...) inside JSON
    content = re.sub(r'//[^\n]*', '', content)

    # ── 4. Fast path: raw_decode grabs the FIRST valid JSON object ────────────
    # This handles "Extra data" (trailing text / multiple blocks) correctly.
    result = _raw_decode_first_object(content)
    if result is not None:
        return result

    # ── 5. Repair path: try to close truncated / malformed JSON ───────────────
    repaired = try_repair_json(content)
    result = _raw_decode_first_object(repaired)
    if result is not None:
        return result

    # Final fallback: standard loads for a clean error message
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse and repair JSON output: {e}")
        logger.debug(f"Raw content: {original_content[:500]}")
        return {"error": "Failed to parse JSON", "raw": original_content}
