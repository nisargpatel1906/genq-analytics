import uuid
import logging
import os
import json
import asyncio
import pandas as pd
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, Form, Body, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from services.analyzer import analyze_dataframe, normalize_dataframe_types, _create_analysis_sample
from services.schema_linker import build_unified_analytical_dataset, connect_and_materialize_sql
import io
import numpy as np
from app.db import jobs, reports_db, JobCancelledException
from app.utils import sanitize_json

logger = logging.getLogger("genq_api.upload")

router = APIRouter()

PIPELINE_STAGES = [
    {
        "id": "profile",
        "name": "Data Profiler",
        "phase": "Ingestion & Preparation",
        "description": "Profiles dataset dimensions, statistical distributions, and column types.",
    },
    {
        "id": "data_cleaner",
        "name": "Data Quality & Cleaning Agent",
        "phase": "Ingestion & Preparation",
        "description": "Audits corruption, standardizes casing, handles missing values, and removes duplicates.",
    },
    {
        "id": "hypothesis_planner",
        "name": "Research Planning Agent",
        "phase": "Strategic Hypotheses",
        "description": "Formulates empirical business hypotheses and prioritizes target investigations.",
    },
    {
        "id": "data_scientist",
        "name": "Data Scientist Agent",
        "phase": "Hypothesis Testing",
        "description": "Executes quantitative hypothesis tests, effect sizes, and subgroup comparisons.",
    },
    {
        "id": "reflector",
        "name": "Reflector Agent",
        "phase": "Peer Review & Verification",
        "description": "Critiques analysis depth, checks confounders, and requests follow-up tests if needed.",
    },
    {
        "id": "viz_preprocessor",
        "name": "Visualization Preprocessor",
        "phase": "Visual Analytics",
        "description": "Extracts chart specifications and coordinates narrative visualization goals.",
    },
    {
        "id": "viz_coder",
        "name": "Visualization Agent",
        "phase": "Visual Analytics",
        "description": "Writes and executes sandboxed Python code (matplotlib/seaborn) to render charts.",
    },
    {
        "id": "causal_analyst",
        "name": "Causal Inference Agent",
        "phase": "Advanced Intelligence",
        "description": "Evaluates potential confounders and analyzes causal vs correlational drivers.",
    },
    {
        "id": "forecaster",
        "name": "Forecasting Agent",
        "phase": "Advanced Intelligence",
        "description": "Detects temporal signals, projects trend horizons, and models trajectories.",
    },
    {
        "id": "anomaly_detector",
        "name": "Anomaly Detection Agent",
        "phase": "Advanced Intelligence",
        "description": "Scans statistical outliers, behavioral clusters, and segment anomalies.",
    },
    {
        "id": "experimentation",
        "name": "A/B Experimentation Agent",
        "phase": "Advanced Intelligence",
        "description": "Validates Sample Ratio Mismatch (SRM), computes lift % and rollout decisions.",
    },
    {
        "id": "ml_modeler",
        "name": "Machine Learning Agent",
        "phase": "Predictive Modeling",
        "description": "Trains predictive ML models (Random Forest) and extracts top driver importances.",
    },
    {
        "id": "strategic_advisor",
        "name": "Strategic Insights Agent",
        "phase": "Executive Synthesis",
        "description": "Synthesizes findings into high-impact, actionable executive recommendations.",
    },
    {
        "id": "report_writer",
        "name": "Report Writer & Stitcher",
        "phase": "Executive Synthesis",
        "description": "Drafts structured narrative sections and synthesizes comprehensive report body.",
    },
    {
        "id": "auditor",
        "name": "Quality Auditor Agent",
        "phase": "Quality Assurance",
        "description": "Scores analytical rigor, methodology, and triggers self-correction loops if needed.",
    },
]

class SqlConnectionRequest(BaseModel):
    db_uri: str
    query: Optional[str] = None
    tables: Optional[List[str]] = None
    instruction: Optional[str] = None


class AlignmentRequest(BaseModel):
    answers: Optional[Dict[str, str]] = None
    selected_modules: Optional[List[str]] = None
    quick_auto: bool = False


# In-memory and disk cache for datasets pending discovery alignment
pending_jobs_data: Dict[str, tuple[pd.DataFrame, str]] = {}

