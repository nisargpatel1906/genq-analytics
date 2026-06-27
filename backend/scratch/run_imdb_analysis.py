# scratch/run_imdb_analysis.py

import os
import sys
import pandas as pd
import json

sys.path.insert(0, '.')

# Ensure correct API keys are loaded
from dotenv import load_dotenv
load_dotenv()

from services.analyzer import analyze_dataframe

print("Loading IMDB Dataset...")
df = pd.read_csv("../IMDB Dataset.csv")


print("Running new agentic code-generating workflow...")

def progress_callback(event):
    print(f"[{event.get('currentAgent')}] Status: {event.get('status')} | Detail: {event.get('detail')}")

report = analyze_dataframe(df, progress_callback=progress_callback)

print("\n--- REPORT GENERATED ---")
if "error" in report:
    print(f"Error: {report['error']}")
else:
    print(json.dumps(report, indent=2))
    with open("scratch/imdb_generated_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print("\nSaved report to scratch/imdb_generated_report.json")
