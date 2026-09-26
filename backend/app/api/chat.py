import logging
import os
import io
import base64
import json
from typing import Optional, List, Dict, Any
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, confusion_matrix, r2_score, mean_squared_error, mean_absolute_error
from sklearn.preprocessing import LabelEncoder
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, Response
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


class TrainModelRequest(BaseModel):
    target_col: Optional[str] = None
    feature_cols: Optional[List[str]] = None


class SimulateGrowthRequest(BaseModel):
    metric_col: Optional[str] = None
    growth_rate_pct: float = 15.0
    years: int = 5


class RoadmapRequest(BaseModel):
    focus_area: str = "all"
    horizon_days: int = 90


class CausalWhatIfRequest(BaseModel):
    treatment_col: Optional[str] = None
    outcome_col: Optional[str] = None
    delta_change_pct: float = 10.0


class ExecuteCodeRequest(BaseModel):
    code: str


class ExportChatRequest(BaseModel):
    title: Optional[str] = "Executive Analysis Memo"
    history: List[ChatMessage] = []


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

    # Check for direct Copilot tool triggers in user query
    tool_chart = None
    msg_low = user_msg.lower()
    if any(k in msg_low for k in ["simulate growth", "run simulation", "growth projection", "5-year growth", "monte carlo"]):
        try:
            sim_res = tool_simulate_growth_scenario(df, growth_rate_pct=15.0, years=5)
            if "chart_base64" in sim_res:
                chart_embeds.append(f"\n\n![Growth Projection](data:image/png;base64,{sim_res['chart_base64']})\n\n")
            computed_stdout += f"\n\n[GROWTH SIMULATION RESULTS]\n{sim_res.get('narrative', '')}\nTable: {json.dumps(sim_res.get('table', []))[:1000]}"
        except Exception as e:
            logger.warning(f"Chat simulation trigger error: {e}")
    elif any(k in msg_low for k in ["train model", "train predictive model", "custom model", "predictive model", "train a model"]):
        try:
            mod_res = tool_train_custom_model(df)
            if "chart_base64" in mod_res:
                chart_embeds.append(f"\n\n![Model Drivers & Fit](data:image/png;base64,{mod_res['chart_base64']})\n\n")
            computed_stdout += f"\n\n[CUSTOM MODEL RESULTS]\n{mod_res.get('narrative', '')}\nMetrics: {json.dumps(mod_res.get('metrics', {}))}"
        except Exception as e:
            logger.warning(f"Chat train model trigger error: {e}")
    elif any(k in msg_low for k in ["causal what-if", "what-if", "counterfactual", "sensitivity analysis"]):
        try:
            cw_res = tool_run_causal_what_if(df)
            if "chart_base64" in cw_res:
                chart_embeds.append(f"\n\n![Causal What-If Sensitivity](data:image/png;base64,{cw_res['chart_base64']})\n\n")
            computed_stdout += f"\n\n[CAUSAL WHAT-IF RESULTS]\n{cw_res.get('narrative', '')}"
        except Exception as e:
            logger.warning(f"Chat causal what-if trigger error: {e}")
    elif any(k in msg_low for k in ["30-60-90", "strategic roadmap", "action roadmap", "execution roadmap"]):
        try:
            rm_res = tool_generate_strategic_roadmap(report_context, dataset_info)
            computed_stdout += f"\n\n[STRATEGIC ROADMAP]\n{rm_res.get('markdown', '')}"
        except Exception as e:
            logger.warning(f"Chat roadmap trigger error: {e}")

    if computed_stdout:
        system_prompt += f"\n\n--- LIVE COMPUTATION / TOOL OUTPUT ---\n{computed_stdout[:2500]}\n\nGround your answer in these exact computed figures and strategic findings. Do not hallucinate different numbers."

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

# ==============================================================================
# COPILOT ACTION SUITE: ADVANCED ANALYTICAL TOOLS
# ==============================================================================

