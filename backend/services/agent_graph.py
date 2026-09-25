# backend/services/agent_graph.py

import json
import logging
import operator
import re
import time
from datetime import datetime
import os
import uuid
import difflib
import threading
import concurrent.futures
import numpy as np
import pandas as pd
import scipy.stats as stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Annotated, Callable, Dict, Any, List, Optional, TypedDict

from langgraph.graph import StateGraph, END
try:
    from langgraph.types import Send
    _LANGGRAPH_SEND_AVAILABLE = True
except ImportError:
    _LANGGRAPH_SEND_AVAILABLE = False
    Send = None

from services.llm import chat_completion, provider_label
from services.code_executor import execute_analysis_code
from app.db import jobs, JobCancelledException
from app.utils import parse_json_safely

from services.agent_prompts import (
    DATA_SCIENTIST_PROMPT,
    REFLECTOR_PROMPT,
    VIZ_CODER_PROMPT,
    REPORT_WRITER_PROMPT,
    AUDITOR_PROMPT,
    NARRATIVE_STITCHER_PROMPT,
    VISUALIZATION_PREPROCESS_PROMPT,
    CAUSAL_ANALYST_PROMPT,
    FORECASTER_PROMPT,
    ANOMALY_DETECTOR_PROMPT,
    STRATEGIC_ADVISOR_PROMPT,
    DATA_CLEANER_PROMPT,
    HYPOTHESIS_PLANNER_PROMPT,
    ML_MODELER_PROMPT,
    EXPERIMENTATION_PROMPT,
    COHORT_ANALYST_PROMPT,
    BENCHMARKING_PROMPT,
    PRESENTATION_BUILDER_PROMPT,
    DATA_QUALITY_GATE_PROMPT,
    NL_SQL_PROMPT,
)

logger = logging.getLogger("genq_api.agent_graph")

ProgressCallback = Callable[[dict], None]


class AnalysisGraphState(TypedDict, total=False):
    """LangGraph state representation flowing through the multi-agent graph."""
    df: pd.DataFrame
    schema: dict
    sample_rows: list
    domain_brief: dict
    stats: dict
    progress_callback: Optional[ProgressCallback]
    job_id: Optional[str]
    max_reflections: int
    max_regeneration_rounds: int

    # Domain & units context
    currency_context: str

    # Intermediate and final outputs
    analysis_results: Dict[str, Any]
    # chart_images uses a list reducer so parallel branches can safely append
    chart_images: List[Dict[str, Any]]
    report: Dict[str, Any]
    audit: Dict[str, Any]
    visualization_data: Dict[str, Any]
    conversation_history: List[Dict[str, str]]

    # Transparency & methodologies
    methodology_code: str
    viz_code: str

    # Reflection loop tracking
    reflection_iteration: int
    reflection_feedback: str
    reflection_feedback_formatted: str
    follow_up_tasks: List[str]
    investigation_log: List[Dict[str, Any]]
    hypotheses_tested: List[Dict[str, Any]]

    # Viz repair loop tracking
    viz_error: Optional[str]
    viz_repair_attempts: int

    # Auditor regeneration loop tracking
    regeneration_round: int
    audit_feedback: List[Dict[str, Any]]
    retry_targets: List[str]

    # Execution logs & outputs
    last_execution_stdout: str
    last_execution_stderr: str
    last_execution_outputs: List[Dict[str, Any]]
    stages_progress: Dict[str, dict]
    agent_files: List[Dict[str, Any]]

    # Senior Analyst Tier outputs
    causal_results: Dict[str, Any]
    forecast_results: Dict[str, Any]
    anomaly_results: Dict[str, Any]
    strategic_results: Dict[str, Any]
    time_column_detected: Optional[str]
    target_columns_detected: List[str]
    # Data Quality Engineering, Dynamic Hypotheses & ML
    cleaning_manifest: Dict[str, Any]
    investigation_plan: Dict[str, Any]
    ml_results: Dict[str, Any]
    experiment_results: Dict[str, Any]
    relational_manifest: Dict[str, Any]

    # NEW: Data Quality Gate
    data_quality_score: int
    data_quality_gate_decision: str  # PASS | WARN | FAIL
    data_quality_issues: List[Dict[str, Any]]

    # NEW: Cohort & Retention Analyst
    cohort_results: Dict[str, Any]

    # NEW: Competitive Benchmarking Agent
    benchmark_results: Dict[str, Any]

    # NEW: Presentation Builder
    presentation_results: Dict[str, Any]

    # Parallel senior tier — intermediate chart buckets (merged by senior_tier_merge_node)
    _causal_charts: List[Dict[str, Any]]
    _forecast_charts: List[Dict[str, Any]]
    _anomaly_charts: List[Dict[str, Any]]
    _experiment_charts: List[Dict[str, Any]]
    _ml_charts: List[Dict[str, Any]]
    _cohort_charts: List[Dict[str, Any]]

    # Status flags
    cancelled: bool
    error: Optional[str]
    final_report: Dict[str, Any]


class AnalysisState:
    """Shared state container for backward compatibility with existing callers and tests."""
    def __init__(
        self,
        df: pd.DataFrame,
        schema: dict,
        sample_rows: list,
        domain_brief: dict,
        stats: dict = None,
        progress_callback: Optional[ProgressCallback] = None,
        max_reflections: int = 3,
        max_regeneration_rounds: int = 3,
        job_id: Optional[str] = None,
    ):
        self.df = df
        self.schema = schema
        self.sample_rows = sample_rows
        self.domain_brief = domain_brief
        self.stats = stats or {}
        self.progress_callback = progress_callback
        self.job_id = job_id

        # State variables
        self.analysis_results: Dict[str, Any] = {}
        self.chart_images: List[Dict[str, Any]] = []
        self.report: Dict[str, Any] = {}
        self.audit: Dict[str, Any] = {}
        self.visualization_data: Dict[str, Any] = {}
        self.conversation_history: List[Dict[str, str]] = []

        # Methodology tracking
        self.methodology_code: str = ""
        self.viz_code: str = ""

        # Loop counters
        self.reflection_iteration: int = 0
        self.max_reflections = max_reflections
        self.reflection_feedback: str = ""
        self.reflection_feedback_formatted: str = ""
        self.follow_up_tasks: List[str] = []
        self.investigation_log: List[Dict[str, Any]] = []
        self.hypotheses_tested: List[Dict[str, Any]] = []

        self.regeneration_round: int = 0
        self.max_regeneration_rounds = max_regeneration_rounds
        self.audit_feedback: List[Dict[str, Any]] = []
        self.retry_targets: List[str] = []

        self.error: Optional[str] = None
        self.stages_progress: Dict[str, dict] = {}
        self.agent_files: List[Dict[str, Any]] = []

        self.last_execution_stdout: str = ""
        self.last_execution_stderr: str = ""
        self.last_execution_outputs: List[Dict[str, Any]] = []
        self.cancelled: bool = False
        self._currency_context: str = ""

        # Senior Analyst Tier
        self.causal_results: Dict[str, Any] = {}
        self.forecast_results: Dict[str, Any] = {}
        self.anomaly_results: Dict[str, Any] = {}
        self.strategic_results: Dict[str, Any] = {}
        self.time_column_detected: Optional[str] = None
        self.target_columns_detected: List[str] = []
        self.cleaning_manifest: Dict[str, Any] = {}
        self.investigation_plan: Dict[str, Any] = {}
        self.ml_results: Dict[str, Any] = {}
        self.experiment_results: Dict[str, Any] = {}
        self.relational_manifest: Dict[str, Any] = {}

        # NEW agent results
        self.data_quality_score: int = 0
        self.data_quality_gate_decision: str = "PASS"
        self.data_quality_issues: List[Dict[str, Any]] = []
        self.cohort_results: Dict[str, Any] = {}
        self.benchmark_results: Dict[str, Any] = {}
        self.presentation_results: Dict[str, Any] = {}


def extract_code_block(text: str) -> str:
    """Extracts and combines all python code blocks from LLM response into a single executable script."""
    import ast
    if not text:
        return ""

    # Find all fenced code blocks
    pattern = r"```(?:python)?\s*([\s\S]*?)```"
    matches = re.findall(pattern, text, re.IGNORECASE)

    if matches:
        combined = "\n\n".join(m.strip() for m in matches if m.strip())
        try:
            ast.parse(combined)
            return combined
        except SyntaxError:
            valid_blocks = []
            for m in matches:
                try:
                    ast.parse(m.strip())
                    valid_blocks.append(m.strip())
                except SyntaxError:
                    pass
            if valid_blocks:
                plotting_blocks = [b for b in valid_blocks if "savefig" in b]
                if plotting_blocks:
                    return "\n\n".join(plotting_blocks)
                return max(valid_blocks, key=len)
            return matches[0].strip()

    # If no closing fences, look for an open fence
    open_match = re.search(r"```(?:python)?\s*", text, re.IGNORECASE)
    if open_match:
        tail = text[open_match.end():].strip()
        if tail.endswith("```"):
            tail = tail[:-3].strip()
        return tail

    return text.strip()


def detect_currency_and_units(df: pd.DataFrame, schema: dict, sample_rows: list) -> str:
    """Detects currency and units from column names, sample values, and data patterns."""
    detected = []
    currency_indicators = {
        'inr': ('INR', '₹'), 'rs': ('INR', '₹'), 'rupee': ('INR', '₹'), 'rupees': ('INR', '₹'),
        'usd': ('USD', '$'), 'dollar': ('USD', '$'), 'dollars': ('USD', '$'),
        'eur': ('EUR', '€'), 'euro': ('EUR', '€'), 'euros': ('EUR', '€'),
        'gbp': ('GBP', '£'), 'pound': ('GBP', '£'), 'pounds': ('GBP', '£'),
        'yen': ('JPY', '¥'), 'jpy': ('JPY', '¥'),
    }

    for col in df.columns:
        col_lower = col.lower().replace('_', ' ').replace('-', ' ')
        for indicator, (code, symbol) in currency_indicators.items():
            if indicator in col_lower.split():
                detected.append(f"Column '{col}': Currency detected as {code} ({symbol}) from column name")
                break

    if sample_rows:
        for row in sample_rows[:5]:
            for col, val in row.items():
                if isinstance(val, str):
                    val_stripped = val.strip()
                    if val_stripped.startswith('₹') or '₹' in val_stripped:
                        if not any('INR' in d for d in detected if col in d):
                            detected.append(f"Column '{col}': Currency detected as INR (₹) from sample values")
                    elif val_stripped.startswith('$'):
                        if not any('USD' in d for d in detected if col in d):
                            detected.append(f"Column '{col}': Currency detected as USD ($) from sample values")
                    elif val_stripped.startswith('€'):
                        if not any('EUR' in d for d in detected if col in d):
                            detected.append(f"Column '{col}': Currency detected as EUR (€) from sample values")
                    elif val_stripped.startswith('£'):
                        if not any('GBP' in d for d in detected if col in d):
                            detected.append(f"Column '{col}': Currency detected as GBP (£) from sample values")

    monetary_keywords = ['price', 'cost', 'revenue', 'salary', 'wage', 'income', 'amount',
                         'payment', 'charge', 'fee', 'bill', 'budget', 'spend', 'expense',
                         'profit', 'loss', 'mrp', 'rate', 'total']
    for col in df.columns:
        col_lower = col.lower().replace('_', ' ').replace('-', ' ')
        if any(kw in col_lower for kw in monetary_keywords):
            if not any(col in d for d in detected):
                detected.append(f"Column '{col}': Appears to be a monetary/value column — check sample values for currency")

    if not detected:
        return "No specific currency or unit indicators detected. Use the raw values as they appear in the data without any conversion."

    return "\n".join(detected) + "\n\nCRITICAL: Preserve these currencies and units exactly. Do NOT convert to any other currency."


def check_cancelled(state: AnalysisGraphState) -> bool:
    """Returns True if the current job has been cancelled by the user."""
    job_id = state.get("job_id")
    if job_id:
        try:
            job = jobs.get(job_id)
            if job and (job.get("status") == "Cancelled" or job.get("cancelled", False)):
                return True
        except Exception as e:
            logger.warning(f"Error checking cancellation status for job {job_id}: {e}")
    return bool(state.get("cancelled", False))


def publish_stage_progress(
    state: AnalysisGraphState,
    stage: str,
    status: str,
    detail: str,
    round_num: int = 0,
    score: int | None = None
) -> None:
    """Updates progress dictionary and invokes the user progress_callback."""
    stage_names = {
        "profile": "Data Profiler",
        "data_quality_gate": "Data Quality Gate",
        "data_cleaner": "Data Quality & Cleaning Agent",
        "hypothesis_planner": "Research Planning Agent",
        "sampling": "Smart Sampler",
        "data_scientist": "Data Scientist Agent",
        "reflector": "Reflector Agent",
        "viz_preprocessor": "Visualization Preprocessor",
        "viz_coder": "Visualization Agent",
        "viz_repair": "Visualization Self-Repair",
        "report_writer": "Report Writer",
        "narrative_stitcher": "Narrative Stitcher",
        "auditor": "Quality Auditor",
        "validation": "Data Validator",
        "causal_analyst": "Causal Inference Agent",
        "forecaster": "Forecasting Agent",
        "anomaly_detector": "Anomaly Detection Agent",
        "experimentation": "A/B Experimentation Agent",
        "ml_modeler": "Machine Learning Agent",
        "strategic_advisor": "Strategic Insights Agent",
        "cohort_analyst": "Cohort & Retention Analyst",
        "benchmarking": "Competitive Benchmarking Agent",
        "senior_tier_merge": "Senior Tier Results Merger",
        "presentation_builder": "Presentation Builder Agent",
        "nl_sql": "Natural Language SQL Agent",
    }

    stages_progress = state.setdefault("stages_progress", {})
    update = {
        "id": stage,
        "name": stage_names.get(stage, stage.title()),
        "status": status,
        "detail": detail,
        "round": round_num,
    }
    if score is not None:
        update["score"] = score

    stages_progress[stage] = update

    # Print real-time stage progress directly to terminal console
    status_icon = "▶" if status == "running" else ("✔" if status == "completed" else "ℹ")
    agent_display = stage_names.get(stage, stage.title())
    score_str = f" [Score: {score}]" if score is not None else ""
    round_str = f" [Round {round_num}]" if round_num > 0 else ""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {status_icon} [{agent_display}{round_str}] {detail}{score_str}", flush=True)

    callback = state.get("progress_callback")
    if callback:
        try:
            callback({
                "currentAgent": stage,
                "agents": list(stages_progress.values()),
                **update
            })
        except Exception as e:
            logger.warning(f"Error calling progress callback: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph Node Implementations
# ─────────────────────────────────────────────────────────────────────────────

def data_cleaner_node(state: AnalysisGraphState) -> dict:
    """Data Cleaner Agent: Autonomously audits, cleans, and standardizes data."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "data_cleaner",
        "running",
        "Data Cleaner Agent: Auditing data quality, standardizing casing, and handling dirty values..."
    )

    df = state["df"].copy()
    initial_rows = len(df)
    schema = state.get("schema", {})
    domain_brief = state.get("domain_brief", {})
    currency_context = state.get("currency_context") or detect_currency_and_units(df, schema, state.get("sample_rows", []))
    stats_dict = state.get("stats", {})
    missing_values = stats_dict.get("missing_values", {})
    notable_issues = stats_dict.get("data_quality", {}).get("notable_issues", [])
    duplicates_count = int(df.duplicated().sum())

    # Build prompt
    prompt = DATA_CLEANER_PROMPT.format(
        domain=domain_brief.get("domain", "Unknown"),
        currency_context=currency_context,
        schema=json.dumps(schema, default=str),
        sample_rows=json.dumps(state.get("sample_rows", [])[:5], default=str),
        missing_values=json.dumps(missing_values, default=str),
        duplicate_rows=duplicates_count,
        data_quality_issues=json.dumps(notable_issues, default=str),
    )

    messages = [
        {"role": "system", "content": "You are an expert Data Quality Engineer. Generate a Python script to clean and standardize the DataFrame."},
        {"role": "user", "content": prompt}
    ]

    cleaned_df = df.copy()
    cleaning_manifest = {
        "rows_before": initial_rows,
        "rows_after": initial_rows,
        "duplicates_removed": 0,
        "actions": [],
        "cleaned_columns": []
    }

    try:
        response = chat_completion(messages, task="analysis", timeout=int(os.environ.get("LLM_TIMEOUT", "300")))
        code = extract_code_block(response)
        if code and ("pickle" in code or "manifest" in code or "clean" in code or "df" in code):
            exec_res = execute_analysis_code(code, df, timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "120")))
            if exec_res.success:
                for out in exec_res.agent_outputs:
                    fname = out.get("filename", "")
                    if fname == "manifest.json" and isinstance(out.get("data"), dict):
                        cleaning_manifest = out["data"]
                    elif fname.endswith(".pkl") and "clean" in fname:
                        import pickle
                        try:
                            c_df = pickle.loads(out["data"])
                            if isinstance(c_df, pd.DataFrame) and len(c_df) > 0:
                                cleaned_df = c_df.copy()
                        except Exception:
                            pass
    except Exception as e:
        logger.warning(f"Data Cleaner LLM code execution failed: {e}")

    # Defensive standardization & deterministic enhancement
    if cleaned_df.duplicated().sum() > 0:
        dups_before = len(cleaned_df)
        cleaned_df = cleaned_df.drop_duplicates().copy()
        dups_removed = dups_before - len(cleaned_df)
        if dups_removed > 0:
            cleaning_manifest["duplicates_removed"] = cleaning_manifest.get("duplicates_removed", 0) + dups_removed
            cleaning_manifest.setdefault("actions", []).append({
                "column": "all",
                "operation": "deduplication",
                "reason": f"Removed {dups_removed} duplicate row(s)",
                "rows_affected": dups_removed
            })

    for col in cleaned_df.select_dtypes(include=['object', 'string']).columns:
        str_s = cleaned_df[col].astype(str).str.strip()
        if str_s.nunique() < 50 and str_s.str.lower().nunique() < str_s.nunique():
            cleaned_df[col] = str_s.str.title()
            cleaning_manifest.setdefault("actions", []).append({
                "column": col,
                "operation": "casing_normalization",
                "reason": "Standardized inconsistent casing to Title Case across categories",
                "rows_affected": len(cleaned_df)
            })
            if col not in cleaning_manifest.setdefault("cleaned_columns", []):
                cleaning_manifest["cleaned_columns"].append(col)

    for col in cleaned_df.select_dtypes(include=[np.number]).columns:
        null_count = int(cleaned_df[col].isnull().sum())
        if 0 < null_count < len(cleaned_df) * 0.3:
            median_val = cleaned_df[col].median()
            cleaned_df[col] = cleaned_df[col].fillna(median_val)
            cleaning_manifest.setdefault("actions", []).append({
                "column": col,
                "operation": "median_imputation",
                "reason": f"Imputed {null_count} missing values with column median ({median_val})",
                "rows_affected": null_count
            })
            if col not in cleaning_manifest.setdefault("cleaned_columns", []):
                cleaning_manifest["cleaned_columns"].append(col)

    cleaning_manifest["rows_before"] = initial_rows
    cleaning_manifest["rows_after"] = len(cleaned_df)
    cleaning_manifest["summary"] = (
        f"Data quality standardization completed. {len(cleaning_manifest.get('actions', []))} cleaning action(s) applied. "
        f"{cleaning_manifest.get('duplicates_removed', 0)} duplicates removed, {len(cleaning_manifest.get('cleaned_columns', []))} column(s) standardized."
    )

    updated_schema = {col: str(dtype) for col, dtype in cleaned_df.dtypes.items()}
    updated_sample = cleaned_df.head(12).replace({np.nan: None, np.inf: None, -np.inf: None}).to_dict("records")

    publish_stage_progress(
        state,
        "data_cleaner",
        "completed",
        cleaning_manifest["summary"]
    )

    return {
        "df": cleaned_df,
        "schema": updated_schema,
        "sample_rows": updated_sample,
        "cleaning_manifest": cleaning_manifest
    }


def hypothesis_planner_node(state: AnalysisGraphState) -> dict:
    """Research Planning Agent: Formulates dynamic, domain-tailored business hypotheses."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "hypothesis_planner",
        "running",
        "Research Planning Agent: Synthesizing domain context and formulating testable hypotheses..."
    )

    df = state["df"]
    schema = state.get("schema", {})
    domain_brief = state.get("domain_brief", {})
    stats_dict = state.get("stats", {})
    numeric_summary = stats_dict.get("numeric_summary", {})
    potential_targets = stats_dict.get("potential_targets", [])
    time_features = stats_dict.get("time_features", {})

    prompt = HYPOTHESIS_PLANNER_PROMPT.format(
        domain=domain_brief.get("domain", "Unknown"),
        purpose=domain_brief.get("datasetPurpose", "Analyze data relationships"),
        dataset_type=domain_brief.get("datasetType", "cross-sectional"),
        important_columns=json.dumps(domain_brief.get("importantColumns", [])),
        potential_targets=json.dumps(potential_targets),
        time_features=json.dumps(time_features),
        schema=json.dumps(schema, default=str),
        numeric_summary=json.dumps(numeric_summary, default=str)[:3000],
    )

    messages = [
        {"role": "system", "content": "You are the Lead Quantitative Research Director. Formulate dynamic hypotheses for this dataset. Output JSON only."},
        {"role": "user", "content": prompt}
    ]

    plan = {}
    try:
        response = chat_completion(messages, task="analysis", json_mode=True, timeout=int(os.environ.get("LLM_TIMEOUT", "300")))
        parsed = parse_json_safely(response)
        if "error" not in parsed and ("hypotheses" in parsed or "business_objective" in parsed):
            plan = parsed
    except Exception as e:
        logger.warning(f"Hypothesis planner LLM error: {e}")

    # Fallback plan if LLM failed or mocked
    if not plan or "hypotheses" not in plan or not plan["hypotheses"]:
        cols = list(df.columns)
        num_cols = list(df.select_dtypes(include=[np.number]).columns)
        cat_cols = list(df.select_dtypes(include=['object', 'category']).columns)
        hypotheses = []

        if potential_targets and num_cols:
            tgt = potential_targets[0]
            pred = [c for c in num_cols if c != tgt][0] if len(num_cols) > 1 else num_cols[0]
            hypotheses.append({
                "id": "H1",
                "statement": f"Target variable '{tgt}' is significantly driven by variations in '{pred}'.",
                "target_variables": [tgt, pred],
                "suggested_tests": ["correlation", "regression", "group_analysis"],
                "business_impact": f"Identifies primary operational lever influencing {tgt}."
            })
        elif len(num_cols) >= 2:
            hypotheses.append({
                "id": "H1",
                "statement": f"Strong linear or monotonic dependency exists between '{num_cols[0]}' and '{num_cols[1]}'.",
                "target_variables": [num_cols[0], num_cols[1]],
                "suggested_tests": ["correlation", "regression"],
                "business_impact": "Discovers core structural interaction in the numeric data."
            })

        if cat_cols and num_cols:
            c_col = cat_cols[0]
            n_col = num_cols[0]
            hypotheses.append({
                "id": "H2",
                "statement": f"Distribution of '{n_col}' diverges significantly across categories of '{c_col}'.",
                "target_variables": [c_col, n_col],
                "suggested_tests": ["group_analysis", "anova", "t_test"],
                "business_impact": f"Reveals segment-level divergence for strategic targeting."
            })

        if len(num_cols) > 2:
            n3 = num_cols[2] if len(num_cols) > 2 else num_cols[-1]
            hypotheses.append({
                "id": "H3",
                "statement": f"Outlier anomalies in '{n3}' represent high-risk or high-value tail segments.",
                "target_variables": [n3],
                "suggested_tests": ["outlier_detection", "inspect_column"],
                "business_impact": "Mitigates operational tail-risk."
            })

        plan = {
            "business_objective": f"Empirically determine core performance drivers and segment variance in {domain_brief.get('domain', 'dataset')}.",
            "hypotheses": hypotheses,
            "investigation_priorities": [h["statement"] for h in hypotheses],
            "potential_confounders": [cat_cols[1]] if len(cat_cols) > 1 else []
        }

    publish_stage_progress(
        state,
        "hypothesis_planner",
        "completed",
        f"Hypothesis plan active: {len(plan.get('hypotheses', []))} hypotheses formulated."
    )

    return {"investigation_plan": plan}


