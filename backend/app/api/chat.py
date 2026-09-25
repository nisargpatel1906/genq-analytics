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
from services.agent_prompts import DEEP_CHAT_SYSTEM_PROMPT, NL_SQL_PROMPT

load_dotenv()

logger = logging.getLogger("genq_api.chat")
router = APIRouter()


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str = ""
    question: str | None = None
    history: list[ChatMessage] = []

    @property
    def query_text(self) -> str:
        return self.message or self.question or ""



class NLSQLRequest(BaseModel):
    question: str
    dialect: str = "sqlite"


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


def _build_rich_context(report_data: dict, df: pd.DataFrame) -> tuple[str, str]:
    """Builds rich report_context and dataset_info strings for DEEP_CHAT_SYSTEM_PROMPT."""
    filename = report_data.get("filename", "unknown")
    stats = report_data.get("stats", {})
    shape = stats.get("shape", {})
    report = report_data.get("report", {})

    # Dataset info block
    cols_desc = []
    numeric_stats = []
    if not df.empty:
        for col in df.columns:
            dtype_str = str(df[col].dtype)
            n_null = int(df[col].isnull().sum())
            n_uniq = int(df[col].nunique())
            cols_desc.append(f"  • {col} ({dtype_str}): {n_uniq} unique, {n_null} nulls")
        for col in df.select_dtypes(include="number").columns[:8]:
            try:
                numeric_stats.append(f"  • {col}: mean={df[col].mean():.2f}, std={df[col].std():.2f}, min={df[col].min():.2f}, max={df[col].max():.2f}")
            except Exception:
                pass

    dataset_info = "\n".join([
        f"FILE: {filename}",
        f"SHAPE: {shape.get('rows', len(df))} rows × {shape.get('columns', len(df.columns))} columns",
        f"DOMAIN: {report.get('domain', 'Unknown')}",
        "",
        "COLUMNS (name, type, unique count, null count):",
        "\n".join(cols_desc[:25]) if cols_desc else "Not available",
        "",
        "NUMERIC STATISTICS:",
        "\n".join(numeric_stats) if numeric_stats else "Not available",
    ])

    # Report context block — comprehensive
    ctx_parts = [
        f"REPORT TITLE: {report.get('title', filename)}",
        "",
        "EXECUTIVE SUMMARY:",
        (report.get("executiveSummary") or report.get("executive_summary", "Not available"))[:1500],
        "",
    ]

    # Key findings
    findings = report.get("keyFindings") or report.get("key_findings", [])
    if findings:
        ctx_parts.append("KEY FINDINGS (sorted by impact):")
        for f in sorted(findings, key=lambda x: x.get("impact_score", 0), reverse=True)[:8]:
            impact = f.get("impact_score", "")
            effect = f.get("effect_size", "")
            ctx_parts.append(f"  • [{impact}/10] {f.get('title','')}: {f.get('detail','')[:200]} (effect: {effect})")
        ctx_parts.append("")

    # ML results
    ml_res = report.get("ml_predictive_modeling", {})
    if ml_res and "summary" in ml_res:
        ctx_parts.append("MACHINE LEARNING:")
        ctx_parts.append(f"  • {ml_res.get('summary', '')}")
        ctx_parts.append(f"  • Top 5 drivers: {json.dumps(ml_res.get('feature_importances', [])[:5])}")
        ctx_parts.append("")

    # Causal analysis
    causal = report.get("causal_analysis", {})
    if causal and "causal_summary" in causal:
        ctx_parts.append("CAUSAL INFERENCE:")
        ctx_parts.append(f"  • {causal.get('causal_summary', '')[:400]}")
        ctx_parts.append("")

    # Forecast
    forecast = report.get("forecast", {})
    if forecast and not forecast.get("skipped"):
        ctx_parts.append("FORECAST:")
        ctx_parts.append(f"  • Time column: {forecast.get('time_column', 'N/A')}")
        ctx_parts.append(f"  • {json.dumps(forecast.get('projections', {}))[:400]}")
        ctx_parts.append("")

    # Cohort analysis (new)
    cohort = report.get("cohort_analysis", {})
    if cohort and "summary" in cohort:
        ctx_parts.append("COHORT & RETENTION:")
        ctx_parts.append(f"  • {cohort.get('summary', '')[:400]}")
        ctx_parts.append(f"  • Churn rate: {cohort.get('churn_rate_overall', 'N/A')}")
        ctx_parts.append("")

    # Benchmark analysis (new)
    benchmark = report.get("benchmark_analysis", {})
    if benchmark and "benchmark_summary" in benchmark:
        ctx_parts.append("INDUSTRY BENCHMARKS:")
        ctx_parts.append(f"  • {benchmark.get('benchmark_summary', '')[:400]}")
        bms = benchmark.get("benchmarks", [])[:5]
        for b in bms:
            ctx_parts.append(f"    - {b.get('metric_name', '')}: {b.get('observed_value', '')} vs industry avg {b.get('industry_average', '')} [{b.get('verdict', '')}]")
        ctx_parts.append("")

    # A/B experiment
    exp = report.get("experiment_results", {})
    if exp and exp.get("is_experiment"):
        ctx_parts.append("A/B EXPERIMENT:")
        ctx_parts.append(f"  • Decision: {exp.get('rollout_decision', 'N/A')}")
        ctx_parts.append(f"  • {exp.get('recommendation', '')[:300]}")
        ctx_parts.append("")

    # Strategic brief
    strategic = report.get("strategic_brief", {})
    if strategic:
        ctx_parts.append("STRATEGIC BRIEF:")
        ctx_parts.append(f"  • Headline: {strategic.get('executive_headline', '')[:200]}")
        recs = strategic.get("recommendations", [])
        for r in recs[:3]:
            ctx_parts.append(f"  • [{r.get('priority','?').upper()}] {r.get('action','')[:150]}")
        ctx_parts.append("")

    # Data quality gate (new)
    dq = report.get("data_quality_gate", {})
    if dq:
        ctx_parts.append("DATA QUALITY:")
        ctx_parts.append(f"  • Health Score: {dq.get('score', 'N/A')}/100 [{dq.get('decision', 'N/A')}]")
        ctx_parts.append("")

    # Anomalies
    anomalies = report.get("anomalies", [])
    if anomalies:
        ctx_parts.append("ANOMALIES:")
        for a in anomalies[:5]:
            ctx_parts.append(f"  • [{a.get('severity','?').upper()}] {a.get('column','')}: {a.get('description','')[:150]}")
        ctx_parts.append("")

    report_context = "\n".join(ctx_parts)
    return report_context, dataset_info