def _cache_pending_job_df(job_id: str, df: pd.DataFrame, filename: str):
    pending_jobs_data[job_id] = (df, filename)
    try:
        temp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "temp"))
        os.makedirs(temp_dir, exist_ok=True)
        df.to_parquet(os.path.join(temp_dir, f"{job_id}.parquet"))
    except Exception as e:
        logger.warning(f"Could not write temp parquet for pending job {job_id}: {e}")

def _get_pending_job_df(job_id: str) -> Optional[tuple[pd.DataFrame, str]]:
    if job_id in pending_jobs_data:
        return pending_jobs_data[job_id]
    try:
        temp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "temp"))
        p_path = os.path.join(temp_dir, f"{job_id}.parquet")
        if os.path.exists(p_path):
            df = pd.read_parquet(p_path)
            fname = jobs.get(job_id, {}).get("filename", "uploaded_data.csv")
            pending_jobs_data[job_id] = (df, fname)
            return df, fname
    except Exception as e:
        logger.warning(f"Could not load temp parquet for pending job {job_id}: {e}")
    return None


def generate_discovery_profile(df: pd.DataFrame, filename: str) -> dict:
    """
    Inspects schema, sample rows, and statistical traits to:
    1. Infer domain and context
    2. Check viability for all 7 senior tier modules
    3. Generate 3-5 dynamic, domain-tailored business discovery questions
    """
    df_norm = normalize_dataframe_types(df)
    cols = list(df_norm.columns)
    numeric_cols = df_norm.select_dtypes(include='number').columns.tolist()
    cat_cols = df_norm.select_dtypes(include=['object', 'category', 'string']).columns.tolist()

    # Time series detection
    time_cols = [
        c for c in cols
        if pd.api.types.is_datetime64_any_dtype(df_norm[c])
        or any(t in c.lower() for t in ["date", "time", "timestamp", "year", "month", "created", "order_date", "day"])
    ]
    has_time = len(time_cols) > 0
    time_col_name = time_cols[0] if time_cols else None

    # Identifier detection
    id_cols = [
        c for c in cols
        if any(t in c.lower() for t in ["id", "uuid", "cust", "user", "client", "member", "account", "emp", "employee"])
        and df_norm[c].nunique() > 10
    ]
    has_id = len(id_cols) > 0
    id_col_name = id_cols[0] if id_cols else None

    # Lifecycle / churn detection
    churn_cols = [
        c for c in cols
        if any(t in c.lower() for t in ["churn", "retention", "tenure", "status", "active", "cancelled", "attrition", "left"])
    ]
    has_retention = len(churn_cols) > 0

    # Variant / A/B treatment detection
    variant_cols = [
        c for c in cols
        if any(t in c.lower() for t in ["variant", "group", "treatment", "test_group", "experiment", "arm", "bucket"])
        and df_norm[c].nunique() in [2, 3, 4]
    ]
    has_variant = len(variant_cols) > 0
    variant_col_name = variant_cols[0] if variant_cols else None

    # Target candidates
    target_cols = [
        c for c in cols
        if any(t in c.lower() for t in ["churn", "target", "converted", "revenue", "sales", "price", "label", "outcome", "loss", "profit", "rating", "satisfaction", "default", "attrition", "income", "salary"])
    ]

    # Domain classification
    col_str = " ".join([c.lower() for c in cols]) + " " + filename.lower()
    if any(k in col_str for k in ["churn", "cart", "product", "sales", "order", "discount", "device", "shop", "ecommerce", "sku"]):
        domain = "E-Commerce & Retail"
        domain_desc = "Customer transactions, shopping behaviors, churn, and promotion elasticity."
        q1_opts = [
            "Identify key drivers of customer churn & drop-off",
            "Optimize pricing, discount elasticity & profit margins",
            "Segment high-LTV vs price-sensitive customer cohorts",
            "Diagnose operational bottlenecks & checkout drop-off"
        ]
    elif any(k in col_str for k in ["mrr", "arr", "subscription", "plan", "seats", "active", "saas", "dau", "mau"]):
        domain = "SaaS & Subscription Tech"
        domain_desc = "Recurring subscription dynamics, user engagement, and lifetime value."
        q1_opts = [
            "Analyze subscription renewal & expansion triggers",
            "Forecast ARR/MRR growth and revenue velocity",
            "Identify power users vs disengaged accounts",
            "Diagnose feature adoption patterns impacting churn"
        ]
    elif any(k in col_str for k in ["employee", "attrition", "salary", "income", "department", "tenure", "hr", "workforce", "overtime"]):
        domain = "HR & Workforce Talent Analytics"
        domain_desc = "Employee retention, compensation equity, and workforce productivity."
        q1_opts = [
            "Pinpoint primary root-causes driving talent attrition",
            "Audit compensation equity & performance correlations",
            "Identify high-burnout departments & overtime risk",
            "Design targeted retention interventions for top talent"
        ]
    elif any(k in col_str for k in ["loan", "credit", "interest", "balance", "default", "financial", "bank", "portfolio"]):
        domain = "Banking & Financial Services"
        domain_desc = "Credit risk, portfolio delinquency, and financial performance."
        q1_opts = [
            "Predict credit default and risk exposure",
            "Identify portfolio concentrations and high-margin segments",
            "Audit delinquency drivers across loan tiers",
            "Formulate risk-mitigation lending guidelines"
        ]
    elif any(k in col_str for k in ["patient", "hospital", "diagnosis", "health", "clinical", "medical", "dosage"]):
        domain = "Healthcare & Life Sciences"
        domain_desc = "Patient outcomes, clinical cohorts, and operational care metrics."
        q1_opts = [
            "Analyze patient recovery drivers and treatment efficacy",
            "Identify clinical risk factors and readmission rates",
            "Optimize resource allocation across medical care units",
            "Evaluate intervention outcomes across patient segments"
        ]
    else:
        domain = "Enterprise Business Intelligence"
        domain_desc = "Multivariate statistical exploration, driver modeling, and performance optimization."
        q1_opts = [
            f"Identify primary operational drivers influencing {cols[0]}",
            "Uncover hidden segment patterns & behavioral clusters",
            "Discover anomaly points and volatility drivers",
            "Formulate 30-60-90 day executive strategic action items"
        ]

    # Viable modules list
    viable_modules = [
        {
            "id": "causal_analyst",
            "name": "Causal Inference Agent",
            "phase": "Advanced Intelligence",
            "icon": "GitBranch",
            "viable": len(cols) >= 3 and len(numeric_cols) >= 1,
            "recommended": True,
            "reason": f"Sufficient multivariate dimensions ({len(cols)} columns) to differentiate correlation from causation." if (len(cols) >= 3 and len(numeric_cols) >= 1) else "Requires at least 3 feature columns for causal reasoning.",
            "estimated_cost_tokens": "~15K tokens · ~4s",
            "tag": "Confounder & Mechanism Audit"
        },
        {
            "id": "forecaster",
            "name": "Forecasting & Trend Agent",
            "phase": "Advanced Intelligence",
            "icon": "TrendingUp",
            "viable": has_time,
            "recommended": has_time,
            "reason": f"Temporal signal detected in column '{time_col_name}' for forward projections." if has_time else "No datetime or temporal series column detected in dataset.",
            "estimated_cost_tokens": "~18K tokens · ~5s",
            "tag": "Longitudinal Projection"
        },
        {
            "id": "cohort_analyst",
            "name": "Cohort & Retention Agent",
            "phase": "Advanced Intelligence",
            "icon": "Users",
            "viable": bool(has_id and (has_time or has_retention)),
            "recommended": bool(has_id and (has_time or has_retention)),
            "reason": f"Entity identifier '{id_col_name}' and lifecycle indicators available for cohort retention analysis." if (has_id and (has_time or has_retention)) else "Requires customer or user identifier columns to compute cohort retention decay.",
            "estimated_cost_tokens": "~16K tokens · ~4s",
            "tag": "Lifecycle Decay & Churn"
        },
        {
            "id": "experimentation",
            "name": "A/B Experimentation Agent",
            "phase": "Advanced Intelligence",
            "icon": "FlaskConical",
            "viable": has_variant,
            "recommended": has_variant,
            "reason": f"Candidate A/B test variant column '{variant_col_name}' detected for SRM validation and lift analysis." if has_variant else "No variant / treatment group column (e.g. Control vs Treatment) detected.",
            "estimated_cost_tokens": "~14K tokens · ~4s",
            "tag": "SRM & Rollout Lift"
        },
        {
            "id": "ml_modeler",
            "name": "Machine Learning Agent",
            "phase": "Predictive Modeling",
            "icon": "Brain",
            "viable": len(cols) >= 3 and len(numeric_cols) >= 1,
            "recommended": True,
            "reason": f"Trains predictive Random Forest model and ranks top driver importances on target candidates ({', '.join(target_cols[:2]) or 'unsupervised clusters'}).",
            "estimated_cost_tokens": "~22K tokens · ~7s",
            "tag": "Predictive Modeling & Drivers"
        },
        {
            "id": "anomaly_detector",
            "name": "Anomaly Detection Agent",
            "phase": "Advanced Intelligence",
            "icon": "AlertTriangle",
            "viable": len(numeric_cols) >= 1,
            "recommended": True,
            "reason": f"Scans statistical anomalies (>3σ) and clustering outliers across {len(numeric_cols)} numeric metrics.",
            "estimated_cost_tokens": "~12K tokens · ~3s",
            "tag": "Outlier & Cluster Detection"
        },
        {
            "id": "benchmarking",
            "name": "Competitive Benchmarking Agent",
            "phase": "Executive Synthesis",
            "icon": "Award",
            "viable": True,
            "recommended": True,
            "reason": "Compares observed metrics against domain standards and industry benchmark distributions.",
            "estimated_cost_tokens": "~10K tokens · ~3s",
            "tag": "Industry Baseline Comparison"
        },
    ]

    # Dynamic Questions
    kpi_options = [f"Optimize / Maximize {c}" for c in (target_cols + numeric_cols)[:3]]
    if not kpi_options:
        kpi_options = ["Maximize Operational Efficiency", "Minimize Overall Variance", "Improve Retention"]

    questions = [
        {
            "id": "business_objective",
            "title": "Primary Strategic Objective",
            "description": "What core outcome or decision should this analysis primarily address?",
            "category": "strategic_goal",
            "options": q1_opts,
            "default": q1_opts[0],
            "allow_custom": True,
            "custom_placeholder": "Or state your specific business question, thesis, or custom objective..."
        },
        {
            "id": "target_audience",
            "title": "Target Audience & Decision-Makers",
            "description": "Who will consume and act on this report?",
            "category": "stakeholder",
            "options": [
                "C-Suite & Executive Board (Strategic overview & macro ROI)",
                "Growth Marketing & Sales Leadership (Acquisition & CAC/LTV)",
                "Product & Engineering Teams (Feature engagement & churn)",
                "Operations & Finance Committee (Cost efficiency & risk)"
            ],
            "default": "C-Suite & Executive Board (Strategic overview & macro ROI)",
            "allow_custom": True,
            "custom_placeholder": "Or specify the key stakeholders..."
        },
        {
            "id": "kpi_priority",
            "title": "Core North-Star Metric / KPI",
            "description": "Which detected metric should receive highest analytical weight?",
            "category": "metric_focus",
            "options": kpi_options,
            "default": kpi_options[0],
            "allow_custom": True,
            "custom_placeholder": "Or specify another custom metric..."
        },
        {
            "id": "time_horizon",
            "title": "Execution & Planning Horizon",
            "description": "What timeframe should recommendations and projections target?",
            "category": "horizon",
            "options": [
                "Immediate 30-Day Tactical Quick Wins",
                "Quarterly OKR Strategic Realignment (90-Day)",
                "Multi-Year Enterprise Growth Strategy & Forecasting"
            ],
            "default": "Quarterly OKR Strategic Realignment (90-Day)",
            "allow_custom": True,
            "custom_placeholder": "Or specify your execution horizon..."
        }
    ]

    return {
        "domain": domain,
        "domain_confidence": 92,
        "domain_description": domain_desc,
        "dataset_summary": f"{len(df_norm):,} rows × {len(cols)} columns",
        "viable_modules": viable_modules,
        "questions": questions,
        "detected_characteristics": {
            "has_time": has_time,
            "time_column": time_col_name,
            "has_id": has_id,
            "id_column": id_col_name,
            "has_variant": has_variant,
            "variant_column": variant_col_name,
            "target_candidates": target_cols[:4],
            "numeric_count": len(numeric_cols),
            "categorical_count": len(cat_cols)
        }
    }


