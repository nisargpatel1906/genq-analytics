"""
export_notebook.py — Generates a Jupyter notebook (.ipynb) from a stored report.

The notebook is reconstructed from the report's stored data:
  - Dataset schema and sample rows → data loading cell
  - investigation_log tool calls → annotated analysis cells
  - visualization_code_used → runnable viz cell
  - keyFindings / executiveSummary / recommendations → markdown summary cells

No re-execution of LLM calls is needed — everything comes from what was
already stored in the report record.
"""
import json
import io
from datetime import datetime
from fastapi.responses import StreamingResponse


# ── nbformat-like helpers (no nbformat dependency needed) ────────────────────

def _nb_metadata() -> dict:
    return {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "name": "python",
            "version": "3.11.0"
        }
    }


def _markdown_cell(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": source
    }


def _code_cell(source: str, output_text: str = "") -> dict:
    outputs = []
    if output_text:
        outputs.append({
            "output_type": "stream",
            "name": "stdout",
            "text": output_text
        })
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": source,
        "outputs": outputs
    }


# ── Notebook builder ─────────────────────────────────────────────────────────

def _build_notebook(report_id: str, report_data: dict) -> dict:
    """
    Builds a complete Jupyter notebook dict from the stored report record.
    """
    cells = []
    report = report_data.get("report", {})
    stats = report_data.get("stats", {})
    filename = report_data.get("filename", "dataset.csv")
    domain = report.get("domain", "Data Analysis")
    created_at = report_data.get("created_at", datetime.now().strftime("%b %d, %Y"))
    schema = stats.get("schema", {})
    sample_rows = report_data.get("data_sample", [])
    investigation_log = report.get("investigation_log", [])
    viz_code = report.get("visualization_code_used", "")
    findings = report.get("keyFindings", [])
    anomalies = report.get("anomalies", [])
    recommendations = report.get("recommendations", [])
    exec_summary = report.get("executiveSummary", "")

    # ── 1. Title cell ────────────────────────────────────────────────────────
    cells.append(_markdown_cell(
        f"# {domain} — AI Analysis Report\n\n"
        f"**File:** `{filename}`  \n"
        f"**Generated:** {created_at}  \n"
        f"**Report ID:** `{report_id}`\n\n"
        f"---\n\n"
        f"This notebook was automatically reconstructed from the GenQ Analytics agent run. "
        f"All analysis steps, statistical tests, and visualizations performed by the AI agent "
        f"are reproduced here as reproducible Python code."
    ))

    # ── 2. Imports + data loading ────────────────────────────────────────────
    col_names = list(schema.keys()) if schema else (
        list(sample_rows[0].keys()) if sample_rows else []
    )

    # Generate dtype hints from schema
    dtype_comments = ""
    if schema:
        dtype_lines = []
        for col, info in schema.items():
            dtype = info.get("dtype", "object") if isinstance(info, dict) else str(info)
            dtype_lines.append(f"#   {col!r}: {dtype}")
        if dtype_lines:
            dtype_comments = "\n# Column dtypes from schema:\n" + "\n".join(dtype_lines) + "\n"

    # Embed a small inline sample so the notebook works without the original file
    sample_json_str = json.dumps(sample_rows[:20], indent=2, default=str)

    setup_code = (
        "import pandas as pd\n"
        "import numpy as np\n"
        "import matplotlib.pyplot as plt\n"
        "import seaborn as sns\n"
        "import scipy.stats as stats\n"
        "import warnings\n"
        "warnings.filterwarnings('ignore')\n"
        "\n"
        "sns.set_theme(style='whitegrid')\n"
        "plt.rcParams['figure.dpi'] = 120\n"
        "\n"
        f"# ── Load dataset ────────────────────────────────────────────────────\n"
        f"# Option A: Load your original file\n"
        f"# df = pd.read_csv('{filename}')   # or pd.read_excel(...)\n"
        f"\n"
        f"# Option B: Use the embedded sample data (first 20 rows from original analysis)\n"
        f"_sample_data = {sample_json_str}\n"
        f"df = pd.DataFrame(_sample_data)\n"
        f"{dtype_comments}\n"
        f"print(f'Dataset loaded: {{len(df)}} rows × {{len(df.columns)}} columns')\n"
        f"df.head()"
    )
    cells.append(_markdown_cell("## 1. Setup & Data Loading"))
    cells.append(_code_cell(
        setup_code,
        f"Dataset loaded: {len(sample_rows)} rows × {len(col_names)} columns\n"
    ))

    # ── 3. Schema overview ───────────────────────────────────────────────────
    cells.append(_markdown_cell("## 2. Dataset Overview"))
    overview_code = (
        "print('=== Dataset Info ===')\n"
        "print(df.info())\n"
        "print()\n"
        "print('=== Descriptive Statistics ===')\n"
        "df.describe(include='all').T"
    )
    cells.append(_code_cell(overview_code))

    # ── 4. Agent investigation log → cells ───────────────────────────────────
    if investigation_log:
        cells.append(_markdown_cell(
            "## 3. Agent Investigation Steps\n\n"
            "The following cells reconstruct the step-by-step analysis performed by the AI Data Scientist agent. "
            "Each tool call is shown with its reasoning (thought) and result."
        ))

        tool_code_templates = {
            "inspect_column": (
                "# inspect_column: {col_name}\n"
                "col = df['{col_name}']\n"
                "if pd.api.types.is_numeric_dtype(col):\n"
                "    display(col.describe().to_frame())\n"
                "    print(f'Skewness: {{col.skew():.4f}}, Kurtosis: {{col.kurt():.4f}}')\n"
                "else:\n"
                "    display(col.value_counts(normalize=True).head(10).to_frame())"
            ),
            "run_test_correlation": (
                "# run_test: Pearson & Spearman correlation between '{col_a}' and '{col_b}'\n"
                "from scipy import stats as _stats\n"
                "_clean = df[['{col_a}', '{col_b}']].dropna()\n"
                "pearson_r, pearson_p = _stats.pearsonr(_clean['{col_a}'], _clean['{col_b}'])\n"
                "spearman_r, spearman_p = _stats.spearmanr(_clean['{col_a}'], _clean['{col_b}'])\n"
                "print(f'Pearson r={{pearson_r:.4f}}, p={{pearson_p:.4e}}')\n"
                "print(f'Spearman r={{spearman_r:.4f}}, p={{spearman_p:.4e}}')"
            ),
            "run_test_t_test": (
                "# run_test: Independent samples t-test '{col_a}' by '{col_b}' groups\n"
                "from scipy import stats as _stats\n"
                "_groups = df['{col_b}'].dropna().unique()[:2]\n"
                "_g1 = df[df['{col_b}'] == _groups[0]]['{col_a}'].dropna()\n"
                "_g2 = df[df['{col_b}'] == _groups[1]]['{col_a}'].dropna()\n"
                "_t, _p = _stats.ttest_ind(_g1, _g2, equal_var=False)\n"
                "print(f'Group 1 ({{}}) mean={{_g1.mean():.4f}}, Group 2 ({{}}) mean={{_g2.mean():.4f}}'.format(_groups[0], _groups[1]))\n"
                "print(f't-statistic={{_t:.4f}}, p-value={{_p:.4e}}')"
            ),
            "run_test_chi2_test": (
                "# run_test: Chi-squared test between '{col_a}' and '{col_b}'\n"
                "from scipy import stats as _stats\n"
                "_ct = pd.crosstab(df['{col_a}'], df['{col_b}'])\n"
                "_chi2, _p, _dof, _exp = _stats.chi2_contingency(_ct)\n"
                "print(f'Chi2={{_chi2:.4f}}, p={{_p:.4e}}, dof={{_dof}}')"
            ),
            "create_chart": (
                "# create_chart: {chart_type} of '{x}' vs '{y}'\n"
                "fig, ax = plt.subplots(figsize=(9, 5))\n"
                "sns.{chart_type}plot(data=df, x='{x}', y='{y}', ax=ax)\n"
                "ax.set_title('{chart_type_title} of {x} vs {y}')\n"
                "plt.tight_layout()\n"
                "plt.show()"
            ),
            "save_finding": (
                "# save_finding: '{title}'\n"
                "print('Finding: {title}')\n"
                "print('Evidence: {evidence}')\n"
                "print('Confidence: {confidence}%')"
            ),
        }

        step_num = 1
        for log_entry in investigation_log:
            if log_entry.get("agent") != "data_scientist":
                continue
            action = log_entry.get("action", "")
            result = log_entry.get("result", "")

            # Parse action to figure out tool call info
            action_lower = action.lower()

            # Generate human-readable code cell from action description
            if "inspect_column" in action_lower or "inspect" in action_lower:
                # Extract column name from action string
                col_name = action.replace("Called inspect_column with", "").strip()
                col_name = col_name.strip("{}' ").replace("col_name:", "").strip().strip("'\"")
                if col_name and col_name in (col_names or []):
                    md = (
                        f"### Step {step_num}: Inspect Column `{col_name}`\n\n"
                        f"**Thought:** {action}\n\n"
                        f"**Result:** `{str(result)[:300]}`"
                    )
                    code = tool_code_templates["inspect_column"].format(col_name=col_name)
                    cells.append(_markdown_cell(md))
                    cells.append(_code_cell(code, str(result)[:300] + "\n"))
                    step_num += 1

            elif "correlation" in action_lower:
                parts = action.split("->")[0] if "->" in action else action
                cols_mentioned = [c for c in col_names if c in parts]
                col_a = cols_mentioned[0] if len(cols_mentioned) > 0 else "col_a"
                col_b = cols_mentioned[1] if len(cols_mentioned) > 1 else "col_b"
                md = (
                    f"### Step {step_num}: Correlation Test — `{col_a}` vs `{col_b}`\n\n"
                    f"**Thought:** {action}\n\n"
                    f"**Result:** `{str(result)[:300]}`"
                )
                code = tool_code_templates["run_test_correlation"].format(col_a=col_a, col_b=col_b)
                cells.append(_markdown_cell(md))
                cells.append(_code_cell(code, str(result)[:300] + "\n"))
                step_num += 1

            elif "t_test" in action_lower or "t-test" in action_lower:
                cols_mentioned = [c for c in col_names if c in action]
                col_a = cols_mentioned[0] if len(cols_mentioned) > 0 else "numeric_col"
                col_b = cols_mentioned[1] if len(cols_mentioned) > 1 else "group_col"
                md = f"### Step {step_num}: T-Test — `{col_a}` by `{col_b}`\n\n**Result:** `{str(result)[:300]}`"
                code = tool_code_templates["run_test_t_test"].format(col_a=col_a, col_b=col_b)
                cells.append(_markdown_cell(md))
                cells.append(_code_cell(code, str(result)[:300] + "\n"))
                step_num += 1

            elif "chi2" in action_lower:
                cols_mentioned = [c for c in col_names if c in action]
                col_a = cols_mentioned[0] if len(cols_mentioned) > 0 else "col_a"
                col_b = cols_mentioned[1] if len(cols_mentioned) > 1 else "col_b"
                md = f"### Step {step_num}: Chi-Squared Test — `{col_a}` vs `{col_b}`\n\n**Result:** `{str(result)[:300]}`"
                code = tool_code_templates["run_test_chi2_test"].format(col_a=col_a, col_b=col_b)
                cells.append(_markdown_cell(md))
                cells.append(_code_cell(code, str(result)[:300] + "\n"))
                step_num += 1

            elif "chart" in action_lower or "scatter" in action_lower or "bar" in action_lower or "line" in action_lower:
                cols_mentioned = [c for c in col_names if c in action]
                col_x = cols_mentioned[0] if len(cols_mentioned) > 0 else col_names[0] if col_names else "x"
                col_y = cols_mentioned[1] if len(cols_mentioned) > 1 else (col_names[1] if len(col_names) > 1 else "y")
                chart_type = "scatter"
                for ct in ["line", "bar", "box", "scatter"]:
                    if ct in action_lower:
                        chart_type = ct
                        break
                md = f"### Step {step_num}: Create Chart — {chart_type.title()} of `{col_x}` vs `{col_y}`"
                code = tool_code_templates["create_chart"].format(
                    chart_type=chart_type,
                    chart_type_title=chart_type.title(),
                    x=col_x,
                    y=col_y
                )
                cells.append(_markdown_cell(md))
                cells.append(_code_cell(code))
                step_num += 1

            elif "finding" in action_lower:
                title = action.replace("Saved key finding:", "").strip()
                evidence = str(result)[:400] if result else ""
                md = (
                    f"### Step {step_num}: Saved Finding\n\n"
                    f"**Finding:** {title}\n\n"
                    f"**Evidence:** {evidence}"
                )
                cells.append(_markdown_cell(md))
                step_num += 1

    # ── 5. Visualization code ────────────────────────────────────────────────
    if viz_code and viz_code.strip() and viz_code != "Iterative Tool-calling Execution Loop":
        cells.append(_markdown_cell(
            "## 4. Visualization Agent Code\n\n"
            "The following cell contains the Python code generated by the AI Visualization Agent. "
            "This code creates the publication-quality charts included in the report.\n\n"
            "> **Note:** Chart filenames referenced below were saved relative to the analysis working directory. "
            "Run this cell after loading your data to regenerate the charts locally."
        ))
        cells.append(_code_cell(viz_code))

    # ── 6. Key findings summary ──────────────────────────────────────────────
    if findings:
        findings_md = "## 5. Key Findings\n\n"
        for i, f in enumerate(findings, 1):
            title = f.get("title", f"Finding {i}")
            detail = f.get("detail", f.get("evidence", ""))
            confidence = f.get("confidence", "")
            impact = f.get("impact_score", "")
            chart_ref = f.get("supporting_chart", "")
            findings_md += f"### {i}. {title}\n\n"
            findings_md += f"{detail}\n\n"
            if confidence:
                findings_md += f"**Confidence:** {confidence}%  \n"
            if impact:
                findings_md += f"**Impact Score:** {impact}/10  \n"
            if chart_ref:
                findings_md += f"**Chart:** `{chart_ref}`  \n"
            findings_md += "\n"
        cells.append(_markdown_cell(findings_md))

    # ── 7. Anomalies ─────────────────────────────────────────────────────────
    if anomalies:
        anom_md = "## 6. Anomalies & Outliers\n\n"
        for a in anomalies:
            title = a.get("description", a.get("title", "Anomaly"))
            severity = a.get("severity", "medium")
            detail = a.get("detail", a.get("columns", ""))
            anom_md += f"- **{title}** *(severity: {severity})*\n"
            if detail:
                anom_md += f"  - {detail}\n"
        cells.append(_markdown_cell(anom_md))

    # ── 8. Recommendations ───────────────────────────────────────────────────
    if recommendations:
        rec_md = "## 7. Strategic Recommendations\n\n"
        for i, r in enumerate(recommendations, 1):
            action = r.get("action", r.get("recommendation", f"Recommendation {i}"))
            rationale = r.get("rationale", "")
            priority = r.get("priority", "medium")
            outcome = r.get("expected_outcome", "")
            rec_md += f"### {i}. {action}\n\n"
            rec_md += f"**Priority:** {priority.upper()}  \n"
            if rationale:
                rec_md += f"**Rationale:** {rationale}  \n"
            if outcome:
                rec_md += f"**Expected Outcome:** {outcome}  \n"
            rec_md += "\n"
        cells.append(_markdown_cell(rec_md))

    # ── 9. Executive summary ─────────────────────────────────────────────────
    if exec_summary:
        cells.append(_markdown_cell(
            f"## 8. Executive Summary\n\n{exec_summary}"
        ))

    # ── 10. Footer ───────────────────────────────────────────────────────────
    cells.append(_markdown_cell(
        "---\n\n"
        "*This notebook was auto-generated by [GenQ Analytics](https://github.com/). "
        "All analysis was performed by an AI Data Scientist agent using in-memory tool calls. "
        "Results are reproducible by running the cells above with the original dataset.*"
    ))

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": _nb_metadata(),
        "cells": cells
    }


# ── FastAPI response handler ─────────────────────────────────────────────────

def generate_notebook_response(report_id: str, report_data: dict) -> StreamingResponse:
    """
    Builds and streams the .ipynb file as an HTTP attachment.
    """
    notebook = _build_notebook(report_id, report_data)
    nb_json = json.dumps(notebook, indent=2, ensure_ascii=False)
    nb_bytes = nb_json.encode("utf-8")

    filename = report_data.get("filename", "analysis").rsplit(".", 1)[0]
    # Sanitize filename for content-disposition
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in filename)

    return StreamingResponse(
        io.BytesIO(nb_bytes),
        media_type="application/x-ipynb+json",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_analysis.ipynb"',
            "Content-Length": str(len(nb_bytes))
        }
    )
