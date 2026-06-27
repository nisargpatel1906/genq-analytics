import os
import sys
import pandas as pd
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState

def test_reflection_feedback():
    df = pd.DataFrame({"col1": [1, 2, 3]})
    schema = {"col1": "int64"}
    sample_rows = [{"col1": 1}]
    domain_brief = {"domain": "Test Domain", "datasetPurpose": "Testing feedback loop"}
    
    state = AnalysisState(
        df=df,
        schema=schema,
        sample_rows=sample_rows,
        domain_brief=domain_brief,
        max_reflections=1
    )
    
    # Pre-populate execution fields in the state
    state.last_execution_stdout = "Execution completed successfully. Loaded 3 rows."
    state.last_execution_stderr = "Warning: deprecated package import."
    state.last_execution_outputs = [
        {"filename": "test_output.json", "type": "analysis_results", "purpose": "Main test statistics"},
        {"filename": "raw_stats.csv", "type": "data", "purpose": "Raw parsed output"}
    ]
    
    graph = AgentGraph(state)
    
    # Mock chat_completion for reflector node to trigger self-correction feedback loop
    reflector_response = """
    {
        "needs_more_analysis": true,
        "feedback": "Please perform a segment breakdown by col1 values.",
        "follow_up_tasks": [
            "Calculate mean of col1",
            "Identify distribution gaps"
        ]
    }
    """
    
    with patch("services.agent_graph.chat_completion", return_value=reflector_response) as mock_chat:
        graph._reflector_node()
        
        print("Generated reflection_feedback_formatted:")
        print("-" * 50)
        print(state.reflection_feedback_formatted)
        print("-" * 50)
        
        # Verify Reflector's own feedback and follow up tasks are present
        assert "Please perform a segment breakdown by col1 values." in state.reflection_feedback_formatted
        assert "Calculate mean of col1" in state.reflection_feedback_formatted
        assert "Identify distribution gaps" in state.reflection_feedback_formatted
        
        # Verify stdout, stderr, and output manifest metadata are present
        assert "Execution completed successfully. Loaded 3 rows." in state.reflection_feedback_formatted
        assert "Warning: deprecated package import." in state.reflection_feedback_formatted
        assert "test_output.json" in state.reflection_feedback_formatted
        assert "Main test statistics" in state.reflection_feedback_formatted
        assert "raw_stats.csv" in state.reflection_feedback_formatted
        assert "Raw parsed output" in state.reflection_feedback_formatted
        
        print("\nALL AGENT SELF-CORRECTION FEEDBACK VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_reflection_feedback()
