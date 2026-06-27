import os
import sys
import pandas as pd
import json
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState

def test_auditor_dataset_context():
    # Setup state with known data
    df = pd.DataFrame({
        "age": [20, 30, 40],
        "salary": [10000, 20000, 30000]
    })
    schema = {"age": "int64", "salary": "int64"}
    sample_rows = []
    domain_brief = {"domain": "Test"}
    stats = {
        "numeric_summary": {
            "age": {"mean": 30.0, "min": 20.0, "max": 40.0, "sum": 90.0},
            "salary": {"mean": 20000.0, "min": 10000.0, "max": 30000.0, "sum": 60000.0}
        },
        "grouped_summary": {},
        "missing_values": {"age": 0, "salary": 0}
    }
    
    state = AnalysisState(
        df=df,
        schema=schema,
        sample_rows=sample_rows,
        domain_brief=domain_brief,
        stats=stats
    )
    
    graph = AgentGraph(state)
    
    # CASE 1: Valid report (matches stats)
    valid_report = {
        "keyFindings": [
            {
                "title": "Average age is 30",
                "detail": "The average age of the employees is 30 years.",
            },
            {
                "title": "Maximum salary is 30k",
                "detail": "We observed a peak salary of $30,000, while the lowest was $10,000.",
            }
        ]
    }
    
    warnings_valid = graph._validate_report_numbers(valid_report)
    print("Warnings for valid report (should be empty):", warnings_valid)
    assert len(warnings_valid) == 0, f"Expected no warnings, got: {warnings_valid}"
    
    # CASE 2: Invalid report (hallucinated values)
    invalid_report = {
        "keyFindings": [
            {
                "title": "Average age is 50",
                "detail": "The mean age of the employees is 50 years.", # actual mean is 30 (deviation > 20%)
            },
            {
                "title": "Minimum salary is 5k",
                "detail": "The lowest salary was 5000.", # actual min is 10000 (deviation > 20%)
            }
        ]
    }
    
    warnings_invalid = graph._validate_report_numbers(invalid_report)
    print("\nWarnings for invalid report:")
    print(json.dumps(warnings_invalid, indent=2))
    
    # Assert we caught the deviations
    assert len(warnings_invalid) == 2, f"Expected 2 warnings, got {len(warnings_invalid)}"
    finding_titles = [w["finding"] for w in warnings_invalid]
    assert "Average age is 50" in finding_titles
    assert "Minimum salary is 5k" in finding_titles
    
    # Test _auditor_node and prompt formatting
    state.report = invalid_report
    state.chart_images = []
    
    mock_audit_response = """
    {
        "approved": true,
        "score": 95,
        "sectionScores": {
            "analytical_depth": 95,
            "specificity": 95,
            "formatting_and_alignment": 95
        },
        "summary": "Looks good.",
        "issues": [],
        "retryTargets": []
    }
    """
    
    with patch("services.agent_graph.chat_completion", return_value=mock_audit_response) as mock_chat:
        graph._auditor_node()
        
        # Verify call to chat_completion
        mock_chat.assert_called_once()
        args, kwargs = mock_chat.call_args
        messages = args[0]
        user_message = next(msg["content"] for msg in messages if msg["role"] == "user")
        
        # Verify prompt components
        assert "Ground Truth Dataset Statistics" in user_message
        assert "Automated Numeric Validation Warnings" in user_message
        assert "mean age" in user_message  # the validation warning message
        
        # Verify state is updated and approved is overridden to False due to warnings
        print("\nAudit state after execution:")
        print(json.dumps(graph.state.audit, indent=2))
        
        assert graph.state.audit["approved"] is False, "Expected approved to be overridden to False"
        assert graph.state.audit["score"] < 88, "Expected score to be capped under 88"
        assert len(graph.state.audit["issues"]) == 2, "Expected 2 issues to be appended"
        assert "report" in graph.state.audit["retryTargets"], "Expected report in retry targets"
        
    print("\nALL QUALITY AUDITOR DATASET CONTEXT & VALIDATION VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_auditor_dataset_context()