def process_file_task_aligned(
    job_id: str,
    df: pd.DataFrame,
    filename: str,
    business_context: Optional[dict] = None,
    selected_modules: Optional[list] = None
):
    """Executes the pipeline with user-aligned business context and selective modules."""
    try:
        db_job = jobs.get(job_id)
        if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
            logger.info(f"Job {job_id} cancelled before processing.")
            return

        jobs[job_id]["step"] = 1
        jobs[job_id]["status"] = "Ingesting Data & Mapping Schema..."

        df = normalize_dataframe_types(df)
        jobs[job_id]["rows"] = len(df)
        jobs[job_id]["columns"] = len(df.columns)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 [Ingest] Processing '{filename}': {len(df):,} rows x {len(df.columns)} columns", flush=True)

        sample_max = 10_000
        if len(df) > sample_max:
            jobs[job_id]["step"] = 1
            jobs[job_id]["status"] = (
                f"Large dataset detected ({len(df):,} rows). "
                f"Smart sampling to {sample_max:,} rows for analysis..."
            )

        jobs[job_id]["step"] = 2
        jobs[job_id]["status"] = "Starting aligned agent workflow..."

        def update_agent_progress(event: dict):
            db_job = jobs.get(job_id)
            if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
                raise JobCancelledException("Job cancelled by user.")

            update_data = {
                "status": event.get("detail", "Agent workflow is running..."),
                "current_agent": event.get("currentAgent"),
                "agent_progress": event.get("agents", []),
                "regeneration_round": event.get("round", 0),
            }
            if event.get("score") is not None:
                update_data["audit_score"] = event["score"]
            jobs[job_id].update(update_data)

        logger.info(f"Job {job_id}: Initiating aligned AI analysis (modules: {selected_modules})")
        ai_report = analyze_dataframe(
            df,
            progress_callback=update_agent_progress,
            job_id=job_id,
            business_context=business_context,
            selected_modules=selected_modules
        )

        if ai_report.get("cancelled", False) or "Job cancelled" in ai_report.get("error", ""):
            jobs[job_id]["status"] = "Cancelled"
            return

        if "error" in ai_report:
            raise Exception(f"AI Analysis Failed: {ai_report.get('error')}")

        jobs[job_id]["step"] = 3
        jobs[job_id]["status"] = "Preparing visual engine..."

        report_id = f"rep_{uuid.uuid4().hex[:8]}"
        chart_sample, _ = _create_analysis_sample(df, max_rows=5_000)
        sample = chart_sample.copy()
        for col in sample.select_dtypes(include=['datetime64']).columns:
            sample[col] = sample[col].astype(str)
        sample = sample.replace({np.nan: None, np.inf: None, -np.inf: None})

        col_types = {
            "numeric": df.select_dtypes(include='number').columns.tolist(),
            "categorical": df.select_dtypes(include=['object', 'category']).columns.tolist(),
            "datetime": df.select_dtypes(include='datetime64').columns.tolist(),
        }
        import numpy as _np
        binary_cols = [
            c for c in col_types["numeric"]
            if df[c].nunique() == 2
            and _np.issubdtype(df[c].dtype, _np.integer) or df[c].dtype == bool
            and set(df[c].dropna().unique()).issubset({0, 1, True, False})
        ]
        col_types["binary"] = binary_cols

        stats_dict = dict(ai_report.get("_meta", {}))
        stats_dict["shape"] = {"rows": len(df), "columns": len(df.columns)}

        reports_db[report_id] = sanitize_json({
            "id": report_id,
            "filename": filename,
            "created_at": datetime.now().strftime("%b %d, %Y"),
            "stats": stats_dict,
            "report": ai_report,
            "data_sample": sample.to_dict('records'),
            "col_types": col_types,
            "business_context": business_context,
            "selected_modules": selected_modules,
        })

        try:
            ds_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "datasets"))
            os.makedirs(ds_dir, exist_ok=True)
            df.to_parquet(os.path.join(ds_dir, f"{report_id}.parquet"))
        except Exception as _pe:
            logger.warning(f"Could not save parquet dataset for {report_id}: {_pe}")

        jobs[job_id]["step"] = 4
        jobs[job_id]["status"] = "Complete"
        jobs[job_id]["report_id"] = report_id
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 💾 [Report] Successfully saved report {report_id} for job {job_id}", flush=True)

    except JobCancelledException:
        logger.info(f"Job {job_id} cancelled during execution.")
        jobs[job_id]["status"] = "Cancelled"
    except Exception as e:
        db_job = jobs.get(job_id)
        if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
            jobs[job_id]["status"] = "Cancelled"
        else:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            jobs[job_id]["status"] = "Failed"
            jobs[job_id]["error"] = str(e)


