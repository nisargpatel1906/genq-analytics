import logging
import pandas as pd
import numpy as np
import json
import os
import re
import time
from typing import Callable
from dotenv import load_dotenv
from services.llm import chat_completion, provider_label
from app.utils import coerce_numeric_series, parse_json_safely

logger = logging.getLogger("genq_api.analyzer")

load_dotenv()

# Legacy prompts removed. Only DOMAIN_PROMPT is retained for domain classification.

DOMAIN_PROMPT = """
You are a data domain classifier for GenQ Analytics.

Infer what this dataset most likely represents from the schema, column names, value ranges,
missingness, and sample rows. Do not overclaim. If the domain is unclear, say so.

CRITICAL: You must also determine the dataset structure and recommend the best analysis approach.

Output ONLY this JSON schema:
{
  "domain": "string",
  "domainConfidence": 0,
  "datasetPurpose": "string",
  "datasetType": "time-series|cross-sectional|panel|survey|transactional|geospatial|text|categorical|mixed",
  "importantColumns": ["string"],
  "analysisApproach": "string",
  "keyCharacteristics": {
    "hasTimeColumn": false,
    "hasGeospatial": false,
    "highCardinalityCols": ["string"],
    "isSparse": false,
    "likelyTargetCols": ["string"]
  },
  "analysisPlan": ["string"]
}
"""

# Legacy multi-agent sequential workflow prompts removed.

ProgressCallback = Callable[[dict], None]

def map_schema(df: pd.DataFrame) -> dict:
    return {col: str(dtype) for col, dtype in df.dtypes.items()}

def normalize_dataframe_types(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col]):
            continue

        lower_col = col.lower()
        looks_like_identifier = any(token in lower_col for token in ["id", "code", "phone", "zip", "pin"])
        numeric = coerce_numeric_series(df[col])
        non_null_ratio = numeric.notna().mean()
        unique_ratio = numeric.nunique(dropna=True) / max(len(numeric.dropna()), 1)

        if non_null_ratio >= 0.65 and (unique_ratio < 0.98 or not looks_like_identifier):
            df[col] = numeric
            continue

        if any(token in lower_col for token in ["date", "time", "created", "updated"]):
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().mean() >= 0.65:
                df[col] = parsed

    return df

def _sample_rows(df: pd.DataFrame, limit: int = 12) -> list[dict]:
    sample = df.head(limit).replace({np.nan: None, np.inf: None, -np.inf: None})
    for col in sample.select_dtypes(include=['datetime64']).columns:
        sample[col] = sample[col].astype(str)
    return sample.to_dict("records")


# ── Smart Sampling ────────────────────────────────────────────────────────────

