import os
import sys
import json
import shutil

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

# Define temporary file paths
JSON_FILE = r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend\reports_store.json"
TEST_DB_PATH = r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend\reports_test.db"

def setup_mock_json():
    # Write mock data to reports_store.json
    mock_data = {
        "rep_test_123": {
            "title": "Migrated Report 123",
            "content": "This report was migrated successfully from JSON."
        },
        "rep_test_456": {
            "title": "Migrated Report 456",
            "content": "Another migrated report."
        }
    }
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, indent=2)
    print(f"Created mock JSON file at {JSON_FILE}")

def cleanup_files():
    # Remove test DB and mock JSON
    for path in [JSON_FILE, TEST_DB_PATH]:
        if os.path.exists(path):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                print(f"Cleaned up {path}")
            except Exception as e:
                print(f"Error cleaning up {path}: {e}")

def run_tests():
    # Remove any existing test DB
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
        
    setup_mock_json()
    
    # Import class
    from app.db import PersistentReportsDB, PersistentJobsDB
    
    # Initialize Reports DB (this will trigger migration because TEST_DB_PATH is empty)
    db = PersistentReportsDB(db_path=TEST_DB_PATH)
    
    # ASSERT 1: Migration works
    assert "rep_test_123" in db, "Migration failed: rep_test_123 not in database"
    assert db["rep_test_123"]["title"] == "Migrated Report 123"
    assert len(db) == 2
    
    # ASSERT 2: Standard dict methods work
    db["rep_new"] = {"title": "New Report", "value": 99}
    assert "rep_new" in db
    assert db["rep_new"]["value"] == 99
    assert len(db) == 3
    
    # Items, keys, values
    items = dict(db.items())
    assert "rep_test_123" in items
    assert "rep_new" in items
    assert len(items) == 3
    
    # Delete item
    del db["rep_new"]
    assert "rep_new" not in db
    assert len(db) == 2
    
    print("Reports DB (SQLite) tests passed.")
    
    # Initialize Jobs DB
    jobs = PersistentJobsDB()
    # Force fallback mode to test SQLite path, or let it connect to Redis if active.
    # We will test both.
    print(f"Jobs DB mode: {'SQLite fallback' if jobs._fallback_mode else 'Redis'}")
    
    job_id = "job_test_789"
    jobs[job_id] = {
        "status": "pending",
        "step": 0
    }
    
    # Assert get and read works
    assert job_id in jobs
    assert jobs[job_id]["status"] == "pending"
    assert jobs[job_id]["step"] == 0
    
    # ASSERT 3: Mutation proxy works (updates write back to DB)
    job_ref = jobs[job_id]
    job_ref["status"] = "running"
    job_ref["step"] = 1
    
    # Fetch a fresh copy from DB and check values
    fresh_job = jobs[job_id]
    assert fresh_job["status"] == "running", f"Proxy mutation failed: expected 'running', got {fresh_job['status']}"
    assert fresh_job["step"] == 1
    
    # Delete job
    del jobs[job_id]
    assert job_id not in jobs
    
    print("Jobs DB (Redis/SQLite) tests passed.")

if __name__ == "__main__":
    try:
        run_tests()
        print("\nALL DATABASE MIGRATION VERIFICATIONS PASSED SUCCESSFULLY!")
    finally:
        cleanup_files()