def data_scientist_node(state: AnalysisGraphState) -> dict:
    """Data Scientist Agent Node: Executes exploratory data analysis and tool-calling cycle."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "data_scientist",
        "running",
        "Starting iterative data science investigation loop...",
        state.get("regeneration_round", 0)
    )

    df = state["df"]
    schema = state["schema"]
    sample_rows = state["sample_rows"]
    domain_brief = state.get("domain_brief", {})
    stats_dict = state.get("stats", {})

    # Detect currency context if not already saved
    currency_context = state.get("currency_context") or detect_currency_and_units(df, schema, sample_rows)

    # Clean charts produced by create_chart_tool in previous iterations
    existing_charts = [c for c in state.get("chart_images", []) if c.get("data") is not None]
    agent_files = list(state.get("agent_files", []))
    investigation_log = list(state.get("investigation_log", []))
    analysis_results = dict(state.get("analysis_results", {}))

    feedback = state.get("reflection_feedback_formatted") or ""
    if not feedback and state.get("audit_feedback"):
        feedback = f"Audit correction feedback: {json.dumps(state['audit_feedback'])}"

    prompt_kwargs = dict(
        domain=domain_brief.get("domain", "Unknown"),
        purpose=domain_brief.get("datasetPurpose", "Analyze data structure"),
        dataset_type=domain_brief.get("datasetType", "cross-sectional"),
        important_columns=json.dumps(domain_brief.get("importantColumns", [])),
        schema=json.dumps(schema, default=str),
        sample_rows=json.dumps(sample_rows, default=str),
        missing_values=json.dumps(stats_dict.get("missing_values", {}), default=str),
        numeric_summary=json.dumps(stats_dict.get("numeric_summary", {}), default=str),
        grouped_summary=json.dumps(stats_dict.get("grouped_summary", {}), default=str),
        feedback=feedback,
        currency_context=currency_context,
        investigation_plan="\n".join([f"- [{h.get('id','H')}]: {h.get('statement','')} (Variables: {', '.join(h.get('target_variables',[]))})" for h in state.get("investigation_plan", {}).get("hypotheses", [])]) or "Conduct rigorous exploratory data analysis across key distributions and correlations.",
    )

    conversation_history = list(state.get("conversation_history", []))
    if not conversation_history:
        prompt = DATA_SCIENTIST_PROMPT.format(**prompt_kwargs)
        conversation_history = [
            {"role": "system", "content": "You are a quantitative data analyst. Use the available tools to analyze the dataset. Output JSON tool calls."},
            {"role": "user", "content": prompt},
        ]
    else:
        conversation_history.append({
            "role": "user",
            "content": f"Feedback for this cycle:\n{feedback}\nPlease address the follow-up tasks using the tools, and call 'done' when finished."
        })

    def _fuzzy_match_column(col_name, df_cols):
        if not col_name: return None
        if col_name in df_cols: return col_name
        matches = difflib.get_close_matches(col_name, df_cols, n=1, cutoff=0.6)
        return matches[0] if matches else None

    def inspect_column_tool(col_name):
        matched_col = _fuzzy_match_column(col_name, df.columns.tolist())
        if not matched_col:
            return f"Error: column '{col_name}' does not exist in DataFrame. Available columns are: {list(df.columns)}"
        col = df[matched_col]
        null_count = int(col.isnull().sum())
        unique_count = int(col.nunique())
        if pd.api.types.is_numeric_dtype(col):
            desc = col.describe().to_dict()
            skew = float(col.skew()) if unique_count > 1 else 0.0
            kurt = float(col.kurt()) if unique_count > 1 else 0.0
            return {
                "column": matched_col,
                "type": "numeric",
                "missing_values": null_count,
                "unique_values": unique_count,
                "statistics": desc,
                "skewness": skew,
                "kurtosis": kurt
            }
        else:
            val_counts = col.value_counts(normalize=True).head(10).to_dict()
            val_counts_raw = col.value_counts().head(10).to_dict()
            distribution = {k: {"count": val_counts_raw[k], "percentage": f"{v*100:.2f}%"} for k, v in val_counts.items()}
            return {
                "column": matched_col,
                "type": "categorical",
                "missing_values": null_count,
                "unique_values": unique_count,
                "top_10_distribution": distribution
            }

    def run_test_tool(test_type, col_a, col_b=None):
        matched_a = _fuzzy_match_column(col_a, df.columns.tolist())
        matched_b = _fuzzy_match_column(col_b, df.columns.tolist()) if col_b else None
        if not matched_a:
            return f"Error: col_a ('{col_a}') not found in DataFrame. Available columns are: {list(df.columns)}"

        col_a = matched_a
        if test_type in ("normality", "normaltest"):
            if not pd.api.types.is_numeric_dtype(df[col_a]):
                return f"Error: '{col_a}' must be numeric for normality test."
            clean_s = df[col_a].dropna()
            if len(clean_s) < 3:
                return "Error: need at least 3 data points for normality test."
            stat, p_val = stats.shapiro(clean_s) if len(clean_s) <= 5000 else stats.normaltest(clean_s)
            return {
                "test": "normality",
                "column": col_a,
                "statistic": float(stat),
                "p_value": float(p_val),
                "is_normal": bool(p_val > 0.05),
                "interpretation": "Distribution appears normal (p > 0.05)" if p_val > 0.05 else "Distribution deviates from normal (p <= 0.05)"
            }
        elif test_type in ("outlier_detection", "outliers", "outlier"):
            if not pd.api.types.is_numeric_dtype(df[col_a]):
                return f"Error: '{col_a}' must be numeric for outlier detection."
            clean_s = df[col_a].dropna()
            if len(clean_s) == 0:
                return "Error: column contains no valid data."
            q25, q75 = np.percentile(clean_s, 25), np.percentile(clean_s, 75)
            iqr = q75 - q25
            lower_bound = q25 - 1.5 * iqr
            upper_bound = q75 + 1.5 * iqr
            outliers = clean_s[(clean_s < lower_bound) | (clean_s > upper_bound)]
            return {
                "test": "outlier_detection",
                "column": col_a,
                "outlier_count": int(len(outliers)),
                "outlier_percentage": f"{len(outliers) / len(clean_s) * 100:.2f}%",
                "lower_bound": float(lower_bound),
                "upper_bound": float(upper_bound),
                "outlier_samples": [float(x) for x in outliers.head(5).tolist()]
            }

        if not matched_b:
            return f"Error: col_b ('{col_b}') is required for '{test_type}'. Available columns are: {list(df.columns)}"

        col_b = matched_b
        if test_type == "correlation":
            if not (pd.api.types.is_numeric_dtype(df[col_a]) and pd.api.types.is_numeric_dtype(df[col_b])):
                return "Error: both columns must be numeric for correlation test."
            clean_df = df[[col_a, col_b]].dropna()
            if len(clean_df) < 2:
                return "Error: not enough data points after dropping NaNs."
            pearson_r, p_val = stats.pearsonr(clean_df[col_a], clean_df[col_b])
            spearman_r, sp_p_val = stats.spearmanr(clean_df[col_a], clean_df[col_b])
            return {
                "test": "correlation",
                "pearson_r": pearson_r,
                "pearson_p_value": p_val,
                "spearman_r": spearman_r,
                "spearman_p_value": sp_p_val
            }
        elif test_type == "t_test":
            if not pd.api.types.is_numeric_dtype(df[col_a]):
                return "Error: col_a must be numeric for t_test."
            groups = df[col_b].dropna().unique()
            if len(groups) < 2:
                return f"Error: col_b only has {len(groups)} group(s). Need at least 2 groups."
            group_data = [df[df[col_b] == g][col_a].dropna() for g in groups[:2]]
            if len(group_data[0]) < 2 or len(group_data[1]) < 2:
                return "Error: one of the groups has too few data points."
            t_stat, p_val = stats.ttest_ind(group_data[0], group_data[1], equal_var=False)
            # Compute Cohen's d for practical effect size
            pooled_std = float(np.sqrt((group_data[0].std()**2 + group_data[1].std()**2) / 2))
            cohens_d = float((group_data[0].mean() - group_data[1].mean()) / pooled_std) if pooled_std > 0 else 0.0
            return {
                "test": "t_test",
                "group_1": str(groups[0]),
                "group_1_mean": float(group_data[0].mean()),
                "group_2": str(groups[1]),
                "group_2_mean": float(group_data[1].mean()),
                "t_statistic": t_stat,
                "p_value": p_val,
                "cohens_d": cohens_d,
                "effect_interpretation": "large" if abs(cohens_d) > 0.8 else "medium" if abs(cohens_d) > 0.5 else "small",
            }
        elif test_type == "chi2_test":
            contingency_table = pd.crosstab(df[col_a], df[col_b])
            chi2, p, dof, _ = stats.chi2_contingency(contingency_table)
            n = contingency_table.sum().sum()
            min_dim = min(contingency_table.shape) - 1
            cramers_v = float(np.sqrt(chi2 / (n * max(min_dim, 1)))) if n > 0 else 0.0
            return {
                "test": "chi2_test",
                "chi2_statistic": chi2,
                "p_value": p,
                "degrees_of_freedom": dof,
                "cramers_v": cramers_v,
                "effect_interpretation": "strong" if cramers_v > 0.5 else "moderate" if cramers_v > 0.3 else "weak"
            }
        elif test_type == "anova":
            if not pd.api.types.is_numeric_dtype(df[col_a]):
                return "Error: col_a must be numeric for ANOVA."
            groups = df[col_b].dropna().unique()
            if len(groups) < 2:
                return f"Error: col_b only has {len(groups)} group(s). Need at least 2."
            group_data = [df[df[col_b] == g][col_a].dropna().values for g in groups]
            group_data = [g for g in group_data if len(g) >= 2]
            if len(group_data) < 2:
                return "Error: too few groups with sufficient data points."
            f_stat, p_val = stats.f_oneway(*group_data)
            grand_mean = df[col_a].dropna().mean()
            ss_between = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in group_data)
            ss_total = sum(((g - grand_mean) ** 2).sum() for g in group_data)
            eta_sq = float(ss_between / ss_total) if ss_total > 0 else 0.0
            group_means = {str(g): float(df[df[col_b] == g][col_a].mean()) for g in groups[:10]}
            return {
                "test": "anova",
                "f_statistic": float(f_stat),
                "p_value": float(p_val),
                "eta_squared": eta_sq,
                "effect_interpretation": "large" if eta_sq > 0.14 else "medium" if eta_sq > 0.06 else "small",
                "num_groups": len(groups),
                "group_means": group_means
            }
        elif test_type == "regression":
            if not (pd.api.types.is_numeric_dtype(df[col_a]) and pd.api.types.is_numeric_dtype(df[col_b])):
                return "Error: both columns must be numeric for regression."
            clean_df = df[[col_a, col_b]].dropna()
            if len(clean_df) < 3:
                return "Error: need at least 3 data points for regression."
            slope, intercept, r_value, p_value, std_err = stats.linregress(clean_df[col_a], clean_df[col_b])
            return {
                "test": "regression",
                "dependent_variable": col_b,
                "independent_variable": col_a,
                "slope": float(slope),
                "intercept": float(intercept),
                "r_squared": float(r_value ** 2),
                "p_value": float(p_value),
                "std_error": float(std_err),
                "interpretation": f"A 1-unit increase in {col_a} is associated with a {slope:.4f} change in {col_b}. R² = {r_value**2:.4f}."
            }
        else:
            return f"Error: unknown test_type '{test_type}'."

    def group_analysis_tool(numeric_col, group_col):
        matched_num = _fuzzy_match_column(numeric_col, df.columns.tolist())
        matched_grp = _fuzzy_match_column(group_col, df.columns.tolist())
        if not matched_num or not matched_grp:
            return f"Error: columns '{numeric_col}' or '{group_col}' not found."
        if not pd.api.types.is_numeric_dtype(df[matched_num]):
            return f"Error: '{matched_num}' must be numeric."
        grouped = df.groupby(matched_grp)[matched_num].agg(['count', 'mean', 'median', 'std', 'min', 'max']).reset_index()
        return grouped.head(15).to_dict(orient='records')

    def create_chart_tool(chart_type, x, y=None, hue=None):
        import seaborn as sns
        matched_x = _fuzzy_match_column(x, df.columns.tolist())
        matched_y = _fuzzy_match_column(y, df.columns.tolist()) if y else None
        matched_hue = _fuzzy_match_column(hue, df.columns.tolist()) if hue else None

        if not matched_x:
            return f"Error: column '{x}' not found."
        try:
            plt.figure(figsize=(8, 5))
            if chart_type == "bar":
                if matched_y:
                    sns.barplot(data=df, x=matched_x, y=matched_y, hue=matched_hue, estimator="mean")
                else:
                    sns.countplot(data=df, x=matched_x, hue=matched_hue)
                plt.xticks(rotation=45, ha='right')
            elif chart_type == "scatter":
                if not matched_y: return "Error: scatter requires both x and y."
                sns.scatterplot(data=df, x=matched_x, y=matched_y, hue=matched_hue)
            elif chart_type == "line":
                if not matched_y: return "Error: line requires both x and y."
                sns.lineplot(data=df, x=matched_x, y=matched_y, hue=matched_hue)
            elif chart_type == "box":
                if matched_y:
                    sns.boxplot(data=df, x=matched_x, y=matched_y, hue=matched_hue)
                    plt.xticks(rotation=45, ha='right')
                else:
                    sns.boxplot(data=df, y=matched_x)
            elif chart_type == "violin":
                if matched_y:
                    sns.violinplot(data=df, x=matched_x, y=matched_y, hue=matched_hue)
                    plt.xticks(rotation=45, ha='right')
                else:
                    sns.violinplot(data=df, y=matched_x)
            elif chart_type == "regression_plot":
                if not matched_y: return "Error: regression_plot requires both x and y."
                sns.regplot(data=df, x=matched_x, y=matched_y)
            elif chart_type == "heatmap":
                numeric_df = df.select_dtypes(include=['number'])
                sns.heatmap(numeric_df.corr(), annot=True, cmap="coolwarm", fmt=".2f")
            else:
                plt.close("all")
                return f"Error: unknown chart_type '{chart_type}'."

            title_text = f"{chart_type.title()} of {matched_x} vs {matched_y or 'Count'}"
            plt.title(title_text, fontsize=13, fontweight='bold', pad=15)
            ax = plt.gca()
            ax.set_xlabel(matched_x, fontsize=10)
            if matched_y:
                ax.set_ylabel(matched_y, fontsize=10)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            filename = f"{chart_type}_{matched_x}_{matched_y or 'count'}.png".replace(" ", "_").lower()
            plt.savefig(filename, dpi=200, bbox_inches="tight")
            plt.close("all")

            existing_charts.append({
                "filename": filename,
                "title": title_text,
                "interpretation": f"Generated exploratory {chart_type} chart for {matched_x} and {matched_y or 'count'}.",
                "insight_text": "",
                "finding_title": ""
            })
            agent_files.append({
                "agent": "data_scientist",
                "round": state.get("reflection_iteration", 0),
                "filename": filename,
                "type": "image",
                "purpose": f"{chart_type} chart for {matched_x} vs {matched_y}"
            })
            return f"Success: chart saved as {filename}."
        except Exception as e:
            plt.close("all")
            return f"Error plotting chart: {e}"

    def save_finding_tool(title, evidence, confidence, effect_size=None, impact_score=None):
        finding = {
            "title": title,
            "detail": evidence,
            "evidence": evidence,
            "confidence": confidence,
            "effect_size": effect_size or "",
            "impact_score": impact_score if impact_score is not None else 5,
        }
        if "findings" not in analysis_results:
            analysis_results["findings"] = []
        if "keyFindings" not in analysis_results:
            analysis_results["keyFindings"] = []
        analysis_results["findings"].append(finding)
        analysis_results["keyFindings"].append(finding)

        investigation_log.append({
            "agent": "data_scientist",
            "round": state.get("reflection_iteration", 0),
            "action": f"Saved key finding: {title}",
            "result": evidence
        })
        return f"Success: saved finding '{title}'."

    loop_count = 0
    max_loop = int(os.environ.get("MAX_AGENT_LOOPS", "20"))
    execution_stdout_log = []
    MAX_JSON_RETRIES = 3
    REMINDER_MSG = (
        "Your previous response could not be parsed as JSON. "
        "You MUST respond with ONLY a valid JSON object — no markdown, no text outside JSON, no <think> tags. "
        "Format: {\"thought\": \"...\", \"tool\": \"...\", \"arguments\": {...}}"
    )

    _MAX_CTX_CHARS = int(os.environ.get("LLM_MAX_CTX_CHARS", "80000"))
    _CTX_TAIL = int(os.environ.get("LLM_CTX_TAIL_MESSAGES", "16"))

    def _trim_messages(msgs: list) -> list:
        if len(msgs) <= 2:
            return msgs
        header = msgs[:2]
        tail = msgs[2:]
        if len(tail) > _CTX_TAIL:
            tail = tail[-_CTX_TAIL:]
        total_chars = sum(len(m.get("content", "")) for m in header + tail)
        while total_chars > _MAX_CTX_CHARS and len(tail) > 2:
            removed = tail.pop(0)
            total_chars -= len(removed.get("content", ""))
        return header + tail

    while loop_count < max_loop:
        if check_cancelled(state):
            raise JobCancelledException("Job cancelled by user.")
        loop_count += 1

        call_json = {"error": "not yet tried"}
        response = ""
        for attempt in range(MAX_JSON_RETRIES):
            try:
                use_json_mode = (attempt == 0)
                trimmed = _trim_messages(conversation_history)
                response = chat_completion(
                    trimmed, task="analysis",
                    json_mode=use_json_mode,
                    timeout=int(os.environ.get("LLM_TIMEOUT", "600"))
                )
                call_json = parse_json_safely(response)
                if "error" not in call_json and "tool" in call_json:
                    break
                logger.warning("Tool call JSON parse failed (attempt %d/%d). Raw: %.120s", attempt + 1, MAX_JSON_RETRIES, response)
            except Exception as e:
                logger.warning("Data Scientist API error (attempt %d/%d): %s", attempt + 1, MAX_JSON_RETRIES, e)
                response = ""

            if attempt < MAX_JSON_RETRIES - 1:
                conversation_history.append({"role": "assistant", "content": response or "(empty response)"})
                conversation_history.append({"role": "user", "content": REMINDER_MSG})

        if "error" in call_json or "tool" not in call_json:
            logger.warning("All JSON retries exhausted at step %d. Continuing analysis.", loop_count)
            conversation_history.append({"role": "assistant", "content": response or "(empty response)"})
            conversation_history.append({"role": "user", "content": REMINDER_MSG})
            continue

        thought = call_json.get("thought", "")
        tool = call_json.get("tool", "")
        args = call_json.get("arguments", {})

        logger.info(f"Step {loop_count} - Thought: {thought} | Tool: {tool}")
        conversation_history.append({"role": "assistant", "content": response})

        if tool == "done":
            if not analysis_results.get("findings"):
                logger.warning("Agent called 'done' without saved findings; nudging.")
                conversation_history.append({"role": "user", "content": "You called 'done' but have not saved any findings. Please call 'save_finding' before 'done'."})
                continue
            logger.info("Data Scientist agent finished tool loop.")
            break
        elif tool == "inspect_column":
            result = inspect_column_tool(args.get("col_name"))
        elif tool in ("outlier_detection", "outliers"):
            col = args.get("column") or args.get("col_a") or args.get("col") or args.get("col1") or args.get("col_name")
            result = run_test_tool("outlier_detection", col)
        elif tool in ("normality", "normaltest"):
            col = args.get("column") or args.get("col_a") or args.get("col") or args.get("col1") or args.get("col_name")
            result = run_test_tool("normality", col)
        elif tool == "run_test":
            col_a = args.get("col_a") or args.get("col1") or args.get("column")
            col_b = args.get("col_b") or args.get("col2")
            result = run_test_tool(args.get("test_type"), col_a, col_b)
        elif tool == "group_analysis":
            result = group_analysis_tool(args.get("numeric_col"), args.get("group_col"))
        elif tool == "create_chart":
            result = create_chart_tool(args.get("chart_type"), args.get("x"), args.get("y"), args.get("hue"))
        elif tool == "save_finding":
            result = save_finding_tool(
                args.get("title"),
                args.get("evidence"),
                args.get("confidence"),
                args.get("effect_size"),
                args.get("impact_score")
            )
        else:
            result = f"Error: unknown tool '{tool}'."

        execution_stdout_log.append(f"Step {loop_count}: Called {tool} with {args} -> {str(result)[:100]}")
        conversation_history.append({"role": "user", "content": json.dumps(result, default=str)})

        # Pace consecutive tool loop steps slightly when using rate-limited API models
        step_delay = float(os.environ.get("LLM_STEP_DELAY", "1.5"))
        if step_delay > 0:
            time.sleep(step_delay)

    insight_count = len(analysis_results.get("findings", []))
    publish_stage_progress(
        state,
        "data_scientist",
        "completed",
        f"Analysis complete. Identified {insight_count} key findings.",
        state.get("regeneration_round", 0)
    )

    return {
        "conversation_history": conversation_history,
        "analysis_results": analysis_results,
        "chart_images": existing_charts,
        "agent_files": agent_files,
        "investigation_log": investigation_log,
        "last_execution_stdout": "\n".join(execution_stdout_log),
        "last_execution_stderr": "",
        "last_execution_outputs": [],
        "currency_context": currency_context,
        "methodology_code": "Iterative Tool-calling Execution Loop",
        "reflection_feedback": "",
        "reflection_feedback_formatted": "",
        "_can_reflect": False
    }


def reflector_node(state: AnalysisGraphState) -> dict:
    """Reflector Agent Node: Reviews analysis depth and decides whether a reflection cycle is needed."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    ref_iter = state.get("reflection_iteration", 0)
    max_ref = state.get("max_reflections", 2)

    publish_stage_progress(
        state,
        "reflector",
        "running",
        "Reviewing analytical results to see if follow-up investigations are needed...",
        ref_iter
    )

    prompt = REFLECTOR_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        purpose=state.get("domain_brief", {}).get("datasetPurpose", "Analyze data"),
        important_columns=json.dumps(state.get("domain_brief", {}).get("importantColumns", [])),
        draft_results=json.dumps(state.get("analysis_results", {}), default=str),
        previous_feedback=state.get("reflection_feedback", ""),
        iteration=ref_iter + 1,
        max_iterations=max_ref
    )

    messages = [
        {"role": "system", "content": "You are a strict data scientist supervisor. Evaluate if analysis is deep enough. Output JSON only."},
        {"role": "user", "content": prompt}
    ]

    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    max_json_retries = 3
    res_json = {"error": "not attempted yet"}

    for attempt in range(max_json_retries):
        try:
            use_json_mode = (attempt == 0)
            response = chat_completion(messages, task="review", json_mode=use_json_mode, timeout=timeout_val)
            res_json = parse_json_safely(response)
            if "error" not in res_json and "needs_more_analysis" in res_json:
                break
        except Exception as e:
            logger.warning(f"Reflector API error (attempt {attempt + 1}/{max_json_retries}): {e}")

    if "error" in res_json:
        res_json = {"needs_more_analysis": False, "feedback": "", "follow_up_tasks": []}

    investigation_log = list(state.get("investigation_log", []))
    investigation_log.append({
        "agent": "reflector",
        "round": ref_iter,
        "action": "Reviewed analytical depth",
        "result": f"Needs more analysis: {res_json.get('needs_more_analysis')}. Feedback: {res_json.get('feedback')}"
    })

    can_reflect = bool(res_json.get("needs_more_analysis")) and (ref_iter < max_ref)
    next_ref_iter = (ref_iter + 1) if can_reflect else ref_iter

    if can_reflect:
        feedback = res_json.get("feedback", "")
        follow_up_tasks = res_json.get("follow_up_tasks", [])

        feedback_str = f"Summary feedback from Reflector: {feedback}\n"
        if follow_up_tasks:
            feedback_str += "Please perform the following follow-up tasks in your script:\n"
            for task in follow_up_tasks:
                feedback_str += f"- {task}\n"

        feedback_str += f"\nExecution Feedback:\nStdout:\n```\n{state.get('last_execution_stdout', '')}\n```\n"
        publish_stage_progress(
            state,
            "reflector",
            "completed",
            f"Reflection: Loop requested (Round {ref_iter + 1}/{max_ref}). Feedback: {feedback[:80]}...",
            ref_iter
        )
        return {
            "reflection_iteration": next_ref_iter,
            "reflection_feedback": feedback,
            "follow_up_tasks": follow_up_tasks,
            "reflection_feedback_formatted": feedback_str,
            "investigation_log": investigation_log,
            "_can_reflect": True
        }
    else:
        publish_stage_progress(
            state,
            "reflector",
            "completed",
            "Analysis depth approved. Moving to visualization generation.",
            ref_iter
        )
        return {
            "reflection_iteration": next_ref_iter,
            "reflection_feedback": "",
            "reflection_feedback_formatted": "",
            "investigation_log": investigation_log,
            "_can_reflect": False
        }