def process_file_task(job_id: str, file_content: bytes, filename: str):
    """Backward compatibility wrapper."""
    if filename.endswith('.csv'):
        df = pd.read_csv(io.BytesIO(file_content))
    elif filename.endswith('.xlsx'):
        df = pd.read_excel(io.BytesIO(file_content))
    else:
        df = pd.read_csv(io.BytesIO(file_content))
    process_file_task_aligned(job_id, df, filename)


def process_multi_file_task(job_id: str, files_data: List[tuple[str, bytes]], instruction: Optional[str] = None):
    try:
        db_job = jobs.get(job_id)
        if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
            logger.info(f"Job {job_id} cancelled before processing.")
            return

        jobs[job_id]["step"] = 1
        jobs[job_id]["status"] = "Ingesting Multiple Tables & Linking Schema..."

        tables = {}
        for fname, content in files_data:
            if fname.endswith(".csv"):
                df_item = pd.read_csv(io.BytesIO(content))
            elif fname.endswith(".xlsx"):
                df_item = pd.read_excel(io.BytesIO(content))
            else:
                df_item = pd.read_csv(io.BytesIO(content))
            tables[fname] = normalize_dataframe_types(df_item)

        unified_df, relational_manifest = build_unified_analytical_dataset(tables, user_instruction=instruction)

        jobs[job_id]["rows"] = len(unified_df)
        jobs[job_id]["columns"] = len(unified_df.columns)
        jobs[job_id]["relational_manifest"] = relational_manifest

        jobs[job_id]["step"] = 2
        jobs[job_id]["status"] = "Running Full Agent Analytics Pipeline..."

        def update_multi_progress(event: dict):
            db_job = jobs.get(job_id)
            if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
                raise JobCancelledException("Job cancelled by user.")

            update_data = {
                "status": event.get("detail", "Agent workflow is running..."),
                "current_agent": event.get("currentAgent"),
                "agent_progress": event.get("agents", []),
                "regeneration_round": event.get("round", 0),
            }
            if event.get("score") is not None:
                update_data["audit_score"] = event["score"]
            jobs[job_id].update(update_data)

        report = analyze_dataframe(
            unified_df,
            progress_callback=update_multi_progress,
            job_id=job_id,
            relational_manifest=relational_manifest,
        )

        report_id = f"rep_{uuid.uuid4().hex[:8]}"
        reports_db[report_id] = {
            "id": report_id,
            "filename": f"Multi_Table_Joined_({len(files_data)}_tables)",
            "uploaded_at": datetime.now().isoformat(),
            "report": report,
            "stats": {"shape": {"rows": len(unified_df), "columns": len(unified_df.columns)}},
            "data_sample": unified_df.head(10).to_dict("records"),
            "relational_manifest": relational_manifest,
        }

        dataset_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "datasets")
        os.makedirs(dataset_dir, exist_ok=True)
        dataset_path = os.path.join(dataset_dir, f"{report_id}.parquet")
        unified_df.to_parquet(dataset_path, index=False)

        jobs[job_id]["step"] = 3
        jobs[job_id]["status"] = "Complete"
        jobs[job_id]["report_id"] = report_id

    except JobCancelledException:
        logger.info(f"Job {job_id} cancelled during multi-file processing.")
        jobs[job_id]["status"] = "Cancelled"
    except Exception as e:
        logger.error(f"Multi-table job {job_id} failed: {e}", exc_info=True)
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"] = str(e)


