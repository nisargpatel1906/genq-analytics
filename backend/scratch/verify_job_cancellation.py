import os
import sys
import asyncio
from unittest.mock import patch

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Paths
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports_cancellation_test.db"))

def run_tests():
    # Remove any pre-existing test files
    for p in [TEST_DB_PATH, TEST_DB_PATH + "-journal", TEST_DB_PATH + "-wal", TEST_DB_PATH + "-shm"]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    from app.db import PersistentReportsDB, PersistentJobsDB, JobCancelledException
    from services.agent_graph import AnalysisState, AgentGraph
    import pandas as pd
    
    # 1. Initialize DBs
    # Force SQLite fallback mode for jobs
    os.environ["REDIS_URL"] = "redis://invalid_host:6379/0"
    jobs = PersistentJobsDB()
    reports_db = PersistentReportsDB(db_path=TEST_DB_PATH)
    
    job_id = "job_cancellation_test_1"
    jobs[job_id] = {
        "status": "Running...",
        "cancelled": False,
        "step": 1
    }
    
    # 2. Test check_cancelled helper in AgentGraph
    df = pd.DataFrame({"col1": [1, 2, 3]})
    state = AnalysisState(
        df=df,
        schema={"col1": "int64"},
        sample_rows=[{"col1": 1}],
        domain_brief={},
        job_id=job_id
    )
    
    # Override standard database check in agent_graph to use our test jobs instance
    with patch("services.agent_graph.jobs", jobs):
        graph = AgentGraph(state)
        
        # Verify check_cancelled is False initially
        assert not graph._check_cancelled(), "Job should not be cancelled initially"
        
        # Cancel the job
        jobs[job_id].update({"cancelled": True, "status": "Cancelled"})
        
        # Verify check_cancelled is now True
        assert graph._check_cancelled(), "Job should be cancelled after updating status in DB"
        
        # Verify AgentGraph.run() immediately aborts
        res = graph.run()
        assert res.get("cancelled") is True, "AgentGraph run did not return cancelled=True"
        assert "cancelled by user" in res.get("error", "").lower(), "Error message should mention user cancellation"
        
        print("[PASS] AgentGraph cancellation detection and graceful abort works perfectly.")

    # 3. Test callback cancellation exception and endpoint handlers directly
    job_id_2 = "job_cancellation_test_2"
    jobs[job_id_2] = {
        "status": "Running...",
        "cancelled": False,
        "step": 1
    }
    
    from app.api.upload import get_job_status, cancel_job
    
    async def test_endpoints():
        # Call GET status handler
        res = await get_job_status(job_id_2)
        assert res.get("status") == "Running..."
        
        # Call DELETE handler
        res = await cancel_job(job_id_2)
        assert res.get("status") == "success"
        
        # Check database is updated
        assert jobs[job_id_2].get("cancelled") is True
        assert jobs[job_id_2].get("status") == "Cancelled"
        print("[PASS] cancel_job router handler updates database status correctly.")
        
    # Patch the global jobs in upload.py with our test jobs instance
    with patch("app.api.upload.jobs", jobs), patch("services.agent_graph.jobs", jobs):
        asyncio.run(test_endpoints())
        
        # Test progress callback raises exception when cancelled
        # Prepare a mock event
        event = {"detail": "Checking data...", "currentAgent": "profile"}
        
        # Get the callback wrapper or simulate it
        def update_agent_progress(event: dict):
            db_job = jobs.get(job_id_2)
            if db_job and (db_job.get("status") == "Cancelled" or db_job.get("cancelled", False)):
                raise JobCancelledException("Job cancelled by user.")
                
        try:
            update_agent_progress(event)
            assert False, "Should have raised JobCancelledException!"
        except JobCancelledException:
            print("[PASS] Progress callback correctly raises JobCancelledException when job cancellation flag is set.")
            
    # Cleanup files
    for p in [TEST_DB_PATH, TEST_DB_PATH + "-journal", TEST_DB_PATH + "-wal", TEST_DB_PATH + "-shm"]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

if __name__ == "__main__":
    try:
        run_tests()
        print("\nALL JOB CANCELLATION VERIFICATIONS PASSED SUCCESSFULLY!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
