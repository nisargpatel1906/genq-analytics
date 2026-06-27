import os
import sys
import json
import sqlite3

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Paths
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports_split_test.db"))
DATA_DIR = os.path.join(os.path.dirname(TEST_DB_PATH), "data")
SAMPLES_DIR = os.path.join(DATA_DIR, "samples")
IMAGES_DIR = os.path.join(DATA_DIR, "images")

def run_tests():
    # Remove any pre-existing test files
    for p in [TEST_DB_PATH, TEST_DB_PATH + "-journal", TEST_DB_PATH + "-wal", TEST_DB_PATH + "-shm"]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
                
    # Instantiate DB
    from app.db import PersistentReportsDB
    db = PersistentReportsDB(db_path=TEST_DB_PATH)
    
    report_id = "rep_split_test_1"
    
    # Prepare mock large report
    mock_data_sample = [{"col1": f"val{i}", "col2": i} for i in range(5000)]
    mock_chart_images = ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="]
    
    mock_report = {
        "title": "Large Test Report",
        "description": "A report with large raw data and chart images.",
        "data_sample": mock_data_sample,
        "report": {
            "title": "Large Test Report Inner",
            "_meta": {
                "chart_images": mock_chart_images,
                "other_meta": "keep_this"
            }
        }
    }
    
    print("Saving mock report to DB...")
    db[report_id] = mock_report
    
    # Assert 1: Files are created on filesystem
    sample_file = os.path.join(SAMPLES_DIR, f"{report_id}_sample.json")
    image_file = os.path.join(IMAGES_DIR, f"{report_id}_images.json")
    
    assert os.path.exists(sample_file), f"Data sample file not created at {sample_file}"
    assert os.path.exists(image_file), f"Chart images file not created at {image_file}"
    print("[PASS] Files successfully saved to the filesystem.")
    
    # Assert 2: SQLite contains only metadata and not the heavy files
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM reports WHERE id = ?", (report_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None, "Report was not written to SQLite"
    db_json = json.loads(row[0])
    
    assert "data_sample" not in db_json, "data_sample was not stripped from SQLite record!"
    
    report_inner = db_json.get("report", {})
    _meta = report_inner.get("_meta", {})
    assert "chart_images" not in _meta, "chart_images was not stripped from SQLite record!"
    assert _meta.get("other_meta") == "keep_this", "Other metadata in _meta was accidentally stripped!"
    
    print("[PASS] SQLite database stores only lightweight metadata and strips heavy fields.")
    
    # Assert 3: Reading from DB restores the full report
    read_report = db[report_id]
    assert read_report.get("data_sample") == mock_data_sample, "Loaded data_sample does not match mock data sample!"
    
    read_inner = read_report.get("report", {})
    read_meta = read_inner.get("_meta", {})
    assert read_meta.get("chart_images") == mock_chart_images, "Loaded chart_images do not match mock chart images!"
    assert read_meta.get("other_meta") == "keep_this", "Loaded other_meta was lost!"
    print("[PASS] Reconstructing the report dynamically on read works perfectly.")
    
    # Assert 4: Deleting the report cleans up the files
    print("Deleting report from DB...")
    del db[report_id]
    
    assert not os.path.exists(sample_file), f"Data sample file still exists at {sample_file} after deletion!"
    assert not os.path.exists(image_file), f"Chart images file still exists at {image_file} after deletion!"
    
    # Assert SQLite has 0 records
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM reports")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 0, f"SQLite report record was not deleted. Count: {count}"
    print("[PASS] Filesystem cleanup and SQLite deletion work perfectly.")

def cleanup():
    # Clean up files created
    report_id = "rep_split_test_1"
    sample_file = os.path.join(SAMPLES_DIR, f"{report_id}_sample.json")
    image_file = os.path.join(IMAGES_DIR, f"{report_id}_images.json")
    for f in [sample_file, image_file, TEST_DB_PATH, TEST_DB_PATH + "-journal", TEST_DB_PATH + "-wal", TEST_DB_PATH + "-shm"]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass
                
    # Remove empty dirs if they are empty
    for d in [SAMPLES_DIR, IMAGES_DIR, DATA_DIR]:
        if os.path.exists(d) and not os.listdir(d):
            try:
                os.rmdir(d)
            except Exception:
                pass

if __name__ == "__main__":
    try:
        run_tests()
        print("\nALL SPLIT FILESYSTEM DB VERIFICATIONS PASSED SUCCESSFULLY!")
    finally:
        cleanup()
