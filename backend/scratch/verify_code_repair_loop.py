import os
import sys
import pandas as pd
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState
from services.code_executor import ExecutionResult

def test_code_repair_loop_success():
    # Setup state
    df = pd.DataFrame({"age": [20, 30]})
    state = AnalysisState(df=df, schema={}, sample_rows=[], domain_brief={})
    state.visualization_data = {"visualizations": []}
    
    graph = AgentGraph(state)
    
    os.environ["CODE_REPAIR_MAX_ATTEMPTS"] = "3"
    
    # Mock chat completions:
    # 1. Initial code gen
    # 2. First repair response
    # 3. Second repair response
    mock_chat_responses = [
        "```python\n# Failed code 1\n```",
        "```python\n# Failed code 2\n```",
        "```python\n# Successful code\n```"
    ]
    
    # Mock executions:
    # 1. Initial execution fails
    # 2. First repair execution fails
    # 3. Second repair execution succeeds
    mock_exec_results = [
        ExecutionResult(success=False, stdout="", stderr="NameError: name 'df' is not defined", error_message="NameError: name 'df' is not defined"),
        ExecutionResult(success=False, stdout="", stderr="KeyError: 'Salary'", error_message="KeyError: 'Salary'"),
        ExecutionResult(success=True, stdout="", stderr="", agent_outputs=[{"type": "image", "filename": "chart.png", "data": b"mock_png"}])
    ]
    
    with patch("services.agent_graph.chat_completion", side_effect=mock_chat_responses) as mock_chat, \
         patch("services.agent_graph.execute_analysis_code", side_effect=mock_exec_results) as mock_exec, \
         patch("services.agent_graph.AgentGraph._prepare_visualization_data"):
             
        graph._viz_coder_node()
        
        # Verify executions count: 1 initial + 2 repairs = 3 total runs
        assert mock_exec.call_count == 3
        # Verify LLM calls count: 1 initial + 2 repairs = 3 total calls
        assert mock_chat.call_count == 3
        
        # Verify traceback propagation
        # Call 2 should receive error 1 traceback
        call2_messages = mock_chat.call_args_list[1][0][0]
        call2_user_content = next(msg["content"] for msg in call2_messages if msg["role"] == "user")
        assert "NameError: name 'df' is not defined" in call2_user_content
        
        # Call 3 should receive error 2 traceback
        call3_messages = mock_chat.call_args_list[2][0][0]
        call3_user_content = next(msg["content"] for msg in call3_messages if msg["role"] == "user")
        assert "KeyError: 'Salary'" in call3_user_content
        
        assert len(state.chart_images) == 1
        assert state.chart_images[0]["filename"] == "chart.png"
        
        print("Successful repair test passed.")

def test_code_repair_loop_exhaustion():
    df = pd.DataFrame({"age": [20, 30]})
    state = AnalysisState(df=df, schema={}, sample_rows=[], domain_brief={})
    state.visualization_data = {"visualizations": []}
    
    graph = AgentGraph(state)
    
    os.environ["CODE_REPAIR_MAX_ATTEMPTS"] = "3"
    
    # 4 LLM responses (1 initial + 3 repairs)
    mock_chat_responses = [
        "```python\n# Failed code 1\n```",
        "```python\n# Failed code 2\n```",
        "```python\n# Failed code 3\n```",
        "```python\n# Failed code 4\n```"
    ]
    
    # 4 Executions (1 initial + 3 repairs), all fail
    mock_exec_results = [
        ExecutionResult(success=False, stdout="", stderr="Error 1", error_message="Error 1"),
        ExecutionResult(success=False, stdout="", stderr="Error 2", error_message="Error 2"),
        ExecutionResult(success=False, stdout="", stderr="Error 3", error_message="Error 3"),
        ExecutionResult(success=False, stdout="", stderr="Error 4", error_message="Error 4")
    ]
    
    with patch("services.agent_graph.chat_completion", side_effect=mock_chat_responses) as mock_chat, \
         patch("services.agent_graph.execute_analysis_code", side_effect=mock_exec_results) as mock_exec, \
         patch("services.agent_graph.AgentGraph._prepare_visualization_data"):
             
        graph._viz_coder_node()
        
        # Max repairs is 3, so total executions should be 4 (1 initial + 3 repairs)
        assert mock_exec.call_count == 4
        assert mock_chat.call_count == 4
        
        # Verify fallback is handled gracefully
        assert len(state.chart_images) == 0
        assert not state.error
        
        print("Repair exhaustion test passed.")

if __name__ == "__main__":
    test_code_repair_loop_success()
    test_code_repair_loop_exhaustion()
    print("\nALL CODE REPAIR LOOP VERIFICATIONS PASSED SUCCESSFULLY!")
