import logging
import os
import base64
import json
import pandas as pd
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.db import reports_db
from dotenv import load_dotenv
from services.llm import chat_completion, chat_completion_stream, provider_label
from services.code_executor import execute_analysis_code
from services.agent_graph import extract_code_block

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
You are an expert quantitative data analyst and senior consultant embedded in GenQ Analytics.
You have direct access to the analyzed dataset (as DataFrame `df`), its schema, statistical profile,
key findings, anomalies, machine learning predictions, and strategic recommendations.

Your job is to:
- Act like an elite data analyst sitting next to the user.
- Answer factual and statistical questions about the data clearly and accurately.
- When live computation or data filtering was executed on the dataset, ground your answers in the exact computed numbers and tables.
- Never hallucinate numbers. If numbers were computed, cite the exact results.
- Keep responses focused, professional, and actionable.
- Format responses in clean GitHub markdown (using bolding, bullet points, and tables where helpful).
"""


def _get_report_dataframe(report_id: str, report_data: dict) -> pd.DataFrame:
    """Retrieves the DataFrame for a report from disk parquet or data sample."""
    ds_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "datasets", f"{report_id}.parquet"))
    if os.path.exists(ds_path):
        try:
            return pd.read_parquet(ds_path)
        except Exception as e:
            logger.warning(f"Error loading parquet dataset for {report_id}: {e}")

    sample = report_data.get("data_sample", [])
    if sample:
        try:
            return pd.DataFrame(sample)
        except Exception as e:
            logger.warning(f"Error converting sample to DataFrame for {report_id}: {e}")

    return pd.DataFrame()


def _build_context(report_data: dict, df: pd.DataFrame) -> str:
    """Builds a rich context string from the stored report for the LLM."""
    filename = report_data.get("filename", "unknown")
    stats = report_data.get("stats", {})
    shape = stats.get("shape", {})
    report = report_data.get("report", {})

    cols_desc = []
    if not df.empty:
        for col in df.columns:
            dtype_str = str(df[col].dtype)
            n_null = int(df[col].isnull().sum())
            n_uniq = int(df[col].nunique())
            cols_desc.append(f"  • {col} ({dtype_str}): {n_uniq} unique values, {n_null} nulls")

    ctx_parts = [
        f"DATASET: {filename}",
        f"SIZE: {shape.get('rows', len(df))} rows × {shape.get('columns', len(df.columns))} columns",
        f"DOMAIN: {report.get('domain', 'Not specified')}",
        "",
        "COLUMNS IN DATAFRAME `df`:",
        "\n".join(cols_desc[:25]) if cols_desc else "Schema not available",
        "",
        "EXECUTIVE SUMMARY:",
        report.get("executiveSummary") or report.get("executive_summary", "Not available"),
        "",
    ]

    # Key Findings
    findings = report.get("keyFindings") or report.get("key_findings", [])
    if findings:
        ctx_parts.append("KEY FINDINGS:")
        for f in findings[:6]:
            ctx_parts.append(f"  • {f.get('title','')}: {f.get('detail','')}")
        ctx_parts.append("")

    # Machine Learning & Predictive Insights
    ml_res = report.get("ml_predictive_modeling", {})
    if ml_res and "summary" in ml_res:
        ctx_parts.append("MACHINE LEARNING & PREDICTIVE MODELING:")
        ctx_parts.append(f"  • Model: {ml_res.get('model_name', 'Trained Model')} on target '{ml_res.get('target_column', 'N/A')}'")
        ctx_parts.append(f"  • Metrics: {json.dumps(ml_res.get('metrics', {}))}")
        ctx_parts.append(f"  • Top Drivers: {json.dumps(ml_res.get('feature_importances', [])[:5])}")
        ctx_parts.append("")

    # Data Cleaning Manifest
    cleaning = report.get("data_cleaning_manifest", {})
    if cleaning and "summary" in cleaning:
        ctx_parts.append("DATA CLEANING & QUALITY MANIFEST:")
        ctx_parts.append(f"  • {cleaning.get('summary', '')}")
        ctx_parts.append("")

    # Anomalies
    anomalies = report.get("anomalies", [])
    if anomalies:
        ctx_parts.append("ANOMALIES:")
        for a in anomalies[:5]:
            ctx_parts.append(f"  • [{a.get('severity','?').upper()}] {a.get('column','')}: {a.get('description','')}")
        ctx_parts.append("")

    # Recommendations
    recs = report.get("recommendations", [])
    if recs:
        ctx_parts.append("STRATEGIC RECOMMENDATIONS:")
        for i, r in enumerate(recs[:5], 1):
            ctx_parts.append(f"  {i}. [{r.get('priority','?').upper()}] {r.get('action','')}: {r.get('rationale','')}")
        ctx_parts.append("")

    return "\n".join(ctx_parts)


def _execute_chat_code_query(message: str, df: pd.DataFrame) -> tuple[str, list[str]]:
    """
    If the user's question involves quantitative querying or chart generation,
    asks the LLM to write a concise Python snippet and executes it on df in the sandbox.
    Returns (stdout_text, chart_markdown_images).
    """
    if df.empty:
        return "", []

    query_keywords = [
        "calculate", "how many", "what is the average", "mean", "median", "sum", "total",
        "compare", "correlation", "highest", "lowest", "top", "bottom", "filter",
        "chart", "plot", "graph", "histogram", "distribution", "breakdown", "by region",
        "churn rate", "spend", "count", "percentage", "ratio"
    ]
    msg_low = message.lower()
    is_query = any(k in msg_low for k in query_keywords)
    if not is_query and len(message.split()) > 3:
        if not any(c.lower() in msg_low for c in df.columns):
            return "", []

    col_info = {c: str(df[c].dtype) for c in df.columns}
    code_prompt = f"""