def _execute_chat_code_query(message: str, df: pd.DataFrame, report_context: str) -> tuple[str, list[str]]:
    """
    Determines if the user's message requires live computation on df.
    If so, asks the LLM to write Python code and executes it in sandbox.
    Returns (stdout_text, chart_markdown_images).
    """
    if df.empty:
        return "", []

    # Expanded keyword detection — much broader than before
    query_keywords = [
        "calculate", "compute", "how many", "what is the", "what are the",
        "mean", "average", "median", "sum", "total", "count", "percentage",
        "compare", "correlation", "highest", "lowest", "top", "bottom",
        "filter", "where", "group by", "segment", "break down", "breakdown",
        "chart", "plot", "graph", "histogram", "distribution", "scatter",
        "trend", "over time", "by month", "by week", "by region", "by category",
        "churn", "retention", "revenue", "spend", "customers", "orders",
        "show me", "give me", "list the", "find the", "rank", "sort",
        "outlier", "anomaly", "predict", "forecast",
    ]
    msg_low = message.lower()
    is_query = any(k in msg_low for k in query_keywords)

    # Also trigger if user mentions any column name
    if not is_query:
        is_query = any(col.lower() in msg_low for col in df.columns)

    if not is_query:
        return "", []

    col_info = {c: str(df[c].dtype) for c in df.columns}
    sample_vals = {}
    for c in list(df.columns)[:8]:
        try:
            sample_vals[c] = df[c].dropna().head(3).tolist()
        except Exception:
            pass

    code_prompt = f"""Write a Python script to answer the user query on pandas DataFrame `df`.

Query: "{message}"

Available columns and types:
{json.dumps(col_info, indent=2)}

Sample values:
{json.dumps(sample_vals, indent=2, default=str)}

Rules:
- df is already loaded in memory.
- Print the exact answer using print(). Format tables with df.to_string() or tabulate if useful.
- If the user asks for a chart, use matplotlib and seaborn. Save to `chat_chart.png`:
  import matplotlib.pyplot as plt; import seaborn as sns
  sns.set_theme(style="whitegrid")
  fig, ax = plt.subplots(figsize=(10, 6))
  # ... your chart code ...
  plt.tight_layout()
  plt.savefig("chat_chart.png", dpi=150, bbox_inches="tight")
  plt.close()
- Always guard with try/except around the entire computation.
- Never use df.dropna() globally — only on relevant columns.
- Output ONLY an executable python code block.
"""

    messages = [
        {"role": "system", "content": "You are a quantitative data analyst. Write Python code to compute the exact answer. Output only a python code block."},
        {"role": "user", "content": code_prompt}
    ]

    try:
        resp = chat_completion(messages, task="analysis", timeout=90)
        code = extract_code_block(resp)
        if code:
            exec_res = execute_analysis_code(code, df, timeout_seconds=45)
            stdout = exec_res.stdout.strip() if exec_res.stdout else ""
            if exec_res.stderr and not stdout:
                logger.warning(f"Chat code exec stderr: {exec_res.stderr[:200]}")
            chart_embeds = []
            for out in exec_res.agent_outputs:
                if out.get("type") == "image" and isinstance(out.get("data"), (bytes, bytearray)):
                    b64_str = base64.b64encode(out["data"]).decode("utf-8")
                    chart_embeds.append(f"\n\n![Live Chart](data:image/png;base64,{b64_str})\n\n")
            return stdout, chart_embeds
    except Exception as e:
        logger.warning(f"Chat code execution failed: {e}")

    return "", []


