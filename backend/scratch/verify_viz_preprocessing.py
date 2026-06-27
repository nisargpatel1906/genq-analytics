import os
import sys
import pandas as pd
import json
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState

def test_visualization_preprocessing():
    df = pd.DataFrame({"col1": [1, 2, 3]})
    schema = {"col1": "int64"}
    sample_rows = [{"col1": 1}]
    domain_brief = {"domain": "Test Domain", "datasetPurpose": "Testing preprocessing"}
    
    state = AnalysisState(
        df=df,
        schema=schema,
        sample_rows=sample_rows,
        domain_brief=domain_brief
    )
    
    state.analysis_results = {
        "monthly_cohorts": {
            "findings": [
                {"title": "Retention drop in Month 2", "evidence": "Retention dropped from 80% to 40%."}
            ]
        }
    }
    
    graph = AgentGraph(state)
    
    preprocessor_response = """
    {
        "visualizations": [
            {
                "finding_title": "Retention drop in Month 2",
                "chart_type": "line",
                "x_axis": "Month",
                "y_axis": "Retention Rate",
                "data_points": {"Month 1": 0.8, "Month 2": 0.4},
                "plotting_instructions": "Plot a line chart of Retention Rate by Month using data_points."
            }
        ]
    }
    """
    
    # Mocking chat_completion for preprocessing and viz coder execution
    with patch("services.agent_graph.chat_completion", return_value=preprocessor_response) as mock_chat:
        graph._prepare_visualization_data()
        
        # Verify that state.visualization_data is set correctly
        assert state.visualization_data["visualizations"][0]["finding_title"] == "Retention drop in Month 2"
        assert state.visualization_data["visualizations"][0]["chart_type"] == "line"
        assert state.visualization_data["visualizations"][0]["data_points"]["Month 2"] == 0.4
        
        print("Preprocessed Visualization Data:")
        print(json.dumps(state.visualization_data, indent=2))
        
        # Test formatting VIZ_CODER_PROMPT with visualization_data
        from services.agent_prompts import VIZ_CODER_PROMPT
        formatted_prompt = VIZ_CODER_PROMPT.format(
            domain=state.domain_brief.get("domain"),
            full_analysis=json.dumps(state.analysis_results),
            visualization_data=json.dumps(state.visualization_data),
            schema=json.dumps(state.schema)
        )
        
        # Assert the formatted prompt contains the preprocessed plan
        assert "Retention drop in Month 2" in formatted_prompt
        assert "plotting_instructions" in formatted_prompt
        
        print("\nALL VISUALIZATION PRE-PROCESSING VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_visualization_preprocessing()
