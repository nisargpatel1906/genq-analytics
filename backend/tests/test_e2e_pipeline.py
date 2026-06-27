import os
import json
import io
import pytest
from unittest.mock import patch
from docx import Document

@pytest.fixture(autouse=True)
def set_env_api_key():
    with patch.dict(os.environ, {
        "GENQ_API_KEY": "test_api_key",
        "MAX_FILE_SIZE_MB": "500",
        "LLM_VALIDATE_ON_FULL_DATA": "false",
        "LLM_MAX_REGENERATION_ROUNDS": "1",
        "AGENT_MAX_REFLECTIONS": "1",
        "LLM_NARRATIVE_STITCHER": "true"
    }):
        yield

def mock_chat_completion(messages, task, json_mode=False, timeout=600):
    if task == "analysis":
        # ReAct tool calling loop simulation.
        # len(messages) == 2 -> Turn 1
        # len(messages) == 4 -> Turn 2
        # len(messages) == 6 -> Turn 3
        # len(messages) == 8 -> Turn 4
        # len(messages) == 10 -> Turn 5
        turn = len(messages)
        if turn == 2:
            return json.dumps({
                "thought": "Inspect column col1",
                "tool": "inspect_column",
                "arguments": {"col_name": "col1"}
            })
        elif turn == 4:
            return json.dumps({
                "thought": "Run correlation between col1 and col2",
                "tool": "run_test",
                "arguments": {"test_type": "correlation", "col_a": "col1", "col_b": "col2"}
            })
        elif turn == 6:
            return json.dumps({
                "thought": "Create scatter plot",
                "tool": "create_chart",
                "arguments": {"chart_type": "scatter", "x": "col1", "y": "col2"}
            })
        elif turn == 8:
            return json.dumps({
                "thought": "Save finding",
                "tool": "save_finding",
                "arguments": {"title": "Col1 Col2 Correlation", "evidence": "Strong positive correlation observed", "confidence": 95}
            })
        else:
            return json.dumps({
                "thought": "All done",
                "tool": "done",
                "arguments": {}
            })
    elif task == "review":
        # Reflector or Auditor
        system_content = messages[0]["content"]
        if "reflection" in system_content.lower() or "supervisor" in system_content.lower():
            # Reflector
            return json.dumps({
                "needs_more_analysis": False,
                "feedback": "",
                "follow_up_tasks": []
            })
        else:
            # Auditor
            return json.dumps({
                "approved": True,
                "score": 95,
                "sectionScores": {"analytics": 95, "visuals": 95, "report": 95},
                "summary": "Perfect report.",
                "issues": [],
                "retryTargets": []
            })
    elif task == "visual":
        # Viz Coder
        return """```python
import json
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.scatter([10, 30], [20, 40])
plt.savefig("chart_0.png")
plt.close(fig)

manifest = {
    "outputs": [
        {
            "filename": "chart_0.png",
            "type": "image",
            "finding_title": "Col1 Col2 Correlation",
            "interpretation": "Positive trend line visible between Col1 and Col2.",
            "insight_text": "Strong linear relationship"
        }
    ]
}
with open("manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f)
```"""
    elif task == "report":
        # Report Writer or Narrative Stitcher
        is_stitcher = any("executive editor" in m.get("content", "").lower() for m in messages)
        if not is_stitcher:
            # Report Writer
            return json.dumps({
                "domain": "Test Domain",
                "executiveSummary": "Paragraph 1 describing test analysis.\n\nParagraph 2 with findings details.\n\nParagraph 3 containing actionable insights.",
                "keyFindings": [
                    {
                        "title": "Col1 Col2 Correlation",
                        "detail": "Detailed evidence of positive trend between col1 and col2.",
                        "confidence": 95,
                        "impact_score": 8,
                        "supporting_chart": "chart_0.png"
                    }
                ],
                "anomalies": [],
                "recommendations": [
                    {
                        "action": "Investigate col1 further",
                        "rationale": "High variance observed",
                        "priority": "medium"
                    }
                ]
            })
        else:
            # Narrative Stitcher
            return "Polished Paragraph 1.\n\nPolished Paragraph 2.\n\nPolished Paragraph 3."
    else:
        raise ValueError(f"Unknown task {task}")