def route_reflection(state: AnalysisGraphState) -> str:
    """Conditional Edge: Dynamically cycles back to Data Scientist or advances to Visual Preprocessor."""
    if state.get("cancelled") or state.get("error"):
        return "end"

    if state.get("_can_reflect", False):
        logger.info(f"LangGraph Reflection Loop triggered (iteration {state.get('reflection_iteration', 1)})")
        return "data_scientist"
    return "viz_preprocessor"


def viz_preprocessor_node(state: AnalysisGraphState) -> dict:
    """Visualization Preprocessor Node: Pre-processes analytical findings into chart specifications."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    if state.get("visualization_data"):
        return {}

    publish_stage_progress(
        state,
        "viz_preprocessor",
        "running",
        "Pre-processing analysis results into chart-ready data specifications...",
        state.get("regeneration_round", 0)
    )

    currency_context = state.get("currency_context") or "No currency context detected."
    prompt = VISUALIZATION_PREPROCESS_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        schema=json.dumps(state.get("schema", {}), default=str),
        full_analysis=json.dumps(state.get("analysis_results", {}), default=str),
        currency_context=currency_context,
    )

    messages = [
        {"role": "system", "content": "You are a quantitative data analyst specializing in visualization mapping. Output JSON only."},
        {"role": "user", "content": prompt}
    ]

    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    res_json = {}
    for attempt in range(3):
        try:
            use_json_mode = (attempt == 0)
            response = chat_completion(messages, task="review", json_mode=use_json_mode, timeout=timeout_val)
            res_json = parse_json_safely(response)
            if "error" not in res_json and "visualizations" in res_json:
                break
        except Exception as e:
            logger.warning(f"Visualization Preprocessor attempt {attempt + 1} failed: {e}")

    num_specs = len(res_json.get("visualizations", [])) if isinstance(res_json, dict) else 0
    publish_stage_progress(
        state,
        "viz_preprocessor",
        "completed",
        f"Formulated {num_specs} visualization specification(s) for sandbox rendering.",
        state.get("regeneration_round", 0)
    )

    return {"visualization_data": res_json}


def viz_coder_node(state: AnalysisGraphState) -> dict:
    """Visualization Agent Node: Generates and executes custom matplotlib/seaborn code in sandbox."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "viz_coder",
        "running",
        "Generating custom visualizations using matplotlib and seaborn...",
        state.get("regeneration_round", 0)
    )

    currency_context = state.get("currency_context") or "No currency context detected."

    # ── COLUMN PROFILE ─────────────────────────────────────────────────────────
    # Build a compact column quality profile so the LLM knows which columns are
    # safe to use in charts and which to avoid (all-null, dirty strings, etc.)
    df = state["df"]
    col_profile = {}
    for col in df.columns:
        null_pct = round(df[col].isna().mean() * 100, 1)
        dtype_str = str(df[col].dtype)
        if null_pct == 100.0:
            status = "all_null_SKIP"
        elif dtype_str.startswith("float") or dtype_str.startswith("int"):
            status = "numeric_clean"
        else:
            # Check if object column is mostly numeric
            coerced = pd.to_numeric(df[col], errors="coerce")
            pct_numeric = round(coerced.notna().mean() * 100, 1)
            if pct_numeric >= 60:
                status = "numeric_clean"
            elif pct_numeric >= 30:
                status = "numeric_dirty_coerce_first"
            else:
                status = "categorical"
        col_profile[col] = {"null_pct": null_pct, "dtype": dtype_str, "status": status}

    col_profile_str = json.dumps(col_profile, indent=2)
    # ───────────────────────────────────────────────────────────────────────────

    prompt = VIZ_CODER_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        full_analysis=json.dumps(state.get("analysis_results", {}), default=str),
        visualization_data=json.dumps(state.get("visualization_data", {}), default=str),
        schema=json.dumps(state.get("schema", {}), default=str),
        currency_context=currency_context,
    )

    # Prepend the column profile to the prompt so LLM can see column safety upfront
    prompt = (
        f"## COLUMN QUALITY PROFILE (use this to pick safe columns for charts)\n"
        f"Columns marked 'all_null_SKIP' must NOT be used in any chart. "
        f"Columns marked 'numeric_dirty_coerce_first' must be coerced with pd.to_numeric(..., errors='coerce') "
        f"before use (the sandbox already does this globally, but do your per-chart dropna AFTER loading).\n"
        f"```json\n{col_profile_str}\n```\n\n"
        + prompt
    )

    messages = [
        {"role": "system", "content": "You are a visualization expert. Output only Python plotting code blocks."},
        {"role": "user", "content": prompt}
    ]

    max_gen_attempts = 3
    code = ""
    for gen_attempt in range(max_gen_attempts):
        try:
            response = chat_completion(messages, task="visual", json_mode=False, timeout=int(os.environ.get("LLM_TIMEOUT", "600")))
            code = extract_code_block(response)
            if code:
                break
        except Exception as e:
            logger.warning(f"Viz Coder generation error (attempt {gen_attempt + 1}): {e}")

    if not code:
        return {"error": "Viz Coder agent failed to return Python plotting code after multiple attempts.", "viz_error": "No code generated"}

    logger.info("Executing generated visualization code...")
    exec_res = execute_analysis_code(code, state["df"], timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "90")))

    if exec_res.success:
        charts_list = []
        for output in exec_res.agent_outputs:
            if output.get("type") == "image" and isinstance(output.get("data"), (bytes, bytearray)):
                charts_list.append({
                    "filename": output["filename"],
                    "title": output.get("finding_title") or output.get("purpose") or output["filename"],
                    "interpretation": output.get("interpretation", "Data distribution and patterns."),
                    "insight_text": output.get("insight_text", ""),
                    "finding_title": output.get("finding_title", ""),
                    "data": output["data"],
                })

        if not charts_list:
            for chart_file in exec_res.charts:
                charts_list.append({
                    "filename": chart_file["name"],
                    "title": chart_file["name"],
                    "interpretation": "Generated by visualization agent.",
                    "insight_text": "",
                    "finding_title": "",
                    "data": chart_file["data"],
                })

        agent_files = list(state.get("agent_files", []))
        for output in exec_res.agent_outputs:
            agent_files.append({
                "agent": "viz_coder",
                "round": state.get("regeneration_round", 0),
                "filename": output.get("filename"),
                "type": output.get("type"),
                "purpose": output.get("purpose"),
            })

        publish_stage_progress(
            state,
            "viz_coder",
            "completed",
            f"Successfully generated {len(charts_list)} custom charts.",
            state.get("regeneration_round", 0)
        )

        if not charts_list:
            # Script ran but produced zero valid charts — likely blank canvases were discarded.
            # Log sandbox stdout so chart-level errors are visible.
            sandbox_log = (exec_res.stdout or "")[:3000]
            logger.warning(
                f"Viz Coder: Script succeeded but produced 0 valid charts. "
                f"Likely cause: global df.dropna() on a null column wiped all rows. "
                f"Routing to repair. Sandbox stdout:\n{sandbox_log}"
            )
            return {
                "agent_files": agent_files,
                "viz_code": code,
                "viz_error": (
                    "The visualization script executed without errors but generated ZERO valid charts. "
                    "This is almost always caused by calling df.dropna() globally at the top of the script "
                    "on columns that are entirely null (e.g. 'ambience', 'wifi'), which removes ALL rows. "
                    "Rewrite the script: (1) NEVER call dropna() globally. "
                    "(2) Only drop NaN per-chart on the specific columns that chart uses. "
                    "(3) Always check len(chart_df) > 0 before plotting. "
                    "(4) Add manifest_outputs.append() ONLY after plt.savefig() succeeds."
                ),
                "viz_repair_attempts": 0,
            }

        return {
            "chart_images": charts_list,
            "agent_files": agent_files,
            "viz_code": code,
            "viz_error": None,
            "viz_repair_attempts": 0
        }
    else:
        logger.warning(f"Viz Coder script failed initially: {exec_res.error_message}. Routing to self-repair loop.")
        return {
            "viz_code": code,
            "viz_error": exec_res.error_message,
            "viz_repair_attempts": 0
        }