def process_sql_connection_task(job_id: str, db_uri: str, query: Optional[str] = None, tables: Optional[List[str]] = None, instruction: Optional[str] = None):
    try:
        db_job = jobs.get(job_id)
        if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
            logger.info(f"Job {job_id} cancelled before processing.")
            return

        jobs[job_id]["step"] = 1
        jobs[job_id]["status"] = "Connecting to SQL Database & Introspecting..."

        unified_df, relational_manifest = connect_and_materialize_sql(
            db_uri=db_uri,
            query=query,
            table_names=tables,
            user_instruction=instruction,
        )

        jobs[job_id]["rows"] = len(unified_df)
        jobs[job_id]["columns"] = len(unified_df.columns)
        jobs[job_id]["relational_manifest"] = relational_manifest

        jobs[job_id]["step"] = 2
        jobs[job_id]["status"] = "Running Full Agent Analytics Pipeline..."

        def update_sql_progress(event: dict):
            db_job = jobs.get(job_id)
            if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
                raise JobCancelledException("Job cancelled by user.")

            update_data = {
                "status": event.get("detail", "Agent workflow is running..."),
                "current_agent": event.get("currentAgent"),
                "agent_progress": event.get("agents", []),
                "regeneration_round": event.get("round", 0),
            }
            if event.get("score") is not None:
                update_data["audit_score"] = event["score"]
            jobs[job_id].update(update_data)

        report = analyze_dataframe(
            unified_df,
            progress_callback=update_sql_progress,
            job_id=job_id,
            relational_manifest=relational_manifest,
        )

        report_id = f"rep_{uuid.uuid4().hex[:8]}"
        reports_db[report_id] = {
            "id": report_id,
            "filename": "SQL_Database_Analysis",
            "uploaded_at": datetime.now().isoformat(),
            "report": report,
            "stats": {"shape": {"rows": len(unified_df), "columns": len(unified_df.columns)}},
            "data_sample": unified_df.head(10).to_dict("records"),
            "relational_manifest": relational_manifest,
        }

        dataset_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "datasets")
        os.makedirs(dataset_dir, exist_ok=True)
        dataset_path = os.path.join(dataset_dir, f"{report_id}.parquet")
        unified_df.to_parquet(dataset_path, index=False)

        jobs[job_id]["step"] = 3
        jobs[job_id]["status"] = "Complete"
        jobs[job_id]["report_id"] = report_id

    except JobCancelledException:
        logger.info(f"Job {job_id} cancelled during SQL processing.")
        jobs[job_id]["status"] = "Cancelled"
    except Exception as e:
        logger.error(f"SQL connection job {job_id} failed: {e}", exc_info=True)
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"] = str(e)




