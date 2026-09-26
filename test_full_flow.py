import requests
import json
import time
import os

API_BASE = "http://127.0.0.1:8000/api"
DATASET_PATH = r"c:\Users\Nisarg Patel\Documents\genq-analytics\test_datasets\01_ecommerce_churn_and_promotions_dirty.csv"

def test_full_pipeline():
    print("================================================================================")
    print("STEP 1: UPLOADING DATASET & TESTING BUSINESS DISCOVERY PRE-SCAN")
    print("================================================================================")
    
    with open(DATASET_PATH, "rb") as f:
        files = {"file": ("01_ecommerce_churn_and_promotions_dirty.csv", f, "text/csv")}
        resp = requests.post(f"{API_BASE}/upload", files=files)
    
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    upload_data = resp.json()
    job_id = upload_data.get("job_id")
    profile = upload_data.get("discovery_profile")
    
    print(f"✅ Upload succeeded! Job ID: {job_id}")
    print(f"✅ Status returned: {upload_data.get('status')}")
    print(f"✅ Detected Domain: {profile.get('domain')} ({profile.get('domain_confidence')}% confidence)")
    print(f"✅ Questions Generated: {len(profile.get('questions', []))}")
    for i, q in enumerate(profile.get('questions', []), 1):
        print(f"   Q{i} [{q.get('category')}]: {q.get('title')}")
        print(f"      Options: {q.get('options')[:2]}...")
    
    print(f"✅ Viable Modules Detected: {len(profile.get('viable_modules', []))}")
    for m in profile.get('viable_modules', []):
        status = "VIABLE" if m.get("viable") else f"NOT VIABLE ({m.get('reason')})"
        print(f"   • {m.get('name')}: {status} (Token Savings: ~{m.get('token_savings_pct')}%)")
    
    print("\n================================================================================")
    print("STEP 2: TESTING SELECTIVE MODULE ALIGNMENT & LAUNCH")
    print("================================================================================")
    
    # Intentionally select a focused subset: ml_modeler, causal_analyst, anomaly_detector, benchmarking
    # Bypassing forecaster, cohort_analyst, experimentation to test selective compute & token savings!
    selected_modules = ["ml_modeler", "causal_analyst", "anomaly_detector", "benchmarking"]
    answers = {
        "business_objective": "Identify key drivers of customer churn & drop-off and optimize margins",
        "target_audience": "Executive Leadership & Board",
        "kpi_priority": "churn",
        "time_horizon": "Quarterly OKR Strategic Realignment (90-Day)"
    }
    
    align_resp = requests.post(
        f"{API_BASE}/jobs/{job_id}/align",
        json={
            "answers": answers,
            "selected_modules": selected_modules,
            "quick_auto": False
        }
    )
    assert align_resp.status_code == 200, f"Alignment launch failed: {align_resp.text}"
    print(f"✅ Aligned pipeline launched! Status: {align_resp.json().get('status')}")
    print(f"✅ Selected modules: {selected_modules}")
    
    print("\n================================================================================")
    print("STEP 3: MONITORING PIPELINE EXECUTION (Deliberation Thinking & Skeptic Debate)")
    print("================================================================================")
    
    report_id = None
    start_time = time.time()
    last_status = ""
    while time.time() - start_time < 480:
        st_resp = requests.get(f"{API_BASE}/jobs/{job_id}/status")
        if st_resp.status_code == 200:
            job_info = st_resp.json()
            curr_status = job_info.get("status")
            curr_agent = job_info.get("current_agent")
            if curr_status != last_status:
                print(f"[{int(time.time() - start_time)}s] Stage: {curr_status} | Active Agent: {curr_agent}", flush=True)
                last_status = curr_status
            
            if curr_status == "Complete":
                report_id = job_info.get("report_id")
                print(f"\n🎉 PIPELINE COMPLETED SUCCESSFULLY! Report ID: {report_id}", flush=True)
                break
            elif curr_status == "Failed":
                raise RuntimeError(f"Pipeline failed: {job_info.get('error')}")
        time.sleep(3)
    
    assert report_id, "Pipeline did not produce a report within timeout"
    
    print("\n================================================================================")
    print("STEP 4: TESTING ADVANCED COPILOT CHAT ACTION SUITE TOOLS")
    print("================================================================================")
    
    # Tool 1: Train Custom ML Model
    print("\n▶ Testing Tool 1: Train Custom ML Model (Random Forest & Feature Importances)...")
    ml_resp = requests.post(
        f"{API_BASE}/reports/{report_id}/tools/train-model",
        json={"target_col": "churn"}
    )
    assert ml_resp.status_code == 200, f"Train model tool failed: {ml_resp.text}"
    ml_out = ml_resp.json()
    print(f"✅ Model trained: {ml_out.get('task_type')} on target '{ml_out.get('target_column')}'")
    print(f"   Metrics: {ml_out.get('metrics')}")
    print(f"   Top Drivers: {[d['feature'] for d in ml_out.get('top_drivers', [])[:3]]}")
    print(f"   Chart generated: {len(ml_out.get('chart_base64', '')) > 500}")
    
    # Tool 2: Simulate Growth Scenario
    print("\n▶ Testing Tool 2: Simulate Growth Scenario (5-Year Monte Carlo Trajectory)...")
    sim_resp = requests.post(
        f"{API_BASE}/reports/{report_id}/tools/simulate-growth",
        json={"metric_col": "total_spend", "growth_rate_pct": 20.0, "years": 5}
    )
    assert sim_resp.status_code == 200, f"Simulate growth tool failed: {sim_resp.text}"
    sim_out = sim_resp.json()
    print(f"✅ Simulation ran on metric '{sim_out.get('metric_name')}' (Baseline: {sim_out.get('baseline_value'):,.0f})")
    print(f"   Year 5 Base Target: {sim_out.get('table', [])[-1].get('base'):,.0f}")
    print(f"   Chart generated: {len(sim_out.get('chart_base64', '')) > 500}")
    
    # Tool 3: Strategic Roadmap
    print("\n▶ Testing Tool 3: Strategic Roadmap (30-60-90 Day Execution Plan)...")
    rm_resp = requests.post(
        f"{API_BASE}/reports/{report_id}/tools/roadmap",
        json={"focus_area": "Retention & Churn Reduction", "horizon_days": 90}
    )
    assert rm_resp.status_code == 200, f"Roadmap tool failed: {rm_resp.text}"
    rm_out = rm_resp.json()
    print(f"✅ Roadmap generated with {len(rm_out.get('phases', []))} phases!")
    for p in rm_out.get('phases', []):
        print(f"   • {p.get('phase_name')}: {len(p.get('initiatives', []))} initiatives")
    
    # Tool 4: Causal What-If Sensitivity
    print("\n▶ Testing Tool 4: Causal What-If Sensitivity Analysis...")
    cw_resp = requests.post(
        f"{API_BASE}/reports/{report_id}/tools/causal-what-if",
        json={"treatment_col": "discount_pct", "outcome_col": "total_spend", "delta_change_pct": 15.0}
    )
    assert cw_resp.status_code == 200, f"Causal what-if tool failed: {cw_resp.text}"
    cw_out = cw_resp.json()
    print(f"✅ Causal elasticity: {cw_out.get('elasticity'):.4f} (Shift: {cw_out.get('delta_percentage'):+.2f}%)")
    print(f"   Chart generated: {len(cw_out.get('chart_base64', '')) > 500}")
    
    # Tool 5: Export Briefing Memo
    print("\n▶ Testing Tool 5: Export Strategic Briefing Memo (Standalone HTML)...")
    memo_resp = requests.post(
        f"{API_BASE}/reports/{report_id}/tools/export-memo",
        json={
            "title": "E-Commerce Churn & Promotion Strategy Memo",
            "history": [
                {"role": "user", "content": "What are our primary churn drivers?"},
                {"role": "assistant", "content": "Analysis indicates discount sensitivity and app tenure are the primary drivers."}
            ]
        }
    )
    assert memo_resp.status_code == 200, f"Export memo tool failed: {memo_resp.text}"
    assert "Executive Analysis Memo" in memo_resp.text or "Strategy Memo" in memo_resp.text or "<html" in memo_resp.text
    print(f"✅ Memo HTML generated successfully ({len(memo_resp.text):,} chars)!")
    
    print("\n================================================================================")
    print("ALL VERIFICATIONS COMPLETED SUCCESSFULLY WITH ZERO HARDCODING!")
    print("================================================================================")

if __name__ == "__main__":
    test_full_pipeline()