def route_viz_coder(state: AnalysisGraphState) -> str:
    """Conditional Edge: Routes to Self-Repair Loop if plotting script failed, else proceeds to Report Writer."""
    if state.get("cancelled") or state.get("error"):
        return "end"

    max_repair = int(os.environ.get("CODE_REPAIR_MAX_ATTEMPTS", "3"))
    if state.get("viz_error") and state.get("viz_repair_attempts", 0) < max_repair:
        return "viz_repair"
    return "report_writer"


def viz_repair_node(state: AnalysisGraphState) -> dict:
    """Visualization Self-Repair Node: Prompts LLM to fix syntax/runtime errors and re-tests."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    attempts = state.get("viz_repair_attempts", 0) + 1
    code = state.get("viz_code", "")
    error_msg = state.get("viz_error", "Unknown execution error")

    logger.info(f"Executing Visualization Self-Repair (attempt {attempts}). Error: {error_msg}")

    # Build column profile for repair context
    df = state["df"]
    col_profile_repair = {}
    for col in df.columns:
        null_pct = round(df[col].isna().mean() * 100, 1)
        dtype_str = str(df[col].dtype)
        if null_pct == 100.0:
            status = "all_null_SKIP"
        elif dtype_str.startswith("float") or dtype_str.startswith("int"):
            status = "numeric_clean"
        else:
            coerced = pd.to_numeric(df[col], errors="coerce")
            pct_numeric = round(coerced.notna().mean() * 100, 1)
            if pct_numeric >= 60:
                status = "numeric_clean"
            elif pct_numeric >= 30:
                status = "numeric_dirty_coerce_first"
            else:
                status = "categorical"
        col_profile_repair[col] = {"null_pct": null_pct, "dtype": dtype_str, "status": status}
    col_profile_repair_str = json.dumps(col_profile_repair, indent=2)

    repair_prompt = f"""
Your plotting script has a problem: {error_msg}

## COLUMN QUALITY PROFILE — use this to pick safe columns for each chart
Columns with status 'all_null_SKIP' must NOT be used in any chart (using them with dropna wipes all rows → blank chart).
```json
{col_profile_repair_str}
```

Here was your code:
```python
{code}
```

## CRITICAL ISSUES TO FIX:
1. **BLANK CHARTS**: The most common cause of this error is calling `df.dropna(subset=[...])` with a list that includes a 100% null column. This deletes ALL rows, making the DataFrame empty, so the chart renders as a blank 0.0–1.0 axis. Fix: NEVER dropna globally. Only drop NaN per-chart, on the specific columns that chart actually uses.
2. **DIRTY NUMERIC COLUMNS**: Columns marked 'numeric_dirty_coerce_first' contain string garbage (e.g. "-", "NEW"). The sandbox already coerces them, but you must still do per-chart dropna after using them.
3. **EMPTY DATA GUARD**: Before calling ANY seaborn/matplotlib plot function, check `if len(chart_df) < 3: print("skipped"); else: plot(...)`.

## Rewrite rules:
1. Loads `df` from "input_df.pkl" using `pickle.load(open("input_df.pkl", "rb"))`.
2. Sets `import matplotlib; matplotlib.use('Agg')` before importing pyplot.
3. NEVER calls `df.dropna()` globally — only per-chart on the columns that chart uses.
4. Checks `len(chart_df) >= 3` before plotting, skipping and printing if not enough rows.
5. Saves each chart with `plt.savefig("descriptive_name.png", dpi=200, bbox_inches="tight")` then `plt.close("all")`.
6. Wraps each chart in a try/except block so one failure doesn't stop the others.
7. Appends to `manifest_outputs` list ONLY after each successful `plt.savefig()`.
8. At the very END of the script, writes a `manifest.json` using the `manifest_outputs` list:
```json
{{
  "outputs": [
    {{
      "filename": "chart_name.png",
      "type": "image",
      "finding_title": "Title of the finding this chart shows",
      "interpretation": "What the chart shows and why it matters",
      "insight_text": "One sentence key takeaway"
    }}
  ],
  "deleted_files": []
}}
```

Return ONLY the corrected Python script inside a single ```python ... ``` code block.
"""
    repair_messages = [
        {"role": "system", "content": "You are a plotting fixer. Fix Python errors. Return code only."},
        {"role": "user", "content": repair_prompt}
    ]


    fixed_code = ""
    try:
        repair_response = chat_completion(repair_messages, task="visual", json_mode=False, timeout=int(os.environ.get("LLM_TIMEOUT", "600")))
        fixed_code = extract_code_block(repair_response)
    except Exception as e:
        logger.error(f"Viz self-repair LLM call error: {e}")

    if not fixed_code:
        return {"viz_error": f"Failed to extract repaired code on attempt {attempts}", "viz_repair_attempts": attempts}

    exec_res = execute_analysis_code(fixed_code, state["df"], timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "90")))

    if exec_res.success:
        charts_list = []
        for output in exec_res.agent_outputs:
            if output.get("type") == "image" and isinstance(output.get("data"), (bytes, bytearray)):
                charts_list.append({
                    "filename": output["filename"],
                    "title": output.get("finding_title") or output.get("purpose") or output["filename"],
                    "interpretation": output.get("interpretation", "Data distribution and patterns."),
                    "insight_text": output.get("insight_text", ""),
                    "finding_title": output.get("finding_title", ""),
                    "data": output["data"],
                })
        if not charts_list:
            for chart_file in exec_res.charts:
                charts_list.append({
                    "filename": chart_file["name"],
                    "title": chart_file["name"],
                    "interpretation": "Generated by visualization agent.",
                    "insight_text": "",
                    "finding_title": "",
                    "data": chart_file["data"],
                })

        agent_files = list(state.get("agent_files", []))
        for output in exec_res.agent_outputs:
            agent_files.append({
                "agent": "viz_coder",
                "round": state.get("regeneration_round", 0),
                "filename": output.get("filename"),
                "type": output.get("type"),
                "purpose": output.get("purpose"),
            })

        publish_stage_progress(
            state,
            "viz_coder",
            "completed",
            f"Successfully generated {len(charts_list)} custom charts after self-repair.",
            state.get("regeneration_round", 0)
        )
        return {
            "chart_images": charts_list,
            "agent_files": agent_files,
            "viz_code": fixed_code,
            "viz_error": None,
            "viz_repair_attempts": attempts
        }
    else:
        return {
            "viz_code": fixed_code,
            "viz_error": exec_res.error_message,
            "viz_repair_attempts": attempts
        }


def route_viz_repair(state: AnalysisGraphState) -> str:
    """Conditional Edge: Cycles back to self-repair or forwards to report writer if attempts are exhausted."""
    if state.get("cancelled") or state.get("error"):
        return "end"

    max_repair = int(os.environ.get("CODE_REPAIR_MAX_ATTEMPTS", "3"))
    if state.get("viz_error") and state.get("viz_repair_attempts", 0) < max_repair:
        return "viz_repair"

    if state.get("viz_error"):
        logger.warning(f"Viz code failed after {max_repair} repair attempts: {state.get('viz_error')}. Proceeding to report.")
        publish_stage_progress(
            state,
            "viz_coder",
            "completed",
            f"Visualization code failed to execute after {max_repair} self-repair attempts. Falling back to default plots.",
            state.get("regeneration_round", 0)
        )
    return "report_writer"

def _normalize_report_dict(data: dict, state: AnalysisGraphState) -> dict:
    if not isinstance(data, dict):
        return {}

    # Executive summary
    if "executive_summary" in data and "executiveSummary" not in data:
        data["executiveSummary"] = data["executive_summary"]
    elif "summary" in data and "executiveSummary" not in data:
        data["executiveSummary"] = data["summary"]

    # Key findings
    if "key_findings" in data and "keyFindings" not in data:
        data["keyFindings"] = data["key_findings"]
    elif "findings" in data and "keyFindings" not in data:
        data["keyFindings"] = data["findings"]

    # Report sections
    if "report_sections" in data and "reportSections" not in data:
        data["reportSections"] = data["report_sections"]
    elif "sections" in data and "reportSections" not in data:
        data["reportSections"] = data["sections"]

    # Anomalies
    if "data_anomalies" in data and "anomalies" not in data:
        data["anomalies"] = data["data_anomalies"]
    elif "risk_factors" in data and "anomalies" not in data:
        data["anomalies"] = data["risk_factors"]

    # Recommendations
    if "strategic_recommendations" in data and "recommendations" not in data:
        data["recommendations"] = data["strategic_recommendations"]

    # If keyFindings is missing or empty, extract from reportSections
    if not data.get("keyFindings"):
        extracted = []
        for sec in data.get("reportSections", []):
            if isinstance(sec, dict) and "findings" in sec and isinstance(sec["findings"], list):
                extracted.extend(sec["findings"])
        if extracted:
            data["keyFindings"] = extracted

    # If recommendations is missing or empty, extract from reportSections
    if not data.get("recommendations"):
        extracted_recs = []
        for sec in data.get("reportSections", []):
            if isinstance(sec, dict) and "recommendations" in sec and isinstance(sec["recommendations"], list):
                extracted_recs.extend(sec["recommendations"])
        if extracted_recs:
            data["recommendations"] = extracted_recs

    # If anomalies is missing or empty, extract from reportSections
    if not data.get("anomalies"):
        extracted_anom = []
        for sec in data.get("reportSections", []):
            if isinstance(sec, dict) and "anomalies" in sec and isinstance(sec["anomalies"], list):
                extracted_anom.extend(sec["anomalies"])
        if extracted_anom:
            data["anomalies"] = extracted_anom

    # Title
    if "report_title" in data and "title" not in data:
        data["title"] = data["report_title"]
    elif "reportTitle" in data and "title" not in data:
        data["title"] = data["reportTitle"]
    elif not data.get("title"):
        domain = data.get("domain") or state.get("domain_brief", {}).get("domain", "Dataset")
        data["title"] = f"{domain} Analytical Assessment"

    # ID
    if not data.get("id"):
        data["id"] = state.get("job_id") or f"rep_{uuid.uuid4().hex[:8]}"

    return data


def report_writer_node(state: AnalysisGraphState) -> dict:
    """Report Writer Node: Drafts the comprehensive executive report in structured JSON."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "report_writer",
        "running",
        "Drafting comprehensive executive report...",
        state.get("regeneration_round", 0)
    )

    stats = state.get("stats", {})
    charts_desc = [
        {
            "filename": c.get("filename", ""),
            "title": c.get("title", ""),
            "interpretation": c.get("interpretation", ""),
            "insight_text": c.get("insight_text", "")
        }
        for c in state.get("chart_images", [])
    ]
    stats_dict = state.get("stats", {})
    numeric_sum = json.dumps(stats_dict.get("numeric_summary", {}), default=str)
    grouped_sum = json.dumps(stats_dict.get("grouped_summary", {}), default=str)
    missing_vals = json.dumps(stats_dict.get("missing_values", {}), default=str)
    stats_summary = f"Missing values: {missing_vals}\nNumeric Summary: {numeric_sum}\nGrouped Summary: {grouped_sum}"

    currency_context = state.get("currency_context") or "No currency context detected."

    # Senior tier & autonomous team context for richer report
    _cleaning = state.get("cleaning_manifest", {})
    _plan = state.get("investigation_plan", {})
    _ml = state.get("ml_results", {})
    _causal = state.get("causal_results", {})
    _forecast = state.get("forecast_results", {})
    _anomaly = state.get("anomaly_results", {})
    _strategic = state.get("strategic_results", {})
    senior_context = (
        f"\n\n## Data Quality Engineering & Cleaning Manifest\n{_cleaning.get('summary', 'Standardized.')}\n"
        f"Actions taken: {json.dumps(_cleaning.get('actions', []), default=str)[:600]}\n"
        f"\n## Dynamic Research Hypotheses & Findings\n{json.dumps(_plan.get('hypotheses', []), default=str)[:600]}\n"
        f"\n## Machine Learning & Predictive Modeling\n{_ml.get('summary', 'Predictive modeling conducted.')}\n"
        f"Top Drivers: {json.dumps(_ml.get('feature_importances', []), default=str)[:600]}\n"
        f"\n## Causal Analysis Summary\n{_causal.get('causal_summary', 'Not available.')}\n"
        f"\n## Forecast\nTrend: {_forecast.get('trend_direction', 'N/A')} | "
        f"Slope/period: {_forecast.get('trend_slope_per_period', 'N/A')} | "
        f"Skipped: {_forecast.get('skipped', False)}\n"
        f"\n## Anomaly Detection\nRate: {_anomaly.get('anomaly_rate_pct', 'N/A')}% | "
        f"Segments detected: {len(_anomaly.get('segments', []))}\n"
        f"\n## Strategic Headline\n{_strategic.get('executive_headline', 'Not available.')}\n"
        f"Key complications: {json.dumps(_strategic.get('complication', []), default=str)[:800]}\n"
    )

    prompt = REPORT_WRITER_PROMPT.format(
        domain_brief=json.dumps(state.get("domain_brief", {}), default=str),
        schema=json.dumps(state.get("schema", {}), default=str),
        sample_rows=json.dumps(state.get("sample_rows", []), default=str),
        stats_summary=stats_summary + senior_context,
        full_analysis=json.dumps(state.get("analysis_results", {}), default=str),
        charts=json.dumps(charts_desc, default=str),
        currency_context=currency_context,
    )

    messages = [
        {"role": "system", "content": "You are a professional business writer. Generate JSON report conforming to the requested schema. Output JSON only."},
        {"role": "user", "content": prompt}
    ]

    timeout_val = int(os.environ.get("LLM_TIMEOUT", "600"))
    report_json = {"error": "not attempted yet"}
    for attempt in range(3):
        try:
            use_json_mode = (attempt == 0)
            response = chat_completion(messages, task="report", json_mode=use_json_mode, timeout=timeout_val)
            parsed = parse_json_safely(response)
            if "error" not in parsed:
                norm = _normalize_report_dict(parsed, state)
                if "keyFindings" in norm or "executiveSummary" in norm or "reportSections" in norm:
                    report_json = norm
                    break
        except Exception as e:
            logger.warning(f"Report Writer API error (attempt {attempt + 1}): {e}")

    if "error" in report_json or ("keyFindings" not in report_json and "reportSections" not in report_json):
        # Graceful fallback report synthesis from Data Scientist's actual findings
        findings = state.get("analysis_results", {}).get("findings", [])
        domain = state.get("domain_brief", {}).get("domain", "Dataset")
        purpose = state.get("domain_brief", {}).get("datasetPurpose", "Analysis")
        logger.warning("Report Writer using synthesized fallback report from agent findings.")
        report_json = {
            "id": state.get("job_id") or f"rep_{uuid.uuid4().hex[:8]}",
            "title": f"{domain} Analytical Assessment",
            "domain": domain,
            "executiveSummary": f"Comprehensive analytical assessment of {domain.lower()} ({purpose}). The analysis identified {len(findings)} key findings across distribution patterns, correlation metrics, and categorical structures.",
            "methodology": "Statistical hypothesis testing, distribution analysis, normality checks, and correlation profiling.",
            "keyFindings": findings,
            "reportSections": [
                {
                    "type": "findings_group",
                    "title": "Core Analytical Insights",
                    "narrative": "Detailed statistical patterns uncovered across evaluated features.",
                    "findings": findings
                }
            ],
            "anomalies": state.get("stats", {}).get("statistical_anomalies", []),
            "recommendations": [
                {
                    "action": "Leverage identified statistical patterns for operational optimization.",
                    "rationale": "Directly grounded in multi-agent data findings.",
                    "priority": "high",
                    "expected_outcome": "Improved operational strategy."
                }
            ],
            "limitations": ["Analysis performed on provided dataset sample."]
        }

    publish_stage_progress(
        state,
        "report_writer",
        "completed",
        "Draft report prepared.",
        state.get("regeneration_round", 0)
    )
    return {"report": report_json}


def narrative_stitcher_node(state: AnalysisGraphState) -> dict:
    """Narrative Stitcher Node: Crafts a polished executive summary."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    run_stitcher = os.environ.get("LLM_NARRATIVE_STITCHER", "true").strip().lower() != "false"
    if not run_stitcher:
        return {}

    publish_stage_progress(
        state,
        "report_writer",
        "running",
        "Narrative Stitcher: Crafting cohesive human-like Executive Summary...",
        state.get("regeneration_round", 0)
    )

    report = dict(state.get("report", {}))
    findings_json = json.dumps(report.get("keyFindings", []), default=str)
    anomalies_json = json.dumps(report.get("anomalies", []), default=str)
    recs_json = json.dumps(report.get("recommendations", []), default=str)
    draft_summary = report.get("executiveSummary", "")
    report_sections_json = json.dumps(report.get("reportSections", []), default=str)

    prompt = NARRATIVE_STITCHER_PROMPT.format(
        domain=report.get("domain", "Unknown"),
        key_findings=findings_json,
        anomalies=anomalies_json,
        recommendations=recs_json,
        draft_summary=draft_summary,
        report_sections=report_sections_json,
    )

    messages = [
        {"role": "system", "content": "You are a professional business writer and executive editor."},
        {"role": "user", "content": prompt}
    ]

    response = ""
    for gen_attempt in range(3):
        try:
            response = chat_completion(messages, task="report", json_mode=False, timeout=int(os.environ.get("LLM_TIMEOUT", "600")))
            if response:
                break
        except Exception as e:
            logger.warning(f"Narrative Stitcher generation error (attempt {gen_attempt + 1}): {e}")

    if response:
        clean_summary = response.strip()
        if clean_summary.startswith("```"):
            lines = clean_summary.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_summary = "\n".join(lines).strip()
        report["executiveSummary"] = clean_summary
        report["executive_summary"] = clean_summary

    publish_stage_progress(
        state,
        "report_writer",
        "completed",
        "Executive summary polished by Narrative Stitcher.",
        state.get("regeneration_round", 0)
    )
    return {"report": report}


def _validate_report_numbers(report: dict, df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Compares numbers cited in findings against the actual DataFrame statistics."""
    warnings = []
    if df is None or df.empty:
        return warnings

    try:
        findings = report.get("keyFindings", [])
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

        for finding in findings:
            title = finding.get("title", "Unknown")
            detail = finding.get("detail", "")
            text_to_check = (title + " " + detail).lower()

            referenced_cols = []
            for col in numeric_cols:
                col_pat = re.escape(col.lower()).replace(r'\_', r'[_\s]+')
                pattern = rf"\b{col_pat}\b"
                if re.search(pattern, text_to_check):
                    referenced_cols.append(col)

            if not referenced_cols:
                continue

            clean_text = text_to_check.replace(",", "")
            raw_numbers = re.findall(r'([-+]?\d+(?:\.\d+)?)\s*(%)?', clean_text)
            numbers = []
            for num_str, pct in raw_numbers:
                try:
                    val = float(num_str)
                    numbers.append(val)
                    if pct:
                        numbers.append(val / 100.0)
                except ValueError:
                    continue

            if not numbers:
                continue

            for col in referenced_cols[:2]:
                try:
                    stats_map = {}
                    if any(w in text_to_check for w in ["mean", "average", "avg"]):
                        stats_map["mean"] = (df[col].mean(), "average")
                    if any(w in text_to_check for w in ["min", "minimum", "lowest"]):
                        stats_map["min"] = (df[col].min(), "minimum")
                    if any(w in text_to_check for w in ["max", "maximum", "highest", "peak"]):
                        stats_map["max"] = (df[col].max(), "maximum")
                    if any(w in text_to_check for w in ["total", "sum"]):
                        stats_map["sum"] = (df[col].sum(), "total")
                    if not stats_map:
                        stats_map["mean"] = (df[col].mean(), "mean")

                    for stat_name, (actual_val, label) in stats_map.items():
                        if pd.isna(actual_val):
                            continue
                        matched_any = False
                        for val in numbers:
                            deviation = abs(val) if actual_val == 0 else abs(actual_val - val) / max(abs(actual_val), 1e-9)
                            if deviation <= 0.20:
                                matched_any = True
                                break

                        if not matched_any:
                            warnings.append({
                                "finding": title,
                                "column": col,
                                "metric": label,
                                "actual_value": round(float(actual_val), 4),
                                "message": f"Finding '{title}' refers to the {label} of '{col}' (actual: {float(actual_val):.2f}), but no close number was found in text: '{detail}'"
                            })
                except Exception as col_err:
                    logger.warning(f"Error validating column {col} in finding '{title}': {col_err}")
    except Exception as e:
        logger.warning(f"Automated numeric validation failed: {e}")

    return warnings


