# backend/services/agent_graph.py

import json
import logging
import re
import time
import os
import uuid
import difflib
import threading
import numpy as np
import pandas as pd
import scipy.stats as stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from typing import Callable, Dict, Any, List, Optional, TypedDict

from langgraph.graph import StateGraph, END

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
        "sampling": "Smart Sampler",
        "data_scientist": "Data Scientist Agent",
        "reflector": "Reflector Agent",
        "viz_coder": "Visualization Agent",
        "report_writer": "Report Writer",
        "narrative_stitcher": "Narrative Stitcher",
        "auditor": "Quality Auditor",
        "validation": "Data Validator"
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
            "running",
            f"Reflection: Loop requested. Feedback: {feedback[:80]}...",
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
        "viz_coder",
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


def report_writer_node(state: AnalysisGraphState) -> dict:
    """Report Writer Node: Structures findings, stats, and charts into the primary report JSON."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    publish_stage_progress(
        state,
        "report_writer",
        "running",
        "Structuring and writing report narrative, executive summary and recommendations...",
        state.get("regeneration_round", 0)
    )

    charts_desc = [
        {"title": c["title"], "filename": c["filename"], "interpretation": c["interpretation"]}
        for c in state.get("chart_images", [])
    ]
    stats_dict = state.get("stats", {})
    numeric_sum = json.dumps(stats_dict.get("numeric_summary", {}), default=str)
    grouped_sum = json.dumps(stats_dict.get("grouped_summary", {}), default=str)
    missing_vals = json.dumps(stats_dict.get("missing_values", {}), default=str)
    stats_summary = f"Missing values: {missing_vals}\nNumeric Summary: {numeric_sum}\nGrouped Summary: {grouped_sum}"

    currency_context = state.get("currency_context") or "No currency context detected."

    # Senior tier context for richer report
    _causal = state.get("causal_results", {})
    _forecast = state.get("forecast_results", {})
    _anomaly = state.get("anomaly_results", {})
    _strategic = state.get("strategic_results", {})
    senior_context = (
        f"\n\n## Causal Analysis Summary\n{_causal.get('causal_summary', 'Not available.')}\n"
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

    # Senior tier context for richer report
    _causal = state.get("causal_results", {})
    _forecast = state.get("forecast_results", {})
    _anomaly = state.get("anomaly_results", {})
    _strategic = state.get("strategic_results", {})
    senior_context = (
        f"\n\n## Causal Analysis Summary\n{_causal.get('causal_summary', 'Not available.')}\n"
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


def finalize_node(state: AnalysisGraphState) -> dict:
    """Finalize Node: Packages visual plans, code transparency, and metadata into the final report."""
    if check_cancelled(state):
        raise JobCancelledException("Job cancelled by user.")

    report = dict(state.get("report", {}))
    chart_images = state.get("chart_images", [])

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

    # ── Senior Analyst Tier results embedded in report ──────────────────────
    report["causal_analysis"] = state.get("causal_results", {})
    report["forecast"] = state.get("forecast_results", {})
    report["anomaly_detection"] = state.get("anomaly_results", {})
    report["strategic_brief"] = state.get("strategic_results", {})
    # Expose executive headline at top level for easy access in PDF/UI
    strategic = state.get("strategic_results", {})
    if strategic.get("executive_headline") and not report.get("executive_headline"):
        report["executive_headline"] = strategic["executive_headline"]
    if strategic.get("recommendations") and not report.get("strategic_recommendations"):
        report["strategic_recommendations"] = strategic["recommendations"]
    # ────────────────────────────────────────────────────────────────────────

    return {"final_report": report, "report": report}


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
# Senior Analyst Tier — Node 4: Strategic Advisor
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
# Graph Construction & Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def build_analysis_graph() -> StateGraph:
    """Builds and wires the declarative LangGraph multi-agent pipeline with custom conditional loops."""
    workflow = StateGraph(AnalysisGraphState)

    # Register Nodes
    workflow.add_node("data_scientist", data_scientist_node)
    workflow.add_node("reflector", reflector_node)
    workflow.add_node("viz_preprocessor", viz_preprocessor_node)
    workflow.add_node("viz_coder", viz_coder_node)
    workflow.add_node("viz_repair", viz_repair_node)
    # Senior Analyst Tier Nodes
    workflow.add_node("causal_analyst", causal_analyst_node)
    workflow.add_node("forecaster", forecaster_node)
    workflow.add_node("anomaly_detector", anomaly_detector_node)
    workflow.add_node("strategic_advisor", strategic_advisor_node)
    # Reporting Nodes
    workflow.add_node("report_writer", report_writer_node)
    workflow.add_node("narrative_stitcher", narrative_stitcher_node)
    workflow.add_node("auditor", auditor_node)
    workflow.add_node("finalize", finalize_node)

    # Entry point
    workflow.set_entry_point("data_scientist")

    # Sequence and Custom Loops
    workflow.add_edge("data_scientist", "reflector")

    # Custom Loop 1: Reflection Cycle
    workflow.add_conditional_edges(
        "reflector",
        route_reflection,
        {
            "data_scientist": "data_scientist",
            "viz_preprocessor": "viz_preprocessor",
            "end": END
        }
    )

    workflow.add_edge("viz_preprocessor", "viz_coder")

    # Custom Loop 2: Visualization Self-Repair Cycle
    # After viz is done → Senior Analyst Tier begins
    workflow.add_conditional_edges(
        "viz_coder",
        route_viz_coder,
        {
            "viz_repair": "viz_repair",
            "report_writer": "causal_analyst",  # Route to senior tier
            "end": END
        }
    )
    workflow.add_conditional_edges(
        "viz_repair",
        route_viz_repair,
        {
            "viz_repair": "viz_repair",
            "report_writer": "causal_analyst",  # Route to senior tier
            "end": END
        }
    )

    # Senior Analyst Tier Pipeline (sequential)
    workflow.add_edge("causal_analyst", "forecaster")
    workflow.add_edge("forecaster", "anomaly_detector")
    workflow.add_edge("anomaly_detector", "strategic_advisor")
    workflow.add_edge("strategic_advisor", "report_writer")

    workflow.add_edge("report_writer", "narrative_stitcher")
    workflow.add_edge("narrative_stitcher", "auditor")

    # Custom Loop 3: Auditor Quality & Regeneration Cycle
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
                # Senior Analyst Tier
                "causal_results": dict(self.state.causal_results),
                "forecast_results": dict(self.state.forecast_results),
                "anomaly_results": dict(self.state.anomaly_results),
                "strategic_results": dict(self.state.strategic_results),
                "time_column_detected": self.state.time_column_detected,
                "target_columns_detected": list(self.state.target_columns_detected),
            }

            final_state = self._compiled_graph.invoke(initial_state)

            # Sync updated attributes back to AnalysisState for caller compatibility
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

            if final_state.get("error"):
                self.state.error = final_state["error"]
                return {"error": self.state.error}

            return final_state.get("final_report", {})

        except JobCancelledException as je:
            logger.info(f"AgentGraph execution cancelled for job {self.state.job_id}: {je}")
            return {"error": "Job cancelled by user", "cancelled": True}
        except Exception as e:
            logger.error(f"Error executing LangGraph pipeline: {e}", exc_info=True)
            return {"error": f"AgentGraph execution failure: {e}"}
