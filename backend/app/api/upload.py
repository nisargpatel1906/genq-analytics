import uuid
import logging
import os
import pandas as pd
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from services.analyzer import analyze_dataframe, normalize_dataframe_types, _create_analysis_sample
import io
import numpy as np
from app.db import jobs, reports_db, JobCancelledException
from app.utils import sanitize_json

logger = logging.getLogger("genq_api.upload")

router = APIRouter()

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

            jobs[job_id]["status"] = event.get("detail", "Agent workflow is running...")
            jobs[job_id]["current_agent"] = event.get("currentAgent")
            jobs[job_id]["agent_progress"] = event.get("agents", [])
            if event.get("score") is not None:
                jobs[job_id]["audit_score"] = event["score"]
            jobs[job_id]["regeneration_round"] = event.get("round", 0)
        
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
        
        reports_db[report_id] = sanitize_json({
            "id": report_id,
            "filename": filename,
            "created_at": datetime.now().strftime("%b %d, %Y"),
            # stats are embedded in ai_report["_meta"] — no need to duplicate them here
            "stats": ai_report.get("_meta", {}),
            "report": ai_report,
            "data_sample": sample.to_dict('records'),
            "col_types": col_types,
        })
        
        # Step 4
        jobs[job_id]["step"] = 4
        jobs[job_id]["status"] = "Complete"
        jobs[job_id]["report_id"] = report_id
        logger.info(f"Job {job_id}: Process complete. Report generated with ID: {report_id}")
        
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

@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        return {"error": "Job not found"}
    return jobs[job_id]

@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Set status and cancellation flag in DB
    jobs[job_id].update({"cancelled": True, "status": "Cancelled"})
    logger.info(f"Cancellation requested for job: {job_id}")
    return {"status": "success", "message": "Job cancellation request received."}