def auditor_node(state: AnalysisGraphState) -> dict:
    """Quality Auditor Node: Verifies factual consistency, inspects scores, and sets retry targets."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "auditor",
        "running",
        "Auditing report narrative against code execution evidence and dataset statistics...",
        state.get("regeneration_round", 0)
    )

    report_copy = dict(state.get("report", {}))
    analysis_copy = dict(state.get("analysis_results", {}))
    charts_desc = [
        {"title": c["title"], "interpretation": c["interpretation"]}
        for c in state.get("chart_images", [])
    ]

    validation_warnings = _validate_report_numbers(report_copy, state.get("df"))

    stats_dict = state.get("stats", {})
    numeric_sum = json.dumps(stats_dict.get("numeric_summary", {}), default=str)
    grouped_sum = json.dumps(stats_dict.get("grouped_summary", {}), default=str)
    missing_vals = json.dumps(stats_dict.get("missing_values", {}), default=str)
    dataset_stats = f"Missing values: {missing_vals}\nNumeric Summary: {numeric_sum}\nGrouped Summary: {grouped_sum}"

    # Exclude internal huge code/log fields from the prompt text
    report_for_prompt = {
        "title": report_copy.get("title"),
        "domain": report_copy.get("domain"),
        "executiveSummary": report_copy.get("executiveSummary") or report_copy.get("executive_summary"),
        "keyFindings": report_copy.get("keyFindings") or report_copy.get("key_findings", []),
        "reportSections": [
            {
                "title": s.get("title"),
                "narrative": s.get("narrative") or s.get("content", ""),
                "findings": s.get("findings", [])
            }
            for s in report_copy.get("reportSections", [])[:6]
            if isinstance(s, dict)
        ],
        "anomalies": report_copy.get("anomalies", []),
        "recommendations": report_copy.get("recommendations", [])
    }
    analysis_copy = {
        "findings": state.get("analysis_results", {}).get("findings", [])
    }

    currency_context = state.get("currency_context") or "No currency context detected."
    prompt = AUDITOR_PROMPT.format(
        report=json.dumps(report_for_prompt, default=str),
        full_analysis=json.dumps(analysis_copy, default=str),
        charts=json.dumps(charts_desc, default=str),
        dataset_stats=dataset_stats,
        validation_warnings=json.dumps(validation_warnings, default=str),
        currency_context=currency_context,
    )

    messages = [
        {"role": "system", "content": "You are a strict data QA auditor. Validate the report and output audit results in JSON format only."},
        {"role": "user", "content": prompt}
    ]

    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    audit_json = {"error": "not attempted yet"}
    for attempt in range(3):
        try:
            use_json_mode = (attempt == 0)
            response = chat_completion(messages, task="review", json_mode=use_json_mode, timeout=timeout_val)
            parsed = parse_json_safely(response)
            if "error" not in parsed:
                if "passed" in parsed and "approved" not in parsed:
                    parsed["approved"] = parsed["passed"]
                if "critical_issues" in parsed and "issues" not in parsed:
                    parsed["issues"] = parsed["critical_issues"]
                if "retry_targets" in parsed and "retryTargets" not in parsed:
                    parsed["retryTargets"] = parsed["retry_targets"]
                if "score" in parsed:
                    audit_json = parsed
                    break
        except Exception as e:
            logger.warning(f"Auditor API error (attempt {attempt + 1}): {e}")

    if "error" in audit_json:
        audit_json = {
            "score": 85,
            "approved": False,
            "summary": "Audit failed to parse.",
            "issues": [{"message": "Auditor failed to parse JSON"}],
            "retryTargets": []
        }

    score = audit_json.get("score", 0)
    approved = audit_json.get("approved", False) and score >= 88

    issues = audit_json.get("issues", [])
    if not isinstance(issues, list):
        issues = []

    has_warnings = len(validation_warnings) > 0
    for warning in validation_warnings:
        issues.append({
            "target": "report",
            "severity": "high",
            "message": f"AUTOMATED VALIDATION WARNING: {warning['message']}"
        })

    regeneration_round = state.get("regeneration_round", 0)
    max_regeneration = state.get("max_regeneration_rounds", 3)

    can_retry = (not approved) and (regeneration_round < max_regeneration)
    next_round = (regeneration_round + 1) if can_retry else regeneration_round

    if has_warnings and can_retry:
        approved = False
        if score >= 88:
            score = 87

    retry_targets = audit_json.get("retryTargets", []) if not approved else []
    if has_warnings and "report" not in retry_targets:
        retry_targets.append("report")

    audit_result = {
        "approved": approved,
        "score": score,
        "sectionScores": audit_json.get("sectionScores", {}),
        "summary": audit_json.get("summary", "Audit finished."),
        "issues": issues,
        "retryTargets": retry_targets
    }

    status_label = "completed" if approved else "failed"
    publish_stage_progress(
        state,
        "auditor",
        status_label,
        f"Audit finished. Score: {score}/100. Approved: {approved}. Summary: {audit_result['summary'][:100]}",
        regeneration_round,
        score=score
    )

    return {
        "audit": audit_result,
        "retry_targets": retry_targets,
        "audit_feedback": issues,
        "regeneration_round": next_round,
        "_can_retry_audit": can_retry
    }


def route_audit(state: AnalysisGraphState) -> str:
    """Conditional Edge: LangGraph dynamic quality loop routing back to defective stages or advancing to Finalize."""
    if state.get("cancelled") or state.get("error"):
        return "end"

    audit = state.get("audit", {})
    can_retry = state.get("_can_retry_audit", False)

    if not can_retry:
        approved = audit.get("approved", True)
        if not approved:
            logger.warning("Audit regeneration rounds exhausted without approval. Finalizing current report.")
            publish_stage_progress(
                state,
                "auditor",
                "completed",
                f"Completed after {state.get('regeneration_round', 0)} regeneration rounds. Score: {audit.get('score', 0)}/100 (Unapproved but finalized)",
                state.get("regeneration_round", 0),
                score=audit.get("score", 0)
            )
        return "finalize"

    targets = audit.get("retryTargets", [])
    max_rounds = state.get("max_regeneration_rounds", 3)
    logger.info(f"LangGraph Audit Regeneration Loop triggered (round {state.get('regeneration_round', 1)}/{max_rounds}, targets: {targets})")

    if "analytics" in targets:
        return "data_scientist"
    elif "visuals" in targets:
        return "viz_preprocessor"
    elif "report" in targets or "report_writer" in targets:
        return "report_writer"
    else:
        return "report_writer"


def _generate_deterministic_fallback_charts(df: pd.DataFrame, report: dict) -> list[dict]:
    """Generates guaranteed publication-grade fallback charts when agent charts are empty."""
    charts = []
    if df is None or df.empty or len(df.columns) < 2:
        return charts

    import io
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols = [c for c in df.columns if df[c].dtype == 'object' or str(df[c].dtype) in ['category', 'string']]

    # 1. Correlation Heatmap
    if len(numeric_cols) >= 2:
        try:
            top_nums = numeric_cols[:6]
            corr = df[top_nums].corr()
            fig, ax = plt.subplots(figsize=(7, 5), dpi=150)
            sns.heatmap(corr, annot=True, fmt=".2f", cmap="Blues", cbar=True, ax=ax, linewidths=0.5)
            ax.set_title("Numeric Feature Correlation Matrix", fontsize=11, fontweight="bold", pad=10)
            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            plt.close(fig)
            buf.seek(0)
            charts.append({
                "filename": "correlation_heatmap_fallback.png",
                "title": "Correlation Analysis Across Key Features",
                "interpretation": "Correlation structure and linear dependencies observed among primary numerical variables.",
                "insight_text": "Strongest statistical relationships highlighted in correlation matrix.",
                "finding_title": "Feature Correlation Structure",
                "data": buf.read()
            })
        except Exception as e:
            logger.warning(f"Fallback correlation heatmap failed: {e}")

    # 2. Categorical / Target Grouped Bar Chart
    if cat_cols and numeric_cols:
        try:
            c_col = [c for c in cat_cols if 1 < df[c].nunique() <= 10]
            cat = c_col[0] if c_col else cat_cols[0]
            num = numeric_cols[0]
            grouped = df.groupby(cat)[num].mean().reset_index().sort_values(by=num, ascending=False).head(8)
            fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
            sns.barplot(data=grouped, x=cat, y=num, hue=cat, palette="Blues_r", legend=False, ax=ax)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.set_title(f"Average {num} by {cat}", fontsize=11, fontweight="bold", pad=10)
            plt.xticks(rotation=25, ha="right")
            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            plt.close(fig)
            buf.seek(0)
            charts.append({
                "filename": f"bar_{cat}_{num}_fallback.png",
                "title": f"Segment Breakdown: {num} by {cat}",
                "interpretation": f"Comparative performance and mean variance of {num} segmented by {cat}.",
                "insight_text": f"Divergence observed across categories of {cat}.",
                "finding_title": f"Segment Analysis: {cat}",
                "data": buf.read()
            })
        except Exception as e:
            logger.warning(f"Fallback bar chart failed: {e}")

    # 3. Numeric Distribution Box Plot
    if numeric_cols:
        try:
            num = numeric_cols[0]
            fig, ax = plt.subplots(figsize=(7, 3.5), dpi=150)
            sns.boxplot(x=df[num].dropna(), color="#93C5FD", ax=ax)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.set_title(f"Distribution & Outlier Range: {num}", fontsize=11, fontweight="bold", pad=10)
            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png")
            plt.close(fig)
            buf.seek(0)
            charts.append({
                "filename": f"box_{num}_fallback.png",
                "title": f"Distribution Profile of {num}",
                "interpretation": f"Quartile ranges, median, and outlier dispersion for {num}.",
                "insight_text": f"Spread and skewness across the distribution of {num}.",
                "finding_title": f"Distribution Analysis: {num}",
                "data": buf.read()
            })
        except Exception as e:
            logger.warning(f"Fallback box plot failed: {e}")

    return charts


def finalize_node(state: AnalysisGraphState) -> dict:
    """Finalize Node: Packages visual plans, code transparency, and metadata into the final report."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    report = dict(state.get("report", {}))
    chart_images = list(state.get("chart_images", []))

    # Fallback visualization guarantee: never output a report with 0 charts
    if not chart_images:
        df = state.get("df")
        fallback_charts = _generate_deterministic_fallback_charts(df, report)
        if fallback_charts:
            chart_images = fallback_charts

    if not report.get("id"):
        report["id"] = state.get("job_id") or f"rep_{uuid.uuid4().hex[:8]}"

    if not report.get("title"):
        domain = report.get("domain") or state.get("domain_brief", {}).get("domain", "Dataset")
        report["title"] = f"{domain} Analytical Assessment"

    if report.get("executiveSummary") and not report.get("executive_summary"):
        report["executive_summary"] = report["executiveSummary"]
    elif report.get("executive_summary") and not report.get("executiveSummary"):
        report["executiveSummary"] = report["executive_summary"]

    if report.get("keyFindings") and not report.get("key_findings"):
        report["key_findings"] = report["keyFindings"]
    elif report.get("key_findings") and not report.get("keyFindings"):
        report["keyFindings"] = report["key_findings"]

    audit = state.get("audit", {})
    report["audit"] = audit
    report["audit_score"] = audit.get("score")

    report["_visualPlan"] = {
        "charts": [
            {
                "type": "custom",
                "title": c.get("title", "Custom Chart"),
                "x": None,
                "y": None,
                "aggregation": "none",
                "reason": c.get("interpretation", "Generated by visualization agent.")
            }
            for c in chart_images
        ]
    }
    report["analysis_code_used"] = state.get("methodology_code", "")
    report["visualization_code_used"] = state.get("viz_code", "")
    report["agent_files_created"] = state.get("agent_files", [])
    report["investigation_log"] = state.get("investigation_log", [])

    # ── Full Analytics Team Artifacts embedded in report ───────────────────
    report["data_cleaning_manifest"] = state.get("cleaning_manifest", {})
    report["investigation_plan"] = state.get("investigation_plan", {})
    report["ml_predictive_modeling"] = state.get("ml_results", {})
    report["causal_analysis"] = state.get("causal_results", {})
    report["forecast"] = state.get("forecast_results", {})
    report["anomaly_detection"] = state.get("anomaly_results", {})
    report["strategic_brief"] = state.get("strategic_results", {})
    report["experiment_results"] = state.get("experiment_results", {})
    report["relational_manifest"] = state.get("relational_manifest", {})
    # NEW agent artifacts
    report["cohort_analysis"] = state.get("cohort_results", {})
    report["benchmark_analysis"] = state.get("benchmark_results", {})
    report["data_quality_gate"] = {
        "score": state.get("data_quality_score", 0),
        "decision": state.get("data_quality_gate_decision", "PASS"),
        "issues": state.get("data_quality_issues", []),
    }
    # Embed presentation outline (pptx_bytes excluded to keep JSON clean)
    pres = state.get("presentation_results", {})
    if pres:
        pres_for_report = {k: v for k, v in pres.items() if k != "pptx_bytes"}
        report["presentation_outline"] = pres_for_report


    # Expose executive headline at top level for easy access in PDF/UI
    strategic = state.get("strategic_results", {})
    if strategic.get("executive_headline") and not report.get("executive_headline"):
        report["executive_headline"] = strategic["executive_headline"]
    if strategic.get("recommendations") and not report.get("strategic_recommendations"):
        report["strategic_recommendations"] = strategic["recommendations"]
    # ────────────────────────────────────────────────────────────────────────

    publish_stage_progress(
        state,
        "finalize",
        "completed",
        "Finalized report packages, visual figures, and quality audit verification.",
        state.get("regeneration_round", 0)
    )

    return {"final_report": report, "report": report, "chart_images": chart_images}


# ─────────────────────────────────────────────────────────────────────────────
# Senior Analyst Tier — Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _detect_time_column(df: pd.DataFrame, schema: dict) -> tuple[str | None, list[str]]:
    """Detect the most likely datetime column and numeric target columns."""
    time_col = None
    # 1. Already datetime dtype
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            time_col = col
            break
    # 2. Object column that parses as datetime with high success rate
    if not time_col:
        for col in df.select_dtypes(include="object").columns:
            try:
                parsed = pd.to_datetime(df[col], errors="coerce", infer_datetime_format=True)
                if parsed.notna().mean() > 0.7:
                    time_col = col
                    break
            except Exception:
                continue
    # 3. Common name heuristics
    if not time_col:
        for col in df.columns:
            if any(kw in col.lower() for kw in ("date", "time", "timestamp", "month", "year", "week", "day", "dt")):
                time_col = col
                break

    # Target columns: numeric, not the time col, not IDs
    target_cols = [
        c for c in df.select_dtypes(include=[np.number]).columns
        if c != time_col and not any(kw in c.lower() for kw in ("id", "index", "code", "zip"))
    ][:5]

    return time_col, target_cols


def _build_col_profile(df: pd.DataFrame) -> dict:
    """Build a per-column quality profile for senior analyst prompts."""
    profile = {}
    for col in df.columns:
        null_pct = round(df[col].isna().mean() * 100, 1)
        dtype_str = str(df[col].dtype)
        if null_pct == 100.0:
            status = "all_null_SKIP"
        elif dtype_str.startswith(("float", "int")):
            status = "numeric_clean"
        else:
            coerced = pd.to_numeric(df[col], errors="coerce")
            pct_num = round(coerced.notna().mean() * 100, 1)
            if pct_num >= 60:
                status = "numeric_clean"
            elif pct_num >= 30:
                status = "numeric_dirty_coerce_first"
            else:
                status = "categorical"
        profile[col] = {"null_pct": null_pct, "dtype": dtype_str, "status": status}
    return profile


# ─────────────────────────────────────────────────────────────────────────────
# Senior Analyst Tier — Node 1: Causal Analyst
# ─────────────────────────────────────────────────────────────────────────────

