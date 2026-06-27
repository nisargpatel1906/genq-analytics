import os
import io
import uuid
import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def set_env_api_key():
    with patch.dict(os.environ, {"GENQ_API_KEY": "test_api_key", "MAX_FILE_SIZE_MB": "500"}):
        yield

def test_api_unauthorized(client):
    # Test upload without API key fails
    response = client.post("/api/upload", files={"file": ("test.csv", b"a,b\n1,2", "text/csv")})
    assert response.status_code == 401

    # Test list reports without API key fails
    response = client.get("/api/reports")
    assert response.status_code == 401

def test_api_invalid_key(client):
    # Test upload with invalid API key fails
    headers = {"X-API-Key": "wrong_key"}
    response = client.post("/api/upload", files={"file": ("test.csv", b"a,b\n1,2", "text/csv")}, headers=headers)
    assert response.status_code == 401

def test_critical_path_flow(client):
    headers = {"X-API-Key": "test_api_key"}

    # Mock analyze_dataframe to bypass the actual LLM graph run
    mock_report = {
        "executiveSummary": "This is a mock executive summary.",
        "keyFindings": [
            {
                "title": "Finding 1",
                "detail": "Detail of finding 1",
                "confidenceScore": 90
            }
        ],
        "anomalies": [],
        "recommendations": []
    }

    # Patch analyze_dataframe in upload.py
    with patch("app.api.upload.analyze_dataframe", return_value=mock_report):
        file_content = b"col1,col2\n10,20\n30,40"
        response = client.post(
            "/api/upload",
            files={"file": ("test.csv", file_content, "text/csv")},
            headers=headers
        )
        assert response.status_code == 200
        res_data = response.json()
        assert res_data["status"] == "success"
        job_id = res_data["job_id"]
        assert job_id is not None

        # Check job status
        status_resp = client.get(f"/api/jobs/{job_id}/status", headers=headers)
        assert status_resp.status_code == 200
        job_data = status_resp.json()
        
        # Verify job is either Complete or processing finished
        assert job_data["status"] in ("Complete", "Uploading...", "Ingesting Data & Mapping Schema...", "Starting the agent workflow...", "Preparing visual engine...") or "report_id" in job_data
        
        report_id = job_data.get("report_id")
        # In case the background task executed synchronously
        if report_id:
            # Retrieve report
            report_resp = client.get(f"/api/reports/{report_id}", headers=headers)
            assert report_resp.status_code == 200
            report_data = report_resp.json()
            assert report_data["report"]["executiveSummary"] == "This is a mock executive summary."

            # List reports
            list_resp = client.get("/api/reports", headers=headers)
            assert list_resp.status_code == 200
            reports_list = list_resp.json()
            assert any(r["id"] == report_id for r in reports_list)

            # Export report as PDF
            pdf_resp = client.get(f"/api/export/{report_id}/pdf", headers=headers)
            assert pdf_resp.status_code == 200
            assert pdf_resp.headers["content-type"] == "application/pdf"

            # Export report as DOCX
            docx_resp = client.get(f"/api/export/{report_id}/docx", headers=headers)
            assert docx_resp.status_code == 200
            assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in docx_resp.headers["content-type"]

            # Get charts
            charts_resp = client.get(f"/api/charts/{report_id}", headers=headers)
            assert charts_resp.status_code == 200
            assert "charts" in charts_resp.json()