def tool_train_custom_model(
    df: pd.DataFrame,
    target_col: Optional[str] = None,
    feature_cols: Optional[List[str]] = None
) -> dict:
    """Trains a Random Forest classifier or regressor, returning metrics, drivers, and visualization."""
    if df.empty:
        return {"error": "Dataset is empty"}

    # Target column selection
    if not target_col or target_col not in df.columns:
        # Prioritize binary / churn / classification columns
        cand_targets = [
            c for c in df.columns
            if df[c].nunique() == 2 or any(k in c.lower() for k in ["churn", "target", "converted", "attrition", "status", "label", "purchased"])
        ]
        if cand_targets:
            target_col = cand_targets[0]
        else:
            num_cols = df.select_dtypes(include="number").columns.tolist()
            target_col = num_cols[-1] if num_cols else df.columns[-1]

    # Feature columns selection
    if not feature_cols:
        id_patterns = ["id", "uuid", "guid", "code", "index", "key", "url", "email", "address", "phone"]
        cand_features = []
        for c in df.columns:
            if c == target_col:
                continue
            c_low = c.lower()
            if any(p in c_low for p in id_patterns) and df[c].nunique() > len(df) * 0.5:
                continue
            if df[c].nunique() <= 1:
                continue
            cand_features.append(c)
        feature_cols = cand_features[:12]

    if not feature_cols:
        return {"error": "No valid predictive features found in dataset"}

    # Clean data
    df_clean = df[[target_col] + feature_cols].dropna(subset=[target_col]).copy()
    if len(df_clean) < 10:
        return {"error": f"Insufficient non-null rows ({len(df_clean)}) for training on {target_col}"}

    y_raw = df_clean[target_col]
    is_classification = (y_raw.dtype == 'object' or str(y_raw.dtype).startswith('bool') or y_raw.nunique() <= 5)

    X = pd.DataFrame(index=df_clean.index)
    for col in feature_cols:
        s = df_clean[col]
        if pd.api.types.is_numeric_dtype(s):
            X[col] = s.fillna(s.median())
        else:
            le = LabelEncoder()
            X[col] = le.fit_transform(s.astype(str).fillna("missing"))

    if is_classification:
        target_le = LabelEncoder()
        y = target_le.fit_transform(y_raw.astype(str))
        target_classes = [str(c) for c in target_le.classes_]
    else:
        y = y_raw.values.astype(float)
        target_classes = []

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), dpi=120)
    fig.patch.set_facecolor('#FAF7F2')
    ax1.set_facecolor('#FAF7F2')
    ax2.set_facecolor('#FAF7F2')

    metrics = {}
    top_drivers = []

    if is_classification:
        clf = RandomForestClassifier(n_estimators=100, max_depth=7, random_state=42)
        clf.fit(X_train, y_train)
        y_pred = clf.predict(X_test)
        acc = float(accuracy_score(y_test, y_pred))
        f1 = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
        prec = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
        rec = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        metrics = {
            "task": "classification",
            "accuracy": round(acc, 4),
            "f1_score": round(f1, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "classes": target_classes
        }
        importances = clf.feature_importances_
        feat_imp = sorted(zip(feature_cols, importances), key=lambda x: x[1], reverse=True)[:10]
        top_drivers = [{"feature": f, "importance": round(float(imp), 4)} for f, imp in feat_imp]

        y_pos = range(len(feat_imp))
        ax1.barh(y_pos, [x[1] for x in reversed(feat_imp)], color='#8B6F3E', edgecolor='#4A3B2C', alpha=0.9)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels([x[0] for x in reversed(feat_imp)], fontsize=10)
        ax1.set_xlabel("Predictive Importance", fontsize=10, fontweight='bold', color='#1A1208')
        ax1.set_title(f"Key Drivers of {target_col}", fontsize=12, fontweight='bold', color='#1A1208', pad=10)
        ax1.grid(axis='x', linestyle='--', alpha=0.5)

        cm = confusion_matrix(y_test, y_pred)
        sns.heatmap(cm, annot=True, fmt="d", cmap="YlOrBr", ax=ax2, cbar=False,
                    xticklabels=target_classes[:len(cm)], yticklabels=target_classes[:len(cm)])
        ax2.set_xlabel("Predicted Class", fontsize=10, fontweight='bold', color='#1A1208')
        ax2.set_ylabel("True Class", fontsize=10, fontweight='bold', color='#1A1208')
        ax2.set_title(f"Confusion Matrix (Acc: {acc:.1%})", fontsize=12, fontweight='bold', color='#1A1208', pad=10)

    else:
        reg = RandomForestRegressor(n_estimators=100, max_depth=7, random_state=42)
        reg.fit(X_train, y_train)
        y_pred = reg.predict(X_test)
        r2 = float(r2_score(y_test, y_pred))
        rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
        mae = float(mean_absolute_error(y_test, y_pred))
        metrics = {
            "task": "regression",
            "r2_score": round(r2, 4),
            "rmse": round(rmse, 4),
            "mae": round(mae, 4)
        }
        importances = reg.feature_importances_
        feat_imp = sorted(zip(feature_cols, importances), key=lambda x: x[1], reverse=True)[:10]
        top_drivers = [{"feature": f, "importance": round(float(imp), 4)} for f, imp in feat_imp]

        y_pos = range(len(feat_imp))
        ax1.barh(y_pos, [x[1] for x in reversed(feat_imp)], color='#8B6F3E', edgecolor='#4A3B2C', alpha=0.9)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels([x[0] for x in reversed(feat_imp)], fontsize=10)
        ax1.set_xlabel("Predictive Importance", fontsize=10, fontweight='bold', color='#1A1208')
        ax1.set_title(f"Key Drivers of {target_col}", fontsize=12, fontweight='bold', color='#1A1208', pad=10)
        ax1.grid(axis='x', linestyle='--', alpha=0.5)

        ax2.scatter(y_test, y_pred, alpha=0.6, color='#8B6F3E', edgecolor='#4A3B2C', s=35)
        min_v = min(y_test.min(), y_pred.min())
        max_v = max(y_test.max(), y_pred.max())
        ax2.plot([min_v, max_v], [min_v, max_v], color='#A23B2A', linestyle='--', linewidth=1.5, label='Ideal Fit (y=x)')
        ax2.set_xlabel(f"Actual {target_col}", fontsize=10, fontweight='bold', color='#1A1208')
        ax2.set_ylabel(f"Predicted {target_col}", fontsize=10, fontweight='bold', color='#1A1208')
        ax2.set_title(f"Actual vs Predicted (R²={r2:.2f})", fontsize=12, fontweight='bold', color='#1A1208', pad=10)
        ax2.legend(loc='upper left', frameon=True, facecolor='#FAF7F2')
        ax2.grid(True, linestyle='--', alpha=0.5)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    b64_chart = base64.b64encode(buf.getvalue()).decode('utf-8')

    driver_names = [d['feature'] for d in top_drivers[:3]]
    driver_str = ", ".join(driver_names) if driver_names else "features"
    if is_classification:
        narrative = (
            f"Trained a Random Forest Classifier on target '{target_col}' ({len(X)} records).\n"
            f"• Out-of-sample Accuracy: {metrics['accuracy']:.1%} | Weighted F1: {metrics['f1_score']:.2f}.\n"
            f"• Leading predictive drivers: {driver_str}.\n"
            f"• Executive Action: Calibrate strategy around '{top_drivers[0]['feature']}' (captures {top_drivers[0]['importance']*100:.1f}% relative predictive weight)."
        )
    else:
        narrative = (
            f"Trained a Random Forest Regressor on target '{target_col}' ({len(X)} records).\n"
            f"• Explanatory Power (R²): {metrics['r2_score']:.2f} | RMSE: {metrics['rmse']:,.2f}.\n"
            f"• Dominant drivers explaining variance: {driver_str}.\n"
            f"• Executive Action: '{top_drivers[0]['feature']}' exhibits the highest marginal correlation ({top_drivers[0]['importance']*100:.1f}% weight). Interventions on this feature drive direct changes in {target_col}."
        )

    return {
        "task_type": "classification" if is_classification else "regression",
        "target_column": target_col,
        "feature_columns": feature_cols,
        "metrics": metrics,
        "top_drivers": top_drivers,
        "narrative": narrative,
        "chart_base64": b64_chart
    }


def tool_simulate_growth_scenario(
    df: pd.DataFrame,
    metric_col: Optional[str] = None,
    growth_rate_pct: float = 15.0,
    years: int = 5
) -> dict:
    """Projects multi-year growth trajectories under Conservative, Base, and Aggressive scenarios with Monte Carlo uncertainty."""
    if df.empty:
        return {"error": "Dataset is empty"}

    # Find volume/financial metric
    if not metric_col or metric_col not in df.columns:
        cand_metrics = [
            c for c in df.select_dtypes(include="number").columns
            if any(k in c.lower() for k in ["revenue", "sales", "arr", "mrr", "spend", "profit", "orders", "users", "amount", "total"])
        ]
        if cand_metrics:
            metric_col = cand_metrics[0]
        else:
            num_cols = df.select_dtypes(include="number").columns.tolist()
            metric_col = num_cols[0] if num_cols else None

    if not metric_col:
        return {"error": "No numeric metric found for simulation"}

    series = df[metric_col].dropna()
    baseline = float(series.sum()) if series.sum() > 0 else float(series.mean())
    if baseline <= 0:
        baseline = 100000.0

    years = max(1, min(10, years))
    c_rate = (growth_rate_pct * 0.5) / 100.0
    b_rate = growth_rate_pct / 100.0
    a_rate = (growth_rate_pct * 1.8) / 100.0

    year_indices = list(range(years + 1))
    c_path = [baseline * ((1.0 + c_rate) ** y) for y in year_indices]
    b_path = [baseline * ((1.0 + b_rate) ** y) for y in year_indices]
    a_path = [baseline * ((1.0 + a_rate) ** y) for y in year_indices]

    # Monte Carlo simulation around base plan (250 runs)
    np.random.seed(42)
    mc_paths = np.zeros((250, years + 1))
    mc_paths[:, 0] = baseline
    for y in range(1, years + 1):
        rand_shocks = np.random.normal(loc=b_rate, scale=0.07, size=250)
        mc_paths[:, y] = mc_paths[:, y - 1] * (1.0 + rand_shocks)

    ci_10 = np.percentile(mc_paths, 10, axis=0)
    ci_90 = np.percentile(mc_paths, 90, axis=0)

    # Plot
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=120)
    fig.patch.set_facecolor('#FAF7F2')
    ax.set_facecolor('#FAF7F2')

    ax.fill_between(year_indices, ci_10, ci_90, color='#8B6F3E', alpha=0.15, label='80% Monte Carlo Confidence Band')
    ax.plot(year_indices, b_path, color='#8B6F3E', linewidth=2.8, marker='o', label=f'Base Plan (+{growth_rate_pct:.1f}% CAGR)')
    ax.plot(year_indices, c_path, color='#4A3B2C', linewidth=2.0, linestyle='--', marker='s', label=f'Conservative (+{growth_rate_pct*0.5:.1f}% CAGR)')
    ax.plot(year_indices, a_path, color='#2D5A43', linewidth=2.0, linestyle='-.', marker='^', label=f'Aggressive (+{growth_rate_pct*1.8:.1f}% CAGR)')

    # Labels and end annotations
    ax.set_title(f"Strategic Growth Trajectory Simulation: {metric_col.upper()} (Years 0–{years})", fontsize=12, fontweight='bold', color='#1A1208', pad=12)
    ax.set_xlabel("Projection Horizon (Years from Today)", fontsize=10, fontweight='bold', color='#1A1208')
    ax.set_ylabel(f"Projected {metric_col}", fontsize=10, fontweight='bold', color='#1A1208')
    ax.set_xticks(year_indices)
    ax.set_xticklabels([f"Year {y}" if y > 0 else "Current Baseline" for y in year_indices])
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper left', frameon=True, facecolor='#FAF7F2')

    # Format numbers nicely
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, p: f"{x:,.0f}"))

    # End point annotation
    ax.annotate(f"Base Target:\n{b_path[-1]:,.0f}", xy=(years, b_path[-1]),
                xytext=(years - 0.7, b_path[-1] * 1.05),
                arrowprops=dict(facecolor='#8B6F3E', shrink=0.08, width=1.5, headwidth=6),
                fontweight='bold', fontsize=9, color='#1A1208',
                bbox=dict(boxstyle="round,pad=0.3", fc="#EDE4D0", ec="#8B6F3E", lw=1))

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    b64_chart = base64.b64encode(buf.getvalue()).decode('utf-8')

    table_data = []
    for y in year_indices:
        table_data.append({
            "year": f"Year {y}" if y > 0 else "Baseline",
            "conservative": round(c_path[y], 2),
            "base": round(b_path[y], 2),
            "aggressive": round(a_path[y], 2),
            "p10_uncertainty": round(ci_10[y], 2),
            "p90_uncertainty": round(ci_90[y], 2)
        })

    narrative = (
        f"Simulated {years}-year growth scenarios for {metric_col} starting from baseline {baseline:,.0f}:\n"
        f"• Base Case (+{growth_rate_pct:.1f}% CAGR): reaches {b_path[-1]:,.0f} by Year {years} (+{((b_path[-1]/baseline)-1)*100:.1f}% cumulative gain).\n"
        f"• Conservative Downside (+{growth_rate_pct*0.5:.1f}% CAGR): reaches {c_path[-1]:,.0f}.\n"
        f"• Aggressive Upside (+{growth_rate_pct*1.8:.1f}% CAGR): reaches {a_path[-1]:,.0f}.\n"
        f"• Monte Carlo Risk Analysis: 80% of stochastic paths fall within {ci_10[-1]:,.0f} – {ci_90[-1]:,.0f} at horizon."
    )

    return {
        "metric_name": metric_col,
        "baseline_value": baseline,
        "years": years,
        "growth_rate_pct": growth_rate_pct,
        "table": table_data,
        "narrative": narrative,
        "chart_base64": b64_chart
    }