@router.post("/reports/{report_id}/chat")
async def chat_with_report(report_id: str, body: ChatRequest):
    """
    Deep multi-turn analyst chat endpoint with live computation.
    - Uses DEEP_CHAT_SYSTEM_PROMPT for elite analyst persona
    - Auto-detects quantitative queries and runs live code on the dataset
    - Streams response token-by-token
    - Includes cohort, benchmark, causal, forecast, ML, A/B, and quality gate context
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)
    report_context, dataset_info = _build_rich_context(report_data, df)

    # Build system prompt with full context
    system_prompt = DEEP_CHAT_SYSTEM_PROMPT.format(
        report_context=report_context[:8000],
        dataset_info=dataset_info[:2000],
    )

    user_msg = body.query_text
    # Run live computation if query is quantitative
    computed_stdout, chart_embeds = _execute_chat_code_query(user_msg, df, report_context)

    if computed_stdout:
        system_prompt += f"\n\n--- LIVE COMPUTATION OUTPUT ---\n{computed_stdout[:2000]}\n\nGround your answer in these exact computed figures. Do not hallucinate different numbers."

    llm_messages = [{"role": "system", "content": system_prompt}]
    for h in body.history[-12:]:  # Larger history window (12 turns)
        llm_messages.append({"role": h.role, "content": h.content})
    llm_messages.append({"role": "user", "content": user_msg})

    async def generate():
        try:
            # Prepend any generated charts
            for chart_md in chart_embeds:
                yield f"data: {chart_md}\n\n"

            async for chunk in chat_completion_stream(llm_messages, task="chat", timeout=300):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"Chat stream error for {report_id}: {e}")
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/reports/{report_id}/nl-sql")
async def nl_to_sql(report_id: str, body: NLSQLRequest):
    """
    Natural Language to SQL endpoint.
    Converts the user's question to SQL, executes it against the dataset (stored as SQLite),
    and returns the query + results.
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)

    if df.empty:
        raise HTTPException(status_code=404, detail="Dataset not available for SQL queries")

    # Build table schema info
    table_schemas = {
        "data": {col: str(df[col].dtype) for col in df.columns}
    }
    sample_data = {
        "data": df.head(3).to_dict(orient="records")
    }

    prompt = NL_SQL_PROMPT.format(
        question=body.question,
        table_schemas=json.dumps(table_schemas, indent=2),
        sample_data=json.dumps(sample_data, default=str, indent=2),
        dialect=body.dialect,
    )

    messages = [
        {"role": "system", "content": "You are an expert SQL analyst. Convert natural language to SQL. Output JSON only."},
        {"role": "user", "content": prompt},
    ]

    try:
        response = chat_completion(messages, task="analysis", json_mode=True, timeout=90)
        from app.utils import parse_json_safely
        parsed = parse_json_safely(response)

        if not parsed.get("is_answerable", True):
            return {"sql": None, "explanation": parsed.get("explanation", "Cannot answer from available data."),
                    "results": [], "error": "Not answerable"}

        sql = parsed.get("sql_query", "")

        # Execute SQL against df using sqlite3
        result_rows = []
        try:
            import sqlite3
            import re
            conn = sqlite3.connect(":memory:")
            # Register standard table alias options
            for tbl in ["data", "dataset", "df", "table", "customers", "customer_data", "sales", "records"]:
                try:
                    df.to_sql(tbl, conn, if_exists="replace", index=False)
                except Exception:
                    pass
            # Also register any table name found in FROM / JOIN clauses in the generated query
            tables = re.findall(r'(?:from|join)\s+["`\'\[]?([a-zA-Z_0-9]+)["`\'\]]?', sql, re.IGNORECASE)
            for tbl in tables:
                if tbl.lower() not in {"select", "where", "group", "having", "limit", "values"}:
                    try:
                        df.to_sql(tbl, conn, if_exists="replace", index=False)
                    except Exception:
                        pass

            # Universal resilience: quote table names after FROM/JOIN in brackets if they collide with SQL keywords
            exec_sql = sql
            for tbl in set(tables):
                exec_sql = re.sub(rf'(?i)\b(from|join)\s+["`\']?{re.escape(tbl)}["`\']?\b', rf'\1 [{tbl}]', exec_sql)

            try:
                cursor = conn.execute(exec_sql)
            except Exception:
                # Fallback: substitute FROM <table_name> with FROM data (which is always registered)
                fallback_sql = re.sub(r'(?i)\b(from|join)\s+["`\'\[]?[a-zA-Z_0-9]+["`\'\]]?', r'\1 data', sql)
                cursor = conn.execute(fallback_sql)

            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(500)
            result_rows = [dict(zip(columns, row)) for row in rows]
            conn.close()
        except Exception as exec_err:
            logger.warning(f"NL-SQL execution failed: {exec_err}")
            return {
                "sql": sql,
                "explanation": parsed.get("explanation", ""),
                "results": [],
                "error": str(exec_err),
                "columns": parsed.get("expected_columns", []),
            }

        return {
            "sql": sql,
            "explanation": parsed.get("explanation", ""),
            "assumptions": parsed.get("assumptions", []),
            "results": result_rows[:200],
            "row_count": len(result_rows),
            "columns": list(result_rows[0].keys()) if result_rows else parsed.get("expected_columns", []),
        }

    except Exception as e:
        logger.error(f"NL-SQL endpoint error: {e}")
        raise HTTPException(status_code=500, detail=f"NL→SQL conversion failed: {e}")


