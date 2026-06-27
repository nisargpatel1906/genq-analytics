# backend/services/agent_graph.py

import json
import logging
import re
import time
import os
import numpy as np
import pandas as pd
import scipy.stats as stats
from typing import Callable, Dict, Any, List, Optional
import threading

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
    VISUALIZATION_PREPROCESS_PROMPT
)

logger = logging.getLogger("genq_api.agent_graph")

ProgressCallback = Callable[[dict], None]
class AnalysisState:
    """Shared state flowing through the agent graph."""
    def __init__(
        self,
        df: pd.DataFrame,
        schema: dict,
        sample_rows: list[dict],
        domain_brief: dict,
        stats: dict = None,
        progress_callback: Optional[ProgressCallback] = None,
        max_reflections: int = 2,
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
        
        self.error: Optional[str] = None
        self.stages_progress: Dict[str, dict] = {}
        
        # Audit trail of every file any agent created across the full run
        self.agent_files: List[Dict[str, Any]] = []

        # Last execution outputs for self-correction feedback loop
        self.last_execution_stdout: str = ""
        self.last_execution_stderr: str = ""
        self.last_execution_outputs: List[Dict[str, Any]] = []
def extract_code_block(text: str) -> str:
    """Extracts code block content wrapped in ```python ... ```."""
    pattern = r"```python\s*(.*?)\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    pattern_generic = r"```\s*(.*?)\s*```"
    match_generic = re.search(pattern_generic, text, re.DOTALL)
    if match_generic:
        return match_generic.group(1).strip()
    
    return text.strip()


class AgentGraph:
    """Executes the agentic pipeline using a custom lightweight state machine."""
    
    def __init__(self, state: AnalysisState):
        self.state = state
        self._lock = threading.Lock()

    def _check_cancelled(self) -> bool:
        """Returns True if the current job has been cancelled by the user."""
        if self.state.job_id:
            try:
                job = jobs.get(self.state.job_id)
                if job and (job.get("status") == "Cancelled" or job.get("cancelled", False)):
                    return True
            except Exception as e:
                logger.warning(f"Error checking cancellation status for job {self.state.job_id}: {e}")
        return False


    def publish_progress(self, stage: str, status: str, detail: str, round_num: int = 0, score: int | None = None):
        """Updates internal progress dictionary and calls the user progress_callback."""
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
        
        update = {
            "id": stage,
            "name": stage_names.get(stage, stage.title()),
            "status": status,
            "detail": detail,
            "round": round_num,
        }
        if score is not None:
            update["score"] = score
            
        with self._lock:
            self.state.stages_progress[stage] = update
            stages_list = list(self.state.stages_progress.values())
        
        if self.state.progress_callback:
            self.state.progress_callback({
                "currentAgent": stage,
                "agents": stages_list,
                **update
            })

    def run(self) -> dict:
        """Runs the state machine until completion or failure."""
        try:
            if self._check_cancelled():
                raise JobCancelledException("Job cancelled by user.")

            # 1. Data Scientist node
            self._data_scientist_node()
            if self.state.error:
                return {"error": self.state.error}

            # 2. Reflection loop
            while self.state.reflection_iteration < self.state.max_reflections:
                if self._check_cancelled():
                    raise JobCancelledException("Job cancelled by user.")
                self._reflector_node()
                if not self.state.reflection_feedback:
                    break
                
                # If reflector asked for more, run data scientist again with feedback
                self.state.reflection_iteration += 1
                logger.info(f"Reflector requested loop {self.state.reflection_iteration}. Feedback: {self.state.reflection_feedback}")
                if self._check_cancelled():
                    raise JobCancelledException("Job cancelled by user.")
                self._data_scientist_node(feedback=self.state.reflection_feedback_formatted)
                if self.state.error:
                    return {"error": self.state.error}

            # 3 & 4. Visualizations and Report Draft Sequentially
            if self._check_cancelled():
                raise JobCancelledException("Job cancelled by user.")
            self._run_visuals_and_report_sequentially()
            if self.state.error:
                return {"error": self.state.error}
            
            # 4.5. Narrative Stitcher node
            if self._check_cancelled():
                raise JobCancelledException("Job cancelled by user.")
            self._narrative_stitcher_node()
            if self.state.error:
                return {"error": self.state.error}

            # 5. Quality Auditor node
            if self._check_cancelled():
                raise JobCancelledException("Job cancelled by user.")
            self._auditor_node()
            
            # 6. Audit regeneration loop
            while not self.state.audit.get("approved", True) and self.state.regeneration_round < self.state.max_regeneration_rounds:
                if self._check_cancelled():
                    raise JobCancelledException("Job cancelled by user.")
                self.state.regeneration_round += 1
                targets = self.state.audit.get("retryTargets", [])
                issues = self.state.audit.get("issues", [])
                
                logger.info(f"Audit failed. Starting regeneration round {self.state.regeneration_round}. Targets: {targets}")
                
                # Format audit feedback to pass to agents
                self.state.audit_feedback = issues
                
                if "analytics" in targets:
                    if self._check_cancelled():
                        raise JobCancelledException("Job cancelled by user.")
                    self._data_scientist_node(feedback=f"Audit correction feedback: {json.dumps(issues)}")
                    if self.state.error:
                        return {"error": self.state.error}
                    targets.append("visuals")
                    targets.append("report_writer")
                    
                if "visuals" in targets and ("report" in targets or "report_writer" in targets):
                    if self._check_cancelled():
                        raise JobCancelledException("Job cancelled by user.")
                    self._run_visuals_and_report_sequentially()
                    if self.state.error:
                        return {"error": self.state.error}
                    if self._check_cancelled():
                        raise JobCancelledException("Job cancelled by user.")
                    self._narrative_stitcher_node()
                    if self.state.error:
                        return {"error": self.state.error}
                elif "visuals" in targets:
                    if self._check_cancelled():
                        raise JobCancelledException("Job cancelled by user.")
                    self._viz_coder_node()
                    if self.state.error:
                        return {"error": self.state.error}
                elif "report" in targets or "report_writer" in targets:
                    if self._check_cancelled():
                        raise JobCancelledException("Job cancelled by user.")
                    self._report_writer_node()
                    if self.state.error:
                        return {"error": self.state.error}
                    if self._check_cancelled():
                        raise JobCancelledException("Job cancelled by user.")
                    self._narrative_stitcher_node()
                    if self.state.error:
                        return {"error": self.state.error}
                
                # Re-audit
                if self._check_cancelled():
                    raise JobCancelledException("Job cancelled by user.")
                self._auditor_node()

            # If still not approved after max retries, finalize report anyway
            if not self.state.audit.get("approved", True):
                logger.warning("Audit regeneration rounds exhausted without approval. Finalizing with current report.")
                self.publish_progress(
                    "auditor",
                    "completed",
                    f"Completed after {self.state.regeneration_round} regeneration rounds. Score: {self.state.audit.get('score', 0)}/100 (Unapproved but finalized)",
                    self.state.regeneration_round,
                    score=self.state.audit.get('score', 0)
                )
            
            # Format report and add metadata
            result_report = self.state.report.copy()
            # Include custom charts for UI display
            result_report["_visualPlan"] = {
                "charts": [
                    {
                        "type": "custom",
                        "title": c.get("title", "Custom Chart"),
                        "x": None,
                        "y": None,
                        "aggregation": "none",
                        "reason": c.get("interpretation", "Generated by visualization agent.")
                    }
                    for c in self.state.chart_images
                ]
            }
            # Attach code used for transparency
            result_report["analysis_code_used"] = self.state.methodology_code
            result_report["visualization_code_used"] = self.state.viz_code
            # Attach agent file audit trail and investigation log for transparency
            result_report["agent_files_created"] = self.state.agent_files
            result_report["investigation_log"] = self.state.investigation_log
            
            return result_report

        except JobCancelledException as je:
            logger.info(f"AgentGraph execution cancelled for job {self.state.job_id}: {je}")
            return {"error": "Job cancelled by user", "cancelled": True}
        except Exception as e:
            logger.error(f"Error executing agent graph: {e}", exc_info=True)
            return {"error": f"AgentGraph execution failure: {e}"}


    def _data_scientist_node(self, feedback: str = ""):
        """Node for Data Scientist agent. Executes step-by-step tool calling loop."""
        self.publish_progress(
            "data_scientist",
            "running",
            "Starting iterative data science investigation loop...",
            self.state.regeneration_round
        )

        # BUG-7 fix: clear charts that came from create_chart_tool in prior rounds.
        # Charts produced by _viz_coder_node (with binary data) survive across rounds;
        # charts from create_chart_tool (filename-only, no data) are regenerated each round
        # and would otherwise accumulate duplicates.
        with self._lock:
            self.state.chart_images = [
                c for c in self.state.chart_images if c.get("data") is not None
            ]

        stats = self.state.stats
        numeric_sum = json.dumps(stats.get("numeric_summary", {}), default=str)
        grouped_sum = json.dumps(stats.get("grouped_summary", {}), default=str)
        missing_vals = json.dumps(stats.get("missing_values", {}), default=str)

        prompt_kwargs = dict(
            domain=self.state.domain_brief.get("domain", "Unknown"),
            purpose=self.state.domain_brief.get("datasetPurpose", "Analyze data structure"),
            dataset_type=self.state.domain_brief.get("datasetType", "cross-sectional"),
            important_columns=json.dumps(self.state.domain_brief.get("importantColumns", [])),
            schema=json.dumps(self.state.schema, default=str),
            sample_rows=json.dumps(self.state.sample_rows, default=str),
            missing_values=missing_vals,
            numeric_summary=numeric_sum,
            grouped_summary=grouped_sum,
            feedback=feedback,
        )

        if not self.state.conversation_history:
            prompt = DATA_SCIENTIST_PROMPT.format(**prompt_kwargs)
            self.state.conversation_history = [
                {"role": "system", "content": "You are a quantitative data analyst. Use the available tools to analyze the dataset. Output JSON tool calls."},
                {"role": "user", "content": prompt},
            ]
        else:
            self.state.conversation_history.append({
                "role": "user",
                "content": f"Here is the Reflector feedback for this round:\n{feedback}\nPlease address the follow-up tasks using the tools, and call 'done' when finished."
            })

        messages = self.state.conversation_history

        import difflib
        def _fuzzy_match_column(col_name, df_cols):
            if not col_name: return None
            if col_name in df_cols: return col_name
            matches = difflib.get_close_matches(col_name, df_cols, n=1, cutoff=0.6)
            return matches[0] if matches else None

        # Define internal tool execution handlers
        def inspect_column_tool(col_name):
            df = self.state.df
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

        def run_test_tool(test_type, col_a, col_b):
            df = self.state.df
            matched_a = _fuzzy_match_column(col_a, df.columns.tolist())
            matched_b = _fuzzy_match_column(col_b, df.columns.tolist())
            if not matched_a or not matched_b:
                return f"Error: col_a ('{col_a}') or col_b ('{col_b}') not found in DataFrame. Available columns are: {list(df.columns)}"
            
            # Use matched columns
            col_a = matched_a
            col_b = matched_b
            
            import scipy.stats as stats
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
                return {
                    "test": "t_test",
                    "group_1": str(groups[0]),
                    "group_1_mean": float(group_data[0].mean()),
                    "group_2": str(groups[1]),
                    "group_2_mean": float(group_data[1].mean()),
                    "t_statistic": t_stat,
                    "p_value": p_val
                }
            elif test_type == "chi2_test":
                contingency_table = pd.crosstab(df[col_a], df[col_b])
                chi2, p, dof, expected = stats.chi2_contingency(contingency_table)
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
                # Compute eta-squared (effect size for ANOVA)
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
                    "interpretation": f"A 1-unit increase in {col_a} is associated with a {slope:.4f} change in {col_b}. R² = {r_value**2:.4f} means {col_a} explains {r_value**2*100:.1f}% of the variance in {col_b}."
                }
            elif test_type == "effect_size":
                if not pd.api.types.is_numeric_dtype(df[col_a]):
                    return "Error: col_a must be numeric for effect size."
                groups = df[col_b].dropna().unique()
                if len(groups) < 2:
                    return f"Error: col_b only has {len(groups)} group(s). Need at least 2."
                g1 = df[df[col_b] == groups[0]][col_a].dropna()
                g2 = df[df[col_b] == groups[1]][col_a].dropna()
                if len(g1) < 2 or len(g2) < 2:
                    return "Error: one of the groups has too few data points."
                pooled_std = float(np.sqrt(((len(g1) - 1) * g1.std()**2 + (len(g2) - 1) * g2.std()**2) / (len(g1) + len(g2) - 2)))
                cohens_d = float((g1.mean() - g2.mean()) / pooled_std) if pooled_std > 0 else 0.0
                return {
                    "test": "effect_size",
                    "group_1": str(groups[0]),
                    "group_1_mean": float(g1.mean()),
                    "group_1_std": float(g1.std()),
                    "group_2": str(groups[1]),
                    "group_2_mean": float(g2.mean()),
                    "group_2_std": float(g2.std()),
                    "cohens_d": cohens_d,
                    "abs_cohens_d": abs(cohens_d),
                    "effect_interpretation": "large" if abs(cohens_d) > 0.8 else "medium" if abs(cohens_d) > 0.5 else "small",
                    "practical_significance": f"The difference between {groups[0]} and {groups[1]} is {abs(cohens_d):.2f} standard deviations — a {'large' if abs(cohens_d) > 0.8 else 'medium' if abs(cohens_d) > 0.5 else 'small'} practical effect."
                }
            elif test_type == "normality":
                matched_col = _fuzzy_match_column(col_a, df.columns.tolist())
                if not matched_col:
                    return f"Error: column '{col_a}' not found. Available columns: {list(df.columns)}"
                col_data = df[matched_col].dropna()
                if not pd.api.types.is_numeric_dtype(col_data):
                    return "Error: column must be numeric for normality test."
                sample = col_data.sample(min(5000, len(col_data)), random_state=42)
                if len(sample) < 3:
                    return "Error: need at least 3 data points."
                w_stat, p_val = stats.shapiro(sample)
                skewness = float(col_data.skew())
                kurtosis = float(col_data.kurt())
                return {
                    "test": "normality",
                    "column": matched_col,
                    "shapiro_w": float(w_stat),
                    "p_value": float(p_val),
                    "is_normal": p_val > 0.05,
                    "skewness": skewness,
                    "kurtosis": kurtosis,
                    "interpretation": f"{'Normally distributed' if p_val > 0.05 else 'NOT normally distributed'} (p={p_val:.4f}). Skewness={skewness:.2f}, Kurtosis={kurtosis:.2f}."
                }
            elif test_type == "outlier_detection":
                matched_col = _fuzzy_match_column(col_a, df.columns.tolist())
                if not matched_col:
                    return f"Error: column '{col_a}' not found. Available columns: {list(df.columns)}"
                col_data = df[matched_col].dropna()
                if not pd.api.types.is_numeric_dtype(col_data):
                    return "Error: column must be numeric for outlier detection."
                q1 = float(col_data.quantile(0.25))
                q3 = float(col_data.quantile(0.75))
                iqr = q3 - q1
                lower_bound = q1 - 1.5 * iqr
                upper_bound = q3 + 1.5 * iqr
                outliers = col_data[(col_data < lower_bound) | (col_data > upper_bound)]
                return {
                    "test": "outlier_detection",
                    "column": matched_col,
                    "method": "IQR (1.5x)",
                    "q1": q1,
                    "q3": q3,
                    "iqr": float(iqr),
                    "lower_bound": float(lower_bound),
                    "upper_bound": float(upper_bound),
                    "outlier_count": len(outliers),
                    "outlier_percentage": f"{len(outliers)/len(col_data)*100:.2f}%",
                    "total_rows": len(col_data),
                    "outlier_min": float(outliers.min()) if len(outliers) > 0 else None,
                    "outlier_max": float(outliers.max()) if len(outliers) > 0 else None
                }
            else:
                return f"Error: unknown test_type '{test_type}'. Available types: correlation, t_test, chi2_test, anova, regression, effect_size, normality, outlier_detection."

        def group_analysis_tool(numeric_col, group_col):
            df = self.state.df
            df_cols = df.columns.tolist()
            matched_num = _fuzzy_match_column(numeric_col, df_cols)
            matched_grp = _fuzzy_match_column(group_col, df_cols)
            if not matched_num:
                return f"Error: numeric column '{numeric_col}' not found. Available: {df_cols}"
            if not matched_grp:
                return f"Error: group column '{group_col}' not found. Available: {df_cols}"
            if not pd.api.types.is_numeric_dtype(df[matched_num]):
                return f"Error: '{matched_num}' is not numeric."
            grouped = df.groupby(matched_grp)[matched_num].agg(["mean", "median", "std", "count", "min", "max"])
            grouped = grouped.sort_values("mean", ascending=False)
            result = {
                "numeric_column": matched_num,
                "group_column": matched_grp,
                "num_groups": len(grouped),
                "groups": {}
            }
            for grp_name, row in grouped.head(15).iterrows():
                result["groups"][str(grp_name)] = {
                    "mean": round(float(row["mean"]), 4),
                    "median": round(float(row["median"]), 4),
                    "std": round(float(row["std"]), 4) if not pd.isna(row["std"]) else 0.0,
                    "count": int(row["count"]),
                    "min": round(float(row["min"]), 4),
                    "max": round(float(row["max"]), 4)
                }
            # Compute overall spread
            means = [v["mean"] for v in result["groups"].values()]
            if len(means) >= 2:
                result["spread"] = {
                    "highest_group": max(result["groups"], key=lambda k: result["groups"][k]["mean"]),
                    "lowest_group": min(result["groups"], key=lambda k: result["groups"][k]["mean"]),
                    "range": round(max(means) - min(means), 4),
                    "ratio": round(max(means) / min(means), 2) if min(means) > 0 else None
                }
            return result

        def create_chart_tool(chart_type, x, y=None, hue=None):
            df = self.state.df
            
            # Fuzzy match columns
            df_cols = df.columns.tolist()
            if x:
                matched_x = _fuzzy_match_column(x, df_cols)
                if not matched_x: return f"Error: column x ('{x}') not found in DataFrame. Available columns are: {list(df_cols)}"
                x = matched_x
            if y:
                matched_y = _fuzzy_match_column(y, df_cols)
                if not matched_y: return f"Error: column y ('{y}') not found in DataFrame. Available columns are: {list(df_cols)}"
                y = matched_y
            if hue:
                matched_hue = _fuzzy_match_column(hue, df_cols)
                if not matched_hue: return f"Error: column hue ('{hue}') not found in DataFrame. Available columns are: {list(df_cols)}"
                hue = matched_hue
                
            import matplotlib.pyplot as plt
            import seaborn as sns
            plt.figure(figsize=(8, 4.5))
            sns.set_theme(style="whitegrid")
            try:
                if chart_type == "line":
                    sns.lineplot(data=df, x=x, y=y, hue=hue)
                elif chart_type == "bar":
                    sns.barplot(data=df, x=x, y=y, hue=hue)
                elif chart_type == "scatter":
                    sns.scatterplot(data=df, x=x, y=y, hue=hue)
                elif chart_type == "box":
                    sns.boxplot(data=df, x=x, y=y, hue=hue)
                elif chart_type == "violin":
                    sns.violinplot(data=df, x=x, y=y, hue=hue, inner="quartile")
                elif chart_type == "regression_plot":
                    plt.close("all")
                    fig, ax = plt.subplots(figsize=(8, 4.5))
                    sns.regplot(data=df, x=x, y=y, ax=ax, scatter_kws={"alpha": 0.4}, line_kws={"color": "red"})
                elif chart_type == "pairplot":
                    plt.close("all")
                    numeric_cols = df.select_dtypes(include="number").columns[:5].tolist()
                    if x and x in numeric_cols:
                        numeric_cols = [x] + [c for c in numeric_cols if c != x]
                    pair_fig = sns.pairplot(df[numeric_cols[:4]], diag_kind="kde", plot_kws={"alpha": 0.5})
                    filename = f"pairplot_{x or 'numeric'}.png".replace(" ", "_").lower()
                    pair_fig.savefig(filename, dpi=180, bbox_inches="tight")
                    plt.close("all")
                    with self._lock:
                        self.state.chart_images.append({
                            "filename": filename,
                            "title": f"Pairplot of top numeric columns",
                            "interpretation": f"Multi-variable relationship matrix for numeric columns.",
                            "insight_text": "",
                            "finding_title": ""
                        })
                        self.state.agent_files.append({
                            "agent": "data_scientist",
                            "round": self.state.reflection_iteration,
                            "filename": filename,
                            "type": "image",
                            "purpose": f"Pairplot of numeric columns"
                        })
                    return f"Success: pairplot saved as {filename}."
                elif chart_type == "heatmap":
                    sns.heatmap(df.select_dtypes(include='number').corr(), annot=True, cmap="coolwarm")
                else:
                    plt.close("all")
                    return f"Error: unknown chart_type '{chart_type}'. Available: line, bar, scatter, box, violin, regression_plot, pairplot, heatmap."
                plt.title(f"{chart_type.title()} of {x} vs {y or 'Count'}")
                plt.tight_layout()
                filename = f"{chart_type}_{x}_{y or 'count'}.png".replace(" ", "_").lower()
                plt.savefig(filename, dpi=180, bbox_inches="tight")
                plt.close("all")
                
                with self._lock:
                    self.state.chart_images.append({
                        "filename": filename,
                        "title": f"{chart_type.title()} of {x} vs {y or 'Count'}",
                        "interpretation": f"Visual distribution of {x} and {y or 'counts'}.",
                        "insight_text": "",
                        "finding_title": ""
                    })
                    self.state.agent_files.append({
                        "agent": "data_scientist",
                        "round": self.state.reflection_iteration,
                        "filename": filename,
                        "type": "image",
                        "purpose": f"{chart_type} chart for {x} vs {y}"
                    })
                return f"Success: chart saved as {filename}."
            except Exception as e:
                plt.close("all")
                return f"Error plotting chart: {e}"

        def save_finding_tool(title, evidence, confidence):
            finding = {
                "title": title,
                "detail": evidence,
                "evidence": evidence,
                "confidence": confidence
            }
            with self._lock:
                if "findings" not in self.state.analysis_results:
                    self.state.analysis_results["findings"] = []
                if "keyFindings" not in self.state.analysis_results:
                    self.state.analysis_results["keyFindings"] = []
                self.state.analysis_results["findings"].append(finding)
                self.state.analysis_results["keyFindings"].append(finding)
                
                self.state.investigation_log.append({
                    "agent": "data_scientist",
                    "round": self.state.reflection_iteration,
                    "action": f"Saved key finding: {title}",
                    "result": evidence
                })
            return f"Success: saved finding '{title}'."

        loop_count = 0
        max_loop = 15
        execution_stdout_log = []

        MAX_JSON_RETRIES = 3
        REMINDER_MSG = (
            "Your previous response could not be parsed as JSON. "
            "You MUST respond with ONLY a valid JSON object — no markdown, no text outside JSON, no <think> tags. "
            "Format: {\"thought\": \"...\", \"tool\": \"...\", \"arguments\": {...}}"
        )

        # Context trimming — keep messages within Ollama's context window.
        # Strategy: always keep [0] system + [1] initial user prompt,
        # then keep the most recent `tail` message pairs.
        _MAX_CTX_CHARS = int(os.environ.get("LLM_MAX_CTX_CHARS", "60000"))  # ~20k tokens @ 3 chars/tok
        _CTX_TAIL = int(os.environ.get("LLM_CTX_TAIL_MESSAGES", "12"))      # keep last 12 messages

        def _trim_messages(msgs: list) -> list:
            """Return a context-safe slice of the message list."""
            if len(msgs) <= 2:
                return msgs
            # Always keep system (0) + initial user prompt (1)
            header = msgs[:2]
            tail = msgs[2:]
            # Trim by tail count first
            if len(tail) > _CTX_TAIL:
                tail = tail[-_CTX_TAIL:]
            # Then trim by estimated character budget
            total_chars = sum(len(m.get("content", "")) for m in header + tail)
            while total_chars > _MAX_CTX_CHARS and len(tail) > 2:
                removed = tail.pop(0)
                total_chars -= len(removed.get("content", ""))
            return header + tail

        while loop_count < max_loop:
            if self._check_cancelled():
                raise JobCancelledException("Job cancelled by user.")
            loop_count += 1

            # --- robust JSON-fetch with up to MAX_JSON_RETRIES retries ---
            call_json = {"error": "not yet tried"}
            for attempt in range(MAX_JSON_RETRIES):
                try:
                    use_json_mode = (attempt == 0)   # first try with json_mode, then without
                    trimmed_messages = _trim_messages(messages)
                    response = chat_completion(
                        trimmed_messages, task="analysis",
                        json_mode=use_json_mode,
                        timeout=int(os.environ.get("LLM_TIMEOUT", "600"))
                    )
                    call_json = parse_json_safely(response)
                    if "error" not in call_json and "tool" in call_json:
                        break  # good parse — exit retry loop
                    logger.warning(
                        "Tool call JSON parse failed (attempt %d/%d). Raw: %.120s",
                        attempt + 1, MAX_JSON_RETRIES, response
                    )
                except Exception as e:
                    logger.warning("Data Scientist API error (attempt %d/%d): %s", attempt + 1, MAX_JSON_RETRIES, e)
                    response = ""
                    if attempt == MAX_JSON_RETRIES - 1:
                        # Log but don't crash, let the loop handle it as a failure
                        pass
                
                if attempt < MAX_JSON_RETRIES - 1:
                    # Inject a corrective reminder into the conversation without
                    # advancing the main loop counter — the model will see its own
                    # bad output followed by a correction request.
                    messages.append({"role": "assistant", "content": response or "(empty response)"})
                    messages.append({"role": "user", "content": REMINDER_MSG})

            if "error" in call_json or "tool" not in call_json:
                logger.warning(
                    "All %d JSON-parse retries exhausted at step %d. "
                    "Skipping this step and continuing analysis.",
                    MAX_JSON_RETRIES, loop_count
                )
                # Don't abort — inject a nudge and let the loop try again naturally
                messages.append({"role": "assistant", "content": response or "(empty response)"})
                messages.append({"role": "user", "content": REMINDER_MSG})
                continue
            
            thought = call_json.get("thought", "")
            tool = call_json.get("tool", "")
            args = call_json.get("arguments", {})
            
            logger.info(f"Step {loop_count} - Thought: {thought}")
            logger.info(f"Step {loop_count} - Tool: {tool} with args: {args}")
            
            messages.append({"role": "assistant", "content": response})
            
            if tool == "done":
                # BUG-12 fix: if the model calls 'done' without saving any findings,
                # nudge it to save at least one before finishing.
                if not self.state.analysis_results.get("findings"):
                    logger.warning("Agent called 'done' with 0 saved findings — nudging to save at least one.")
                    messages.append({"role": "user", "content": (
                        "You called 'done' but you have not saved any findings yet. "
                        "You MUST call 'save_finding' with at least one key insight before calling 'done'."
                    )})
                    continue
                logger.info("Agent finished tool loop.")
                break
            elif tool == "inspect_column":
                result = inspect_column_tool(args.get("col_name"))
            elif tool == "run_test":
                col_a = args.get("col_a") or args.get("col1")
                col_b = args.get("col_b") or args.get("col2")
                result = run_test_tool(args.get("test_type"), col_a, col_b)
            elif tool == "group_analysis":
                result = group_analysis_tool(args.get("numeric_col"), args.get("group_col"))
            elif tool == "create_chart":
                result = create_chart_tool(args.get("chart_type"), args.get("x"), args.get("y"), args.get("hue"))
            elif tool == "save_finding":
                result = save_finding_tool(args.get("title"), args.get("evidence"), args.get("confidence"))
            else:
                result = f"Error: unknown tool '{tool}'. Available tools: inspect_column, run_test, group_analysis, create_chart, save_finding, done."
            
            logger.info(f"Step {loop_count} - Tool Result: {str(result)[:200]}")
            execution_stdout_log.append(f"Step {loop_count}: Called {tool} with {args} -> {str(result)}")
            messages.append({"role": "user", "content": json.dumps(result, default=str)})

        self.state.last_execution_stdout = "\n".join(execution_stdout_log)
        self.state.last_execution_stderr = ""
        self.state.last_execution_outputs = []
        self.state.methodology_code = "Iterative Tool-calling Execution Loop"

        insight_count = len(self.state.analysis_results.get("findings", []))
        self.publish_progress(
            "data_scientist",
            "completed",
            f"Analysis complete (tool-calling loop). Identified {insight_count} key findings.",
            self.state.regeneration_round
        )


    def _reflector_node(self):
        """Node for Reflector agent checking completeness of findings."""
        self.publish_progress(
            "reflector",
            "running",
            "Reviewing analytical results to see if follow-up investigations are needed...",
            self.state.reflection_iteration
        )
        
        with self._lock:
            draft_results_str = json.dumps(self.state.analysis_results, default=str)
            
        prompt = REFLECTOR_PROMPT.format(
            domain=self.state.domain_brief.get("domain", "Unknown"),
            purpose=self.state.domain_brief.get("datasetPurpose", "Analyze data"),
            draft_results=draft_results_str,
            previous_feedback=self.state.reflection_feedback,
            iteration=self.state.reflection_iteration + 1,
            max_iterations=self.state.max_reflections
        )
        
        messages = [
            {"role": "system", "content": "You are a strict data scientist supervisor. Evaluate if analysis is deep enough. Output JSON only."},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"Calling Reflector Agent (model: {provider_label('review')})")
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
                logger.warning(f"Reflector JSON parsing failed (attempt {attempt + 1}/{max_json_retries}).")
            except Exception as e:
                logger.warning(f"Reflector API error (attempt {attempt + 1}/{max_json_retries}): {e}")
                if attempt == max_json_retries - 1:
                    raise
        
        if "error" in res_json:
            # If all fail, gracefully fallback to no more analysis
            logger.error(f"Reflector failed to return valid JSON. Skipping reflection. Error: {res_json['error']}")
            res_json = {"needs_more_analysis": False, "feedback": "", "follow_up_tasks": []}
        
        # Log reflector action
        self.state.investigation_log.append({
            "agent": "reflector",
            "round": self.state.reflection_iteration,
            "action": "Reviewed analytical depth",
            "result": f"Needs more analysis: {res_json.get('needs_more_analysis')}. Feedback: {res_json.get('feedback')}"
        })
        
        if res_json.get("needs_more_analysis") and self.state.reflection_iteration < self.state.max_reflections:
            self.state.reflection_feedback = res_json.get("feedback", "")
            self.state.follow_up_tasks = res_json.get("follow_up_tasks", [])
            
            # Construct formatted feedback string for the next Data Scientist prompt
            feedback_str = f"Summary feedback from Reflector: {self.state.reflection_feedback}\n"
            if self.state.follow_up_tasks:
                feedback_str += "Please perform the following follow-up tasks in your script:\n"
                for task in self.state.follow_up_tasks:
                    feedback_str += f"- {task}\n"
            
            # Append execution details to feed back to the agent
            feedback_str += "\nExecution Feedback from the previous round:\n"
            feedback_str += f"Stdout:\n```\n{self.state.last_execution_stdout}\n```\n"
            if self.state.last_execution_stderr:
                feedback_str += f"Stderr:\n```\n{self.state.last_execution_stderr}\n```\n"
            
            if self.state.last_execution_outputs:
                feedback_str += "Generated Files in previous execution:\n"
                for outfile in self.state.last_execution_outputs:
                    filename = outfile.get("filename", "unknown")
                    file_type = outfile.get("type", "unknown")
                    purpose = outfile.get("purpose", "unknown")
                    feedback_str += f"- `{filename}` (Type: {file_type}, Purpose: {purpose})\n"
            
            self.state.reflection_feedback_formatted = feedback_str
            
            self.publish_progress(
                "reflector",
                "running",
                f"Reflection: Loop requested. Feedback: {self.state.reflection_feedback[:80]}...",
                self.state.reflection_iteration
            )
        else:
            self.state.reflection_feedback = ""
            self.state.reflection_feedback_formatted = ""
            self.publish_progress(
                "reflector",
                "completed",
                "Analysis depth approved. Moving to visualization generation.",
                self.state.reflection_iteration
            )

    def _prepare_visualization_data(self):
        """Pre-processes free-form analysis results into a standardized chart-ready plan."""
        # Only compute if not already populated in this run/round
        if self.state.visualization_data:
            return

        self.publish_progress(
            "viz_coder",
            "running",
            "Pre-processing analysis results into chart-ready data specifications...",
            self.state.regeneration_round
        )

        prompt = VISUALIZATION_PREPROCESS_PROMPT.format(
            domain=self.state.domain_brief.get("domain", "Unknown"),
            schema=json.dumps(self.state.schema, default=str),
            full_analysis=json.dumps(self.state.analysis_results, default=str)
        )

        messages = [
            {"role": "system", "content": "You are a quantitative data analyst specializing in visualization mapping. Output JSON only."},
            {"role": "user", "content": prompt}
        ]

        logger.info(f"Calling Visualization Preprocessor Agent (model: {provider_label('review')})")
        timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
        
        max_json_retries = 3
        res_json = {"error": "not attempted yet"}
        
        for attempt in range(max_json_retries):
            try:
                use_json_mode = (attempt == 0)
                response = chat_completion(messages, task="review", json_mode=use_json_mode, timeout=timeout_val)
                res_json = parse_json_safely(response)
                if "error" not in res_json and "visualizations" in res_json:
                    break
                logger.warning(f"Visualization Preprocessor JSON parsing failed (attempt {attempt + 1}/{max_json_retries}).")
            except Exception as e:
                logger.warning(f"Visualization Preprocessor API error (attempt {attempt + 1}/{max_json_retries}): {e}")
                if attempt == max_json_retries - 1:
                    raise

        with self._lock:
            self.state.visualization_data = res_json

    def _viz_coder_node(self):
        """Node for Viz Coder writing custom matplotlib/seaborn code."""
        self._prepare_visualization_data()

        self.publish_progress(
            "viz_coder",
            "running",
            "Generating custom visualizations using matplotlib and seaborn...",
            self.state.regeneration_round
        )
        
        prompt = VIZ_CODER_PROMPT.format(
            domain=self.state.domain_brief.get("domain", "Unknown"),
            full_analysis=json.dumps(self.state.analysis_results, default=str),
            visualization_data=json.dumps(self.state.visualization_data, default=str),
            schema=json.dumps(self.state.schema, default=str)
        )
        
        messages = [
            {"role": "system", "content": "You are a visualization expert. Output only Python plotting code blocks."},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"Calling Viz Coder Agent (model: {provider_label('visual')})")
        
        max_gen_attempts = 3
        code = ""
        for gen_attempt in range(max_gen_attempts):
            try:
                response = chat_completion(messages, task="visual", json_mode=False, timeout=int(os.environ.get("LLM_TIMEOUT", "600")))
                code = extract_code_block(response)
                if code:
                    break
                logger.warning(f"Viz Coder returned empty code (attempt {gen_attempt + 1}/{max_gen_attempts}). Retrying...")
            except Exception as e:
                logger.warning(f"Viz Coder generation error (attempt {gen_attempt + 1}/{max_gen_attempts}): {e}")
                if gen_attempt == max_gen_attempts - 1:
                    raise
                    
        if not code:
            with self._lock:
                self.state.error = "Viz Coder agent failed to return Python plotting code after multiple attempts."
            return
            
        logger.info("Executing generated visualization code...")
        exec_res = execute_analysis_code(code, self.state.df, timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "90")))
        
        max_repair_attempts = int(os.environ.get("CODE_REPAIR_MAX_ATTEMPTS", "3"))
        repair_attempt = 0
        
        while not exec_res.success and repair_attempt < max_repair_attempts:
            if self._check_cancelled():
                raise JobCancelledException("Job cancelled by user.")
            repair_attempt += 1
            logger.warning(f"Visualization script failed (attempt {repair_attempt}/{max_repair_attempts}): {exec_res.error_message}. Trying self-repair...")
            repair_prompt = f"""
Your plotting script failed with the following error:
{exec_res.error_message}

Here was your code:
```python
{code}
```

Please fix the code (ensure to load df from input_df.pkl, setup plt backend to 'Agg', save plots as PNGs, and write viz_results.json description).
Return the corrected Python script inside a single ```python ... ``` code block.
"""
            repair_messages = [
                {"role": "system", "content": "You are a plotting fixer. Fix Python errors. Return code only."},
                {"role": "user", "content": repair_prompt}
            ]
            repair_response = chat_completion(repair_messages, task="visual", json_mode=False, timeout=int(os.environ.get("LLM_TIMEOUT", "600")))
            fixed_code = extract_code_block(repair_response)
            if not fixed_code:
                logger.error("Self-repair failed to extract valid python code from response.")
                break
                
            code = fixed_code
            logger.info(f"Executing repaired visualization code (attempt {repair_attempt + 1})...")
            exec_res = execute_analysis_code(code, self.state.df, timeout_seconds=int(os.environ.get("CODE_EXEC_TIMEOUT", "90")))
            
        if not exec_res.success:
            logger.error(f"Viz code failed after {max_repair_attempts} repair attempts: {exec_res.error_message}. Proceeding with default chart fallback.")
            # We won't crash the whole run, we'll let it proceed with no charts or fallbacks later
            with self._lock:
                self.state.chart_images = []
                self.state.viz_code = code
            self.publish_progress(
                "viz_coder",
                "completed",
                f"Visualization code failed to execute after {max_repair_attempts} self-repair attempts. Falling back to default plots.",
                self.state.regeneration_round
            )
            return

        # Collect all image outputs declared by the agent
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
        # Fallback to legacy charts list if agent_outputs had no images
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

        # Record all files in the audit trail
        with self._lock:
            for output in exec_res.agent_outputs:
                self.state.agent_files.append({
                    "agent": "viz_coder",
                    "round": self.state.regeneration_round,
                    "filename": output.get("filename"),
                    "type": output.get("type"),
                    "purpose": output.get("purpose"),
                })
            
            self.state.chart_images = charts_list
            self.state.viz_code = code
        
        self.publish_progress(
            "viz_coder",
            "completed",
            f"Successfully generated {len(charts_list)} custom charts.",
            self.state.regeneration_round
        )

    def _report_writer_node(self):
        """Node for Report Writer combining findings and charts into the final JSON."""
        self.publish_progress(
            "report_writer",
            "running",
            "Structuring and writing report narrative, executive summary and recommendations...",
            self.state.regeneration_round
        )
        
        # Describe the charts created to pass to report writer
        with self._lock:
            charts_desc = [
                {"title": c["title"], "filename": c["filename"], "interpretation": c["interpretation"]}
                for c in self.state.chart_images
            ]
            full_analysis_str = json.dumps(self.state.analysis_results, default=str)
        
        numeric_sum = json.dumps(self.state.stats.get("numeric_summary", {}), default=str)
        grouped_sum = json.dumps(self.state.stats.get("grouped_summary", {}), default=str)
        missing_vals = json.dumps(self.state.stats.get("missing_values", {}), default=str)
        stats_summary = f"Missing values: {missing_vals}\nNumeric Summary: {numeric_sum}\nGrouped Summary: {grouped_sum}"

        prompt = REPORT_WRITER_PROMPT.format(
            domain_brief=json.dumps(self.state.domain_brief, default=str),
            schema=json.dumps(self.state.schema, default=str),
            sample_rows=json.dumps(self.state.sample_rows, default=str),
            stats_summary=stats_summary,
            full_analysis=full_analysis_str,
            charts=json.dumps(charts_desc, default=str)
        )
        
        messages = [
            {"role": "system", "content": "You are a professional business writer. Generate JSON report conforming to the requested schema. Output JSON only."},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"Calling Report Writer (model: {provider_label('report')})")
        timeout_val = int(os.environ.get("LLM_TIMEOUT", "600"))
        
        max_json_retries = 3
        report_json = {"error": "not attempted yet"}
        
        for attempt in range(max_json_retries):
            try:
                use_json_mode = (attempt == 0)
                response = chat_completion(messages, task="report", json_mode=use_json_mode, timeout=timeout_val)
                report_json = parse_json_safely(response)
                if "error" not in report_json and ("keyFindings" in report_json or "executiveSummary" in report_json):
                    break
                logger.warning(f"Report Writer JSON parsing failed (attempt {attempt + 1}/{max_json_retries}).")
            except Exception as e:
                logger.warning(f"Report Writer API error (attempt {attempt + 1}/{max_json_retries}): {e}")
                if attempt == max_json_retries - 1:
                    raise
                    
        if "error" in report_json:
            with self._lock:
                self.state.error = f"Report Writer failed to generate valid JSON: {report_json['error']}"
            return
            
        with self._lock:
            self.state.report = report_json
        
        self.publish_progress(
            "report_writer",
            "completed",
            "Draft report prepared.",
            self.state.regeneration_round
        )

    def _narrative_stitcher_node(self):
        """Node for Narrative Stitcher agent rewriting the executive summary."""
        run_stitcher = os.environ.get("LLM_NARRATIVE_STITCHER", "true").strip().lower() != "false"
        if not run_stitcher:
            return

        self.publish_progress(
            "report_writer",
            "running",
            "Narrative Stitcher: Crafting cohesive human-like Executive Summary...",
            self.state.regeneration_round
        )

        with self._lock:
            report = self.state.report.copy() if isinstance(self.state.report, dict) else self.state.report
            
        findings_json = json.dumps(report.get("keyFindings", []), default=str)
        anomalies_json = json.dumps(report.get("anomalies", []), default=str)
        recs_json = json.dumps(report.get("recommendations", []), default=str)
        draft_summary = report.get("executiveSummary", "")

        prompt = NARRATIVE_STITCHER_PROMPT.format(
            domain=report.get("domain", "Unknown"),
            key_findings=findings_json,
            anomalies=anomalies_json,
            recommendations=recs_json,
            draft_summary=draft_summary
        )

        messages = [
            {"role": "system", "content": "You are a professional business writer and executive editor."},
            {"role": "user", "content": prompt}
        ]

        logger.info(f"Calling Narrative Stitcher Agent (model: {provider_label('report')})")
        
        max_gen_attempts = 3
        response = ""
        for gen_attempt in range(max_gen_attempts):
            try:
                response = chat_completion(messages, task="report", json_mode=False, timeout=int(os.environ.get("LLM_TIMEOUT", "600")))
                if response:
                    break
                logger.warning(f"Narrative Stitcher returned empty string (attempt {gen_attempt + 1}/{max_gen_attempts}).")
            except Exception as e:
                logger.warning(f"Narrative Stitcher generation error (attempt {gen_attempt + 1}/{max_gen_attempts}): {e}")
                if gen_attempt == max_gen_attempts - 1:
                    raise
        
        if response:
            clean_summary = response.strip()
            if clean_summary.startswith("```"):
                lines = clean_summary.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_summary = "\n".join(lines).strip()
            with self._lock:
                self.state.report["executiveSummary"] = clean_summary

        self.publish_progress(
            "report_writer",
            "completed",
            "Executive summary polished by Narrative Stitcher.",
            self.state.regeneration_round
        )

    def _validate_report_numbers(self, report: dict) -> List[Dict[str, Any]]:
        """Automated check to compare numbers cited in findings against the actual DataFrame stats."""
        warnings = []
        df = self.state.df
        if df is None or df.empty:
            return warnings
            
        try:
            findings = report.get("keyFindings", [])
            numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
            
            for finding in findings:
                title = finding.get("title", "Unknown")
                detail = finding.get("detail", "")
                text_to_check = (title + " " + detail).lower()
                
                # Check for column references in the finding text using word boundary check
                referenced_cols = []
                for col in numeric_cols:
                    col_pat = re.escape(col.lower()).replace(r'\_', r'[_\s]+')
                    pattern = rf"\b{col_pat}\b"
                    if re.search(pattern, text_to_check):
                        referenced_cols.append(col)
                
                if not referenced_cols:
                    continue
                    
                # Clean up commas in numbers (e.g. 60,000 -> 60000)
                clean_text = text_to_check.replace(",", "")
                # Find all numbers (possibly followed by a percent sign)
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
                        # Compute statistics for comparison
                        stats_map = {}
                        
                        # Mean / Average
                        if any(w in text_to_check for w in ["mean", "average", "avg"]):
                            stats_map["mean"] = (df[col].mean(), "average")
                        
                        # Min
                        if any(w in text_to_check for w in ["min", "minimum", "lowest"]):
                            stats_map["min"] = (df[col].min(), "minimum")
                            
                        # Max
                        if any(w in text_to_check for w in ["max", "maximum", "highest", "peak"]):
                            stats_map["max"] = (df[col].max(), "maximum")
                            
                        # Sum
                        if any(w in text_to_check for w in ["total", "sum"]):
                            stats_map["sum"] = (df[col].sum(), "total")
                            
                        # If no specific keyword is found, default to checking mean just in case
                        if not stats_map:
                            stats_map["mean"] = (df[col].mean(), "mean")
                            
                        for stat_name, (actual_val, label) in stats_map.items():
                            if pd.isna(actual_val):
                                continue
                            
                            # Find if any cited number is close to actual_val
                            matched_any = False
                            for val in numbers:
                                # Calculate relative deviation
                                if actual_val == 0:
                                    deviation = abs(val)
                                else:
                                    deviation = abs(actual_val - val) / max(abs(actual_val), 1e-9)
                                    
                                if deviation <= 0.20:
                                    matched_any = True
                                    break
                                    
                            if not matched_any:
                                warnings.append({
                                    "finding": title,
                                    "column": col,
                                    "metric": label,
                                    "actual_value": round(float(actual_val), 4),
                                    "deviation_pct": round(float(min(abs(actual_val - v) / max(abs(actual_val), 1e-9) for v in numbers) * 100), 1) if numbers else 100.0,
                                    "message": f"Finding '{title}' refers to the {label} of '{col}' (actual: {float(actual_val):.2f}), but no close number (within 20% deviation) was found in the text: '{detail}'"
                                })
                                
                    except Exception as col_err:
                        logger.warning(f"Error validating column {col} in finding '{title}': {col_err}")
                        continue
        except Exception as e:
            logger.warning(f"Automated numeric validation failed: {e}")
            
        return warnings

    def _auditor_node(self):
        """Node for Quality Auditor verifying accuracy and formatting."""
        self.publish_progress(
            "auditor",
            "running",
            "Auditing report narrative against code execution evidence and dataset statistics...",
            self.state.regeneration_round
        )
        
        with self._lock:
            charts_desc = [
                {"title": c["title"], "interpretation": c["interpretation"]}
                for c in self.state.chart_images
            ]
            report_copy = self.state.report.copy() if isinstance(self.state.report, dict) else self.state.report
            analysis_copy = self.state.analysis_results.copy() if isinstance(self.state.analysis_results, dict) else self.state.analysis_results
        
        # Run automated numeric validation
        validation_warnings = self._validate_report_numbers(report_copy)
        
        # Format the dataset stats
        numeric_sum = json.dumps(self.state.stats.get("numeric_summary", {}), default=str)
        grouped_sum = json.dumps(self.state.stats.get("grouped_summary", {}), default=str)
        missing_vals = json.dumps(self.state.stats.get("missing_values", {}), default=str)
        dataset_stats = f"Missing values: {missing_vals}\nNumeric Summary: {numeric_sum}\nGrouped Summary: {grouped_sum}"
        
        prompt = AUDITOR_PROMPT.format(
            report=json.dumps(report_copy, default=str),
            full_analysis=json.dumps(analysis_copy, default=str),
            charts=json.dumps(charts_desc, default=str),
            dataset_stats=dataset_stats,
            validation_warnings=json.dumps(validation_warnings, default=str)
        )
        
        messages = [
            {"role": "system", "content": "You are a strict data QA auditor. Validate the report and output audit results in JSON format only."},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"Calling Quality Auditor (model: {provider_label('review')})")
        timeout_val = int(os.environ.get("LLM_TIMEOUT", "300"))
        
        max_json_retries = 3
        audit_json = {"error": "not attempted yet"}
        
        for attempt in range(max_json_retries):
            try:
                use_json_mode = (attempt == 0)
                response = chat_completion(messages, task="review", json_mode=use_json_mode, timeout=timeout_val)
                audit_json = parse_json_safely(response)
                if "error" not in audit_json and "score" in audit_json:
                    break
                logger.warning(f"Auditor JSON parsing failed (attempt {attempt + 1}/{max_json_retries}).")
            except Exception as e:
                logger.warning(f"Auditor API error (attempt {attempt + 1}/{max_json_retries}): {e}")
                if attempt == max_json_retries - 1:
                    raise
                    
        if "error" in audit_json:
            # Fallback if auditor completely fails
            logger.error(f"Auditor failed to return valid JSON. Error: {audit_json['error']}")
            audit_json = {"score": 85, "approved": False, "summary": "Audit failed to parse.", "issues": [{"message": "Auditor failed to parse JSON"}], "retryTargets": []}
        
        # Normalize audit response
        score = audit_json.get("score", 0)
        approved = audit_json.get("approved", False) and score >= 88
        
        # Inject automated validation warnings into audit issues and force retry if severe
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
            
        if has_warnings and self.state.regeneration_round < self.state.max_regeneration_rounds:
            approved = False
            if score >= 88:
                score = 87 # Cap score to force retry
                
        retry_targets = audit_json.get("retryTargets", []) if not approved else []
        if has_warnings and "report" not in retry_targets:
            retry_targets.append("report")
            
        self.state.audit = {
            "approved": approved,
            "score": score,
            "sectionScores": audit_json.get("sectionScores", {}),
            "summary": audit_json.get("summary", "Audit finished."),
            "issues": issues,
            "retryTargets": retry_targets
        }
        
        status_label = "completed" if approved else "failed"
        self.publish_progress(
            "auditor",
            status_label,
            f"Audit finished. Score: {score}/100. Approved: {approved}. Summary: {self.state.audit['summary'][:100]}",
            self.state.regeneration_round,
            score=score
        )

    def _run_visuals_and_report_sequentially(self):
        """Runs the visualization coder first, then the report writer."""
        logger.info("Executing Visual Coder first, then Report Writer sequentially...")
        self._viz_coder_node()
        if self.state.error:
            return
        
        self._report_writer_node()