@router.post("/upload")
async def upload_dataset(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    # 1. Enforce concurrent job rate limiting
    active_jobs = sum(1 for job in jobs.values() if job.get("status") not in ("Complete", "Failed", "Cancelled"))
    if active_jobs >= 3:
        raise HTTPException(status_code=429, detail="Too many concurrent analysis requests. Please try again later.")

    # 2. Enforce file extension validation
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".csv", ".xlsx"):
        raise HTTPException(status_code=400, detail="Invalid file format. Only CSV and XLSX files are allowed.")

    # 3. Enforce MIME type validation
    allowed_mimes = {
        "text/csv",
        "application/vnd.ms-excel",
        "application/csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream"
    }
    if file.content_type not in allowed_mimes:
        raise HTTPException(status_code=400, detail="Invalid file MIME type.")

    # Read content to check file size
    content = await file.read()

    # 4. Enforce file size limit
    max_mb = int(os.environ.get("MAX_FILE_SIZE_MB", 500))
    max_bytes = max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds maximum allowed size of {max_mb}MB.")

    # Parse DataFrame
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.endswith('.xlsx'):
            df = pd.read_excel(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content))
    except Exception as parse_err:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {parse_err}")

    if df.empty or len(df.columns) == 0:
        raise HTTPException(status_code=400, detail="The uploaded dataset is empty or has no columns.")

    df = normalize_dataframe_types(df)

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    logger.info(f"Received file upload: {filename}. Assigned Job ID: {job_id}")
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 📥 [Upload] Received file '{filename}' ({len(content)/1024:.1f} KB) -> Assigned Job ID: {job_id}", flush=True)

    profile = generate_discovery_profile(df, filename)
    _cache_pending_job_df(job_id, df, filename)

    jobs[job_id] = {
        "step": 0,
        "status": "awaiting_discovery_alignment",
        "report_id": None,
        "agent_progress": [],
        "audit_score": None,
        "regeneration_round": 0,
        "rows": len(df),
        "columns": len(df.columns),
        "filename": filename,
        "discovery_profile": profile,
    }

    return {
        "status": "awaiting_alignment",
        "job_id": job_id,
        "discovery_profile": profile,
        "rows": len(df),
        "columns": len(df.columns),
        "filename": filename,
    }


