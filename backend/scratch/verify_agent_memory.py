import sys
import os
import pandas as pd
import json
from unittest.mock import patch, MagicMock

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_graph import AgentGraph, AnalysisState

def test_agent_memory():
    df = pd.DataFrame({"revenue": [100, 200]})
    schema = {"revenue": "int64"}
    sample_rows = df.head(1).to_dict('records')
    domain_brief = {"domain": "Sales", "datasetPurpose": "Testing memory"}
    
    state = AnalysisState(
        df=df,
        schema=schema,
        sample_rows=sample_rows,
        domain_brief=domain_brief
    )
    
    graph = AgentGraph(state)

    # Round 1 Responses
    round_1_response = json.dumps({
        "thought": "I will inspect column revenue.",
        "tool": "inspect_column",
        "arguments": {"col_name": "revenue"}
    })
    round_1_done = json.dumps({
        "thought": "I have inspected the column, now done.",
        "tool": "done",
        "arguments": {}
    })
    
    # Round 2 Responses
    round_2_response = json.dumps({
        "thought": "I see reflector feedback. I will call done.",
        "tool": "done",
        "arguments": {}
    })

    responses_1 = [round_1_response, round_1_done]
    idx_1 = 0
    def mock_chat_1(*args, **kwargs):
        nonlocal idx_1
        res = responses_1[idx_1]
        idx_1 += 1
        return res

    # Mock chat_completion for Round 1
    with patch("services.agent_graph.chat_completion", side_effect=mock_chat_1):
        graph._data_scientist_node()
        
        # Verify conversation history was initialized
        # system + user + assistant (inspect) + user (inspect result) + assistant (done)
        assert len(state.conversation_history) == 5
        assert state.conversation_history[2]["role"] == "assistant"
        assert "inspect_column" in state.conversation_history[2]["content"]

    # Mock Reflector node to construct feedback string
    reflector_mock_response = json.dumps({
        "needs_more_analysis": True,
        "feedback": "Please segment the revenue data.",
        "follow_up_tasks": ["Segment by categories"]
    })
    with patch("services.agent_graph.chat_completion", return_value=reflector_mock_response):
        graph._reflector_node()
        assert "Segment by categories" in state.reflection_feedback_formatted

    # Mock chat_completion for Round 2
    with patch("services.agent_graph.chat_completion", return_value=round_2_response) as mock_chat_round2:
        graph._data_scientist_node(feedback=state.reflection_feedback_formatted)
        
        # Verify round 1 history is PRESERVED, and reflector feedback is APPENDED
        # Index 5 should be the Reflector feedback user instruction
        assert state.conversation_history[5]["role"] == "user"
        assert "Here is the Reflector feedback" in state.conversation_history[5]["content"]
        assert "Segment by categories" in state.conversation_history[5]["content"]
        
        # Index 6 is assistant's round 2 response
        assert state.conversation_history[6]["role"] == "assistant"
        assert "I see reflector feedback. I will call done." in state.conversation_history[6]["content"]
        
        print("Final Conversation History roles:")
        print([m["role"] for m in state.conversation_history])
        
        print("\nALL CONVERSATION HISTORY MEMORY VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_agent_memory()
