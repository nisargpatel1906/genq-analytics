import uuid
import logging
import os
import json
import asyncio
import pandas as pd
from datetime import datetime
from typing import List, Optional
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

def process_file_task(job_id: str, file_content: bytes, filename: str):
    try:
        # Check cancellation before starting
        db_job = jobs.get(job_id)
        if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
            logger.info(f"Job {job_id} cancelled before processing.")
            return

        # Step 1
        jobs[job_id]["step"] = 1
        jobs[job_id]["status"] = "Ingesting Data & Mapping Schema..."
        
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_content))
        elif filename.endswith('.xlsx'):
            df = pd.read_excel(io.BytesIO(file_content))
        else:
            df = pd.read_csv(io.BytesIO(file_content))
            
        if df.empty or len(df.columns) == 0:
            raise Exception("The uploaded dataset is empty or invalid.")

        df = normalize_dataframe_types(df)
            
        jobs[job_id]["rows"] = len(df)
        jobs[job_id]["columns"] = len(df.columns)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 📊 [Ingest] Parsed '{filename}': {len(df):,} rows x {len(df.columns)} columns", flush=True)

        # Smart sampling step — notify frontend when dataset is large
        sample_max = 10_000
        if len(df) > sample_max:
            jobs[job_id]["step"] = 1
            jobs[job_id]["status"] = (
                f"Large dataset detected ({len(df):,} rows). "
                f"Smart sampling to {sample_max:,} rows for analysis..."
            )
            logger.info(f"Job {job_id}: Large dataset ({len(df)} rows) — smart sampling will be applied.")

        # NOTE: do NOT call extract_statistics(df) here — analyze_dataframe() handles
        # statistics internally on its sampled DataFrame, keeping stats consistent with analysis.

            
        # Step 2
        jobs[job_id]["step"] = 2
        jobs[job_id]["status"] = "Starting the agent workflow..."


        def update_agent_progress(event: dict):
            # Check database cancellation
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
        
        # Real AI call
        logger.info(f"Job {job_id}: Initiating AI analysis for dataframe with {len(df)} rows and {len(df.columns)} columns")
        ai_report = analyze_dataframe(df, progress_callback=update_agent_progress, job_id=job_id)
        
        if ai_report.get("cancelled", False) or "Job cancelled" in ai_report.get("error", ""):
            jobs[job_id]["status"] = "Cancelled"
            logger.info(f"Job {job_id}: Processing terminated because of cancellation request.")
            return

        if "error" in ai_report:
            raise Exception(f"AI Analysis Failed: {ai_report.get('error')}")
        
        # Step 3
        jobs[job_id]["step"] = 3
        jobs[job_id]["status"] = "Preparing visual engine..."
        
        report_id = f"rep_{uuid.uuid4().hex[:8]}"
        
        # Store a representative data sample for chart generation at export time
        # Use smart sampler (5K rows) instead of head(1000) for better distribution coverage
        chart_sample, _ = _create_analysis_sample(df, max_rows=5_000)
        sample = chart_sample.copy()
        # Convert non-JSON-safe types
        for col in sample.select_dtypes(include=['datetime64']).columns:
            sample[col] = sample[col].astype(str)
        
        # Replace NaN and Inf with None (JSON-safe)
        sample = sample.replace({np.nan: None, np.inf: None, -np.inf: None})
        
        # Store column type metadata for chart reasoning
        col_types = {
            "numeric": df.select_dtypes(include='number').columns.tolist(),
            "categorical": df.select_dtypes(include=['object', 'category']).columns.tolist(),
            "datetime": df.select_dtypes(include='datetime64').columns.tolist(),
        }
        # Detect binary columns (likely target/label columns)
        # BUG-13 fix: also require integer/bool dtype — float columns like {0.0, 1.0}
        # wrongly pass the issubset check because 0.0 == 0 and 1.0 == 1 in Python.
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
        })

        # Save dataset for interactive conversational agent queries
        try:
            ds_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "datasets"))
            os.makedirs(ds_dir, exist_ok=True)
            df.to_parquet(os.path.join(ds_dir, f"{report_id}.parquet"))
        except Exception as _pe:
            logger.warning(f"Could not save parquet dataset for {report_id}: {_pe}")
        
        # Step 4
        jobs[job_id]["step"] = 4
        jobs[job_id]["status"] = "Complete"
        jobs[job_id]["report_id"] = report_id
        logger.info(f"Job {job_id}: Process complete. Report generated with ID: {report_id}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 💾 [Report] Successfully saved report {report_id} for job {job_id}", flush=True)
        
    except JobCancelledException:
        logger.info(f"Job {job_id} cancelled during execution.")
        jobs[job_id]["status"] = "Cancelled"
        
    except Exception as e:
        # Check if cancellation occurred
        db_job = jobs.get(job_id)
        if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
            logger.info(f"Job {job_id} cancelled during execution (caught exception: {e}).")
            jobs[job_id]["status"] = "Cancelled"
        else:
            logger.error(f"Job {job_id} failed: {e}")
            jobs[job_id]["status"] = "Failed"
            jobs[job_id]["error"] = str(e)


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

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    logger.info(f"Received file upload: {filename}. Assigned Job ID: {job_id}")
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 📥 [Upload] Received file '{filename}' ({len(content)/1024:.1f} KB) -> Assigned Job ID: {job_id}", flush=True)
    jobs[job_id] = {
        "step": 0,
        "status": "Uploading...",
        "report_id": None,
        "agent_progress": [],
        "audit_score": None,
        "regeneration_round": 0,
    }
    
    background_tasks.add_task(process_file_task, job_id, content, filename)
    
    return {"status": "success", "job_id": job_id}


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