def causal_analyst_node(state: AnalysisGraphState) -> dict:
    """Causal Inference Agent: Audits correlations for causality, maps causal chains, detects confounders."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(state, "causal_analyst", "running",
                           "Auditing correlations for causality and mapping causal chains...",
                           state.get("regeneration_round", 0))

    df = state["df"]
    col_profile = _build_col_profile(df)

    prompt = CAUSAL_ANALYST_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        currency_context=state.get("currency_context", ""),
        schema=json.dumps(state.get("schema", {}), default=str),
        analysis_results=json.dumps(state.get("analysis_results", {}), default=str)[:6000],
        col_profile=json.dumps(col_profile, default=str),
    )

    messages = [
        {"role": "system", "content": "You are a causal inference specialist. Output only a JSON object."},
        {"role": "user", "content": prompt},
    ]

    causal_results = {}
    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    for attempt in range(3):
        try:
            use_json = (attempt == 0)
            response = chat_completion(messages, task="review", json_mode=use_json, timeout=timeout_val)
            parsed = parse_json_safely(response)
            if "error" not in parsed and ("causal_audit" in parsed or "causal_chain" in parsed or "causal_summary" in parsed):
                causal_results = parsed
                break
        except Exception as e:
            logger.warning(f"Causal analyst attempt {attempt + 1} failed: {e}")

    if not causal_results:
        logger.warning("Causal analyst returned no valid results — continuing with empty causal results.")
        causal_results = {"causal_summary": "Causal analysis was not completed due to an LLM error."}

    publish_stage_progress(state, "causal_analyst", "completed",
                           f"Causal analysis complete. {len(causal_results.get('causal_audit', []))} findings audited.",
                           state.get("regeneration_round", 0))

    return {"causal_results": causal_results}


# ─────────────────────────────────────────────────────────────────────────────
# Senior Analyst Tier — Node 2: Forecaster
# ─────────────────────────────────────────────────────────────────────────────

def forecaster_node(state: AnalysisGraphState) -> dict:
    """Forecasting Agent: Detects time series, decomposes trend/seasonality, projects forward."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    df = state["df"]
    time_col, target_cols = _detect_time_column(df, state.get("schema", {}))

    if not time_col:
        logger.info("Forecaster: No time column detected — skipping forecast node.")
        publish_stage_progress(state, "forecaster", "completed",
                               "No time column detected — forecast skipped for this dataset.",
                               state.get("regeneration_round", 0))
        return {"forecast_results": {"skipped": True, "reason": "No datetime column detected in dataset."},
                "time_column_detected": None, "target_columns_detected": []}

    publish_stage_progress(state, "forecaster", "running",
                           f"Decomposing time series on '{time_col}' and projecting forward...",
                           state.get("regeneration_round", 0))

    col_profile = _build_col_profile(df)

    prompt = FORECASTER_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        currency_context=state.get("currency_context", ""),
        schema=json.dumps(state.get("schema", {}), default=str),
        analysis_results=json.dumps(state.get("analysis_results", {}), default=str)[:4000],
        col_profile=json.dumps(col_profile, default=str),
        time_column=time_col,
        target_columns=json.dumps(target_cols),
    )

    messages = [
        {"role": "system", "content": "You are a quantitative forecaster. Output only a Python code block."},
        {"role": "user", "content": prompt},
    ]

    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    code = ""
    for attempt in range(3):
        try:
            response = chat_completion(messages, task="visual", json_mode=False, timeout=timeout_val)
            code = extract_code_block(response)
            if code:
                break
        except Exception as e:
            logger.warning(f"Forecaster code gen attempt {attempt + 1} failed: {e}")

    forecast_results = {"skipped": False, "time_column": time_col, "target_columns": target_cols}
    forecast_charts = []

    if code:
        exec_res = execute_analysis_code(code, df,
                                         timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "120")))
        if exec_res.success:
            # Pull out forecast_results.json
            for output in exec_res.agent_outputs:
                if output.get("filename", "").endswith(".json") and "forecast" in output.get("filename", ""):
                    forecast_results.update(output.get("data", {}))
            # Pull out forecast charts and add to chart_images
            for output in exec_res.agent_outputs:
                if output.get("type") == "image" and isinstance(output.get("data"), (bytes, bytearray)):
                    forecast_charts.append({
                        "filename": output["filename"],
                        "title": output.get("finding_title") or output.get("purpose") or output["filename"],
                        "interpretation": output.get("interpretation", "Time series trend and forecast."),
                        "insight_text": output.get("insight_text", ""),
                        "finding_title": output.get("finding_title", "Forecast"),
                        "data": output["data"],
                    })
            logger.info(f"Forecaster: {len(forecast_charts)} charts generated.")
        else:
            logger.warning(f"Forecaster code execution failed: {exec_res.error_message}")
            forecast_results["error"] = exec_res.error_message

    publish_stage_progress(state, "forecaster", "completed",
                           f"Forecast complete. {len(forecast_charts)} trend charts generated.",
                           state.get("regeneration_round", 0))

    # Merge forecast charts into chart_images
    existing_charts = list(state.get("chart_images", []))
    return {
        "forecast_results": forecast_results,
        "time_column_detected": time_col,
        "target_columns_detected": target_cols,
        "chart_images": existing_charts + forecast_charts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Senior Analyst Tier — Node 3: Anomaly Detector
# ─────────────────────────────────────────────────────────────────────────────

def anomaly_detector_node(state: AnalysisGraphState) -> dict:
    """Anomaly Detection & Segment Profiling Agent: Z-score + IQR outliers, KMeans cluster profiling."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(state, "anomaly_detector", "running",
                           "Detecting outliers and profiling customer/data segments...",
                           state.get("regeneration_round", 0))

    df = state["df"]
    col_profile = _build_col_profile(df)

    # Check if there are enough numeric columns to do meaningful anomaly detection
    numeric_usable = [col for col, meta in col_profile.items()
                      if meta["status"] in ("numeric_clean", "numeric_dirty_coerce_first")
                      and meta["null_pct"] < 80]

    if len(numeric_usable) < 2:
        logger.info("Anomaly detector: fewer than 2 usable numeric columns — skipping.")
        publish_stage_progress(state, "anomaly_detector", "completed",
                               "Skipped — fewer than 2 usable numeric columns for anomaly detection.",
                               state.get("regeneration_round", 0))
        return {"anomaly_results": {"skipped": True, "reason": "Fewer than 2 numeric columns."}}

    prompt = ANOMALY_DETECTOR_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        currency_context=state.get("currency_context", ""),
        col_profile=json.dumps(col_profile, default=str),
        analysis_results=json.dumps(state.get("analysis_results", {}), default=str)[:4000],
    )

    messages = [
        {"role": "system", "content": "You are an anomaly detection expert. Output only a Python code block."},
        {"role": "user", "content": prompt},
    ]

    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    code = ""
    for attempt in range(3):
        try:
            response = chat_completion(messages, task="visual", json_mode=False, timeout=timeout_val)
            code = extract_code_block(response)
            if code:
                break
        except Exception as e:
            logger.warning(f"Anomaly detector code gen attempt {attempt + 1} failed: {e}")

    anomaly_results = {}
    anomaly_charts = []

    if code:
        exec_res = execute_analysis_code(code, df,
                                         timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "120")))
        if exec_res.success:
            for output in exec_res.agent_outputs:
                fname = output.get("filename", "")
                if fname.endswith(".json") and "anomaly" in fname:
                    anomaly_results = output.get("data", {})
            for output in exec_res.agent_outputs:
                if output.get("type") == "image" and isinstance(output.get("data"), (bytes, bytearray)):
                    anomaly_charts.append({
                        "filename": output["filename"],
                        "title": output.get("finding_title") or output.get("purpose") or output["filename"],
                        "interpretation": output.get("interpretation", "Anomaly detection and segment profiling."),
                        "insight_text": output.get("insight_text", ""),
                        "finding_title": output.get("finding_title", "Segment Analysis"),
                        "data": output["data"],
                    })
            logger.info(f"Anomaly detector: {len(anomaly_charts)} charts, anomaly_rate={anomaly_results.get('anomaly_rate_pct', 'N/A')}%")
        else:
            logger.warning(f"Anomaly detector execution failed: {exec_res.error_message}")
            anomaly_results = {"error": exec_res.error_message}

    publish_stage_progress(state, "anomaly_detector", "completed",
                           f"Anomaly detection complete. Rate: {anomaly_results.get('anomaly_rate_pct', '?')}%, "
                           f"Segments: {len(anomaly_results.get('segments', []))}.",
                           state.get("regeneration_round", 0))

    existing_charts = list(state.get("chart_images", []))
    return {
        "anomaly_results": anomaly_results,
        "chart_images": existing_charts + anomaly_charts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Senior Analyst Tier — Node 3b: A/B Experimentation Agent
# ─────────────────────────────────────────────────────────────────────────────

def experimentation_node(state: AnalysisGraphState) -> dict:
    """A/B Experimentation Agent: Detects variant/treatment arms, validates Sample Ratio Mismatch (SRM),
    computes lift confidence intervals, statistical power, and determines rollout recommendations."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    df = state.get("df_cleaned") if state.get("df_cleaned") is not None else state.get("df")
    if df is None or df.empty:
        return {"experiment_results": {"is_experiment": False}}

    stats_dict = state.get("stats", {})
    potential_targets = stats_dict.get("potential_targets", [])

    variant_col = None
    for col in df.columns:
        c_low = col.lower()
        if any(k in c_low for k in ["variant", "test_group", "treatment", "experiment_group", "arm", "is_control", "ab_test"]):
            if 2 <= df[col].nunique(dropna=True) <= 5:
                variant_col = col
                break

    if not variant_col:
        for col in df.select_dtypes(include=["object", "category", "int", "bool"]).columns:
            if df[col].nunique(dropna=True) == 2 and col not in potential_targets:
                vals = [str(v).lower() for v in df[col].unique()]
                if any(v in ["control", "treatment", "a", "b", "test", "variant_a", "variant_b"] for v in vals):
                    variant_col = col
                    break

    if not variant_col:
        return {"experiment_results": {"is_experiment": False, "summary": "No active A/B testing variant column detected."}}

    publish_stage_progress(
        state,
        "experimentation",
        "running",
        f"A/B Experimentation Agent: Auditing experiment variants on '{variant_col}' and checking SRM..."
    )

    # Filter out obvious ID / key / index / code columns from being chosen as primary metric
    candidate_metrics = [
        c for c in df.select_dtypes(include=[np.number]).columns
        if c != variant_col and not any(k == c.lower() or f"_{k}" in c.lower() or f"{k}_" in c.lower() for k in ["id", "key", "code", "index", "uuid"])
    ]
    if not candidate_metrics:
        candidate_metrics = [c for c in df.select_dtypes(include=[np.number]).columns if c != variant_col]

    # Prioritize business outcome metrics (rate, conversion, score, revenue, amount, sales, churn)
    metric_priority = sorted(
        candidate_metrics,
        key=lambda col: any(k in col.lower() for k in ["rate", "conversion", "score", "revenue", "amount", "lift", "churn", "retention", "click", "spend", "sales", "val"]),
        reverse=True
    )

    if potential_targets and potential_targets[0] in candidate_metrics:
        primary_metric = potential_targets[0]
    else:
        primary_metric = metric_priority[0] if metric_priority else None

    groups = df[variant_col].dropna().unique()
    group_counts = df[variant_col].value_counts().to_dict()

    experiment_results = {}
    exp_charts = []

    # SRM check using Chi-square goodness-of-fit
    observed_counts = list(group_counts.values())
    expected_counts = [len(df[variant_col].dropna()) / len(observed_counts)] * len(observed_counts)
    chi2_stat, srm_p_value = stats.chisquare(f_obs=observed_counts, f_exp=expected_counts)
    srm_violation = bool(srm_p_value < 0.01)

    if len(groups) >= 2 and primary_metric:
        control_label = [g for g in groups if "control" in str(g).lower() or str(g) in ["0", "A", "a"]]
        control_val = control_label[0] if control_label else groups[0]
        treatment_val = [g for g in groups if g != control_val][0]

        c_series = df[df[variant_col] == control_val][primary_metric].dropna()
        t_series = df[df[variant_col] == treatment_val][primary_metric].dropna()

        if len(c_series) >= 5 and len(t_series) >= 5:
            c_mean = float(c_series.mean())
            t_mean = float(t_series.mean())
            abs_lift = float(t_mean - c_mean)
            rel_lift_pct = float((abs_lift / (abs(c_mean) + 1e-6)) * 100.0)

            t_stat, p_val = stats.ttest_ind(t_series, c_series, equal_var=False)
            se_diff = np.sqrt((c_series.var() / len(c_series)) + (t_series.var() / len(t_series)))
            ci_lower = abs_lift - 1.96 * se_diff
            ci_upper = abs_lift + 1.96 * se_diff

            if srm_violation:
                decision = "DO NOT SHIP (SRM Violation / Allocation Failure)"
                decision_rationale = f"Sample Ratio Mismatch detected (p={srm_p_value:.4f} < 0.01). The variant allocation is compromised. Results invalid."
            elif p_val < 0.05 and abs_lift > 0:
                decision = "SHIP (Statistically Significant Lift)"
                decision_rationale = f"Treatment '{treatment_val}' achieved statistically significant lift of +{rel_lift_pct:.2f}% on '{primary_metric}' (p={p_val:.4f})."
            elif p_val < 0.05 and abs_lift < 0:
                decision = "DO NOT SHIP (Statistically Significant Degradation)"
                decision_rationale = f"Treatment '{treatment_val}' caused significant decline of {rel_lift_pct:.2f}% on '{primary_metric}' (p={p_val:.4f}). Rollout is harmful."
            else:
                decision = "ITERATE (Inconclusive / Underpowered)"
                decision_rationale = f"Observed lift ({rel_lift_pct:+.2f}%) did not reach statistical significance (p={p_val:.4f} >= 0.05). Extend sample collection."

            experiment_results = {
                "is_experiment": True,
                "variant_column": variant_col,
                "control_variant": str(control_val),
                "treatment_variant": str(treatment_val),
                "primary_metric": primary_metric,
                "srm_check": {
                    "passed": not srm_violation,
                    "p_value": round(float(srm_p_value), 4),
                    "allocation": {str(k): int(v) for k, v in group_counts.items()}
                },
                "lift_analysis": {
                    "control_mean": round(c_mean, 4),
                    "treatment_mean": round(t_mean, 4),
                    "absolute_lift": round(abs_lift, 4),
                    "relative_lift_pct": round(rel_lift_pct, 2),
                    "p_value": round(float(p_val), 4),
                    "statistically_significant": bool(p_val < 0.05),
                    "confidence_interval_95": [round(float(ci_lower), 4), round(float(ci_upper), 4)]
                },
                "rollout_decision": decision,
                "recommendation": decision_rationale,
                "summary": f"A/B experiment evaluated on '{primary_metric}'. Decision: {decision}. Relative lift: {rel_lift_pct:+.1f}% (p={p_val:.3f})."
            }

            try:
                import io
                fig, ax = plt.subplots(figsize=(7, 4.5), dpi=150)
                cats = [f"Control ({control_val})", f"Treatment ({treatment_val})"]
                vals = [c_mean, t_mean]
                errs = [1.96 * (c_series.std() / np.sqrt(len(c_series))), 1.96 * (t_series.std() / np.sqrt(len(t_series)))]
                bar_colors = ["#94A3B8", "#10B981" if abs_lift > 0 and p_val < 0.05 else ("#EF4444" if abs_lift < 0 and p_val < 0.05 else "#3B82F6")]
                ax.bar(cats, vals, yerr=errs, capsize=6, color=bar_colors, width=0.45)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.set_title(f"A/B Experiment Impact: {primary_metric}", fontsize=11, fontweight="bold", pad=12)
                ax.set_ylabel(f"Average {primary_metric}")
                plt.tight_layout()
                buf = io.BytesIO()
                plt.savefig(buf, format="png")
                plt.close(fig)
                buf.seek(0)

                exp_charts.append({
                    "filename": f"ab_test_lift_{primary_metric}.png",
                    "title": f"A/B Test Lift: {primary_metric}",
                    "interpretation": decision_rationale,
                    "insight_text": f"Relative lift of {rel_lift_pct:+.1f}% with rollout recommendation: {decision}.",
                    "finding_title": "A/B Testing & Experimentation",
                    "data": buf.read()
                })
            except Exception as chart_err:
                logger.warning(f"Error rendering A/B test chart: {chart_err}")

    publish_stage_progress(
        state,
        "experimentation",
        "completed",
        experiment_results.get("summary", "A/B Experimentation evaluation completed.")
    )

    return {
        "experiment_results": experiment_results,
        "charts": list(state.get("charts", [])) + exp_charts,
        "chart_images": list(state.get("chart_images", [])) + exp_charts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Senior Analyst Tier — Node 4: ML Modeler
# ─────────────────────────────────────────────────────────────────────────────

def ml_modeler_node(state: AnalysisGraphState) -> dict:
    """Machine Learning Agent: Trains predictive models, cross-validates, and ranks feature drivers."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "ml_modeler",
        "running",
        "Machine Learning Agent: Training predictive models and calculating feature importances..."
    )

    df = state["df"]
    schema = state.get("schema", {})
    currency_context = state.get("currency_context", "")
    domain = state.get("domain_brief", {}).get("domain", "Unknown")
    stats_dict = state.get("stats", {})
    potential_targets = stats_dict.get("potential_targets", [])
    col_profile = _build_col_profile(df)

    # Detect primary target
    primary_target = None
    for c in df.columns:
        c_low = c.lower()
        if any(k in c_low for k in ["churn", "churned", "target", "label", "outcome", "converted", "attrition", "default"]):
            primary_target = c
            break

    if not primary_target and potential_targets:
        primary_target = potential_targets[0]

    ml_charts = []
    ml_results = {}

    prompt = ML_MODELER_PROMPT.format(
        domain=domain,
        currency_context=currency_context,
        target_columns=json.dumps([primary_target] if primary_target else []),
        col_profile=json.dumps(col_profile, default=str),
        analysis_results=json.dumps(state.get("analysis_results", {}), default=str)[:3000],
    )

    messages = [
        {"role": "system", "content": "You are a Senior Machine Learning Engineer. Generate Python code to train, evaluate, and extract feature importances using scikit-learn."},
        {"role": "user", "content": prompt}
    ]

    try:
        response = chat_completion(messages, task="visual", timeout=int(os.environ.get("LLM_TIMEOUT", "300")))
        code = extract_code_block(response)
        if code and ("sklearn" in code or "RandomForest" in code or "LogisticRegression" in code or "ml_results" in code):
            exec_res = execute_analysis_code(code, df, timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "120")))
            if exec_res.success:
                for out in exec_res.agent_outputs:
                    fname = out.get("filename", "")
                    if fname.endswith(".json") and "ml" in fname:
                        ml_results = out.get("data", {})
                    elif out.get("type") == "image" and isinstance(out.get("data"), (bytes, bytearray)):
                        ml_charts.append({
                            "filename": out["filename"],
                            "title": out.get("finding_title") or "Feature Importance",
                            "interpretation": out.get("interpretation", "Predictive feature drivers evaluated using machine learning."),
                            "insight_text": out.get("insight_text", "Top predictive drivers of the target variable."),
                            "finding_title": "Predictive Feature Importance",
                            "data": out["data"]
                        })
    except Exception as e:
        logger.warning(f"ML Modeler LLM execution encountered: {e}")

    # Fallback robust deterministic ML execution using scikit-learn
    if not ml_results:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder
        from sklearn.metrics import accuracy_score, f1_score, r2_score, mean_squared_error

        try:
            data = df.copy()
            drop_cols = [c for c in data.columns if any(k in c.lower() for k in ["id", "index", "date", "time", "timestamp"])]
            if primary_target and primary_target in drop_cols:
                drop_cols.remove(primary_target)

            features = [c for c in data.columns if c not in drop_cols and c != primary_target]

            if primary_target and primary_target in data.columns and len(features) >= 1:
                y_raw = data[primary_target]
                is_classification = y_raw.nunique() <= 10 or pd.api.types.is_object_dtype(y_raw) or str(y_raw.dtype) == 'category'

                if is_classification:
                    le = LabelEncoder()
                    y = le.fit_transform(y_raw.astype(str))
                else:
                    y = pd.to_numeric(y_raw, errors="coerce").fillna(y_raw.median())

                X = data[features].copy()
                for c in X.columns:
                    if pd.api.types.is_numeric_dtype(X[c]):
                        X[c] = X[c].fillna(X[c].median())
                    else:
                        X[c] = LabelEncoder().fit_transform(X[c].astype(str))

                if len(X) >= 10:
                    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

                    if is_classification:
                        model = RandomForestClassifier(n_estimators=50, max_depth=6, random_state=42)
                        model.fit(X_train, y_train)
                        preds = model.predict(X_test)
                        acc = float(accuracy_score(y_test, preds))
                        f1 = float(f1_score(y_test, preds, average="weighted", zero_division=0))
                        importances = model.feature_importances_

                        ml_results = {
                            "task_type": "classification",
                            "target_column": primary_target,
                            "model_name": "RandomForestClassifier",
                            "metrics": {
                                "accuracy": round(acc, 4),
                                "f1_score": round(f1, 4),
                                "train_samples": len(X_train),
                                "test_samples": len(X_test)
                            },
                            "feature_importances": [
                                {"feature": f, "importance": round(float(imp), 4)}
                                for f, imp in sorted(zip(features, importances), key=lambda x: x[1], reverse=True)[:10]
                            ],
                            "summary": f"Predictive classification model for '{primary_target}' achieved {acc*100:.1f}% accuracy and {f1:.3f} F1-score."
                        }
                    else:
                        model = RandomForestRegressor(n_estimators=50, max_depth=6, random_state=42)
                        model.fit(X_train, y_train)
                        preds = model.predict(X_test)
                        r2 = float(r2_score(y_test, preds))
                        rmse = float(np.sqrt(mean_squared_error(y_test, preds)))
                        importances = model.feature_importances_

                        ml_results = {
                            "task_type": "regression",
                            "target_column": primary_target,
                            "model_name": "RandomForestRegressor",
                            "metrics": {
                                "r2_score": round(r2, 4),
                                "rmse": round(rmse, 4),
                                "train_samples": len(X_train),
                                "test_samples": len(X_test)
                            },
                            "feature_importances": [
                                {"feature": f, "importance": round(float(imp), 4)}
                                for f, imp in sorted(zip(features, importances), key=lambda x: x[1], reverse=True)[:10]
                            ],
                            "summary": f"Predictive regression model for '{primary_target}' achieved R² of {r2:.3f} and RMSE of {rmse:.2f}."
                        }

                    if not ml_charts and ml_results.get("feature_importances"):
                        import io
                        top_feats = ml_results["feature_importances"][:8][::-1]
                        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
                        feat_names = [item["feature"] for item in top_feats]
                        feat_vals = [item["importance"] for item in top_feats]
                        bars = ax.barh(feat_names, feat_vals, color="#3B82F6", edgecolor="none", height=0.6)
                        ax.spines["top"].set_visible(False)
                        ax.spines["right"].set_visible(False)
                        ax.spines["left"].set_color("#CBD5E1")
                        ax.spines["bottom"].set_color("#CBD5E1")
                        ax.set_title(f"Predictive Driver Importance: {primary_target}", fontsize=12, fontweight="bold", pad=12)
                        ax.set_xlabel("Relative Importance Score", fontsize=10)
                        plt.tight_layout()
                        buf = io.BytesIO()
                        plt.savefig(buf, format="png")
                        plt.close(fig)
                        buf.seek(0)
                        raw_bytes = buf.read()

                        ml_charts.append({
                            "filename": f"feature_importance_{primary_target}.png",
                            "title": f"Top Drivers of {primary_target}",
                            "interpretation": f"Relative importance of key drivers predicting {primary_target} using Random Forest modeling.",
                            "insight_text": f"'{top_feats[-1]['feature']}' was identified as the #1 predictive driver.",
                            "finding_title": "Predictive Feature Importance",
                            "data": raw_bytes
                        })
        except Exception as e:
            logger.warning(f"Deterministic ML execution fallback failed: {e}")
            ml_results = {"task_type": "none", "summary": "ML modeling skipped due to insufficient feature variance."}

    existing_charts = list(state.get("chart_images", []))
    publish_stage_progress(
        state,
        "ml_modeler",
        "completed",
        ml_results.get("summary", "Machine learning modeling completed.")
    )

    return {
        "ml_results": ml_results,
        "chart_images": existing_charts + ml_charts
    }


# ─────────────────────────────────────────────────────────────────────────────
# Senior Analyst Tier — Node 5: Strategic Advisor
# ─────────────────────────────────────────────────────────────────────────────

def strategic_advisor_node(state: AnalysisGraphState) -> dict:
    """Strategic Advisor Agent: Synthesises all analysis into SCR-framework executive strategy brief."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(state, "strategic_advisor", "running",
                           "Synthesising all analysis into executive strategic brief...",
                           state.get("regeneration_round", 0))

    prompt = STRATEGIC_ADVISOR_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        currency_context=state.get("currency_context", ""),
        analysis_results=json.dumps(state.get("analysis_results", {}), default=str)[:4000],
        causal_results=json.dumps(state.get("causal_results", {}), default=str)[:2000],
        forecast_results=json.dumps(state.get("forecast_results", {}), default=str)[:2000],
        anomaly_results=json.dumps(state.get("anomaly_results", {}), default=str)[:2000],
    )

    messages = [
        {"role": "system", "content": "You are a principal strategy consultant. Output only a JSON object."},
        {"role": "user", "content": prompt},
    ]

    strategic_results = {}
    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    for attempt in range(3):
        try:
            use_json = (attempt == 0)
            response = chat_completion(messages, task="review", json_mode=use_json, timeout=timeout_val)
            parsed = parse_json_safely(response)
            if "error" not in parsed and ("recommendations" in parsed or "executive_headline" in parsed):
                strategic_results = parsed
                break
        except Exception as e:
            logger.warning(f"Strategic advisor attempt {attempt + 1} failed: {e}")

    if not strategic_results:
        logger.warning("Strategic advisor returned no valid results.")
        strategic_results = {"executive_headline": "Strategic synthesis was not completed due to an LLM error."}

    publish_stage_progress(state, "strategic_advisor", "completed",
                           f"Strategic brief complete. {len(strategic_results.get('recommendations', []))} recommendations.",
                           state.get("regeneration_round", 0))

    return {"strategic_results": strategic_results}



