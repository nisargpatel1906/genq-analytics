import base64
from fastapi import APIRouter, HTTPException

from app.db import reports_db
from app.api.chart_builder import build_charts
from app.api.export_pdf import generate_pdf_response
from app.api.export_docx import generate_docx_response
from app.api.export_notebook import generate_notebook_response

router = APIRouter()

@router.get("/export/{report_id}")
@router.get("/export/{report_id}/pdf")
async def export_pdf(report_id: str):
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    return generate_pdf_response(report_id, report_data)

@router.get("/export/{report_id}/docx")
async def export_docx(report_id: str):
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    return generate_docx_response(report_id, report_data)

@router.get("/export/{report_id}/notebook")
async def export_notebook(report_id: str):
    """
    Returns an executed Jupyter notebook (.ipynb) reconstructed from the
    stored report — no LLM re-execution required.
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    return generate_notebook_response(report_id, report_data)

@router.get("/charts/{report_id}")
async def get_report_charts(report_id: str):
    """
    Returns all charts for a report as base64-encoded PNG strings.
    Used by the frontend dashboard and report page to display live charts.
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    charts = build_charts(report_data)

    result = []
    for ch in charts:
        img_bytes = ch["buf"].read()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        result.append({
            "title": ch["title"],
            "interpretation": ch["interpretation"],
            "image": f"data:image/png;base64,{b64}"
        })

    return {"charts": result}