def tool_generate_strategic_roadmap(
    report_context: str,
    dataset_info: str,
    focus_area: str = "all",
    horizon_days: int = 90
) -> dict:
    """Uses LLM reasoning to produce a 30-60-90 Day Strategic Execution Roadmap with owners, OKRs, and KPIs."""
    prompt = f"""You are a Principal Management Consultant and Chief Strategy Officer.
Formulate a rigorous 30-60-90 Day Strategic Execution Roadmap for this organization based on the dataset findings.

FOCUS AREA: {focus_area}
HORIZON: {horizon_days} Days

DATASET & BUSINESS CONTEXT:
{dataset_info[:1500]}

KEY FINDINGS & METRICS:
{report_context[:4000]}

STRUCTURE YOUR PLAN INTO 3 DISTINCT PHASES:
- Phase 1: Days 1 to 30 (Immediate Wins & Risk Remediation)
- Phase 2: Days 31 to 60 (Operational Optimization & Core Engine Calibration)
- Phase 3: Days 61 to 90 (Strategic Moats, Scaled Expansion & Predictive Automation)

For EACH phase, provide 2 to 3 high-impact initiatives.
Each initiative must specify:
- title: concise action title
- objective: 1-2 sentence core objective
- owner: functional team (e.g. "Growth / RevOps", "Data Science", "Product")
- kpi_target: concrete quantifiable target metric
- expected_impact: projected financial or efficiency outcome
- difficulty: "Low" | "Medium" | "High"

Return ONLY a valid JSON object matching this schema:
{{
  "executive_rationale": "High-level strategic narrative (3-4 sentences)",
  "phases": [
    {{
      "phase_name": "Phase 1: Days 1-30 (Immediate Triage)",
      "timeframe": "Days 1-30",
      "initiatives": [ ... ]
    }},
    {{
      "phase_name": "Phase 2: Days 31-60 (Systematic Optimization)",
      "timeframe": "Days 31-60",
      "initiatives": [ ... ]
    }},
    {{
      "phase_name": "Phase 3: Days 61-90 (Strategic Scaling)",
      "timeframe": "Days 61-90",
      "initiatives": [ ... ]
    }}
  ]
}}"""

    messages = [
        {"role": "system", "content": "You are a Chief Strategy Officer. Produce actionable, high-ROI 30-60-90 day execution roadmaps in strict JSON format."},
        {"role": "user", "content": prompt}
    ]

    try:
        from app.utils import parse_json_safely
        resp = chat_completion(messages, task="report", json_mode=True, timeout=120)
        parsed = parse_json_safely(resp)
        if not parsed.get("phases"):
            raise ValueError("No phases returned in roadmap")
    except Exception as e:
        logger.warning(f"Roadmap LLM generation error: {e}, using analytical template fallback")
        parsed = {
            "executive_rationale": "Prioritize high-leverage bottlenecks identified in initial audit before scaling acquisition or expanding operational footprint.",
            "phases": [
                {
                    "phase_name": "Phase 1: Days 1-30 (Immediate Triage & Remediation)",
                    "timeframe": "Days 1-30",
                    "initiatives": [
                        {"title": "Stem High-Risk Attrition Leaks", "objective": "Flag and intervene on top customer/segment churn indicators.", "owner": "RevOps & Retention", "kpi_target": "5-10% churn reduction in 30 days", "expected_impact": "Stabilize monthly base run-rate", "difficulty": "Low"},
                        {"title": "Pricing & Discount Threshold Audit", "objective": "Realign aggressive discount tiers to prevent margin dilution.", "owner": "Finance / Growth", "kpi_target": "+2.5% Gross Margin recovery", "expected_impact": "Direct margin uplift", "difficulty": "Medium"}
                    ]
                },
                {
                    "phase_name": "Phase 2: Days 31-60 (Systematic Optimization)",
                    "timeframe": "Days 31-60",
                    "initiatives": [
                        {"title": "Cohort-Specific Activation Flows", "objective": "Deploy tailored onboarding and value milestones for lagging cohorts.", "owner": "Product Marketing", "kpi_target": "+15% 30-day cohort retention", "expected_impact": "Accelerate LTV expansion", "difficulty": "Medium"},
                        {"title": "Feature Importance Automation", "objective": "Incorporate ML driver signals directly into daily operational dashboards.", "owner": "Data Engineering", "kpi_target": "100% daily signal refresh", "expected_impact": "Proactive decision capability", "difficulty": "Medium"}
                    ]
                },
                {
                    "phase_name": "Phase 3: Days 61-90 (Strategic Scaling & Moats)",
                    "timeframe": "Days 61-90",
                    "initiatives": [
                        {"title": "Automated Counterfactual Simulation", "objective": "Embed causal elasticity modeling into quarterly budgeting cycles.", "owner": "Executive Team", "kpi_target": "100% capital allocations validated", "expected_impact": "Eliminate misallocated spend", "difficulty": "High"}
                    ]
                }
            ]
        }

    # Format into markdown as well
    md_lines = [f"### 🗺️ Strategic Execution Roadmap ({horizon_days}-Day Horizon)\n", f"**Executive Strategy:** {parsed.get('executive_rationale', '')}\n"]
    for phase in parsed.get("phases", []):
        md_lines.append(f"#### 📅 {phase.get('phase_name', '')}")
        for init in phase.get("initiatives", []):
            md_lines.append(
                f"- **{init.get('title')}** `[{init.get('difficulty')} Difficulty | Owner: {init.get('owner')}]`\n"
                f"  - *Objective*: {init.get('objective')}\n"
                f"  - *Target KPI*: `{init.get('kpi_target')}` | *Expected Impact*: {init.get('expected_impact')}"
            )
        md_lines.append("")

    return {
        "phases": parsed.get("phases", []),
        "executive_rationale": parsed.get("executive_rationale", ""),
        "markdown": "\n".join(md_lines)
    }


