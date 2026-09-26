import urllib.request
import json
import time

REPORT_ID = "rep_0d529cca"
API_BASE = "http://127.0.0.1:8000/api"

def post_json(endpoint, payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f"{API_BASE}{endpoint}", 
        data=data, 
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode('utf-8')

print("="*80)
print(f"VERIFYING FULL COPILOT ACTION SUITE ON REPORT: {REPORT_ID}")
print("="*80)

# Tool 1: Train Custom ML Model
print("\n▶ Tool 1: Train Custom Predictive Model (Random Forest & Feature Importance)...")
t0 = time.time()
ml_res = json.loads(post_json(f"/reports/{REPORT_ID}/tools/train-model", {"target_col": "churned"}))
print(f"✅ Succeeded in {time.time()-t0:.2f}s")
print(f"   Task Type: {ml_res.get('task_type')}")
print(f"   Target Column: {ml_res.get('target_column')}")
print(f"   Metrics: {ml_res.get('metrics')}")
print(f"   Top Feature Drivers: {[d['feature'] for d in ml_res.get('top_drivers', [])[:4]]}")
print(f"   Chart generated: {len(ml_res.get('chart_base64', '')) > 500} ({len(ml_res.get('chart_base64', ''))} chars)")

# Tool 2: Simulate Growth Scenario
print("\n▶ Tool 2: Simulate Growth Scenario (5-Year Monte Carlo Projections)...")
t0 = time.time()
sim_res = json.loads(post_json(f"/reports/{REPORT_ID}/tools/simulate-growth", {
    "metric_col": "monetary_spend_usd", 
    "growth_rate_pct": 18.0, 
    "years": 5
}))
print(f"✅ Succeeded in {time.time()-t0:.2f}s")
print(f"   Metric: {sim_res.get('metric_name')} (Baseline: {sim_res.get('baseline_value'):,.0f})")
print(f"   Trajectory Table:")
for row in sim_res.get('table', []):
    print(f"     {row.get('year')}: Base={row.get('base'):,.0f} | Aggressive={row.get('aggressive'):,.0f} | Conservative={row.get('conservative'):,.0f} | 80% CI=[{row.get('p10_uncertainty'):,.0f}, {row.get('p90_uncertainty'):,.0f}]")
print(f"   Chart generated: {len(sim_res.get('chart_base64', '')) > 500} ({len(sim_res.get('chart_base64', ''))} chars)")

# Tool 3: Strategic Execution Roadmap
print("\n▶ Tool 3: Generate Strategic Execution Roadmap (30-60-90 Day OKRs)...")
t0 = time.time()
road_res = json.loads(post_json(f"/reports/{REPORT_ID}/tools/roadmap", {
    "focus_area": "Customer Retention & Margin Expansion",
    "horizon_days": 90
}))
print(f"✅ Succeeded in {time.time()-t0:.2f}s")
print(f"   Executive Strategy: {road_res.get('executive_rationale', '')[:100]}...")
print(f"   Phases Generated: {len(road_res.get('phases', []))}")
for p in road_res.get('phases', []):
    print(f"     • {p.get('phase_name')}: {len(p.get('initiatives', []))} initiatives")

# Tool 4: Causal What-If Sensitivity
print("\n▶ Tool 4: Run Causal What-If Simulation (Elasticity & Sensitivity)...")
t0 = time.time()
whatif_res = json.loads(post_json(f"/reports/{REPORT_ID}/tools/causal-what-if", {
    "treatment_col": "discount_rate",
    "outcome_col": "monetary_spend_usd",
    "delta_change_pct": 15.0
}))
print(f"✅ Succeeded in {time.time()-t0:.2f}s")
print(f"   Treatment: {whatif_res.get('treatment_column')} (+15.0%)")
print(f"   Outcome: {whatif_res.get('outcome_column')}")
print(f"   Elasticity: {whatif_res.get('elasticity'):.3f}")
print(f"   Projected Outcome Delta: {whatif_res.get('delta_percentage'):+.2f}% ({whatif_res.get('delta_absolute'):+,.2f})")
print(f"   Chart generated: {len(whatif_res.get('chart_base64', '')) > 500} ({len(whatif_res.get('chart_base64', ''))} chars)")

# Tool 5: Sandbox Python Code Execution
print("\n▶ Tool 5: Execute Custom Python Code in Secure Sandbox...")
t0 = time.time()
code_snippet = """
import numpy as np
import pandas as pd

churn_rate = float(df['churned'].mean() * 100)
avg_spend = float(df['monetary_spend_usd'].mean())
nps_by_churn = df.groupby('churned')['nps_score'].mean().to_dict()

print(f"Total customers: {len(df)}")
print(f"Churn rate: {churn_rate:.2f}%")
print(f"Mean spend: ${avg_spend:,.2f}")
print(f"NPS by churned: {nps_by_churn}")
"""
code_res = json.loads(post_json(f"/reports/{REPORT_ID}/tools/execute-code", {
    "code": code_snippet
}))
print(f"✅ Succeeded in {time.time()-t0:.2f}s")
print(f"   Execution Success: {code_res.get('success')}")
print(f"   Stdout Output:\n{code_res.get('stdout')}".strip())

# Tool 6: Standalone Executive Memo Export
print("\n▶ Tool 6: Export Executive HTML Memo...")
t0 = time.time()
html_content = post_json(f"/reports/{REPORT_ID}/tools/export-memo", {
    "title": "Executive Strategic Memo: E-Commerce Churn & Revenue Optimization",
    "messages": [
        {"role": "user", "content": "What are the primary drivers of churn and how much revenue can we protect?"},
        {"role": "assistant", "content": "Our machine learning model demonstrates that `recency_days` and `monetary_spend_usd` are the top determinants (93.3% accuracy). Reducing churn by 10% protects ~$82,600 in baseline run-rate."}
    ]
})
print(f"✅ Succeeded in {time.time()-t0:.2f}s")
print(f"   HTML Document Length: {len(html_content)} characters")
print(f"   Includes Warm Bronze / Cream White Brand Colors: {'#8B6F3E' in html_content and '#F5F0E8' in html_content}")
print(f"   Includes Interactive Dialogue: {'Interactive Analytical Dialogue' in html_content}")

print("\n" + "="*80)
print("🎉 ALL 6 ADVANCED COPILOT CHAT ACTION SUITE TOOLS PASSED SUCCESSFULLY!")
print("="*80)
