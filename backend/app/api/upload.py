import uuid
import logging
import pandas as pd
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, BackgroundTasks
from services.analyzer import extract_statistics, analyze_dataframe
from services.visualizer import generate_chart_configs
import io
from app.db import jobs, reports_db

logger = logging.getLogger("genq_api.upload")

router = APIRouter()

def process_file_task(job_id: str, file_content: bytes, filename: str):
    try:
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
            
        stats = extract_statistics(df)
        
        jobs[job_id]["rows"] = len(df)
        jobs[job_id]["columns"] = len(df.columns)
            
        # Step 2
        jobs[job_id]["step"] = 2
        jobs[job_id]["status"] = "AI is analyzing your data..."
        
        # Real AI call
        logger.info(f"Job {job_id}: Initiating AI analysis for dataframe with {len(df)} rows and {len(df.columns)} columns")
        ai_report = analyze_dataframe(df)
        
        if "error" in ai_report:
            raise Exception(f"AI Analysis Failed: {ai_report.get('error')}")
        
        # Step 3
        jobs[job_id]["step"] = 3
        jobs[job_id]["status"] = "Building AI-suggested visualizations..."
        
        configs = generate_chart_configs(df, ai_report)
        
        report_id = f"rep_{uuid.uuid4().hex[:8]}"
        
        # Store a clean data sample for chart generation at export time
        sample = df.head(1000).copy()
        # Convert non-JSON-safe types
        for col in sample.select_dtypes(include=['datetime64']).columns:
            sample[col] = sample[col].astype(str)
        sample = sample.where(pd.notnull(sample), None)
        # Replace inf/-inf with None
        import numpy as np
        sample = sample.replace([np.inf, -np.inf], None)
        
        # Store column type metadata for chart reasoning
        col_types = {
            "numeric": df.select_dtypes(include='number').columns.tolist(),
            "categorical": df.select_dtypes(include=['object', 'category']).columns.tolist(),
            "datetime": df.select_dtypes(include='datetime64').columns.tolist(),
        }
        # Detect binary columns (likely target/label columns)
        binary_cols = [c for c in col_types["numeric"] if df[c].nunique() == 2 and set(df[c].dropna().unique()).issubset({0, 1, True, False})]
        col_types["binary"] = binary_cols
        
        reports_db[report_id] = {
            "id": report_id,
            "filename": filename,
            "created_at": datetime.now().strftime("%b %d, %Y"),
            "stats": stats,
            "configs": configs,
            "report": ai_report,
            "data_sample": sample.to_dict('records'),
            "col_types": col_types,
        }
        
        # Step 4
        jobs[job_id]["step"] = 4
        jobs[job_id]["status"] = "Complete"
        jobs[job_id]["report_id"] = report_id
        logger.info(f"Job {job_id}: Process complete. Report generated with ID: {report_id}")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        jobs[job_id]["status"] = "Failed"
        jobs[job_id]["error"] = str(e)

@router.post("/upload")
async def upload_dataset(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    job_id = f"job_{uuid.uuid4().hex[:8]}"
    logger.info(f"Received file upload: {file.filename}. Assigned Job ID: {job_id}")
    jobs[job_id] = {"step": 0, "status": "Uploading...", "report_id": None}
    
    content = await file.read()
    background_tasks.add_task(process_file_task, job_id, content, file.filename)
    
    return {"status": "success", "job_id": job_id}

@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    if job_id not in jobs:
        return {"error": "Job not found"}
    return jobs[job_id]