Write a short Python script to answer the user query on pandas DataFrame `df`:
Query: "{message}"

DataFrame Columns & Types:
{json.dumps(col_info)}

Rules:
- The script has `df` pre-loaded in memory.
- Print the exact numerical answer, grouped table, or metrics using `print(...)`.
- If the user explicitly asks for a chart/plot, use `matplotlib.pyplot` and save to `chat_chart.png`:
  ```python
  import matplotlib.pyplot as plt
  # plot code...
  plt.tight_layout()
  plt.savefig("chat_chart.png")
  plt.close()
  ```
- Output ONLY the executable ```python ... ``` code block.
"""
    messages = [
        {"role": "system", "content": "You are a quantitative data analyst. Write a concise python script to compute the exact answer on DataFrame `df`."},
        {"role": "user", "content": code_prompt}
    ]

    try:
        resp = chat_completion(messages, task="analysis", timeout=60)
        code = extract_code_block(resp)
        if code:
            exec_res = execute_analysis_code(code, df, timeout_seconds=30)
            stdout = exec_res.stdout.strip() if exec_res.stdout else ""
            chart_embeds = []
            for out in exec_res.agent_outputs:
                if out.get("type") == "image" and isinstance(out.get("data"), (bytes, bytearray)):
                    b64_str = base64.b64encode(out["data"]).decode("utf-8")
                    chart_embeds.append(f"\n\n![Generated Chart](data:image/png;base64,{b64_str})\n\n")
            return stdout, chart_embeds
    except Exception as e:
        logger.warning(f"Chat code execution query failed: {e}")

    return "", []


@router.post("/reports/{report_id}/chat")
async def chat_with_report(report_id: str, body: ChatRequest):
    """
    Multi-turn interactive analytics chat endpoint.
    Equipped with autonomous code execution and data querying tools.
    Streams the response token-by-token.
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)
    data_context = _build_context(report_data, df)

    # Check if query needs computation or live execution on df
    computed_stdout, chart_embeds = _execute_chat_code_query(body.message, df)
    live_computation_context = ""
    if computed_stdout:
        live_computation_context = f"\n\n--- LIVE COMPUTATION OUTPUT FROM DATASET ---\n{computed_stdout}\nUse these exact computed figures to formulate your answer."

    system_with_context = CHAT_SYSTEM + "\n\n--- REPORT CONTEXT ---\n" + data_context + live_computation_context

    llm_messages = [{"role": "system", "content": system_with_context}]
    for h in body.history[-10:]:
        llm_messages.append({"role": h.role, "content": h.content})
    llm_messages.append({"role": "user", "content": body.message})

    async def generate():
        try:
            # If any charts were generated by live code execution, yield them first
            for chart_md in chart_embeds:
                yield f"data: {chart_md}\n\n"

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
