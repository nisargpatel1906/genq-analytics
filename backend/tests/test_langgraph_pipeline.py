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
    route_audit,
    data_cleaner_node,
    hypothesis_planner_node,
    ml_modeler_node,
    _generate_deterministic_fallback_charts,
)


def test_langgraph_structure_and_nodes():
    """Verify that the LangGraph StateGraph compiles and contains all expected agent nodes."""
    workflow = build_analysis_graph()
    app = workflow.compile()
    
    expected_nodes = {
        "data_cleaner",
        "hypothesis_planner",
        "data_scientist",
        "reflector",
        "viz_preprocessor",
        "viz_coder",
        "viz_repair",
        "forecaster",
        "anomaly_detector",
        "experimentation",
        "ml_modeler",
        "strategic_advisor",
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


def test_data_cleaner_node_deterministic():
    """Verify data_cleaner_node cleans duplicates, standardizes casing, and handles missing values."""
    df_raw = pd.DataFrame({
        "id": [1, 2, 2, 3, 4, 5, 6, 7, 8, 9],
        "region": [" North ", "north", "north", "SOUTH", "South", "East", "West", "east ", "East", "West"],
        "revenue": [100.0, 150.0, 150.0, None, 200.0, 250.0, 300.0, 350.0, 400.0, 450.0]
    })
    state = {
        "df": df_raw,
        "schema": {c: str(df_raw[c].dtype) for c in df_raw.columns},
        "stats": {
            "missing_values": {"revenue": 1},
            "data_quality": {"notable_issues": ["Duplicates detected", "Missing values in revenue"]}
        },
        "sample_rows": df_raw.head(5).to_dict("records"),
        "domain_brief": {"domain": "Sales"}
    }
    with patch("services.agent_graph.chat_completion", side_effect=Exception("Mock LLM offline")):
        res = data_cleaner_node(state)
    
    assert "df" in res
    assert "cleaning_manifest" in res
    cleaned = res["df"]
    manifest = res["cleaning_manifest"]

    # Duplicates removed (1 duplicate row removed: 10 -> 9)
    assert len(cleaned) == 9
    assert manifest["duplicates_removed"] >= 1
    # Casing standardized to Title Case
    unique_regions = cleaned["region"].unique().tolist()
    for reg in unique_regions:
        assert reg in ["North", "South", "East", "West"]
    # Missing value imputed with median
    assert cleaned["revenue"].isnull().sum() == 0


def test_hypothesis_planner_node_fallback():
    """Verify hypothesis_planner_node produces structured testable hypotheses."""
    df = pd.DataFrame({
        "churn": [0, 1, 0, 1, 0, 1, 0, 0, 1, 0],
        "tenure_months": [12, 3, 24, 2, 36, 1, 18, 48, 4, 30],
        "monthly_spend": [50.0, 95.0, 45.0, 110.0, 40.0, 85.0, 60.0, 35.0, 105.0, 55.0]
    })
    state = {
        "df": df,
        "schema": {c: str(df[c].dtype) for c in df.columns},
        "stats": {
            "potential_targets": ["churn"],
            "numeric_summary": df.describe().to_dict()
        },
        "domain_brief": {
            "domain": "SaaS Subscription",
            "datasetPurpose": "Customer retention analysis",
            "importantColumns": ["churn", "tenure_months", "monthly_spend"]
        }
    }
    with patch("services.agent_graph.chat_completion", side_effect=Exception("Mock LLM offline")):
        res = hypothesis_planner_node(state)
    
    assert "investigation_plan" in res
    plan = res["investigation_plan"]
    assert "hypotheses" in plan
    assert len(plan["hypotheses"]) >= 1
    assert "business_objective" in plan
    h1 = plan["hypotheses"][0]
    assert "statement" in h1
    assert "target_variables" in h1


def test_ml_modeler_node_classification():
    """Verify ml_modeler_node detects binary target, fits classifier, and generates feature importance chart."""
    df = pd.DataFrame({
        "churn": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        "discount_rate": [0.05, 0.40, 0.02, 0.35, 0.01, 0.50, 0.08, 0.45, 0.03, 0.30, 0.04, 0.42, 0.01, 0.38, 0.05, 0.48, 0.02, 0.33, 0.06, 0.39],
        "support_tickets": [1, 5, 0, 4, 1, 6, 2, 5, 0, 4, 1, 5, 0, 4, 1, 6, 0, 3, 2, 4],
        "tenure_months": [24, 2, 36, 3, 48, 1, 18, 4, 30, 2, 22, 3, 40, 1, 19, 2, 32, 4, 28, 3]
    })
    state = {
        "df": df,
        "schema": {c: str(df[c].dtype) for c in df.columns},
        "stats": {"potential_targets": ["churn"]},
        "domain_brief": {"domain": "E-Commerce Churn"},
        "analysis_results": {},
        "chart_images": []
    }
    with patch("services.agent_graph.chat_completion", side_effect=Exception("Mock LLM offline")):
        res = ml_modeler_node(state)
    
    assert "ml_results" in res
    ml_res = res["ml_results"]
    assert ml_res["task_type"] == "classification"
    assert ml_res["target_column"] == "churn"
    assert "metrics" in ml_res
    assert "accuracy" in ml_res["metrics"]
    assert "f1_score" in ml_res["metrics"]
    assert "feature_importances" in ml_res
    assert len(ml_res["feature_importances"]) > 0

    # Chart images should contain the feature importance plot
    assert "chart_images" in res
    assert len(res["chart_images"]) >= 1
    chart = res["chart_images"][-1]
    assert "feature_importance" in chart["filename"]
    assert isinstance(chart["data"], bytes)


def test_deterministic_fallback_charts():
    """Verify _generate_deterministic_fallback_charts produces correlation heatmap and breakdown bar chart."""
    df = pd.DataFrame({
        "category": ["A", "B", "A", "B", "A", "B", "A", "B"],
        "metric_x": [10.0, 20.0, 15.0, 25.0, 12.0, 22.0, 18.0, 28.0],
        "metric_y": [100.0, 200.0, 150.0, 250.0, 120.0, 220.0, 180.0, 280.0]
    })
    charts = _generate_deterministic_fallback_charts(df, report={})
    assert len(charts) >= 2
    for c in charts:
        assert "filename" in c
        assert "data" in c
        assert isinstance(c["data"], bytes)
        assert len(c["data"]) > 0

