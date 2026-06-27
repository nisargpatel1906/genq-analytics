from fastapi import APIRouter, HTTPException
from app.db import reports_db
from app.utils import sanitize_json

router = APIRouter()

@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    return sanitize_json(report_data)

@router.put("/reports/{report_id}")
async def update_report(report_id: str, payload: dict):
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    
    if "report" in payload:
        new_report = payload["report"]
        if isinstance(new_report, dict):
            if "report" not in report_data or not isinstance(report_data["report"], dict):
                report_data["report"] = {}
            for key in ["executiveSummary", "keyFindings", "anomalies", "recommendations"]:
                if key in new_report:
                    report_data["report"][key] = new_report[key]
                    
    reports_db[report_id] = report_data
    return sanitize_json(reports_db[report_id])

@router.delete("/reports/{report_id}")
async def delete_report(report_id: str):
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    del reports_db[report_id]
    return {"status": "deleted"}

@router.get("/reports")
async def list_reports():
    results = []
    for r_id, r_data in reports_db.items():
        ai = r_data.get("report", {})
        # Try to extract a meaningful confidence from the findings
        findings = ai.get("keyFindings", [])
        confidence = None
        if findings:
            scores = []
            for f in findings:
                val = f.get("confidence") or f.get("confidenceScore")
                if val is not None:
                    try:
                        scores.append(int(val))
                    except (ValueError, TypeError):
                        pass
            confidence = int(sum(scores) / len(scores)) if scores else None
        results.append({
            "id": r_id,
            "name": r_data.get("filename", "Unknown"),
            "status": "completed",
            "date": r_data.get("created_at", "Today"),
            "rows": r_data.get("stats", {}).get("shape", {}).get("rows", 0),
            "cols": r_data.get("stats", {}).get("shape", {}).get("columns", 0),
            "confidence": confidence,
        })
    return results