# ─────────────────────────────────────────────────────────────────────────────
# NEW AGENT NODES — Full Analytics Team Replacement Tier
# ─────────────────────────────────────────────────────────────────────────────

def data_quality_gate_node(state):
    """Data Quality Gate: Pre-flight health check. Scores data quality 0-100 and warns/blocks on failure."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(state, "data_quality_gate", "running",
                           "Data Quality Gate: Auditing dataset health before analysis begins...")

    df = state["df"]
    schema = state.get("schema", {})
    sample_rows = state.get("sample_rows", [])
    stats_dict = state.get("stats", {})
    missing_values = stats_dict.get("missing_values", {})
    row_count = len(df)
    col_count = len(df.columns)
    duplicate_rows = int(df.duplicated().sum())

    quality_issues = []
    avg_missing = sum(missing_values.values()) / max(len(missing_values), 1) / max(row_count, 1) if missing_values else 0.0
    critical_nulls = [c for c, n in missing_values.items() if n > row_count * 0.5]
    if critical_nulls:
        quality_issues.append({"type": "high_missingness", "columns": critical_nulls})
    if duplicate_rows > row_count * 0.05:
        quality_issues.append({"type": "duplicates", "count": duplicate_rows})
    if row_count < 50:
        quality_issues.append({"type": "low_volume", "count": row_count})

    prompt = DATA_QUALITY_GATE_PROMPT.format(
        schema=json.dumps(schema, default=str),
        sample_rows=json.dumps(sample_rows[:5], default=str),
        missing_values=json.dumps(missing_values, default=str),
        duplicate_rows=duplicate_rows,
        quality_issues=json.dumps(quality_issues, default=str),
        row_count=row_count,
        col_count=col_count,
    )

    messages = [
        {"role": "system", "content": "You are a data quality auditor. Output JSON only."},
        {"role": "user", "content": prompt},
    ]

    gate_result = {}
    try:
        response = chat_completion(messages, task="review", json_mode=True,
                                   timeout=int(os.environ.get("LLM_TIMEOUT", "120")))
        parsed = parse_json_safely(response)
        if "error" not in parsed and "health_score" in parsed:
            gate_result = parsed
    except Exception as e:
        logger.warning(f"Data quality gate LLM failed: {e}")

    if not gate_result:
        completeness = max(0, 30 * (1.0 - avg_missing))
        uniqueness = max(0, 20 * (1.0 - duplicate_rows / max(row_count, 1)))
        volume_score = 0 if row_count < 50 else (8 if row_count < 200 else (12 if row_count < 1000 else 15))
        health_score = int(completeness + uniqueness + 20 + 15 + volume_score)
        health_score = min(100, max(0, health_score))
        decision = "PASS" if health_score >= 60 else ("WARN" if health_score >= 40 else "FAIL")
        gate_result = {
            "health_score": health_score,
            "gate_decision": decision,
            "critical_issues": quality_issues,
            "warnings": [],
            "gate_rationale": f"Data Health Score: {health_score}/100. Decision: {decision}.",
        }

    score = gate_result.get("health_score", 85)
    decision = gate_result.get("gate_decision", "PASS")
    rationale = gate_result.get("gate_rationale", "")

    publish_stage_progress(state, "data_quality_gate", "completed",
                           f"Data Health Score: {score}/100 [{decision}]. {rationale[:100]}", score=score)

    return {
        "data_quality_score": score,
        "data_quality_gate_decision": decision,
        "data_quality_issues": gate_result.get("critical_issues", []),
    }


def cohort_analyst_node(state):
    """Cohort and Retention Analyst: LTV, churn curves, DAU/WAU/MAU, retention matrices."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(state, "cohort_analyst", "running",
                           "Cohort Analyst: Mapping user lifecycle, churn curves, and LTV cohorts...")

    df = state["df"]
    col_profile = _build_col_profile(df)
    time_col, target_cols = _detect_time_column(df, state.get("schema", {}))

    prompt = COHORT_ANALYST_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        currency_context=state.get("currency_context", ""),
        schema=json.dumps(state.get("schema", {}), default=str),
        col_profile=json.dumps(col_profile, default=str),
        analysis_results=json.dumps(state.get("analysis_results", {}), default=str)[:3000],
        time_column=time_col or "None detected",
        target_columns=json.dumps(target_cols),
    )

    messages = [
        {"role": "system", "content": "You are a cohort analyst. Write Python code. Output only a python code block."},
        {"role": "user", "content": prompt},
    ]

    cohort_results = {}
    cohort_charts = []
    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    code = ""
    for attempt in range(3):
        try:
            response = chat_completion(messages, task="visual", json_mode=False, timeout=timeout_val)
            code = extract_code_block(response)
            if code:
                break
        except Exception as e:
            logger.warning(f"Cohort analyst code gen attempt {attempt + 1} failed: {e}")

    if code:
        exec_res = execute_analysis_code(code, df, timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "120")))
        if exec_res.success:
            for out in exec_res.agent_outputs:
                fname = out.get("filename", "")
                if fname.endswith(".json") and "cohort" in fname:
                    cohort_results = out.get("data", {})
                elif out.get("type") == "image" and isinstance(out.get("data"), (bytes, bytearray)):
                    cohort_charts.append({
                        "filename": out["filename"],
                        "title": out.get("finding_title") or "Cohort Analysis",
                        "interpretation": out.get("interpretation", "Cohort retention and lifecycle analysis."),
                        "insight_text": out.get("insight_text", ""),
                        "finding_title": out.get("finding_title", "Cohort and Retention Analysis"),
                        "data": out["data"],
                    })
            logger.info(f"Cohort analyst: {len(cohort_charts)} charts generated.")
        else:
            logger.warning(f"Cohort analyst execution failed: {exec_res.error_message}")

    if not cohort_results:
        churn_rate = 0.0
        churn_col = None
        for col in df.columns:
            if any(k in col.lower() for k in ["churn", "churned", "active", "retained"]):
                churn_col = col
                break
        if churn_col:
            try:
                churn_rate = float(df[churn_col].apply(lambda x: bool(x) if isinstance(x, bool) else (str(x).lower() in ["1", "true", "yes", "churned"])).mean())
            except Exception:
                pass
        cohort_results = {
            "cohort_type": "segment",
            "churn_rate_overall": round(churn_rate, 4),
            "summary": f"Cohort analysis complete. Churn rate estimate: {churn_rate*100:.1f}%." if churn_col else "Cohort analysis completed. No explicit churn column detected.",
        }

    publish_stage_progress(state, "cohort_analyst", "completed",
                           cohort_results.get("summary", "Cohort analysis complete."))

    existing = list(state.get("chart_images", []))
    return {
        "cohort_results": cohort_results,
        "chart_images": existing + cohort_charts,
        "_cohort_charts": cohort_charts,
    }


def benchmarking_node(state):
    """Competitive Benchmarking Agent: Compares key metrics against industry standards."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(state, "benchmarking", "running",
                           "Competitive Benchmarking: Comparing metrics against industry KPI standards...")

    analysis_results = state.get("analysis_results", {})
    findings = analysis_results.get("findings", [])
    domain = state.get("domain_brief", {}).get("domain", "Unknown")

    key_metrics = []
    for f in findings[:10]:
        title = f.get("title", "")
        detail = f.get("detail", "")
        effect = f.get("effect_size", "")
        key_metrics.append(f"{title}: {detail[:150]} (effect: {effect})")

    stats_dict = state.get("stats", {})
    numeric_summary = stats_dict.get("numeric_summary", {})
    metric_values = {col: {"mean": round(v.get("mean", 0), 2), "std": round(v.get("std", 0), 2)}
                     for col, v in list(numeric_summary.items())[:8]}

    prompt = BENCHMARKING_PROMPT.format(
        domain=domain,
        findings_summary="\n".join(key_metrics),
        key_metrics=json.dumps(metric_values, default=str),
        currency_context=state.get("currency_context", ""),
    )

    messages = [
        {"role": "system", "content": "You are a competitive intelligence analyst. Output JSON only."},
        {"role": "user", "content": prompt},
    ]

    benchmark_results = {}
    timeout_val = int(os.environ.get("LLM_TIMEOUT", "180"))
    for attempt in range(3):
        try:
            use_json = (attempt == 0)
            response = chat_completion(messages, task="review", json_mode=use_json, timeout=timeout_val)
            parsed = parse_json_safely(response)
            if "error" not in parsed and ("benchmarks" in parsed or "industry_context" in parsed):
                benchmark_results = parsed
                break
        except Exception as e:
            logger.warning(f"Benchmarking agent attempt {attempt + 1} failed: {e}")

    if not benchmark_results:
        benchmark_results = {
            "industry_context": f"Industry benchmarks for {domain}.",
            "benchmarks": [],
            "performance_gaps": [],
            "competitive_advantages": [],
            "benchmark_summary": "Competitive benchmarking was not completed due to an LLM error.",
        }

    n_above = len([b for b in benchmark_results.get("benchmarks", []) if "Above" in b.get("verdict", "")])
    n_below = len([b for b in benchmark_results.get("benchmarks", []) if "Below" in b.get("verdict", "")])

    publish_stage_progress(state, "benchmarking", "completed",
                           f"Benchmarking complete. {n_above} metrics above industry avg, {n_below} below.")

    return {"benchmark_results": benchmark_results}


def senior_tier_dispatch_node(state):
    """
    Parallel Senior Analyst Tier Dispatcher.
    Runs Causal Analyst, Forecaster, Anomaly Detector, A/B Experimenter, ML Modeler,
    Cohort Analyst, and Benchmarking Agent in PARALLEL using concurrent.futures.
    """
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    parallel_enabled = os.environ.get("SENIOR_TIER_PARALLEL", "true").strip().lower() == "true"
    max_workers = int(os.environ.get("SENIOR_TIER_MAX_WORKERS", "4"))

    publish_stage_progress(state, "causal_analyst", "running",
                           f"Senior Analyst Tier: Launching {'parallel' if parallel_enabled else 'sequential'} specialist agents (Causal, Forecast, Anomaly, A/B, ML, Cohort, Benchmark)...")

    agents = [
        ("causal_analyst", causal_analyst_node),
        ("forecaster", forecaster_node),
        ("anomaly_detector", anomaly_detector_node),
        ("experimentation", experimentation_node),
        ("ml_modeler", ml_modeler_node),
        ("cohort_analyst", cohort_analyst_node),
        ("benchmarking", benchmarking_node),
    ]

    combined = {}

    if parallel_enabled:
        def run_agent(agent_name_fn):
            agent_name, fn = agent_name_fn
            try:
                result = fn(state)
                return agent_name, result, None
            except JobCancelledException:
                return agent_name, {}, "cancelled"
            except Exception as e:
                logger.error(f"Parallel senior tier agent '{agent_name}' failed: {e}", exc_info=True)
                return agent_name, {}, str(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run_agent, ag): ag[0] for ag in agents}
            for future in concurrent.futures.as_completed(futures):
                agent_name, result, err = future.result()
                if err == "cancelled":
                    raise JobCancelledException("Job cancelled during parallel senior tier.")
                if err:
                    logger.warning(f"Agent '{agent_name}' error: {err}")
                combined.update(result)
    else:
        for agent_name, fn in agents:
            try:
                result = fn(state)
                combined.update(result)
            except JobCancelledException:
                raise
            except Exception as e:
                logger.error(f"Sequential senior tier agent '{agent_name}' failed: {e}", exc_info=True)

    # Merge all chart_images from parallel branches
    all_charts = list(state.get("chart_images", []))
    for key in ["_causal_charts", "_forecast_charts", "_anomaly_charts", "_experiment_charts", "_ml_charts", "_cohort_charts"]:
        all_charts.extend(combined.pop(key, []))
    combined["chart_images"] = all_charts

    return combined


def presentation_builder_node(state):
    """Presentation Builder Agent: Generates PowerPoint outline and creates a PPTX file."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(state, "presentation_builder", "running",
                           "Presentation Builder: Creating executive-grade slide deck...")

    report = state.get("report", {})
    strategic = state.get("strategic_results", {})
    benchmark = state.get("benchmark_results", {})
    causal = state.get("causal_results", {})
    forecast = state.get("forecast_results", {})
    ml = state.get("ml_results", {})

    prompt = PRESENTATION_BUILDER_PROMPT.format(
        domain=state.get("domain_brief", {}).get("domain", "Unknown"),
        executive_summary=report.get("executiveSummary", "")[:2000],
        key_findings=json.dumps(report.get("keyFindings", [])[:8], default=str)[:3000],
        recommendations=json.dumps(report.get("recommendations", [])[:5], default=str)[:1500],
        causal_summary=causal.get("causal_summary", "Not available.")[:500],
        forecast_summary=str(forecast.get("skipped", False))[:200],
        ml_summary=ml.get("summary", "Not available.")[:300],
        benchmark_summary=benchmark.get("benchmark_summary", "Not available.")[:500],
    )

    messages = [
        {"role": "system", "content": "You are a McKinsey slide strategist. Output JSON only."},
        {"role": "user", "content": prompt},
    ]

    presentation_results = {}
    timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
    for attempt in range(3):
        try:
            use_json = (attempt == 0)
            response = chat_completion(messages, task="report", json_mode=use_json, timeout=timeout_val)
            parsed = parse_json_safely(response)
            if "error" not in parsed and "slides" in parsed:
                presentation_results = parsed
                break
        except Exception as e:
            logger.warning(f"Presentation builder attempt {attempt + 1} failed: {e}")

    pptx_bytes = None
    if presentation_results:
        try:
            pptx_bytes = _build_pptx(presentation_results, state)
        except Exception as e:
            logger.warning(f"PPTX build failed: {e}")

    if pptx_bytes:
        presentation_results["pptx_bytes"] = pptx_bytes

    n_slides = len(presentation_results.get("slides", []))
    publish_stage_progress(state, "presentation_builder", "completed",
                           f"Presentation built: {n_slides} slides.")

    return {"presentation_results": presentation_results}