@router.post("/jobs/{job_id}/align")
async def align_and_launch_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    req: AlignmentRequest = Body(...)
):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    pending = _get_pending_job_df(job_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Pending dataset for this job not found or expired")

    df, filename = pending
    profile = jobs[job_id].get("discovery_profile", {})

    if req.quick_auto:
        viable_mods = [m["id"] for m in profile.get("viable_modules", []) if m.get("viable", True)]
        selected_modules = viable_mods
        answers = {
            "business_objective": profile.get("questions", [{}])[0].get("default", "Comprehensive autonomous exploratory analysis"),
            "target_audience": "Executive Leadership and Cross-Functional Product/Growth Teams",
            "kpi_priority": "All detected operational and financial drivers",
            "time_horizon": "Quarterly OKR Strategic Realignment (90-Day)"
        }
    else:
        selected_modules = req.selected_modules if req.selected_modules is not None else [
            m["id"] for m in profile.get("viable_modules", []) if m.get("viable", True)
        ]
        answers = req.answers or {}

    jobs[job_id]["step"] = 1
    jobs[job_id]["status"] = "Ingesting Data & Mapping Schema..."
    jobs[job_id]["selected_modules"] = selected_modules
    jobs[job_id]["business_context"] = answers

    background_tasks.add_task(
        process_file_task_aligned,
        job_id,
        df,
        filename,
        answers,
        selected_modules
    )
    return {
        "status": "success",
        "job_id": job_id,
        "selected_modules": selected_modules,
        "business_context": answers
    }


@router.post("/jobs/{job_id}/auto-analyze")
async def auto_analyze_job(job_id: str, background_tasks: BackgroundTasks):
    return await align_and_launch_job(job_id, background_tasks, AlignmentRequest(quick_auto=True))


@router.get("/jobs/{job_id}/discovery")
async def get_job_discovery(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id].get("discovery_profile", {})


@router.post("/upload/multi")
async def upload_multiple_datasets(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    instruction: Optional[str] = Form(None)
):
    if not files or len(files) < 1:
        raise HTTPException(status_code=400, detail="At least one file must be uploaded.")

    active_jobs = sum(1 for job in jobs.values() if job.get("status") not in ("Complete", "Failed", "Cancelled"))
    if active_jobs >= 3:
        raise HTTPException(status_code=429, detail="Too many concurrent analysis requests. Please try again later.")

    files_data = []
    max_mb = int(os.environ.get("MAX_FILE_SIZE_MB", 500))
    max_bytes = max_mb * 1024 * 1024

    for f in files:
        fname = f.filename or ""
        ext = os.path.splitext(fname)[1].lower()
        if ext not in (".csv", ".xlsx"):
            raise HTTPException(status_code=400, detail=f"Invalid file format for '{fname}'. Only CSV and XLSX allowed.")
        content = await f.read()
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"File '{fname}' exceeds {max_mb}MB limit.")
        files_data.append((fname, content))

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    logger.info(f"Received multi-file upload with {len(files_data)} tables. Assigned Job ID: {job_id}")
    jobs[job_id] = {
        "step": 0,
        "status": "Uploading multi-table dataset...",
        "report_id": None,
        "agent_progress": [],
        "audit_score": None,
        "regeneration_round": 0,
    }

    background_tasks.add_task(process_multi_file_task, job_id, files_data, instruction)
    return {"status": "success", "job_id": job_id, "tables_count": len(files_data)}


