# backend/app/api/monitor_routes.py

import os
import io
import logging
from typing import List, Dict, Any, Optional
import pandas as pd
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Body
from app.db import reports_db
from app.utils import sanitize_json
from services.monitor import compute_drift_and_anomaly_alerts, send_webhook_alert

logger = logging.getLogger("genq_api.monitor_routes")

router = APIRouter()

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_cache'))
DATASETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'datasets'))
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(DATASETS_DIR, exist_ok=True)


class CompareJsonRequest(BaseModel):
    baseline_report_id: Optional[str] = None
    current_report_id: Optional[str] = None
    baseline_data: Optional[List[Dict[str, Any]]] = None
    current_data: Optional[List[Dict[str, Any]]] = None
    alert_threshold_psi: Optional[float] = 0.20
    mean_shift_pct_threshold: Optional[float] = 15.0
    webhook_url: Optional[str] = None
    dataset_label: Optional[str] = "Production Snapshot"


class WebhookTestRequest(BaseModel):
    webhook_url: str
    dataset_label: Optional[str] = "Alert Test"


def _load_dataframe_for_report(report_id: str) -> pd.DataFrame:
    """Helper to retrieve full or sampled dataframe for a given report_id."""
    # 1. Check canonical parquet storage
    parquet_path = os.path.join(DATASETS_DIR, f"{report_id}.parquet")
    if os.path.exists(parquet_path):
        try:
            return pd.read_parquet(parquet_path)
        except Exception as e:
            logger.warning("Failed to load cached Parquet for report %s: %s", report_id, e)

    # 2. Check cached CSV storage
    for directory in [DATASETS_DIR, CACHE_DIR]:
        csv_path = os.path.join(directory, f"{report_id}.csv")
        if os.path.exists(csv_path):
            try:
                return pd.read_csv(csv_path)
            except Exception as e:
                logger.warning("Failed to load cached CSV for report %s: %s", report_id, e)

    # 3. Fallback to sample in reports_db
    if report_id in reports_db:
        rep = reports_db[report_id]
        sample = rep.get("data_sample", [])
        if sample:
            return pd.DataFrame(sample)

    raise HTTPException(
        status_code=404,
        detail=f"No dataset snapshot or sample found for report ID '{report_id}'."
    )


@router.post("/monitor/compare")
async def compare_snapshots(payload: CompareJsonRequest):
    """Compares baseline and current data distributions to calculate Population Stability Index (PSI),
    Kolmogorov-Smirnov statistical tests, mean shifts, and dispatches webhook alerts if anomalies are flagged."""
    # Resolve baseline DataFrame
    if payload.baseline_data:
        baseline_df = pd.DataFrame(payload.baseline_data)
    elif payload.baseline_report_id:
        baseline_df = _load_dataframe_for_report(payload.baseline_report_id)
    else:
        raise HTTPException(status_code=400, detail="Must provide either baseline_data or baseline_report_id.")

    # Resolve current DataFrame
    if payload.current_data:
        current_df = pd.DataFrame(payload.current_data)
    elif payload.current_report_id:
        current_df = _load_dataframe_for_report(payload.current_report_id)
    else:
        raise HTTPException(status_code=400, detail="Must provide either current_data or current_report_id.")

    if baseline_df.empty or current_df.empty:
        raise HTTPException(status_code=400, detail="Baseline or current dataset is empty.")

    # Compute drift & operational health
    drift_result = compute_drift_and_anomaly_alerts(
        baseline_df=baseline_df,
        current_df=current_df,
        alert_threshold_psi=payload.alert_threshold_psi or 0.20,
        mean_shift_pct_threshold=payload.mean_shift_pct_threshold or 15.0,
    )

    webhook_res = None
    if payload.webhook_url:
        webhook_res = send_webhook_alert(
            webhook_url=payload.webhook_url,
            alert_report=drift_result,
            dataset_label=payload.dataset_label or "Dataset",
        )
        drift_result["webhook_dispatch"] = webhook_res

    return sanitize_json(drift_result)


@router.post("/monitor/compare-files")
async def compare_snapshot_files(
    baseline_file: Optional[UploadFile] = File(None),
    current_file: Optional[UploadFile] = File(None),
    baseline_report_id: Optional[str] = Form(None),
    current_report_id: Optional[str] = Form(None),
    alert_threshold_psi: float = Form(0.20),
    mean_shift_pct_threshold: float = Form(15.0),
    webhook_url: Optional[str] = Form(None),
    dataset_label: Optional[str] = Form("File Comparison Snapshot"),
):
    """Compares snapshots provided via multipart file upload or mixed with report IDs."""
    if baseline_file:
        b_content = await baseline_file.read()
        baseline_df = pd.read_csv(io.BytesIO(b_content)) if baseline_file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(b_content))
    elif baseline_report_id:
        baseline_df = _load_dataframe_for_report(baseline_report_id)
    else:
        raise HTTPException(status_code=400, detail="Must provide baseline_file or baseline_report_id.")

    if current_file:
        c_content = await current_file.read()
        current_df = pd.read_csv(io.BytesIO(c_content)) if current_file.filename.endswith('.csv') else pd.read_excel(io.BytesIO(c_content))
    elif current_report_id:
        current_df = _load_dataframe_for_report(current_report_id)
    else:
        raise HTTPException(status_code=400, detail="Must provide current_file or current_report_id.")

    drift_result = compute_drift_and_anomaly_alerts(
        baseline_df=baseline_df,
        current_df=current_df,
        alert_threshold_psi=alert_threshold_psi,
        mean_shift_pct_threshold=mean_shift_pct_threshold,
    )

    if webhook_url:
        webhook_res = send_webhook_alert(
            webhook_url=webhook_url,
            alert_report=drift_result,
            dataset_label=dataset_label,
        )
        drift_result["webhook_dispatch"] = webhook_res

    return sanitize_json(drift_result)


@router.post("/monitor/webhook/test")
async def test_webhook(payload: WebhookTestRequest):
    """Dispatches a test alert ping to a configured webhook URL to verify connectivity."""
    mock_report = {
        "status": "HEALTHY",
        "overall_health_score": 98,
        "alerts": [
            {
                "severity": "INFO",
                "title": "Webhook Integration Verification",
                "detail": "GenQ Analytics Monitor is successfully connected to this channel.",
            }
        ],
    }
    res = send_webhook_alert(
        webhook_url=payload.webhook_url,
        alert_report=mock_report,
        dataset_label=payload.dataset_label or "Test",
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=f"Failed to post alert: {res.get('error')}")
    return {"status": "ok", "message": "Alert notification dispatched successfully.", "detail": res}


@router.get("/monitor/snapshots")
async def list_snapshots():
    """Lists all available dataset snapshots available for historical drift analysis."""
    snapshots = []
    for rep_id, rep in reports_db.items():
        csv_path = os.path.join(CACHE_DIR, f"{rep_id}.csv")
        cached = os.path.exists(csv_path)
        sample = rep.get("data_sample", [])
        snapshots.append({
            "report_id": rep_id,
            "filename": rep.get("filename", "Unknown"),
            "created_at": rep.get("created_at"),
            "has_full_cache": cached,
            "sample_rows": len(sample),
            "columns": list(sample[0].keys()) if sample else [],
        })
    return {"snapshots": snapshots}