def tool_run_causal_what_if(
    df: pd.DataFrame,
    treatment_col: Optional[str] = None,
    outcome_col: Optional[str] = None,
    delta_change_pct: float = 10.0
) -> dict:
    """Calculates causal treatment elasticity and simulates counterfactual outcome shift with sensitivity curves."""
    if df.empty:
        return {"error": "Dataset is empty"}

    num_cols = df.select_dtypes(include="number").columns.tolist()
    if len(num_cols) < 2:
        return {"error": "At least two numeric variables are required for causal what-if simulation"}

    if not treatment_col or treatment_col not in df.columns:
        cand_treatments = [c for c in num_cols if any(k in c.lower() for k in ["discount", "price", "spend", "cost", "hours", "tenure", "rate", "salary"])]
        treatment_col = cand_treatments[0] if cand_treatments else num_cols[0]

    if not outcome_col or outcome_col not in df.columns or outcome_col == treatment_col:
        cand_outcomes = [c for c in num_cols if c != treatment_col and any(k in c.lower() for k in ["churn", "revenue", "sales", "score", "performance", "rating", "orders", "conversion"])]
        outcome_col = cand_outcomes[0] if cand_outcomes else [c for c in num_cols if c != treatment_col][0]

    # Clean subset
    covariates = [c for c in num_cols if c not in (treatment_col, outcome_col)][:4]
    cols_to_use = [treatment_col, outcome_col] + covariates
    sub_df = df[cols_to_use].dropna().copy()

    if len(sub_df) < 15:
        return {"error": f"Insufficient non-null rows ({len(sub_df)}) for causal modeling"}

    X_mat = sub_df[[treatment_col] + covariates].values
    y_vec = sub_df[outcome_col].values

    # Fit Ridge regression with controls
    ridge = Ridge(alpha=1.0)
    ridge.fit(X_mat, y_vec)
    beta = float(ridge.coef_[0])

    t_mean = float(sub_df[treatment_col].mean())
    y_mean = float(sub_df[outcome_col].mean())

    # Elasticity: % change in Y per 1% change in X
    elasticity = (beta * (t_mean / y_mean)) if y_mean != 0 else beta

    # Counterfactual simulation
    shift_factor = 1.0 + (delta_change_pct / 100.0)
    X_cf = X_mat.copy()
    X_cf[:, 0] = X_cf[:, 0] * shift_factor

    y_pred_baseline = ridge.predict(X_mat)
    y_pred_cf = ridge.predict(X_cf)

    mean_baseline = float(np.mean(y_pred_baseline))
    mean_cf = float(np.mean(y_pred_cf))
    delta_abs = mean_cf - mean_baseline
    delta_pct = (delta_abs / mean_baseline * 100.0) if mean_baseline != 0 else 0.0

    # Sensitivity range: -30% to +30%
    sensitivity_pcts = np.linspace(-30, 30, 25)
    sensitivity_outcomes = [mean_baseline + beta * (t_mean * (p / 100.0)) for p in sensitivity_pcts]

    # Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5), dpi=120)
    fig.patch.set_facecolor('#FAF7F2')
    ax1.set_facecolor('#FAF7F2')
    ax2.set_facecolor('#FAF7F2')

    # Subplot 1: Sensitivity curve
    ax1.plot(sensitivity_pcts, sensitivity_outcomes, color='#8B6F3E', linewidth=2.5, label='Predicted Outcome Response')
    ax1.scatter([0], [mean_baseline], color='#1A1208', s=70, zorder=5, label='Current Baseline')
    ax1.scatter([delta_change_pct], [mean_cf], color='#A23B2A', s=80, marker='*', zorder=5, label=f'Intervention (+{delta_change_pct:.0f}%)')
    ax1.axvline(0, color='#D4C9B0', linestyle=':')
    ax1.axhline(mean_baseline, color='#D4C9B0', linestyle=':')
    ax1.set_xlabel(f"Percentage Change in {treatment_col} (%)", fontsize=10, fontweight='bold', color='#1A1208')
    ax1.set_ylabel(f"Projected {outcome_col}", fontsize=10, fontweight='bold', color='#1A1208')
    ax1.set_title(f"Sensitivity Curve: {treatment_col} → {outcome_col}", fontsize=11, fontweight='bold', color='#1A1208')
    ax1.legend(loc='best', frameon=True, facecolor='#FAF7F2')
    ax1.grid(True, linestyle='--', alpha=0.5)

    # Subplot 2: Bar / Distribution comparison
    labels = ['Baseline', f'What-If (+{delta_change_pct:.0f}%)']
    values = [mean_baseline, mean_cf]
    colors = ['#4A3B2C', '#8B6F3E']
    bars = ax2.bar(labels, values, color=colors, width=0.45, edgecolor='#1A1208')
    for bar in bars:
        h = bar.get_height()
        ax2.annotate(f"{h:,.2f}",
                     xy=(bar.get_x() + bar.get_width() / 2, h),
                     xytext=(0, 4), textcoords="offset points",
                     ha='center', va='bottom', fontweight='bold', fontsize=10)
    ax2.set_ylabel(f"Mean Expected {outcome_col}", fontsize=10, fontweight='bold', color='#1A1208')
    ax2.set_title(f"Expected Shift: {delta_pct:+.2f}% ({delta_abs:+,.2f})", fontsize=11, fontweight='bold', color='#1A1208')
    ax2.grid(axis='y', linestyle='--', alpha=0.5)

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    b64_chart = base64.b64encode(buf.getvalue()).decode('utf-8')

    narrative = (
        f"Simulated Counterfactual Causal Shift: {treatment_col} changed by {delta_change_pct:+.1f}%.\n"
        f"• Baseline Expected {outcome_col}: {mean_baseline:,.2f} → Projected: {mean_cf:,.2f} ({delta_pct:+.2f}% shift).\n"
        f"• Estimated Marginal Elasticity: {elasticity:.3f} (for every 1% shift in {treatment_col}, {outcome_col} shifts by ~{elasticity:.3f}%).\n"
        f"• Strategic Verdict: {'Positive outcome momentum expected.' if delta_abs > 0 else 'Negative outcome pressure detected; caution advised on aggressive shift.'}"
    )

    return {
        "treatment_column": treatment_col,
        "outcome_column": outcome_col,
        "delta_change_pct": delta_change_pct,
        "baseline_mean": mean_baseline,
        "counterfactual_mean": mean_cf,
        "delta_absolute": delta_abs,
        "delta_percentage": delta_pct,
        "elasticity": elasticity,
        "chart_base64": b64_chart,
        "narrative": narrative
    }


