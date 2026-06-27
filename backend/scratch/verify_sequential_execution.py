import os
import sys
import pandas as pd
import json
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState

def test_sequential_execution():
    df = pd.DataFrame({"col1": [1, 2, 3]})
    schema = {"col1": "int64"}
    sample_rows = [{"col1": 1}]
    domain_brief = {"domain": "Test Domain", "datasetPurpose": "Testing sequential execution"}
    
    state = AnalysisState(
        df=df,
        schema=schema,
        sample_rows=sample_rows,
        domain_brief=domain_brief
    )
    
    state.analysis_results = {
        "findings": [
            {"title": "Revenue growth", "evidence": "Revenue grew by 50%"}
        ]
    }
    
    graph = AgentGraph(state)
    
    # 1. Mock _viz_coder_node to populate state.chart_images
    def mock_viz_coder():
        state.chart_images = [
            {
                "filename": "revenue_growth.png",
                "title": "Revenue Growth Trend",
                "interpretation": "Line chart showing 50% growth"
            }
        ]
        state.viz_code = "print('plotting')"
        
    graph._viz_coder_node = mock_viz_coder
    
    # 2. Mock chat_completion inside _report_writer_node to return a report mapping finding to revenue_growth.png
    mock_report = """
    {
        "domain": "Test Domain",
        "executiveSummary": "Test Summary.",
        "keyFindings": [
            {
                "title": "Revenue growth",
                "detail": "Revenue grew by 50%",
                "confidence": 95,
                "impact_score": 9,
                "supporting_chart": "revenue_growth.png"
            }
        ],
        "anomalies": [],
        "recommendations": []
    }
    """
    
    with patch("services.agent_graph.chat_completion", return_value=mock_report) as mock_chat:
        # Run sequential nodes
        graph._run_visuals_and_report_sequentially()
        
        # Verify that mock_chat was called with charts info in the prompt
        called_args, called_kwargs = mock_chat.call_args
        prompt_used = called_args[0][1]["content"] # user prompt message
        
        print("Prompt passed to Report Writer contains charts:")
        print("-->", "revenue_growth.png" in prompt_used)
        assert "revenue_growth.png" in prompt_used
        assert "Revenue Growth Trend" in prompt_used
        
        # Verify final state report mapping
        assert state.report["keyFindings"][0]["supporting_chart"] == "revenue_growth.png"
        
        print("\nALL SEQUENTIAL EXECUTION AND DIRECT REFERENCE VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_sequential_execution()
