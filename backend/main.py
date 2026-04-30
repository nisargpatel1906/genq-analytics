import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import time
from app.api import upload, reports, export, chat

# Configure logging to write to a file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("genq_analytics.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("genq_api")

app = FastAPI(title="GenQ Analytics API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = '{0:.2f}'.format(process_time)
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Time: {formatted_process_time}ms")
    return response

app.include_router(upload.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(chat.router, prefix="/api")

@app.get("/")
def read_root():
    logger.info("Root endpoint accessed")
    return {"status": "ok", "message": "GenQ Analytics API"}