def tool_execute_custom_code(df: pd.DataFrame, code: str) -> dict:
    """Executes arbitrary analyst Python code against df in a secured sandbox environment."""
    exec_res = execute_analysis_code(code, df, timeout_seconds=45)
    chart_base64_list = []
    for out in exec_res.agent_outputs:
        if out.get("type") == "image" and isinstance(out.get("data"), (bytes, bytearray)):
            chart_base64_list.append(base64.b64encode(out["data"]).decode("utf-8"))

    return {
        "success": exec_res.success,
        "stdout": exec_res.stdout or "",
        "stderr": exec_res.stderr or "",
        "charts": chart_base64_list
    }


# ==============================================================================
# TOOL REST ENDPOINTS
# ==============================================================================

@router.post("/reports/{report_id}/tools/train-model")
async def api_tool_train_model(report_id: str, body: TrainModelRequest):
    """Trains a custom predictive model on the report dataset."""
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)
    if df.empty:
        raise HTTPException(status_code=400, detail="Underlying dataset not available")
    res = tool_train_custom_model(df, target_col=body.target_col, feature_cols=body.feature_cols)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.post("/reports/{report_id}/tools/simulate-growth")
async def api_tool_simulate_growth(report_id: str, body: SimulateGrowthRequest):
    """Runs a 5-10 year multi-scenario growth projection with Monte Carlo uncertainty."""
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)
    if df.empty:
        raise HTTPException(status_code=400, detail="Underlying dataset not available")
    res = tool_simulate_growth_scenario(df, metric_col=body.metric_col, growth_rate_pct=body.growth_rate_pct, years=body.years)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.post("/reports/{report_id}/tools/roadmap")
