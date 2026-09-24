# backend/tests/test_langgraph_pipeline.py

import json
import pytest
import pandas as pd
from unittest.mock import patch

from services.agent_graph import (
    build_analysis_graph,
    AgentGraph,
    AnalysisState,
    AnalysisGraphState,
    route_reflection,
    route_viz_coder,
    route_viz_repair,
    route_audit
)


def test_langgraph_structure_and_nodes():
    """Verify that the LangGraph StateGraph compiles and contains all expected agent nodes."""
    workflow = build_analysis_graph()
    app = workflow.compile()
    
    expected_nodes = {
        "data_scientist",
        "reflector",
        "viz_preprocessor",
        "viz_coder",
        "viz_repair",
        "report_writer",
        "narrative_stitcher",
        "auditor",
        "finalize"
    }
    graph_nodes = set(workflow.nodes.keys())
    assert expected_nodes.issubset(graph_nodes), f"Missing nodes: {expected_nodes - graph_nodes}"


def test_reflection_custom_loop_routing():
    """Verify conditional edge loop routing for the Reflector agent."""
    # When reflection is requested and attempts remain, loop back to data_scientist
    state_reflecting: AnalysisGraphState = {
        "_can_reflect": True,
        "reflection_iteration": 1,
        "max_reflections": 2
    }
    assert route_reflection(state_reflecting) == "data_scientist"

    # When reflection is not requested, proceed forward to viz_preprocessor
    state_done: AnalysisGraphState = {
        "_can_reflect": False,
        "reflection_iteration": 1,
        "max_reflections": 2
    }
    assert route_reflection(state_done) == "viz_preprocessor"


def test_viz_self_repair_custom_loop_routing():
    """Verify conditional edge loop routing for Visualization self-repair."""
    # When plotting failed and repair attempts remain, route to viz_repair
    state_failed: AnalysisGraphState = {
        "viz_error": "SyntaxError: invalid syntax",
        "_can_repair_viz": True,
        "viz_repair_attempts": 1
    }
    assert route_viz_coder(state_failed) == "viz_repair"

    # When plotting succeeded, proceed to report_writer
    state_success: AnalysisGraphState = {
        "viz_error": None,
        "_can_repair_viz": False,
        "viz_repair_attempts": 0
    }
    assert route_viz_coder(state_success) == "report_writer"


def test_auditor_regeneration_custom_loop_routing():
    """Verify dynamic quality control loop routing from the Quality Auditor."""
    # 1. Target: analytics -> loops back to data_scientist
    state_analytics: AnalysisGraphState = {
        "_can_retry_audit": True,
        "regeneration_round": 1,
        "max_regeneration_rounds": 2,
        "audit": {"approved": False, "retryTargets": ["analytics"]}
    }
    assert route_audit(state_analytics) == "data_scientist"

    # 2. Target: visuals -> loops back to viz_preprocessor
    state_visuals: AnalysisGraphState = {
        "_can_retry_audit": True,
        "regeneration_round": 1,
        "max_regeneration_rounds": 2,
        "audit": {"approved": False, "retryTargets": ["visuals"]}
    }
    assert route_audit(state_visuals) == "viz_preprocessor"

    # 3. Target: report -> loops back to report_writer
    state_report: AnalysisGraphState = {
        "_can_retry_audit": True,
        "regeneration_round": 1,
        "max_regeneration_rounds": 2,
        "audit": {"approved": False, "retryTargets": ["report"]}
    }
    assert route_audit(state_report) == "report_writer"

    # 4. Approved or exhausted -> advances to finalize
    state_approved: AnalysisGraphState = {
        "_can_retry_audit": False,
        "regeneration_round": 2,
        "max_regeneration_rounds": 2,
        "audit": {"approved": True, "retryTargets": []}
    }
    assert route_audit(state_approved) == "finalize"
