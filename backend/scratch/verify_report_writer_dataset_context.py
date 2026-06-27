import os
import sys
import pandas as pd
import json
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState

def test_report_writer_dataset_context():
    df = pd.DataFrame({"age": [25, 30, 35], "salary": [50000, 60000, 70000]})
    schema = {"age": "int64", "salary": "int64"}
    sample_rows = [
        {"age": 25, "salary": 50000},
        {"age": 30, "salary": 60000},
        {"age": 35, "salary": 70000}
    ]
    domain_brief = {"domain": "Employee Analytics", "datasetPurpose": "Understand employee demographic distribution"}
    stats = {
        "numeric_summary": {"age": {"mean": 30.0}, "salary": {"mean": 60000.0}},
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
    
    state.analysis_results = {
        "findings": [
            {"title": "Average salary is 60k", "evidence": "The mean salary of the 3 employees is $60,000."}
        ]
    }
    state.chart_images = [
        {"title": "Salary Distribution", "filename": "salary_dist.png", "interpretation": "Distribution of salaries across the sample"}
    ]
    
    graph = AgentGraph(state)
    
    mock_report_response = """
    {
        "domain": "Employee Analytics",
        "executiveSummary": "This report examines employee demographic data... Paragraph 2... Paragraph 3.",
        "keyFindings": [
            {
                "title": "Average salary is 60k",
                "detail": "Average salary across our cohort is 60k.",
                "confidence": 95,
                "impact_score": 5,
                "supporting_chart": "salary_dist.png"
            }
        ],
        "anomalies": [],
        "recommendations": []
    }
    """
    
    with patch("services.agent_graph.chat_completion", return_value=mock_report_response) as mock_chat:
        graph._report_writer_node()
        
        # Verify call to chat_completion
        mock_chat.assert_called_once()
        args, kwargs = mock_chat.call_args
        messages = args[0]
        
        # Extract prompt content
        user_message = next(msg["content"] for msg in messages if msg["role"] == "user")
        
        # Verify prompt details
        assert "Employee Analytics" in user_message, "Domain brief not found in prompt"
        assert '"age": "int64"' in user_message, "Schema not found in prompt"
        assert '50000' in user_message, "Sample rows not found in prompt"
        assert 'Missing values:' in user_message, "Stats summary missing values not found in prompt"
        assert 'Numeric Summary:' in user_message, "Stats summary numeric summary not found in prompt"
        assert 'Average salary is 60k' in user_message, "Analysis results not found in prompt"
        assert 'salary_dist.png' in user_message, "Charts not found in prompt"
        
        # Verify state is updated with the returned mock report
        assert graph.state.report["domain"] == "Employee Analytics"
        assert graph.state.report["keyFindings"][0]["supporting_chart"] == "salary_dist.png"
        
        print("Report Writer Prompt Verification:")
        print("-" * 40)
        print(user_message[:600] + "\n...")
        print("-" * 40)
        print("\nALL REPORT WRITER DATASET CONTEXT VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_report_writer_dataset_context()
