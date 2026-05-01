import math

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