def _stratified_time_sample(df: pd.DataFrame, time_col: str, max_rows: int) -> pd.DataFrame:
    """Keep the most recent 70% + periodic samples from history to preserve trend."""
    try:
        df_sorted = df.sort_values(time_col).reset_index(drop=True)
        n = len(df_sorted)
        recent_count = int(max_rows * 0.70)
        periodic_count = max_rows - recent_count

        # Most recent rows
        recent_df = df_sorted.iloc[max(0, n - recent_count):]

        # Periodic samples from the older portion
        older_df = df_sorted.iloc[:max(0, n - recent_count)]
        if len(older_df) > 0 and periodic_count > 0:
            step = max(1, len(older_df) // periodic_count)
            periodic_df = older_df.iloc[::step].head(periodic_count)
            return pd.concat([periodic_df, recent_df], ignore_index=True)
        return recent_df
    except Exception:
        return df.sample(min(max_rows, len(df)), random_state=42)


def _stratified_target_sample(df: pd.DataFrame, target_col: str, max_rows: int) -> pd.DataFrame:
    """Proportional stratified sample preserving class distribution."""
    try:
        groups = df.groupby(target_col, observed=True)
        fracs = {}
        for name, group in groups:
            fracs[name] = min(1.0, max_rows / len(df))

        sampled = [
            group.sample(frac=fracs[name], random_state=42)
            for name, group in groups
        ]
        result = pd.concat(sampled, ignore_index=True)
        # Trim if over budget
        if len(result) > max_rows:
            result = result.sample(max_rows, random_state=42)
        return result
    except Exception:
        return df.sample(min(max_rows, len(df)), random_state=42)


def _create_analysis_sample(df: pd.DataFrame, max_rows: int | None = None) -> tuple[pd.DataFrame, str]:
    """
    Returns (sample_df, sampling_method) where sampling_method is one of:
    'full' | 'time_series' | 'stratified' | 'random'

    Sampling strategies (applied only when len(df) > max_rows):
    - time-series: recent 70% + periodic samples from history
    - classification: stratified by target column
    - otherwise: reproducible random sample (random_state=42)
    """
    if max_rows is None:
        try:
            max_rows = int(os.environ.get("SAMPLE_MAX_ROWS", "10000"))
        except ValueError:
            max_rows = 10_000

    if len(df) <= max_rows:
        return df, "full"

    # Detect time column
    time_cols = [
        c for c in df.columns
        if any(token in c.lower() for token in ["date", "time", "created", "updated", "timestamp"])
        and pd.api.types.is_datetime64_any_dtype(df[c])
    ]
    if time_cols:
        logger.info("Large dataset (%d rows): using time-series sampling on '%s'", len(df), time_cols[0])
        return _stratified_time_sample(df, time_cols[0], max_rows), "time_series"

    # Detect target / classification column
    target_cols = [
        c for c in df.columns
        if df[c].nunique() <= 10 and df[c].nunique() > 1
        and (pd.api.types.is_object_dtype(df[c]) or df[c].nunique() <= 5)
    ]
    if target_cols:
        logger.info("Large dataset (%d rows): using stratified sampling on '%s'", len(df), target_cols[0])
        return _stratified_target_sample(df, target_cols[0], max_rows), "stratified"

    logger.info("Large dataset (%d rows): using random sampling (seed=42)", len(df))
    return df.sample(max_rows, random_state=42), "random"


# ── Sparse Correlation Matrix ─────────────────────────────────────────────────

def _compute_sparse_correlations(
    df: pd.DataFrame,
    max_cols: int = 20,
    threshold: float = 0.3,
) -> dict:
    """
    Computes a trimmed correlation matrix:
    - Selects the top `max_cols` most variable numeric columns
    - Keeps only pairs where |r| >= threshold
    - Returns a dict of {col: {col: r}} with NaN/Inf replaced by None
    """
    numeric = df.select_dtypes(include=[np.number])
    if numeric.shape[1] < 2:
        result = numeric.corr().replace({np.nan: None, np.inf: None, -np.inf: None})
        return result.to_dict()

    # Top most variable columns
    variances = numeric.var().sort_values(ascending=False)
    top_cols = variances.head(max_cols).index.tolist()

    corr = numeric[top_cols].corr()
    # Mask weak correlations (keep |r| >= threshold but exclude self-correlations)
    mask = corr.abs().where(corr.abs() >= threshold, other=np.nan)
    np.fill_diagonal(mask.values, np.nan)  # exclude diagonal (self-correlation = 1)

    # Drop all-NaN rows and columns
    sparse = corr.where(mask.notna()).dropna(how="all", axis=0).dropna(how="all", axis=1)
    sparse = sparse.replace({np.nan: None, np.inf: None, -np.inf: None})
    return sparse.to_dict()


# ── Data Quality Score ────────────────────────────────────────────────────────

def _compute_data_quality_score(df: pd.DataFrame, stats: dict) -> dict:
    """
    Returns a data quality score (0–100) broken down by dimension:
    - completeness (40 pts): mean non-null ratio across all columns
    - consistency (35 pts): penalise columns with >5% statistical outliers (Z>3)
    - structure (25 pts): reward well-typed, non-trivial categorical columns
    - notable_issues: list of human-readable strings outlining problems
    """
    n_cols = len(df.columns)
    if n_cols == 0:
        return {"score": 0, "completeness": 0, "consistency": 0, "structure": 0, "grade": "F", "notable_issues": []}

    # Completeness
    missing_vals = stats.get("missing_values", {})
    total_cells = len(df) * n_cols
    total_missing = sum(missing_vals.values()) if missing_vals else 0
    completeness_ratio = 1 - (total_missing / max(total_cells, 1))
    completeness_score = round(completeness_ratio * 40, 1)

    # Consistency — penalise heavy outlier columns
    anomalies = stats.get("statistical_anomalies", [])
    penalty = 0
    for a in anomalies:
        outlier_rate = a.get("outlier_count", 0) / max(len(df), 1)
        if outlier_rate > 0.05:
            penalty += 5
    consistency_score = max(0, round(35 - min(penalty, 35), 1))

    # Structure — categorical columns with reasonable cardinality
    cat_cols = df.select_dtypes(include=["object", "category"]).columns
    well_structured = sum(
        1 for c in cat_cols
        if 2 <= df[c].nunique() <= 50
    )
    structure_ratio = well_structured / max(n_cols, 1)
    structure_score = round(structure_ratio * 25, 1)

    total = round(completeness_score + consistency_score + structure_score, 1)
    if total >= 90: grade = "A"
    elif total >= 80: grade = "B"
    elif total >= 65: grade = "C"
    elif total >= 50: grade = "D"
    else: grade = "F"

    # Compute notable issues
    notable_issues = []
    for col, missing in missing_vals.items():
        ratio = missing / len(df)
        if ratio > 0.1:
            notable_issues.append(f"Column '{col}' is missing {ratio*100:.1f}% of its values, which may skew analysis.")
    for a in anomalies:
        outlier_rate = a.get("outlier_count", 0) / len(df)
        if outlier_rate > 0.05:
            notable_issues.append(f"Column '{a['column']}' has a high rate of Z-score outliers ({outlier_rate*100:.1f}%).")
    for col in cat_cols:
        cardinality = df[col].nunique()
        if cardinality == 1:
            notable_issues.append(f"Categorical column '{col}' has only 1 unique value and provides no analytical variance.")
        elif cardinality > 100:
            notable_issues.append(f"Categorical column '{col}' has very high cardinality ({cardinality} unique values) which may complicate segmentation.")

    return {
        "score": total,
        "completeness": completeness_score,
        "consistency": consistency_score,
        "structure": structure_score,
        "grade": grade,
        "notable_issues": notable_issues,
    }





# ── Full-Data Validation ──────────────────────────────────────────────────────

def _validate_findings_on_full_data(
    df_full: pd.DataFrame,
    analytics: dict,
    domain_brief: dict,
) -> list[dict]:
    """
    Spot-checks key analytic findings on the full dataset.
    Returns a list of validation warnings for findings that deviate >20%
    from the sample-based values.

    Only runs when LLM_VALIDATE_ON_FULL_DATA=true (default).
    """
    warnings = []
    try:
        findings = analytics.get("findings", []) or analytics.get("keyFindings", [])
        numeric_cols = df_full.select_dtypes(include=[np.number]).columns.tolist()
        cat_cols = df_full.select_dtypes(include=["object", "category"]).columns.tolist()

        for finding in findings[:6]:  # Check first 6 findings max
            evidence = str(finding.get("evidence", "") or finding.get("detail", ""))

            # Look for column references in the evidence text
            referenced_cols = [
                col for col in numeric_cols
                if col.lower() in evidence.lower()
            ]

            for col in referenced_cols[:2]:  # Check up to 2 columns per finding
                try:
                    # Try to extract a number from the evidence that matches this column
                    numbers = re.findall(r'[-+]?\d+(?:\.\d+)?', evidence)
                    if not numbers:
                        continue

                    # Get full-data mean for this column
                    full_mean = df_full[col].mean()
                    if pd.isna(full_mean):
                        continue

                    # Compare against the first plausible number in evidence
                    for num_str in numbers:
                        sample_val = float(num_str)
                        if sample_val == 0:
                            continue
                        deviation = abs(full_mean - sample_val) / max(abs(sample_val), 1e-9)
                        if deviation > 0.20:
                            warnings.append({
                                "finding": finding.get("title", "Unknown"),
                                "column": col,
                                "sample_value": sample_val,
                                "full_data_value": round(full_mean, 4),
                                "deviation_pct": round(deviation * 100, 1),
                                "message": (
                                    f"Column '{col}' full-data mean ({full_mean:.4f}) deviates "
                                    f"{deviation*100:.1f}% from sample-based value ({sample_val}) "
                                    "in this finding. Interpret with caution."
                                ),
                            })
                            break
                except Exception:
                    continue
    except Exception as e:
        logger.warning("Full-data validation failed (non-critical): %s", e)

    return warnings



def _build_payload(df: pd.DataFrame, stats: dict) -> dict:
    return {
        "schema": map_schema(df),
        "statistics": stats,
        "sampleRows": _sample_rows(df),
        # Sampling metadata for agent context
        "samplingInfo": {
            "sampleSize": stats.get("sample_size", len(df)),
            "fullRowCount": stats.get("full_row_count", len(df)),
            "samplingMethod": stats.get("sampling_method", "full"),
            "wasDownsampled": stats.get("sampling_method", "full") != "full",
        },
    }

def _detect_domain(payload: dict) -> dict:
    stats = payload.get("statistics", {})
    trimmed = {
        "schema": payload.get("schema", {}),
        "sampleRows": payload.get("sampleRows", []),
        "shape": stats.get("shape", {}),
        "missing_values": stats.get("missing_values", {}),
        "sampling": stats.get("sampling", {}),
    }
    messages = [
        {"role": "system", "content": DOMAIN_PROMPT},
        {"role": "user", "content": json.dumps(trimmed, default=str)},
    ]
    logger.info("Starting domain detection using %s", provider_label("domain"))
    timeout = int(os.environ.get("LLM_TIMEOUT", "600"))
    content = chat_completion(messages, task="domain", json_mode=True, timeout=timeout)
    res = parse_json_safely(content or "{}")
    if "error" in res:
        logger.warning("Domain detection JSON mode failed. Retrying with json_mode=False...")
        content = chat_completion(messages, task="domain", json_mode=False, timeout=timeout)
        res = parse_json_safely(content or "{}")
    return res

# Legacy single-agent and multi-agent pipeline helper functions removed.


def analyze_dataframe(df: pd.DataFrame, progress_callback: ProgressCallback | None = None, job_id: str | None = None) -> dict:
    """
    Main entry point. Orchestrates the full agentic pipeline with:
    - Smart sampling for large datasets (>10K rows)
    - Per-agent payload trimming to manage token budgets
    - Optional full-data validation spot-check
    - Automatic quality auditing with targeted regeneration (up to 3 rounds)
    """
    full_row_count = len(df)
    df = normalize_dataframe_types(df)

    # ── Smart Sampling ───────────────────────────────────────────────────
    df_sample, sampling_method = _create_analysis_sample(df)
    was_sampled = len(df_sample) < full_row_count
    if was_sampled:
        logger.info(
            "Sampling: %d/%d rows selected (%s). Full-data validation will run after analysis.",
            len(df_sample), full_row_count, sampling_method,
        )

    stats = extract_statistics(df_sample, full_row_count=full_row_count, sampling_method=sampling_method)
    payload = _build_payload(df_sample, stats)

    try:
        max_regeneration_rounds = max(0, int(os.environ.get("LLM_MAX_REGENERATION_ROUNDS", "3")))
    except ValueError:
        max_regeneration_rounds = 3
    stage_state: dict[str, dict] = {}

    def publish(stage: str, status: str, detail: str, round_number: int = 0, score: int | None = None):
        update = {
            "id": stage,
            "name": {
                "profile": "Data Profiler",
                "sampling": "Smart Sampler",
                "validation": "Data Validator",
            }.get(stage, stage.title()),
            "status": status,
            "detail": detail,
            "round": round_number,
        }
        if score is not None:
            update["score"] = score
        stage_state[stage] = update
        if progress_callback:
            progress_callback({"currentAgent": stage, "agents": list(stage_state.values()), **update})

    try:
        # ── Stage 1: Profile ───────────────────────────────────────────────
        quality = stats.get("data_quality", {})
        publish(
            "profile", "running",
            f"Profiling schema and data quality (Grade: {quality.get('grade', '?')}, Score: {quality.get('score', '?')}/100)."
        )
        domain_brief = _detect_domain(payload)
        if "error" in domain_brief:
            logger.warning("Domain detection failed; continuing with unknown domain: %s", domain_brief.get("error"))
            domain_brief = {
                "domain": "Unknown",
                "domainConfidence": 0,
                "datasetPurpose": "Domain detection failed; infer conservatively from statistics.",
                "importantColumns": list(payload["schema"].keys())[:8],
                "analysisPlan": ["Analyze schema, summary statistics, anomalies, and grouped patterns."],
            }
        sample_note = f" (analysing {len(df_sample):,}/{full_row_count:,} rows via {sampling_method} sampling)" if was_sampled else ""
        publish("profile", "completed", f"Profiled {full_row_count:,} rows and {len(df.columns)} columns.{sample_note}")

        # Run the new AgentGraph with code-generation workflow
        logger.info("Starting code-generating AgentGraph pipeline...")
        from services.agent_graph import AnalysisState, AgentGraph
        import base64
        
        try:
            max_reflections = int(os.environ.get("AGENT_MAX_REFLECTIONS", "2"))
        except ValueError:
            max_reflections = 2
            
        state = AnalysisState(
            df=df_sample,
            schema=payload["schema"],
            sample_rows=payload["sampleRows"],
            domain_brief=domain_brief,
            stats=stats,
            progress_callback=progress_callback,
            max_reflections=max_reflections,
            max_regeneration_rounds=max_regeneration_rounds,
            job_id=job_id,
        )
        
        # Copy current profile stage progress into the state
        state.stages_progress = stage_state.copy()
        
        graph = AgentGraph(state)
        report = graph.run()
        
        if report and "error" not in report:
            logger.info("AgentGraph pipeline executed successfully!")
            
            # Run full-data validation if requested
            validation_warnings: list[dict] = []
            validate_enabled = os.environ.get("LLM_VALIDATE_ON_FULL_DATA", "true").strip().lower() != "false"
            if was_sampled and validate_enabled:
                t_val_start = time.perf_counter()
                publish("validation", "running", "Spot-checking findings against the full dataset.")
                validation_warnings = _validate_findings_on_full_data(df, report, domain_brief)
                t_val = time.perf_counter() - t_val_start
                warn_count = len(validation_warnings)
                publish(
                    "validation", "completed",
                    f"Validated on {full_row_count:,} rows in {t_val:.1f}s. "
                    + (f"{warn_count} finding(s) flagged for caution." if warn_count else "All findings consistent with full data.")
                )
                if validation_warnings:
                    for w in validation_warnings:
                        logger.warning("Validation warning: %s", w["message"])
            
            # Package final report with metadata and charts
            # Convert binary charts to base64 for report DB storage
            # NOTE: charts from the Data Scientist's create_chart_tool have a "filename"
            # but no "data" key — skip those gracefully (they were saved as PNG files).
            chart_images_b64 = []
            for c in state.chart_images:
                raw = c.get("data")
                if raw is None:
                    # Try to read the PNG from the working directory if it was saved there
                    fname = c.get("filename", "")
                    if fname and os.path.exists(fname):
                        try:
                            with open(fname, "rb") as _f:
                                raw = _f.read()
                        except Exception as _e:
                            logger.warning("Could not read chart file %s: %s", fname, _e)
                if raw is None:
                    logger.warning("Chart entry has no binary data and file not found: %s", c.get("filename", "?"))
                    continue
                try:
                    b64_str = base64.b64encode(raw).decode("utf-8")
                    chart_images_b64.append({
                        "title": c.get("title", c.get("filename", "Chart")),
                        "interpretation": c.get("interpretation", ""),
                        "image_b64": b64_str,
                        "image": f"data:image/png;base64,{b64_str}"
                    })
                except Exception as _enc_err:
                    logger.warning("Failed to base64-encode chart %s: %s", c.get("filename"), _enc_err)
            
            report["_meta"] = {
                "llmMode": "agentic_code_gen",
                "domainModel": provider_label("domain"),
                "analysisModel": provider_label("analysis"),
                "visualModel": provider_label("visual"),
                "reportModel": provider_label("report"),
                "reviewModel": provider_label("review"),
                "domainConfidence": domain_brief.get("domainConfidence"),
                "finalGeneration": state.regeneration_round >= state.max_regeneration_rounds,
                "chart_images": chart_images_b64,
                "sampling": {
                    "method": sampling_method,
                    "sampleSize": len(df_sample),
                    "fullRowCount": full_row_count,
                    "wasDownsampled": was_sampled,
                    "validationWarnings": validation_warnings,
                },
                "dataQuality": stats.get("data_quality", {}),
                "agentWorkflow": {
                    "approved": state.audit.get("approved", True),
                    "auditScore": state.audit.get("score", 0),
                    "auditSummary": state.audit.get("summary", "Report generated."),
                    "sectionScores": state.audit.get("sectionScores", {}),
                    "issues": state.audit.get("issues", []),
                    "regenerationRounds": state.regeneration_round,
                    "maxRegenerationRounds": state.max_regeneration_rounds,
                    "stages": list(state.stages_progress.values()),
                },
            }
            return report
        else:
            err_msg = report.get("error") if report else "Unknown error"
            raise RuntimeError(f"AgentGraph pipeline failed: {err_msg}")
            
    except Exception as e:
        logger.error(f"LLM analysis exception: {e}")
        return {"error": str(e)}

def extract_statistics(df: pd.DataFrame, full_row_count: int | None = None, sampling_method: str = "full") -> dict:
    """
    Progressive statistics pipeline:
    - shape, missing_values: computed on full df passed in (already the sample from analyze_dataframe)
    - numeric_summary, correlations: sparse, computed on sample
    - statistical_anomalies: Z-score > 3, computed on sample
    - grouped_summary: categorical group means, computed on sample
    - data_quality: deterministic quality score (0-100)
    - sampling metadata: attached for transparency
    - enriched features: skewness, kurtosis, value_distributions, text_columns, potential_targets, time_features, top_correlations
    """
    stats: dict = {}
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    cat_cols = df.select_dtypes(include=["object", "category"]).columns

    # ── Shape (reported as FULL dataset shape for transparency) ─────────
    stats["shape"] = {
        "rows": full_row_count if full_row_count is not None else len(df),
        "columns": len(df.columns),
    }
    stats["missing_values"] = df.isnull().sum().to_dict()

    # ── Numeric summary ─────────────────────────────────────────────────
    if not numeric_cols.empty:
        desc = df[numeric_cols].describe().replace({np.nan: None, np.inf: None, -np.inf: None}).to_dict()
        # Add skewness and kurtosis
        for col in numeric_cols:
            if col in desc:
                desc[col]["skewness"] = float(df[col].skew()) if pd.notna(df[col].skew()) else None
                desc[col]["kurtosis"] = float(df[col].kurt()) if pd.notna(df[col].kurt()) else None
        stats["numeric_summary"] = desc
        # Sparse correlation instead of full matrix
        stats["correlations"] = _compute_sparse_correlations(df)
    else:
        stats["numeric_summary"] = {}
        stats["correlations"] = {}

    # ── Top Correlations ────────────────────────────────────────────────
    top_corr = []
    seen = set()
    for col_a, col_vals in stats.get("correlations", {}).items():
        for col_b, r in (col_vals or {}).items():
            if r is not None and col_a != col_b:
                key = tuple(sorted([col_a, col_b]))
                if key not in seen:
                    seen.add(key)
                    strength = "strong" if abs(r) >= 0.7 else "moderate" if abs(r) >= 0.4 else "weak"
                    direction = "positive" if r > 0 else "negative"
                    top_corr.append({
                        "col_a": col_a,
                        "col_b": col_b,
                        "r": round(r, 4),
                        "interpretation": f"{strength} {direction} correlation"
                    })
    top_corr.sort(key=lambda x: abs(x["r"]), reverse=True)
    stats["top_correlations"] = top_corr[:10]

    # ── Outlier detection (Z-score > 3 sigma) ────────────────────────────
    anomalies = []
    for col in numeric_cols:
        mean = df[col].mean()
        std = df[col].std()
        if pd.isna(mean) or pd.isna(std) or std == 0:
            continue
        z_scores = np.abs((df[col] - mean) / std)
        outliers = df[z_scores > 3]
        if not outliers.empty:
            anomalies.append({
                "column": col,
                "outlier_count": len(outliers),
                "max_deviation_value": float(
                    outliers[col].max() if outliers[col].max() > mean else outliers[col].min()
                ),
                "mean": float(mean),
                "threshold_3sigma": float(mean + 3 * std),
            })
    stats["statistical_anomalies"] = anomalies

    # ── Grouped stats for categorical columns ──────────────────────────────
    grouped_stats: dict = {}
    for cat in cat_cols:
        if 1 < df[cat].nunique() <= 10:
            grouped = (
                df.groupby(cat)[numeric_cols].mean()
                .replace({np.nan: None, np.inf: None, -np.inf: None})
            )
            grouped_stats[cat] = grouped.to_dict()
    if grouped_stats:
        stats["grouped_summary"] = grouped_stats

    # ── Value Distributions ──────────────────────────────────────────────
    val_dists = {}
    for col in cat_cols:
        if 1 < df[col].nunique() <= 20:
            counts = df[col].value_counts().replace({np.nan: None, np.inf: None, -np.inf: None})
            total = len(df[col].dropna())
            val_dists[col] = {
                str(val): {"count": int(cnt), "percentage": round(float(cnt) / total * 100, 2) if total > 0 else 0}
                for val, cnt in counts.items()
            }
    stats["value_distributions"] = val_dists

    # ── Text Columns ─────────────────────────────────────────────────────
    text_cols = []
    for col in df.columns:
        if df[col].dtype == object or str(df[col].dtype) in ['category', 'string']:
            lengths = df[col].dropna().astype(str).str.len()
            if not lengths.empty and lengths.median() > 20:
                text_cols.append(col)
    stats["text_columns"] = text_cols

    # ── Potential Target Columns Heuristics ──────────────────────────────
    potential_targets = []
    for col in df.columns:
        col_lower = col.lower()
        is_binary = df[col].nunique() == 2
        looks_like_target = any(t in col_lower for t in ["churn", "survived", "converted", "outcome", "label", "target", "y", "status", "class"])
        if is_binary or (looks_like_target and df[col].nunique() <= 10):
            potential_targets.append(col)
    stats["potential_targets"] = potential_targets

    # ── Time Features ────────────────────────────────────────────────────
    time_features = {}
    time_cols = [
        c for c in df.columns
        if any(token in c.lower() for token in ["date", "time", "created", "updated", "timestamp"])
        and pd.api.types.is_datetime64_any_dtype(df[c])
    ]
    if time_cols:
        primary_time = time_cols[0]
        min_d = df[primary_time].min()
        max_d = df[primary_time].max()
        if pd.notna(min_d) and pd.notna(max_d):
            span_days = (max_d - min_d).days
            time_features = {
                "time_column": primary_time,
                "min_date": str(min_d),
                "max_date": str(max_d),
                "span_days": int(span_days),
                "is_time_series": span_days > 1
            }
    stats["time_features"] = time_features

    # ── Data Quality Score ────────────────────────────────────────────────
    stats["data_quality"] = _compute_data_quality_score(df, stats)

    # ── Sampling metadata ─────────────────────────────────────────────────
    stats["sample_size"] = len(df)
    stats["full_row_count"] = full_row_count if full_row_count is not None else len(df)
    stats["sampling_method"] = sampling_method
    stats["sampling"] = {
        "method": sampling_method,
        "sampleSize": len(df),
        "fullRowCount": full_row_count if full_row_count is not None else len(df),
        "wasDownsampled": full_row_count is not None and full_row_count > len(df),
    }

    return stats
