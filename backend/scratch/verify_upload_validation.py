import os
import sys
import time
import threading
import requests
import uvicorn

# Configure environment before imports
os.environ["GENQ_API_KEY"] = "super-secret-upload-key"
os.environ["MAX_FILE_SIZE_MB"] = "2"

# Add backend directory to Python path
sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")
from main import app
from app.db import jobs

def run_tests():
    # Start uvicorn in a background thread
    config = uvicorn.Config(app, host="127.0.0.1", port=8087, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run)
    thread.daemon = True
    thread.start()

    # Wait for server to boot up
    time.sleep(1.5)

    base_url = "http://127.0.0.1:8087/api/upload"
    headers = {"X-API-Key": "super-secret-upload-key"}

    try:
        # 1. Test missing API key
        print("Test 1: Missing API key...")
        res = requests.post(base_url, files={"file": ("test.csv", "a,b,c\n1,2,3", "text/csv")})
        print(f"--> Status: {res.status_code}")
        assert res.status_code == 401, f"Expected 401, got {res.status_code}"

        # 2. Test valid CSV upload
        print("\nTest 2: Valid CSV upload...")
        res = requests.post(
            base_url,
            headers=headers,
            files={"file": ("test.csv", "col1,col2\nval1,val2", "text/csv")}
        )
        print(f"--> Status: {res.status_code}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert res.json()["status"] == "success"
        job_id = res.json()["job_id"]
        print(f"--> Job ID: {job_id}")

        # 3. Test valid XLSX upload
        print("\nTest 3: Valid XLSX upload...")
        res = requests.post(
            base_url,
            headers=headers,
            files={"file": ("test.xlsx", b"dummy xlsx content", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
        print(f"--> Status: {res.status_code}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"

        # 4. Test invalid file extension (txt)
        print("\nTest 4: Invalid extension (.txt)...")
        res = requests.post(
            base_url,
            headers=headers,
            files={"file": ("test.txt", "some text content", "text/csv")}
        )
        print(f"--> Status: {res.status_code}")
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"

        # 5. Test invalid MIME type
        print("\nTest 5: Invalid MIME type...")
        res = requests.post(
            base_url,
            headers=headers,
            files={"file": ("test.csv", "a,b,c\n1,2,3", "image/png")}
        )
        print(f"--> Status: {res.status_code}")
        assert res.status_code == 400, f"Expected 400, got {res.status_code}"

        # 6. Test file size limit (2MB) - uploading 3MB of data
        print("\nTest 6: Exceeding file size limit (3MB, max is 2MB)...")
        large_content = "a" * (3 * 1024 * 1024)
        res = requests.post(
            base_url,
            headers=headers,
            files={"file": ("test.csv", large_content, "text/csv")}
        )
        print(f"--> Status: {res.status_code}")
        assert res.status_code == 413, f"Expected 413, got {res.status_code}"

        # 7. Test concurrency limit (3 active jobs)
        print("\nTest 7: Testing concurrency limit (adding 3 active jobs)...")
        # Populate in-memory db with 3 active jobs
        jobs["dummy_job1"] = {"status": "Running"}
        jobs["dummy_job2"] = {"status": "Analyzing..."}
        jobs["dummy_job3"] = {"status": "Ingesting Data & Mapping Schema..."}
        
        res = requests.post(
            base_url,
            headers=headers,
            files={"file": ("test.csv", "a,b,c\n1,2,3", "text/csv")}
        )
        print(f"--> Status: {res.status_code}")
        assert res.status_code == 429, f"Expected 429, got {res.status_code}"

        # Clean up
        del jobs["dummy_job1"]
        del jobs["dummy_job2"]
        del jobs["dummy_job3"]
        print("--> Concurrency test cleaned up.")

        print("\nALL UPLOAD VALIDATION CHECKS PASSED SUCCESSFULLY!")

    finally:
        # Shutdown server
        server.should_exit = True
        thread.join(timeout=2)

if __name__ == "__main__":
    run_tests()
