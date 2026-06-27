import logging
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.db import reports_db
from dotenv import load_dotenv
from services.llm import chat_completion, chat_completion_stream, provider_label

load_dotenv()

logger = logging.getLogger("genq_api.chat")
router = APIRouter()

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


CHAT_SYSTEM = """\
You are an expert data analyst assistant embedded in a reporting tool called GenQ Analytics.
You have full context about the dataset that was just analyzed — its schema, key statistics,
findings, anomalies, and recommendations are all provided to you below.

Your job is to:
- Answer questions about the data clearly and concisely.
- Help the user refine, rewrite, or extend parts of the report on request.
- When asked to rewrite a section (e.g. "make the executive summary shorter", 
  "add more detail to recommendation 2"), output the improved text directly.
- When asked a factual question, answer it using the data provided.
- Never invent data not present in the context.
- Keep responses focused and professional, under 300 words unless asked otherwise.

Respond in plain conversational text (no JSON, no markdown code blocks unless showing a table).
"""


def _build_context(report_data: dict) -> str:
    """Build a concise context string from the stored report for the LLM."""
    filename = report_data.get("filename", "unknown")
    stats = report_data.get("stats", {})
    shape = stats.get("shape", {})
    report = report_data.get("report", {})

    ctx_parts = [
        f"DATASET: {filename}",
        f"SIZE: {shape.get('rows', '?')} rows × {shape.get('columns', '?')} columns",
        f"DOMAIN: {report.get('domain', 'Not specified')}",
        "",
        "EXECUTIVE SUMMARY:",
        report.get("executiveSummary", "Not available"),
        "",
    ]

    findings = report.get("keyFindings", [])
    if findings:
        ctx_parts.append("KEY FINDINGS:")
        for f in findings[:5]:
            ctx_parts.append(f"  • {f.get('title','')}: {f.get('detail','')}")
        ctx_parts.append("")

    anomalies = report.get("anomalies", [])
    if anomalies:
        ctx_parts.append("ANOMALIES:")
        for a in anomalies[:5]:
            ctx_parts.append(f"  • [{a.get('severity','?').upper()}] {a.get('column','')}: {a.get('description','')}")
        ctx_parts.append("")

    recs = report.get("recommendations", [])
    if recs:
        ctx_parts.append("RECOMMENDATIONS:")
        for i, r in enumerate(recs[:5], 1):
            ctx_parts.append(f"  {i}. [{r.get('priority','?').upper()}] {r.get('action','')}: {r.get('rationale','')}")
        ctx_parts.append("")

    # Add some numeric stats
    num_summary = stats.get("numeric_summary", {})
    if num_summary:
        ctx_parts.append("NUMERIC COLUMNS OVERVIEW (mean / std / min / max):")
        for col, info in list(num_summary.items())[:8]:
            m = info.get("mean", {})
            s = info.get("std", {})
            mn = info.get("min", {})
            mx = info.get("max", {})
            ctx_parts.append(f"  {col}: mean={m}, std={s}, min={mn}, max={mx}")

    return "\n".join(ctx_parts)


@router.post("/reports/{report_id}/chat")
async def chat_with_report(report_id: str, body: ChatRequest):
    """
    Multi-turn chat endpoint. Streams the response token-by-token.
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    data_context = _build_context(report_data)

    system_with_context = CHAT_SYSTEM + "\n\n--- REPORT CONTEXT ---\n" + data_context

    llm_messages = [{"role": "system", "content": system_with_context}]
    for h in body.history[-10:]:
        llm_messages.append({"role": h.role, "content": h.content})
    llm_messages.append({"role": "user", "content": body.message})

    async def generate():
        try:
            async for chunk in chat_completion_stream(llm_messages, task="chat", timeout=300):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Chat stream error for {report_id}: {e}")
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/llm/status")
async def llm_status():
    return {
        "mode": os.environ.get("LLM_MODE", "agentic"),
        "fallback": os.environ.get("LLM_FALLBACK_PROVIDER", ""),
        "domain": provider_label("domain"),
        "analysis": provider_label("analysis"),
        "visual": provider_label("visual"),
        "report": provider_label("report"),
        "review": provider_label("review"),
        "chat": provider_label("chat"),
    }