@patch("services.agent_graph.chat_completion", side_effect=mock_chat_completion)
@patch("services.analyzer.chat_completion", return_value='{"domain": "Test Domain", "domainConfidence": 95, "datasetPurpose": "Testing", "importantColumns": ["col1"]}')
def test_e2e_pipeline_and_docx_export(mock_analyzer_completion, mock_graph_completion, client):
    headers = {"X-API-Key": "test_api_key"}
    
    # 1. Upload the CSV file
    file_content = b"col1,col2\n10,20\n30,40"
    upload_response = client.post(
        "/api/upload",
        files={"file": ("test.csv", file_content, "text/csv")},
        headers=headers
    )
    assert upload_response.status_code == 200
    upload_data = upload_response.json()
    assert upload_data["status"] == "success"
    job_id = upload_data["job_id"]
    
    # 2. Check Job Status (FastAPI runs background tasks synchronously under TestClient)
    status_response = client.get(f"/api/jobs/{job_id}/status", headers=headers)
    assert status_response.status_code == 200
    job_data = status_response.json()
    assert job_data["status"] == "Complete"
    report_id = job_data["report_id"]
    assert report_id is not None
    
    # 3. Retrieve Report data to verify metadata and DB entry
    report_response = client.get(f"/api/reports/{report_id}", headers=headers)
    assert report_response.status_code == 200
    report_res = report_response.json()
    assert report_res["report"]["domain"] == "Test Domain"
    
    # 4. Verify DOCX Export Endpoint
    docx_response = client.get(f"/api/export/{report_id}/docx", headers=headers)
    assert docx_response.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in docx_response.headers["content-type"]
    
    # Read DOCX bytes and parse using python-docx
    docx_bytes = docx_response.content
    doc = Document(io.BytesIO(docx_bytes))
    
    # Assert cover page properties, text, and headings
    text_content = []
    for p in doc.paragraphs:
        if p.text:
            text_content.append(p.text)
            
    full_text = "\n".join(text_content)
    assert "AI Data Analysis Report" in full_text
    assert "Test Domain" in full_text
    assert "Col1 Col2 Correlation" in full_text
    assert "Investigate col1 further" in full_text
    
    # Assert that the custom chart is embedded as an inline image shape
    inline_shapes = []
    for section in doc.sections:
        # Check doc body inline shapes
        pass
    
    # doc.inline_shapes contains all inline shapes in the document body
    assert len(doc.inline_shapes) >= 1, "Expected at least 1 chart image embedded in the DOCX document"
    
    # 5. Verify PDF Export works on this real data too
    pdf_response = client.get(f"/api/export/{report_id}/pdf", headers=headers)
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"] == "application/pdf"

    # 6. Verify Notebook Export endpoint
    nb_response = client.get(f"/api/export/{report_id}/notebook", headers=headers)
    assert nb_response.status_code == 200
    assert "application/x-ipynb+json" in nb_response.headers["content-type"]
    assert "Content-Disposition" in nb_response.headers
    assert ".ipynb" in nb_response.headers["Content-Disposition"]

    # Parse the .ipynb JSON structure
    nb_data = nb_response.json()
    assert nb_data["nbformat"] == 4
    assert isinstance(nb_data["cells"], list)
    assert len(nb_data["cells"]) >= 3   # At minimum: title, setup, overview

    # Verify title cell contains domain
    title_cell = nb_data["cells"][0]
    assert title_cell["cell_type"] == "markdown"
    assert "Test Domain" in title_cell["source"]

    # Verify findings appear somewhere in the notebook markdown cells
    all_md_text = "\n".join(
        c["source"] for c in nb_data["cells"] if c["cell_type"] == "markdown"
    )
    assert "Col1 Col2 Correlation" in all_md_text
