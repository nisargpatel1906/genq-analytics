import sys
import os
import pandas as pd
import json
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState

def test_tool_calling_loop():
    df = pd.DataFrame({
        "revenue": [100, 200, 150, 300, 400],
        "category": ["A", "B", "A", "B", "A"]
    })
    schema = {"revenue": "int64", "category": "object"}
    sample_rows = df.head(2).to_dict('records')
    domain_brief = {"domain": "Sales", "datasetPurpose": "Testing tool calling"}
    
    state = AnalysisState(
        df=df,
        schema=schema,
        sample_rows=sample_rows,
        domain_brief=domain_brief
    )
    
    graph = AgentGraph(state)

    # 1. Test inspect_column handler directly
    # Call inspect_column on a numeric column
    res_numeric = graph._data_scientist_node.__globals__["inspect_column_tool"] = lambda col: graph._data_scientist_node.__code__
    # Actually we can just run the node and mock the chat completions to call tools sequentially:
    # Round 1: inspect_column
    # Round 2: run_test
    # Round 3: save_finding
    # Round 4: done
    
    responses = [
        # Turn 1: inspect revenue column
        json.dumps({
            "thought": "I will inspect the revenue column first.",
            "tool": "inspect_column",
            "arguments": {"col_name": "revenue"}
        }),
        # Turn 2: run t_test
        json.dumps({
            "thought": "I will run a t-test of revenue grouped by category.",
            "tool": "run_test",
            "arguments": {"test_type": "t_test", "col_a": "revenue", "col_b": "category"}
        }),
        # Turn 3: save finding
        json.dumps({
            "thought": "I will save the finding about revenue differences.",
            "tool": "save_finding",
            "arguments": {"title": "Revenue Group Gaps", "evidence": "Revenue was higher in category A.", "confidence": 90}
        }),
        # Turn 4: done
        json.dumps({
            "thought": "All steps completed.",
            "tool": "done",
            "arguments": {}
        })
    ]
    
    call_idx = 0
    def mock_chat_completion(*args, **kwargs):
        nonlocal call_idx
        res = responses[call_idx]
        call_idx += 1
        return res

    with patch("services.agent_graph.chat_completion", side_effect=mock_chat_completion):
        graph._data_scientist_node()
        
        # Verify the findings are populated
        assert len(state.analysis_results["findings"]) == 1
        assert state.analysis_results["findings"][0]["title"] == "Revenue Group Gaps"
        
        # Verify the investigation log has been populated
        assert len(state.investigation_log) == 1
        assert "Saved key finding: Revenue Group Gaps" in state.investigation_log[0]["action"]
        
        # Verify stdout logs
        assert "inspect_column" in state.last_execution_stdout
        assert "run_test" in state.last_execution_stdout
        assert "save_finding" in state.last_execution_stdout
        
        print(state.last_execution_stdout)
        
        print("\nALL ITERATIVE TOOL CALLING LOOP VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_tool_calling_loop()