@router.post("/connect/sql")
async def connect_sql_database(
    background_tasks: BackgroundTasks,
    req: SqlConnectionRequest
):
    if not req.db_uri:
        raise HTTPException(status_code=400, detail="Database URI is required.")

    active_jobs = sum(1 for job in jobs.values() if job.get("status") not in ("Complete", "Failed", "Cancelled"))
    if active_jobs >= 3:
        raise HTTPException(status_code=429, detail="Too many concurrent requests. Please try again later.")

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    logger.info(f"Received SQL connection request for DB: {req.db_uri[:30]}... Assigned Job ID: {job_id}")
    jobs[job_id] = {
        "step": 0,
        "status": "Connecting to SQL database...",
        "report_id": None,
        "agent_progress": [],
        "audit_score": None,
        "regeneration_round": 0,
    }

    background_tasks.add_task(
        process_sql_connection_task,
        job_id,
        req.db_uri,
        req.query,
        req.tables,
        req.instruction
    )
    return {"status": "success", "job_id": job_id}


@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        return {"error": "Job not found"}
    job_data = dict(jobs[job_id])
    job_data["pipeline_stages"] = PIPELINE_STAGES
    return sanitize_json(job_data)


@router.get("/jobs/{job_id}/events")
async def stream_job_events(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        last_dump = None
        while True:
            if job_id not in jobs:
                break
            job_data = dict(jobs[job_id])
            job_data["pipeline_stages"] = PIPELINE_STAGES
            current_dump = json.dumps(sanitize_json(job_data))
            if current_dump != last_dump:
                last_dump = current_dump
                yield f"data: {current_dump}\n\n"
            if job_data.get("status") in ("Complete", "Failed", "Cancelled"):
                break
            await asyncio.sleep(0.7)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Set status and cancellation flag in DB
    jobs[job_id].update({"cancelled": True, "status": "Cancelled"})
    logger.info(f"Cancellation requested for job: {job_id}")
    return {"status": "success", "message": "Job cancellation request received."}