async def api_tool_roadmap(report_id: str, body: RoadmapRequest):
    """Generates a structured 30-60-90 Day Strategic Execution Roadmap."""
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)
    report_context, dataset_info = _build_rich_context(report_data, df)
    res = tool_generate_strategic_roadmap(report_context, dataset_info, focus_area=body.focus_area, horizon_days=body.horizon_days)
    return res


@router.post("/reports/{report_id}/tools/causal-what-if")
async def api_tool_causal_what_if(report_id: str, body: CausalWhatIfRequest):
    """Simulates counterfactual interventions and marginal causal elasticity."""
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)
    if df.empty:
        raise HTTPException(status_code=400, detail="Underlying dataset not available")
    res = tool_run_causal_what_if(df, treatment_col=body.treatment_col, outcome_col=body.outcome_col, delta_change_pct=body.delta_change_pct)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.post("/reports/{report_id}/tools/execute-code")
async def api_tool_execute_code(report_id: str, body: ExecuteCodeRequest):
    """Executes custom Python analysis code on dataset in sandbox."""
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    df = _get_report_dataframe(report_id, report_data)
    if df.empty:
        raise HTTPException(status_code=400, detail="Underlying dataset not available")
    res = tool_execute_custom_code(df, body.code)
    return res


@router.post("/reports/{report_id}/tools/export-memo")
async def api_tool_export_memo(report_id: str, body: ExportChatRequest):
    """Exports chat investigation history into a polished executive memo document."""
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")
    report_data = reports_db[report_id]
    report = report_data.get("report", {})
    filename = report_data.get("filename", "Dataset")

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>{body.title} - GenQ Analytics</title>
<style>
  body {{ font-family: 'DM Mono', monospace, sans-serif; background-color: #F5F0E8; color: #1A1208; margin: 40px; }}
  .header {{ border-bottom: 2px solid #8B6F3E; padding-bottom: 20px; margin-bottom: 30px; }}
  h1 {{ font-family: 'Playfair Display', serif; font-size: 28px; margin: 0 0 10px 0; color: #1A1208; }}
  .meta {{ font-size: 13px; color: #6B5B4E; }}
  .summary {{ background: #EDE4D0; padding: 20px; border-left: 4px solid #8B6F3E; border-radius: 4px; margin-bottom: 30px; }}
  .chat-turn {{ margin-bottom: 20px; padding: 15px; border-radius: 6px; }}
  .user-msg {{ background: #FAF7F2; border: 1px solid #D4C9B0; }}
  .assistant-msg {{ background: #FFFFFF; border: 1px solid #8B6F3E; }}
  .role {{ font-weight: bold; text-transform: uppercase; font-size: 11px; color: #8B6F3E; margin-bottom: 6px; }}
  pre {{ background: #FAF7F2; padding: 10px; border-radius: 4px; overflow-x: auto; }}
</style>
</head>
<body>
  <div class="header">
    <h1>{body.title}</h1>
    <div class="meta">Dataset: <strong>{filename}</strong> | GenQ Copilot Strategic Briefing</div>
  </div>
  <div class="summary">
    <div style="font-weight: bold; margin-bottom: 8px;">Executive Baseline:</div>
    <div>{report.get('executiveSummary', report.get('executive_summary', 'No summary available.'))[:800]}</div>
  </div>
  <div class="conversation">
    <h2>Interactive Analytical Dialogue</h2>
"""
    for msg in body.history:
        cls = "user-msg" if msg.role == "user" else "assistant-msg"
        html_content += f"""
    <div class="chat-turn {cls}">
      <div class="role">{msg.role}</div>
      <div>{msg.content.replace(chr(10), '<br/>')}</div>
    </div>
"""

    html_content += """
  </div>
</body>
</html>
"""
    return Response(content=html_content, media_type="text/html")


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
