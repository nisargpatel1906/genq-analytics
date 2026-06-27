import pandas as pd
import numpy as np
import pytest

from app.utils import coerce_numeric_series, parse_json_safely
from services.analyzer import extract_statistics

def test_coerce_numeric_series():
    # Coercible strings
    s1 = pd.Series(["1.5", "2", "3.75", None, "N/A", "4"])
    coerced = coerce_numeric_series(s1)
    assert coerced.iloc[0] == 1.5
    assert coerced.iloc[1] == 2.0
    assert coerced.iloc[2] == 3.75
    assert pd.isna(coerced.iloc[3])
    assert pd.isna(coerced.iloc[4])
    assert coerced.iloc[5] == 4.0

    # Non-coercible strings
    s2 = pd.Series(["apple", "banana", "cherry"])
    coerced2 = coerce_numeric_series(s2)
    assert coerced2.isna().all()

def test_parse_json_safely():
    # Valid json with LaTeX math blocks and some markdown fluff
    json_str = """
    Here is the response:
    ```json
    {
        "text": "The equation is $E=mc^2$ or $$E = mc^2$$.",
        "value": 42
    }
    ```
    """
    parsed = parse_json_safely(json_str)
    assert parsed == {
        "text": "The equation is E=mc^2 or E = mc^2.",
        "value": 42
    }

    # Auto-repair truncated json
    truncated_str = '{"thought": "Having established smoking...", "arguments": {"x": "age"'
    parsed_truncated = parse_json_safely(truncated_str)
    assert parsed_truncated == {
        "thought": "Having established smoking...",
        "arguments": {
            "x": "age"
        }
    }

    # Auto-repair trailing commas
    trailing_comma_str = '{"value": 123, "list": [1, 2, 3,],}'
    parsed_trailing = parse_json_safely(trailing_comma_str)
    assert parsed_trailing == {
        "value": 123,
        "list": [1, 2, 3]
    }

    # Invalid json fallback
    invalid_str = "not a json string"
    parsed_invalid = parse_json_safely(invalid_str)
    assert "error" in parsed_invalid

def test_extract_statistics():
    # Sample dataframe
    df = pd.DataFrame({
        "num1": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
        "num2": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5],
        "cat1": ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B"],
        "mixed": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "ten"]
    })

    stats = extract_statistics(df)
    
    assert "shape" in stats
    assert stats["shape"]["rows"] == 10
    assert stats["shape"]["columns"] == 4
    
    assert "missing_values" in stats
    assert stats["missing_values"]["num1"] == 0
    
    assert "numeric_summary" in stats
    assert "num1" in stats["numeric_summary"]
    assert "num2" in stats["numeric_summary"]
    
    # Assert custom metrics (skewness/kurtosis) are computed
    assert "skewness" in stats["numeric_summary"]["num1"]
    assert "kurtosis" in stats["numeric_summary"]["num1"]
    
    # Assert correlations are computed
    assert "correlations" in stats
    assert "num1" in stats["correlations"]
    assert "num2" in stats["correlations"]["num1"]
