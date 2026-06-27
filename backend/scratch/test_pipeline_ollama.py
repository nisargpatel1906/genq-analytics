import sys
sys.path.insert(0, '.')

import os
import json
import time
import pandas as pd
from dotenv import load_dotenv

# Set env overrides for testing local Ollama
os.environ["LLM_PROVIDER"] = "ollama"
os.environ["OLLAMA_MODEL"] = "gemma4:12b"
os.environ["LLM_MAX_REGENERATION_ROUNDS"] = "1"  # speed up test
os.environ["AGENT_MAX_REFLECTIONS"] = "1"        # speed up test
os.environ["ENABLE_NOTEBOOK_MODE"] = "true"       # test notebook mode

# Load other environment variables
load_dotenv()

from services.analyzer import analyze_dataframe

print("==================================================")
print("TESTING GENQ PIPELINE END-TO-END WITH OLLAMA")
print("Model: gemma4:12b")
print("==================================================")

# Load data sample from reports db
with open("reports_store.json", "r", encoding="utf-8") as f:
    db = json.load(f)

# Use rep_a0dea4e2 (instagram_posts.csv)
r_data = db.get("rep_a0dea4e2")
if not r_data:
    # fallback to any key
    r_id = list(db.keys())[-1]
    r_data = db[r_id]

print(f"Loading data sample for file: {r_data.get('filename')} (ID: {r_data.get('id')})")
data_sample = r_data.get("data_sample", [])
df = pd.DataFrame(data_sample)
print(f"DataFrame loaded: {df.shape[0]} rows, {df.shape[1]} columns")

def progress_callback(event):
    # Print the stage progress events as they happen
    detail = event.get("detail", "")
    agent = event.get("currentAgent", "")
    status = event.get("status", "")
    print(f"[{agent.upper()}] Status: {status} | {detail}")

t_start = time.perf_counter()
print("\nInitiating analyze_dataframe...")
result = analyze_dataframe(df, progress_callback=progress_callback)
t_elapsed = time.perf_counter() - t_start

print("\n=================== RESULT ===================")
if "error" in result:
    print(f"ERROR: {result['error']}")
else:
    print("SUCCESS!")
    print(f"Execution Time: {t_elapsed:.1f}s")
    print(f"Domain detected: {result.get('domain')}")
    print(f"Executive Summary paragraph count: {len(result.get('executiveSummary', '').split(chr(10)+chr(10)))}")
    print(f"Key Findings: {len(result.get('keyFindings', []))}")
    for idx, f in enumerate(result.get('keyFindings', []), 1):
        print(f"  {idx}. {f.get('title') or f.get('finding')} (confidence: {f.get('confidence') or f.get('confidenceScore')}%)")
    print(f"Anomalies: {len(result.get('anomalies', []))}")
    print(f"Recommendations: {len(result.get('recommendations', []))}")
    print("\nVisual plan charts generated:")
    visual_plan = result.get("_visualPlan", {})
    for chart in visual_plan.get("charts", []):
        print(f"  - Type: {chart.get('type')}, Title: {chart.get('title')}, Reason: {chart.get('reason')}")
print("==============================================")
