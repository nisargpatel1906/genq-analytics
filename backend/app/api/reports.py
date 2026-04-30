from fastapi import APIRouter, HTTPException
from app.db import reports_db

router = APIRouter()

@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    return reports_db[report_id]

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
        confidence = 0
        if findings:
            scores = [f.get("confidenceScore", 0) for f in findings if f.get("confidenceScore")]
            confidence = int(sum(scores) / len(scores)) if scores else 85
        results.append({
            "id": r_id,
            "name": r_data.get("filename", "Unknown"),
            "status": "completed",
            "date": r_data.get("created_at", "Today"),
            "rows": r_data.get("stats", {}).get("shape", {}).get("rows", 0),
            "cols": r_data.get("stats", {}).get("shape", {}).get("columns", 0),
            "confidence": confidence or 85,
        })
    return results
