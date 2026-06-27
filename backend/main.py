import logging
import os
import sys
from fastapi import FastAPI, Request, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import time
from app.api import upload, reports, export_routes, chat

# Ensure standard output uses utf-8 encoding on Windows to prevent StreamHandler UnicodeEncodeErrors
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Configure logging to write to a file with utf-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "genq_analytics.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("genq_api")

app = FastAPI(title="GenQ Analytics API")

allowed_origins_raw = os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    formatted_process_time = '{0:.2f}'.format(process_time)
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Time: {formatted_process_time}ms")
    return response

async def verify_api_key(x_api_key: str = Header(None)):
    expected_key = os.environ.get("GENQ_API_KEY")
    if expected_key:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API Key")

app.include_router(upload.router, prefix="/api", dependencies=[Depends(verify_api_key)])
app.include_router(reports.router, prefix="/api", dependencies=[Depends(verify_api_key)])
app.include_router(export_routes.router, prefix="/api", dependencies=[Depends(verify_api_key)])
app.include_router(chat.router, prefix="/api", dependencies=[Depends(verify_api_key)])

@app.get("/")
def read_root():
    logger.info("Root endpoint accessed")
    return {"status": "ok", "message": "GenQ Analytics API"}