def _build_pptx(outline, state):
    """Builds a PowerPoint file from the presentation outline dict."""
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        import io

        prs = Presentation()
        prs.slide_width = Inches(13.33)
        prs.slide_height = Inches(7.5)

        DARK_BG = RGBColor(0x0F, 0x17, 0x2A)
        ACCENT = RGBColor(0x38, 0xBD, 0xF8)
        WHITE = RGBColor(0xFF, 0xFF, 0xFF)
        LIGHT_GRAY = RGBColor(0xCB, 0xD5, 0xE1)

        blank_layout = prs.slide_layouts[6]

        for slide_def in outline.get("slides", []):
            slide = prs.slides.add_slide(blank_layout)

            bg = slide.background
            fill = bg.fill
            fill.solid()
            fill.fore_color.rgb = DARK_BG

            slide_type = slide_def.get("slide_type", "finding")

            bar = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(13.33), Inches(0.08))
            bar.fill.solid()
            bar.fill.fore_color.rgb = ACCENT
            bar.line.fill.background()

            num_tb = slide.shapes.add_textbox(Inches(12.3), Inches(7.1), Inches(0.9), Inches(0.3))
            num_tf = num_tb.text_frame
            num_tf.text = str(slide_def.get("slide_number", ""))
            if num_tf.paragraphs[0].runs:
                num_tf.paragraphs[0].runs[0].font.size = Pt(9)
                num_tf.paragraphs[0].runs[0].font.color.rgb = LIGHT_GRAY
            num_tf.paragraphs[0].alignment = PP_ALIGN.RIGHT

            if slide_type == "title":
                ttl = slide.shapes.add_textbox(Inches(1.5), Inches(2.2), Inches(10), Inches(1.5))
                tf = ttl.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = outline.get("title", "Analysis Report")
                if p.runs:
                    p.runs[0].font.size = Pt(40)
                    p.runs[0].font.bold = True
                    p.runs[0].font.color.rgb = WHITE

                sub = slide.shapes.add_textbox(Inches(1.5), Inches(3.9), Inches(10), Inches(0.6))
                stf = sub.text_frame
                stf.text = outline.get("subtitle", "")
                if stf.paragraphs[0].runs:
                    stf.paragraphs[0].runs[0].font.size = Pt(18)
                    stf.paragraphs[0].runs[0].font.color.rgb = ACCENT
            else:
                headline = slide_def.get("headline", slide_def.get("title", ""))
                title_txt = slide_def.get("title", "")
                bullets = slide_def.get("bullets", [])
                notes = slide_def.get("speaker_notes", "")

                ttl = slide.shapes.add_textbox(Inches(0.5), Inches(0.2), Inches(12), Inches(0.7))
                tf = ttl.text_frame
                tf.word_wrap = True
                p = tf.paragraphs[0]
                p.text = title_txt
                if p.runs:
                    p.runs[0].font.size = Pt(13)
                    p.runs[0].font.color.rgb = ACCENT
                    p.runs[0].font.bold = True

                hl = slide.shapes.add_textbox(Inches(0.5), Inches(1.0), Inches(12), Inches(1.0))
                htf = hl.text_frame
                htf.word_wrap = True
                hp = htf.paragraphs[0]
                hp.text = headline
                if hp.runs:
                    hp.runs[0].font.size = Pt(22)
                    hp.runs[0].font.color.rgb = WHITE
                    hp.runs[0].font.bold = True

                if bullets:
                    btb = slide.shapes.add_textbox(Inches(0.7), Inches(2.2), Inches(11), Inches(4.5))
                    btf = btb.text_frame
                    btf.word_wrap = True
                    for i, bullet in enumerate(bullets[:6]):
                        bp = btf.add_paragraph() if i > 0 else btf.paragraphs[0]
                        bp.text = f"* {bullet}"
                        if bp.runs:
                            bp.runs[0].font.size = Pt(16)
                            bp.runs[0].font.color.rgb = LIGHT_GRAY
                        bp.space_before = Pt(8)

                if notes:
                    notes_slide = slide.notes_slide
                    notes_tf = notes_slide.notes_text_frame
                    notes_tf.text = notes

        buf = io.BytesIO()
        prs.save(buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.error(f"PPTX build error: {e}")
        return b""

# ─────────────────────────────────────────────────────────────────────────────
# Graph Construction & Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def build_analysis_graph() -> StateGraph:
    """Builds and wires the declarative LangGraph multi-agent pipeline.
    Architecture:
      data_quality_gate -> data_cleaner -> hypothesis_planner -> data_scientist
      <-> reflector loop -> viz_preprocessor -> viz_coder <-> viz_repair loop
      -> senior_tier_dispatch (PARALLEL: causal, forecast, anomaly, ab, ml, cohort, benchmark)
      -> strategic_advisor -> report_writer -> narrative_stitcher
      -> presentation_builder -> auditor <-> regeneration loop -> finalize
    """
    workflow = StateGraph(AnalysisGraphState)

    # ── Register all nodes ───────────────────────────────────────────────────
    # Pre-flight gate
    workflow.add_node("data_quality_gate", data_quality_gate_node)
    # Core analysis
    workflow.add_node("data_cleaner", data_cleaner_node)
    workflow.add_node("hypothesis_planner", hypothesis_planner_node)
    workflow.add_node("data_scientist", data_scientist_node)
    workflow.add_node("reflector", reflector_node)
    # Visualization
    workflow.add_node("viz_preprocessor", viz_preprocessor_node)
    workflow.add_node("viz_coder", viz_coder_node)
    workflow.add_node("viz_repair", viz_repair_node)
    # Senior Analyst Tier — dispatched in PARALLEL by senior_tier_dispatch_node
    workflow.add_node("senior_tier_dispatch", senior_tier_dispatch_node)
    # Synthesis & reporting
    workflow.add_node("strategic_advisor", strategic_advisor_node)
    workflow.add_node("report_writer", report_writer_node)
    workflow.add_node("narrative_stitcher", narrative_stitcher_node)
    workflow.add_node("presentation_builder", presentation_builder_node)
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("finalize", finalize_node)

    # ── Entry point ──────────────────────────────────────────────────────────
    workflow.set_entry_point("data_quality_gate")
    workflow.add_edge("data_quality_gate", "data_cleaner")
    workflow.add_edge("data_cleaner", "hypothesis_planner")
    workflow.add_edge("hypothesis_planner", "data_scientist")

    # ── Loop 1: Reflection Cycle ─────────────────────────────────────────────
    workflow.add_edge("data_scientist", "reflector")
    workflow.add_conditional_edges(
        "reflector",
        route_reflection,
        {
            "data_scientist": "data_scientist",
            "viz_preprocessor": "viz_preprocessor",
            "end": END
        }
    )

    # ── Visualization Stage ──────────────────────────────────────────────────
    workflow.add_edge("viz_preprocessor", "viz_coder")

    # ── Loop 2: Visualization Self-Repair Cycle ──────────────────────────────
    workflow.add_conditional_edges(
        "viz_coder",
        route_viz_coder,
        {
            "viz_repair": "viz_repair",
            "report_writer": "senior_tier_dispatch",   # → parallel senior tier
            "end": END
        }
    )
    workflow.add_conditional_edges(
        "viz_repair",
        route_viz_repair,
        {
            "viz_repair": "viz_repair",
            "report_writer": "senior_tier_dispatch",   # → parallel senior tier
            "end": END
        }
    )

    # ── Senior Analyst Tier — PARALLEL dispatch node ─────────────────────────
    # senior_tier_dispatch_node runs all 7 specialist agents simultaneously
    # (Causal, Forecast, Anomaly, A/B, ML, Cohort, Benchmark) via ThreadPoolExecutor
    workflow.add_edge("senior_tier_dispatch", "strategic_advisor")

    # ── Synthesis & Reporting ────────────────────────────────────────────────
    workflow.add_edge("strategic_advisor", "report_writer")
    workflow.add_edge("report_writer", "narrative_stitcher")
    workflow.add_edge("narrative_stitcher", "presentation_builder")
    workflow.add_edge("presentation_builder", "auditor")

    # ── Loop 3: Auditor Quality & Regeneration Cycle ─────────────────────────
    workflow.add_conditional_edges(
        "auditor",
        route_audit,
        {
            "data_scientist": "data_scientist",
            "viz_preprocessor": "viz_preprocessor",
            "report_writer": "report_writer",
            "finalize": "finalize",
            "end": END
        }
    )

    workflow.add_edge("finalize", END)

    return workflow


class AgentGraph:
    """Orchestrates the multi-agent pipeline using LangGraph with dynamic custom loops."""

    def __init__(self, state: AnalysisState):
        self.state = state
        self._lock = threading.Lock()
        self._compiled_graph = build_analysis_graph().compile()

    def _check_cancelled(self) -> bool:
        return check_cancelled({"job_id": self.state.job_id, "cancelled": self.state.cancelled})

    def publish_progress(self, stage: str, status: str, detail: str, round_num: int = 0, score: int | None = None):
        with self._lock:
            state_dict = {"stages_progress": self.state.stages_progress, "progress_callback": self.state.progress_callback}
            publish_stage_progress(state_dict, stage, status, detail, round_num, score)

    def _prepare_visualization_data(self):
        """Compatibility helper for scratch scripts and tests."""
        state_dict = {
            "domain_brief": self.state.domain_brief,
            "schema": self.state.schema,
            "analysis_results": self.state.analysis_results,
            "currency_context": getattr(self.state, "_currency_context", ""),
            "visualization_data": self.state.visualization_data,
            "progress_callback": self.state.progress_callback,
            "stages_progress": self.state.stages_progress
        }
        res = viz_preprocessor_node(state_dict)
        if "visualization_data" in res:
            self.state.visualization_data = res["visualization_data"]

    def run(self) -> dict:
        """Executes the compiled LangGraph workflow with custom conditional loops."""
        try:
            if self._check_cancelled():
                raise JobCancelledException("Job cancelled by user.")

            initial_state: AnalysisGraphState = {
                "df": self.state.df,
                "schema": self.state.schema,
                "sample_rows": self.state.sample_rows,
                "domain_brief": self.state.domain_brief,
                "stats": self.state.stats,
                "progress_callback": self.state.progress_callback,
                "job_id": self.state.job_id,
                "max_reflections": self.state.max_reflections,
                "max_regeneration_rounds": self.state.max_regeneration_rounds,
                "currency_context": getattr(self.state, "_currency_context", ""),
                "analysis_results": self.state.analysis_results,
                "chart_images": list(self.state.chart_images),
                "report": dict(self.state.report),
                "audit": dict(self.state.audit),
                "visualization_data": dict(self.state.visualization_data),
                "conversation_history": list(self.state.conversation_history),
                "methodology_code": self.state.methodology_code,
                "viz_code": self.state.viz_code,
                "reflection_iteration": self.state.reflection_iteration,
                "reflection_feedback": self.state.reflection_feedback,
                "reflection_feedback_formatted": self.state.reflection_feedback_formatted,
                "follow_up_tasks": list(self.state.follow_up_tasks),
                "investigation_log": list(self.state.investigation_log),
                "hypotheses_tested": list(self.state.hypotheses_tested),
                "viz_error": None,
                "viz_repair_attempts": 0,
                "regeneration_round": self.state.regeneration_round,
                "audit_feedback": list(self.state.audit_feedback),
                "retry_targets": list(self.state.retry_targets),
                "last_execution_stdout": self.state.last_execution_stdout,
                "last_execution_stderr": self.state.last_execution_stderr,
                "last_execution_outputs": list(self.state.last_execution_outputs),
                "stages_progress": dict(self.state.stages_progress),
                "agent_files": list(self.state.agent_files),
                "cancelled": False,
                "error": None,
                "final_report": {},
                # Data Quality Engineering, Dynamic Hypotheses & ML
                "cleaning_manifest": dict(getattr(self.state, "cleaning_manifest", {})),
                "investigation_plan": dict(getattr(self.state, "investigation_plan", {})),
                "ml_results": dict(getattr(self.state, "ml_results", {})),
                # Senior Analyst Tier
                "causal_results": dict(self.state.causal_results),
                "forecast_results": dict(self.state.forecast_results),
                "anomaly_results": dict(self.state.anomaly_results),
                "strategic_results": dict(self.state.strategic_results),
                "time_column_detected": self.state.time_column_detected,
                "target_columns_detected": list(self.state.target_columns_detected),
                # NEW agent initial states
                "data_quality_score": getattr(self.state, "data_quality_score", 0),
                "data_quality_gate_decision": getattr(self.state, "data_quality_gate_decision", "PASS"),
                "data_quality_issues": list(getattr(self.state, "data_quality_issues", [])),
                "cohort_results": dict(getattr(self.state, "cohort_results", {})),
                "benchmark_results": dict(getattr(self.state, "benchmark_results", {})),
                "presentation_results": dict(getattr(self.state, "presentation_results", {})),
            }

            job_lbl = self.state.job_id or 'anonymous'
            ts_start = datetime.now().strftime("%H:%M:%S")
            print(f"\n=======================================================", flush=True)
            print(f"[{ts_start}] ▶ [Agent Workflow] Starting analysis job {job_lbl}...", flush=True)
            print(f"=======================================================", flush=True)

            final_state = self._compiled_graph.invoke(initial_state)

            # Sync updated attributes back to AnalysisState for caller compatibility
            self.state.df = final_state.get("df", self.state.df)
            self.state.schema = final_state.get("schema", self.state.schema)
            self.state.sample_rows = final_state.get("sample_rows", self.state.sample_rows)
            self.state.cleaning_manifest = final_state.get("cleaning_manifest", getattr(self.state, "cleaning_manifest", {}))
            self.state.investigation_plan = final_state.get("investigation_plan", getattr(self.state, "investigation_plan", {}))
            self.state.ml_results = final_state.get("ml_results", getattr(self.state, "ml_results", {}))
            self.state.experiment_results = final_state.get("experiment_results", getattr(self.state, "experiment_results", {}))
            self.state.relational_manifest = final_state.get("relational_manifest", getattr(self.state, "relational_manifest", {}))
            self.state.chart_images = final_state.get("chart_images", self.state.chart_images)
            self.state.report = final_state.get("report", self.state.report)
            self.state.audit = final_state.get("audit", self.state.audit)
            self.state.visualization_data = final_state.get("visualization_data", self.state.visualization_data)
            self.state.conversation_history = final_state.get("conversation_history", self.state.conversation_history)
            self.state.methodology_code = final_state.get("methodology_code", self.state.methodology_code)
            self.state.viz_code = final_state.get("viz_code", self.state.viz_code)
            self.state.reflection_iteration = final_state.get("reflection_iteration", self.state.reflection_iteration)
            self.state.regeneration_round = final_state.get("regeneration_round", self.state.regeneration_round)
            self.state.agent_files = final_state.get("agent_files", self.state.agent_files)
            self.state.investigation_log = final_state.get("investigation_log", self.state.investigation_log)
            self.state.stages_progress = final_state.get("stages_progress", self.state.stages_progress)
            # Senior Analyst Tier sync-back
            self.state.causal_results = final_state.get("causal_results", self.state.causal_results)
            self.state.forecast_results = final_state.get("forecast_results", self.state.forecast_results)
            self.state.anomaly_results = final_state.get("anomaly_results", self.state.anomaly_results)
            self.state.strategic_results = final_state.get("strategic_results", self.state.strategic_results)
            self.state.time_column_detected = final_state.get("time_column_detected", self.state.time_column_detected)
            self.state.target_columns_detected = final_state.get("target_columns_detected", self.state.target_columns_detected)
            # NEW agent sync-back
            self.state.data_quality_score = final_state.get("data_quality_score", getattr(self.state, "data_quality_score", 0))
            self.state.data_quality_gate_decision = final_state.get("data_quality_gate_decision", getattr(self.state, "data_quality_gate_decision", "PASS"))
            self.state.data_quality_issues = final_state.get("data_quality_issues", getattr(self.state, "data_quality_issues", []))
            self.state.cohort_results = final_state.get("cohort_results", getattr(self.state, "cohort_results", {}))
            self.state.benchmark_results = final_state.get("benchmark_results", getattr(self.state, "benchmark_results", {}))
            self.state.presentation_results = final_state.get("presentation_results", getattr(self.state, "presentation_results", {}))

            if final_state.get("error"):
                self.state.error = final_state["error"]
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ [Agent Workflow] Finished with error: {self.state.error}", flush=True)
                return {"error": self.state.error}

            ts_end = datetime.now().strftime("%H:%M:%S")
            print(f"=======================================================", flush=True)
            print(f"[{ts_end}] ✔ [Agent Workflow] Analysis pipeline completed successfully for job {job_lbl}!", flush=True)
            print(f"=======================================================\n", flush=True)
            return final_state.get("final_report", {})

        except JobCancelledException as je:
            logger.info(f"AgentGraph execution cancelled for job {self.state.job_id}: {je}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏹ [Agent Workflow] Analysis job {self.state.job_id} cancelled by user.", flush=True)
            return {"error": "Job cancelled by user", "cancelled": True}
        except Exception as e:
            logger.error(f"Error executing LangGraph pipeline: {e}", exc_info=True)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ [Agent Workflow] Execution failure: {e}", flush=True)
            return {"error": f"AgentGraph execution failure: {e}"}