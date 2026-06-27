import pytest
import os
import sys

# Ensure backend path is in sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Import db modules to redirect the db path BEFORE importing the FastAPI app
from app import db

TEST_DIR = os.path.dirname(__file__)
TEST_REPORTS_DB = os.path.join(TEST_DIR, "reports_test.db")
TEST_JOBS_DB = os.path.join(TEST_DIR, "jobs_test.db")

@pytest.fixture(scope="session", autouse=True)
def setup_test_databases():
    # Remove existing test databases if they exist
    for p in [TEST_REPORTS_DB, TEST_JOBS_DB, TEST_REPORTS_DB + "-journal", TEST_JOBS_DB + "-journal"]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    # Override db paths
    db.reports_db = db.PersistentReportsDB(db_path=TEST_REPORTS_DB)
    
    # Override jobs to SQLite fallback mode using test SQLite DB path
    db.jobs = db.PersistentJobsDB()
    db.jobs._fallback_mode = True
    db.jobs.sqlite_path = TEST_JOBS_DB
    db.jobs._init_sqlite_fallback()

    # Apply patches to API modules
    import app.api.upload
    import app.api.reports
    import app.api.export_routes
    app.api.upload.reports_db = db.reports_db
    app.api.upload.jobs = db.jobs
    app.api.reports.reports_db = db.reports_db
    app.api.export_routes.reports_db = db.reports_db

    yield

    # Clean up test databases
    for p in [TEST_REPORTS_DB, TEST_JOBS_DB, TEST_REPORTS_DB + "-journal", TEST_JOBS_DB + "-journal"]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)
