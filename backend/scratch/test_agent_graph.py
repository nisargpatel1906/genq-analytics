# test_agent_graph.py

import sys
sys.path.insert(0, '.')

import pandas as pd
from unittest.mock import patch, MagicMock
from services.agent_graph import AnalysisState, AgentGraph

print("Running AgentGraph orchestration test...")

df = pd.DataFrame({'a': range(10)})
schema = {'a': 'int'}
sample_rows = [{'a': 0}, {'a': 1}]
domain_brief = {
    "domain": "Test Domain",
    "datasetPurpose": "Testing",
    "datasetType": "cross-sectional",
    "importantColumns": ["a"],
    "keyCharacteristics": {"missing_values": {}}
}

mock_data_scientist_code = """
import json
results = {
    "findings": [
        {"title": "Test Finding", "evidence": "Value is computed", "confidence": 95}
    ],
    "anomalies": [],
    "recommendation_seeds": []
}
with open("results.json", "w", encoding="utf-8") as f:
    json.dump(results, f)

manifest = {
    "outputs": [
        {
            "filename": "results.json",
            "type": "analysis_results",
            "primary": True
        }
    ]
}
with open("manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f)
"""

mock_reflector_response = '{"needs_more_analysis": false, "feedback": ""}'

mock_viz_coder_code = """
import json
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot([1, 2], [3, 4])
plt.savefig("chart_0.png")
plt.close(fig)

manifest = {
    "outputs": [
        {
            "filename": "chart_0.png",
            "type": "image",
            "finding_title": "Test Plot",
            "interpretation": "Line chart"
        }
    ]
}
with open("manifest.json", "w", encoding="utf-8") as f:
    json.dump(manifest, f)
"""

mock_report_writer_response = """
{
  "domain": "Test Domain",
  "executiveSummary": "Paragraph 1\\n\\nParagraph 2\\n\\nParagraph 3",
  "keyFindings": [
    {"title": "Test Finding", "detail": "Test detail", "confidence": 95}
  ],
  "anomalies": [],
  "recommendations": []
}
"""

mock_auditor_response = """
{
  "approved": true,
  "score": 90,
  "sectionScores": {"analytics": 90, "visuals": 90, "report": 90},
  "summary": "Audit approved.",
  "issues": [],
  "retryTargets": []
}
"""

# Let's count calls to track progress
call_count = 0

def mock_chat_completion(messages, task, **kwargs):
    global call_count
    call_count += 1
    
    if task == "analysis":
        # Data Scientist
        return f"```python\n{mock_data_scientist_code}\n```"
    elif task == "review":
        # Reflector or Auditor
        # Reflector runs before visuals, Auditor runs after report
        # We can distinguish by system prompt content
        system_content = messages[0]["content"]
        if "reflection" in system_content.lower():
            return mock_reflector_response
        else:
            return mock_auditor_response
    elif task == "visual":
        # Viz Coder
        return f"```python\n{mock_viz_coder_code}\n```"
    elif task == "report":
        # Report Writer
        return mock_report_writer_response
    
    raise ValueError(f"Unknown task {task}")

# Patch chat_completion
with patch("services.agent_graph.chat_completion", side_effect=mock_chat_completion):
    progress_stages = []
    
    def progress_cb(event):
        progress_stages.append(event["id"])
        
    state = AnalysisState(
        df=df,
        schema=schema,
        sample_rows=sample_rows,
        domain_brief=domain_brief,
        progress_callback=progress_cb,
        max_reflections=1,
        max_regeneration_rounds=1
    )
    
    graph = AgentGraph(state)
    report = graph.run()
    
    assert "error" not in report, f"Report returned error: {report.get('error')}"
    assert report["domain"] == "Test Domain"
    assert len(report["keyFindings"]) == 1
    
    # Check that we ran all stages
    print("Stages completed:", set(progress_stages))
    assert "data_scientist" in progress_stages
    assert "reflector" in progress_stages
    assert "viz_coder" in progress_stages
    assert "report_writer" in progress_stages
    assert "auditor" in progress_stages
    
    # Check that charts were populated
    assert len(state.chart_images) == 1
    assert state.chart_images[0]["filename"] == "chart_0.png"
    assert state.chart_images[0]["title"] == "Test Plot"
    assert len(state.chart_images[0]["data"]) > 0  # check image bytes
    
    print("AgentGraph integration test: PASSED")