@router.get("/reports/{report_id}/insights")
async def get_ranked_insights(report_id: str):
    """
    Returns all findings across the report ranked by impact score.
    Powers the new Insights Feed page.
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    report = report_data.get("report", {})

    all_insights = []

    # Collect from all finding sources
    for section in report.get("reportSections", []):
        for f in section.get("findings", []):
            all_insights.append({
                "title": f.get("title", ""),
                "detail": f.get("detail", ""),
                "impact_score": f.get("impact_score", 5),
                "confidence": f.get("confidence", 70),
                "effect_size": f.get("effect_size", ""),
                "practical_significance": f.get("practical_significance", ""),
                "supporting_chart": f.get("supporting_chart"),
                "category": section.get("type", "findings_group"),
                "section_title": section.get("title", ""),
            })

    # Also include key findings
    for f in report.get("keyFindings", []):
        if not any(i["title"] == f.get("title", "") for i in all_insights):
            all_insights.append({
                "title": f.get("title", ""),
                "detail": f.get("detail", f.get("finding", f.get("description", ""))),
                "impact_score": f.get("impact_score", 5),
                "confidence": f.get("confidence", f.get("confidenceScore", 70)),
                "effect_size": f.get("effect_size", ""),
                "practical_significance": f.get("practical_significance", ""),
                "supporting_chart": f.get("supporting_chart"),
                "category": "key_finding",
                "section_title": "Key Findings",
            })

    # ML insights
    ml = report.get("ml_predictive_modeling", {})
    if ml and "summary" in ml:
        all_insights.append({
            "title": f"ML Prediction: {ml.get('model_name', 'Model')} for {ml.get('target_column', 'target')}",
            "detail": ml.get("summary", ""),
            "impact_score": 8,
            "confidence": round(ml.get("metrics", {}).get("accuracy", 0.75) * 100),
            "effect_size": f"R²={ml.get('metrics', {}).get('r2_score', 'N/A')} | Accuracy={ml.get('metrics', {}).get('accuracy', 'N/A')}",
            "practical_significance": f"Top driver: {ml.get('feature_importances', [{}])[0].get('feature', 'N/A') if ml.get('feature_importances') else 'N/A'}",
            "supporting_chart": None,
            "category": "ml",
            "section_title": "Machine Learning",
        })

    # Causal insights
    causal = report.get("causal_analysis", {})
    if causal and "causal_summary" in causal:
        all_insights.append({
            "title": "Causal Inference Analysis",
            "detail": causal.get("causal_summary", "")[:300],
            "impact_score": 9,
            "confidence": 85,
            "effect_size": "",
            "practical_significance": "",
            "supporting_chart": None,
            "category": "causal",
            "section_title": "Causal Analysis",
        })

    # Cohort insights
    cohort = report.get("cohort_analysis", {})
    if cohort and "summary" in cohort:
        all_insights.append({
            "title": "Cohort & Retention Analysis",
            "detail": cohort.get("summary", "")[:300],
            "impact_score": 8,
            "confidence": 80,
            "effect_size": f"Churn rate: {cohort.get('churn_rate_overall', 'N/A')}",
            "practical_significance": "",
            "supporting_chart": None,
            "category": "cohort",
            "section_title": "Cohort Analysis",
        })

    # Benchmark insights
    for b in report.get("benchmark_analysis", {}).get("benchmarks", []):
        if "Below" in b.get("verdict", ""):
            all_insights.append({
                "title": f"Performance Gap: {b.get('metric_name', '')}",
                "detail": b.get("business_implication", ""),
                "impact_score": 7,
                "confidence": 75,
                "effect_size": f"{b.get('observed_value', '')} vs industry avg {b.get('industry_average', '')}",
                "practical_significance": b.get("business_implication", ""),
                "supporting_chart": None,
                "category": "benchmark",
                "section_title": "Competitive Benchmarking",
            })

    # Sort by impact score descending
    all_insights.sort(key=lambda x: x.get("impact_score", 0), reverse=True)

    return {
        "report_id": report_id,
        "total_insights": len(all_insights),
        "insights": all_insights,
    }


@router.post("/compare")
async def compare_reports(body: dict):
    """
    Compare two reports and return delta analysis.
    """
    report_id_a = body.get("report_id_a")
    report_id_b = body.get("report_id_b")

    if not report_id_a or not report_id_b:
        raise HTTPException(status_code=400, detail="Both report_id_a and report_id_b are required")
    if report_id_a not in reports_db:
        raise HTTPException(status_code=404, detail=f"Report A '{report_id_a}' not found")
    if report_id_b not in reports_db:
        raise HTTPException(status_code=404, detail=f"Report B '{report_id_b}' not found")

    report_a = reports_db[report_id_a]["report"]
    report_b = reports_db[report_id_b]["report"]

    # Compare key metrics
    def safe_get_findings(report):
        findings = report.get("keyFindings") or report.get("key_findings", [])
        return {f.get("title", ""): f for f in findings if f.get("title")}

    findings_a = safe_get_findings(report_a)
    findings_b = safe_get_findings(report_b)

    shared_titles = set(findings_a.keys()) & set(findings_b.keys())
    only_in_a = set(findings_a.keys()) - set(findings_b.keys())
    only_in_b = set(findings_b.keys()) - set(findings_a.keys())

    delta_findings = []
    for title in shared_titles:
        fa = findings_a[title]
        fb = findings_b[title]
        impact_delta = fb.get("impact_score", 5) - fa.get("impact_score", 5)
        confidence_delta = fb.get("confidence", 70) - fa.get("confidence", 70)
        delta_findings.append({
            "title": title,
            "impact_delta": impact_delta,
            "confidence_delta": confidence_delta,
            "finding_a": fa.get("detail", "")[:200],
            "finding_b": fb.get("detail", "")[:200],
        })

    # Compare audit scores
    audit_a = report_a.get("audit", {}).get("score", report_a.get("audit_score", 0))
    audit_b = report_b.get("audit", {}).get("score", report_b.get("audit_score", 0))

    return {
        "report_a_id": report_id_a,
        "report_b_id": report_id_b,
        "report_a_title": report_a.get("title", report_id_a),
        "report_b_title": report_b.get("title", report_id_b),
        "audit_score_a": audit_a,
        "audit_score_b": audit_b,
        "audit_score_delta": audit_b - audit_a,
        "shared_findings_count": len(shared_titles),
        "only_in_a_count": len(only_in_a),
        "only_in_b_count": len(only_in_b),
        "delta_findings": sorted(delta_findings, key=lambda x: abs(x["impact_delta"]), reverse=True)[:10],
        "new_findings_in_b": [findings_b[t] for t in list(only_in_b)[:5]],
        "dropped_findings_from_a": [findings_a[t] for t in list(only_in_a)[:5]],
    }


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
