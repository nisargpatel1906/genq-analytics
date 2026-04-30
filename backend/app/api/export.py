from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.db import reports_db
import os, io, base64, numpy as np, pandas as pd
from datetime import datetime

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

from reportlab.lib.pagesizes import A4
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, PageBreak, Image, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

router = APIRouter()

BRAND_DARK   = colors.HexColor("#111111")
BRAND_ACCENT = colors.HexColor("#1A56DB")
BRAND_BORDER = colors.HexColor("#E5E7EB")
BRAND_MUTED  = colors.HexColor("#6B7280")
TABLEAU10    = ["#4E79A7","#F28E2B","#E15759","#76B7B2","#59A14F",
                "#EDC949","#AF7AA1","#FF9DA7","#9C755F","#BAB0AB"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def draw_header_footer(canvas, doc, title=""):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 9)
    canvas.setFillColor(BRAND_ACCENT)
    canvas.drawString(50, A4[1] - 35, "GenQ Analytics")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(BRAND_MUTED)
    canvas.drawRightString(A4[0] - 50, A4[1] - 35, title[:80])
    canvas.setStrokeColor(BRAND_BORDER)
    canvas.line(50, A4[1] - 45, A4[0] - 50, A4[1] - 45)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(BRAND_MUTED)
    canvas.drawString(50, 28, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    canvas.drawRightString(A4[0] - 50, 28, f"Page {doc.page}")
    canvas.line(50, 42, A4[0] - 50, 42)
    canvas.restoreState()


def _save(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


# ── Intelligent chart engine ──────────────────────────────────────────────────
def build_charts(report_data: dict) -> list:
    """
    Examines the actual dataset structure and generates only charts that
    answer a real analytical question about THIS specific data.
    Returns: [{title, buf, interpretation}, ...]
    """
    charts = []
    records   = report_data.get("data_sample", [])
    col_types = report_data.get("col_types", {})
    stats     = report_data.get("stats", {})

    if not records:
        return []

    df = pd.DataFrame(records)
    num_cols  = [c for c in col_types.get("numeric", [])     if c in df.columns]
    cat_cols  = [c for c in col_types.get("categorical", []) if c in df.columns]
    dt_cols   = [c for c in col_types.get("datetime", [])    if c in df.columns]
    bin_cols  = [c for c in col_types.get("binary", [])      if c in df.columns]
    corr_map  = stats.get("correlations", {})

    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    sns.set_style("whitegrid")

    # ── CHART A: Binary target → violin per top-differentiating feature ────────
    # Question: "Which features separate the two classes the most?"
    if bin_cols and len(num_cols) >= 2:
        target     = bin_cols[0]
        non_target = [c for c in num_cols if c != target]
        c0 = df[df[target] == 0]
        c1 = df[df[target] == 1]
        diffs = sorted(
            [(abs(c1[c].mean() - c0[c].mean()) / (c0[c].std() + 1e-9), c)
             for c in non_target
             if pd.notna(c0[c].mean()) and pd.notna(c1[c].mean()) and c0[c].std() > 0],
            reverse=True
        )
        top4 = [d[1] for d in diffs[:4]]
        if top4:
            fig, axes = plt.subplots(1, len(top4), figsize=(4 * len(top4), 4))
            if len(top4) == 1:
                axes = [axes]
            class_vals = sorted(df[target].dropna().unique())
            labels = [f"Class {int(v)}" for v in class_vals]
            for i, col in enumerate(top4):
                data = [df[df[target] == v][col].dropna().values for v in class_vals]
                axes[i].violinplot(data, positions=range(len(data)), showmedians=True)
                axes[i].set_xticks(range(len(labels)))
                axes[i].set_xticklabels(labels, fontsize=8)
                axes[i].set_title(col[:18], fontsize=9, fontweight="bold")
                axes[i].spines["top"].set_visible(False)
                axes[i].spines["right"].set_visible(False)
            fig.suptitle(f"Top Features by '{target}' Class", fontsize=11, fontweight="bold")
            plt.tight_layout()

            parts = []
            for _, feat in diffs[:3]:
                m0, m1 = c0[feat].mean(), c1[feat].mean()
                parts.append(f"'{feat}' averages {m0:.2f} (class 0) vs {m1:.2f} (class 1)")
            interp = (
                f"Violin plots compare the distribution of each feature split by '{target}'. "
                "Wider sections show where most values cluster; the white dot is the median. "
                "Features shown were selected because they differ most between classes — "
                "they are the strongest natural predictors in this dataset. "
                + " | ".join(parts) + "."
            )
            charts.append({"title": f"Feature Distributions by {target}", "buf": _save(fig), "interpretation": interp})

    # ── CHART B: Time series if datetime exists ────────────────────────────────
    # Question: "How does the most variable metric trend over time?"
    elif dt_cols and num_cols:
        try:
            dt_col = dt_cols[0]
            df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
            df_t = df.dropna(subset=[dt_col]).sort_values(dt_col)
            best_col = max(num_cols, key=lambda c: df_t[c].std() if df_t[c].std() > 0 else 0)
            trend = df_t.set_index(dt_col)[best_col].resample("D").mean().dropna()
            if len(trend) >= 3:
                fig, ax = plt.subplots(figsize=(9, 3.8))
                ax.fill_between(trend.index, trend.values, alpha=0.2, color=TABLEAU10[0])
                ax.plot(trend.index, trend.values, color=TABLEAU10[0], linewidth=1.5)
                ax.set_xlabel(dt_col, fontsize=9)
                ax.set_ylabel(best_col, fontsize=9)
                ax.set_title(f"{best_col} Over Time", fontsize=11, fontweight="bold")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                plt.xticks(rotation=25, fontsize=8)
                plt.tight_layout()
                peak = trend.idxmax().strftime("%Y-%m-%d")
                interp = (
                    f"Time series of '{best_col}' (selected as the most variable metric). "
                    f"Peak value occurred around {peak}. "
                    "Spikes may indicate seasonal patterns, data entry events, or external triggers worth investigating."
                )
                charts.append({"title": f"{best_col} Trend Over Time", "buf": _save(fig), "interpretation": interp})
        except Exception:
            pass

    # ── CHART C: Scatter of strongest correlated pair with regression line ─────
    # Question: "What is the most meaningful relationship between two variables?"
    if corr_map and len(num_cols) >= 2:
        best_r, col_a, col_b = 0.0, None, None
        keys = list(corr_map.keys())
        for i, a in enumerate(keys):
            for b in keys[i+1:]:
                r = corr_map.get(a, {}).get(b)
                if r is not None and abs(r) > abs(best_r):
                    best_r, col_a, col_b = r, a, b

        if col_a and col_b and abs(best_r) > 0.30 and col_a in df.columns and col_b in df.columns:
            plot_df = df[[col_a, col_b]].dropna()
            if len(plot_df) > 10:
                fig, ax = plt.subplots(figsize=(6.5, 4.5))
                color_note = ""
                if cat_cols and cat_cols[0] in df.columns:
                    groups = df[cat_cols[0]].dropna().unique()[:8]
                    for i, g in enumerate(groups):
                        sub = df[df[cat_cols[0]] == g][[col_a, col_b]].dropna()
                        ax.scatter(sub[col_a], sub[col_b], label=str(g),
                                   alpha=0.65, color=TABLEAU10[i % len(TABLEAU10)], s=28)
                    ax.legend(title=cat_cols[0], fontsize=8, title_fontsize=8)
                    color_note = f" Points colored by '{cat_cols[0]}'."
                else:
                    ax.scatter(plot_df[col_a], plot_df[col_b], alpha=0.5, color=TABLEAU10[0], s=28)

                z = np.polyfit(plot_df[col_a].fillna(0), plot_df[col_b].fillna(0), 1)
                xline = np.linspace(plot_df[col_a].min(), plot_df[col_b].max(), 100)
                ax.plot(xline, np.poly1d(z)(xline), "--", color="#E15759", linewidth=1.5, label=f"r={best_r:.2f}")
                ax.legend(fontsize=8)
                ax.set_xlabel(col_a, fontsize=9)
                ax.set_ylabel(col_b, fontsize=9)
                ax.set_title(f"Relationship: {col_a} vs {col_b}", fontsize=11, fontweight="bold")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                plt.tight_layout()

                strength  = "very strong" if abs(best_r) > 0.8 else "strong" if abs(best_r) > 0.6 else "moderate"
                direction = "positive" if best_r > 0 else "negative"
                interp = (
                    f"This scatter plot shows the {strength} {direction} correlation (r = {best_r:.2f}) between "
                    f"'{col_a}' and '{col_b}' — the strongest linear relationship in the dataset.{color_note} "
                    "The dashed line is the regression trend. Points close to the line confirm the relationship "
                    "is consistent; outliers far from it may deserve investigation."
                )
                charts.append({"title": f"Strongest Relationship: {col_a} vs {col_b}", "buf": _save(fig), "interpretation": interp})

    # ── CHART D: Category with biggest metric spread ───────────────────────────
    # Question: "Which group has the best/worst performance on the key metric?"
    if cat_cols and num_cols:
        valid_cats = [(c, df[c].nunique()) for c in cat_cols if 2 <= df[c].nunique() <= 12]
        valid_cats.sort(key=lambda x: x[1])
        if valid_cats:
            best_cat = valid_cats[0][0]
            best_metric, best_spread = None, 0
            for nc in num_cols:
                gmeans = df.groupby(best_cat)[nc].mean()
                spread = gmeans.max() - gmeans.min()
                if pd.notna(spread) and spread > best_spread:
                    best_spread, best_metric = spread, nc

            if best_metric:
                gd = df.groupby(best_cat)[best_metric].agg(["mean", "std"]).dropna()
                gd = gd.sort_values("mean", ascending=True)
                fig, ax = plt.subplots(figsize=(8, max(3.5, len(gd) * 0.45)))
                ax.barh(gd.index.astype(str), gd["mean"],
                        xerr=gd["std"].fillna(0), capsize=4,
                        color=TABLEAU10[:len(gd)], alpha=0.85, height=0.6)
                ax.set_xlabel(f"Mean {best_metric}", fontsize=9)
                ax.set_title(f"{best_metric} by {best_cat}", fontsize=11, fontweight="bold")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                plt.tight_layout()

                top_g = gd["mean"].idxmax()
                bot_g = gd["mean"].idxmin()
                pct   = ((gd.loc[top_g, "mean"] - gd.loc[bot_g, "mean"]) /
                          max(abs(gd.loc[bot_g, "mean"]), 1)) * 100
                interp = (
                    f"Horizontal bars compare average '{best_metric}' across each '{best_cat}' group. "
                    f"'{top_g}' is highest ({gd.loc[top_g,'mean']:.2f}) and '{bot_g}' is lowest ({gd.loc[bot_g,'mean']:.2f}) "
                    f"— a {pct:.0f}% difference. Error bars show ± one standard deviation. "
                    "Groups with wide bars are internally variable; narrow bars mean consistent behaviour within that group."
                )
                charts.append({"title": f"{best_metric} by {best_cat}", "buf": _save(fig), "interpretation": interp})

    # ── CHART E: Histograms of most skewed columns ────────────────────────────
    # Question: "How are values distributed — normal, skewed, or bimodal?"
    if num_cols:
        skews = sorted(
            [(abs(df[c].skew()), df[c].skew(), c) for c in num_cols if pd.notna(df[c].skew())],
            reverse=True
        )[:3]
        if skews:
            n = len(skews)
            fig, axes = plt.subplots(1, n, figsize=(5 * n, 4))
            if n == 1:
                axes = [axes]
            for i, (_, sk, col) in enumerate(skews):
                vals = df[col].dropna()
                axes[i].hist(vals, bins=30, color=TABLEAU10[i], alpha=0.82, edgecolor="white")
                axes[i].axvline(vals.mean(),   color="#E15759", lw=1.5, ls="--", label=f"Mean {vals.mean():.2f}")
                axes[i].axvline(vals.median(), color="#4E79A7", lw=1.5, ls=":",  label=f"Median {vals.median():.2f}")
                axes[i].legend(fontsize=7)
                axes[i].set_xlabel(col, fontsize=9)
                axes[i].set_title(f"{col[:16]} (skew={sk:.2f})", fontsize=9, fontweight="bold")
                axes[i].spines["top"].set_visible(False)
                axes[i].spines["right"].set_visible(False)
            fig.suptitle("Value Distribution — Most Skewed Columns", fontsize=11, fontweight="bold")
            plt.tight_layout()

            descs = []
            for _, sk, col in skews:
                if sk > 1:   descs.append(f"'{col}' is right-skewed (skew={sk:.2f})")
                elif sk < -1: descs.append(f"'{col}' is left-skewed (skew={sk:.2f})")
                else:         descs.append(f"'{col}' is near-symmetric (skew={sk:.2f})")
            interp = (
                "Histograms show the distribution shape of the most skewed numeric columns. "
                "Red dashed = mean; blue dotted = median. When they diverge, the data is skewed. "
                + " | ".join(descs) + ". "
                "Strongly skewed columns are good candidates for log-transformation before modeling."
            )
            charts.append({"title": "Value Distribution Analysis", "buf": _save(fig), "interpretation": interp})

    return charts


# ── PDF builder ───────────────────────────────────────────────────────────────
@router.get("/export/{report_id}")
@router.get("/export/{report_id}/pdf")
async def export_pdf(report_id: str):
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    ai_report   = report_data.get("report", {})
    stats       = report_data.get("stats", {})
    filename    = report_data.get("filename", "dataset")
    pdf_path    = os.path.join(os.path.dirname(__file__), "..", "..", f"{report_id}.pdf")

    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            rightMargin=50, leftMargin=50, topMargin=75, bottomMargin=55)

    S = getSampleStyleSheet()
    title_s = ParagraphStyle("T",  parent=S["Normal"], fontName="Times-Bold",        fontSize=30, textColor=BRAND_DARK,   spaceAfter=8,   alignment=1)
    sub_s   = ParagraphStyle("Su", parent=S["Normal"], fontName="Helvetica",          fontSize=13, textColor=BRAND_MUTED,  spaceAfter=6,   alignment=1)
    h1      = ParagraphStyle("H1", parent=S["Normal"], fontName="Times-Bold",         fontSize=17, textColor=BRAND_DARK,   spaceBefore=18, spaceAfter=8)
    h2      = ParagraphStyle("H2", parent=S["Normal"], fontName="Helvetica-Bold",     fontSize=13, textColor=BRAND_ACCENT, spaceBefore=12, spaceAfter=6)
    body    = ParagraphStyle("B",  parent=S["Normal"], fontName="Helvetica",          fontSize=10, textColor=BRAND_DARK,   leading=15,     spaceAfter=8)
    caption = ParagraphStyle("C",  parent=S["Normal"], fontName="Helvetica-Oblique",  fontSize=9,  textColor=BRAND_MUTED,  leading=13,     spaceAfter=14)
    callout = ParagraphStyle("Ca", parent=S["Normal"], fontName="Helvetica",          fontSize=10, textColor=BRAND_DARK,   leading=14,     spaceAfter=6,
                              leftIndent=14, backColor=colors.HexColor("#F0F4FF"))

    story = []

    # Cover
    shape = stats.get("shape", {})
    story += [Spacer(1, 120),
              Paragraph("AI Data Analysis Report", title_s),
              Spacer(1, 8),
              Paragraph(filename, sub_s)]
    if ai_report.get("domain"):
        story.append(Paragraph(f"Domain: {ai_report['domain']}", sub_s))
    story += [Spacer(1, 10),
              Paragraph(f"{shape.get('rows','?'):,} rows  ×  {shape.get('columns','?')} columns",
                        ParagraphStyle("m", parent=sub_s, fontSize=11)),
              Spacer(1, 80),
              HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
              Spacer(1, 12),
              Paragraph(f"Generated by GenQ Analytics  ·  {datetime.now().strftime('%B %d, %Y')}",
                        ParagraphStyle("f", parent=caption, alignment=1)),
              PageBreak()]

    # Executive Summary
    exec_sum = ai_report.get("executiveSummary", "")
    if exec_sum:
        story += [Paragraph("1. Executive Summary", h1),
                  HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                  Spacer(1, 8),
                  Paragraph(exec_sum, body),
                  Spacer(1, 16)]

    # Statistics table
    num_summary = stats.get("numeric_summary", {})
    missing     = stats.get("missing_values", {})
    story += [Paragraph("2. Dataset Statistics", h1),
              HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
              Spacer(1, 8)]
    if num_summary:
        rows = [["Column", "Mean", "Std Dev", "Min", "Max", "Missing"]]
        for col, d in num_summary.items():
            rows.append([Paragraph(col[:22], body),
                         f"{(d.get('mean') or 0):.3f}",
                         f"{(d.get('std')  or 0):.3f}",
                         f"{(d.get('min')  or 0):.3f}",
                         f"{(d.get('max')  or 0):.3f}",
                         str(missing.get(col, 0))])
        t = Table(rows, colWidths=[1.9*inch, 1*inch, 1*inch, 0.9*inch, 0.9*inch, 0.8*inch])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  BRAND_DARK),
            ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
            ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0,0), (-1,-1), 9),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("GRID",          (0,0), (-1,-1), 0.4, BRAND_BORDER),
            ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("ALIGN",         (1,0), (-1,-1), "CENTER"),
        ]))
        story += [t, Spacer(1, 16)]

    # Visualizations
    story += [Paragraph("3. Data Visualizations & Interpretation", h1),
              HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
              Spacer(1, 8),
              Paragraph(
                  "Each chart below was chosen based on the actual structure of your dataset — "
                  "not a generic template. An interpretation paragraph follows every chart "
                  "explaining what the data is specifically showing.",
                  body),
              Spacer(1, 12)]

    for ch in build_charts(report_data):
        story += [Paragraph(ch["title"], h2),
                  Image(ch["buf"], width=6.0*inch, height=3.6*inch),
                  Spacer(1, 6),
                  Paragraph(f"Interpretation: {ch['interpretation']}", callout),
                  Spacer(1, 18)]

    story.append(PageBreak())

    # Key Findings
    findings = ai_report.get("keyFindings", [])
    if findings:
        story += [Paragraph("4. Key Findings", h1),
                  HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                  Spacer(1, 8)]
        for i, f in enumerate(findings, 1):
            title_t = f.get("title") or f.get("finding") or f"Finding {i}"
            detail  = f.get("detail") or f.get("description") or ""
            conf    = f.get("confidenceScore") or f.get("confidence") or 0
            story.append(Paragraph(f"{i}. {title_t}", h2))
            if detail: story.append(Paragraph(detail, body))
            if conf:   story.append(Paragraph(f"<i>AI confidence: {conf}%</i>", caption))
            story.append(Spacer(1, 8))

    # Anomalies
    anomalies_ai  = ai_report.get("anomalies", [])
    stat_anomalies = stats.get("statistical_anomalies", [])
    if anomalies_ai or stat_anomalies:
        story += [Paragraph("5. Anomalies Detected", h1),
                  HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                  Spacer(1, 8)]
        if stat_anomalies:
            story.append(Paragraph("Statistically Flagged Columns (Z-score > 3σ)", h2))
            tdata = [["Column", "Outlier Rows", "Column Mean", "Extreme Value", "3σ Threshold"]]
            for a in stat_anomalies:
                tdata.append([a.get("column",""), str(a.get("outlier_count","")),
                               f"{a.get('mean',0):.4f}", f"{a.get('max_deviation_value',0):.4f}",
                               f"{a.get('threshold_3sigma',0):.4f}"])
            t = Table(tdata, colWidths=[1.4*inch, 1*inch, 1.1*inch, 1.1*inch, 1.3*inch])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,0),  BRAND_ACCENT),
                ("TEXTCOLOR",     (0,0), (-1,0),  colors.white),
                ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
                ("FONTSIZE",      (0,0), (-1,-1), 9),
                ("TOPPADDING",    (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                ("GRID",          (0,0), (-1,-1), 0.4, BRAND_BORDER),
                ("ROWBACKGROUNDS",(0,1), (-1,-1), [colors.white, colors.HexColor("#FFF7ED")]),
                ("ALIGN",         (1,0), (-1,-1), "CENTER"),
            ]))
            story += [t, Spacer(1, 12)]

        for a in anomalies_ai:
            sev    = str(a.get("severity", "medium")).upper()
            desc   = a.get("description", "")
            impact = a.get("businessImpact", "")
            story.append(Paragraph(f"<b>{a.get('column','Unknown')}  [{sev}]</b>", body))
            if desc:   story.append(Paragraph(desc, body))
            if impact: story.append(Paragraph(f"Business impact: {impact}", caption))
            story.append(Spacer(1, 6))

    # Recommendations
    recs = ai_report.get("recommendations", [])
    if recs:
        story += [PageBreak(),
                  Paragraph("6. Recommendations", h1),
                  HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                  Spacer(1, 8)]
        for i, rec in enumerate(recs, 1):
            priority = str(rec.get("priority", "Medium")).upper()
            story.append(Paragraph(f"{i}. {rec.get('action','')}  <font color='#1A56DB'>[{priority}]</font>", h2))
            if rec.get("rationale"):
                story.append(Paragraph(rec["rationale"], body))
            story.append(Spacer(1, 8))

    doc.build(story,
              onFirstPage=lambda c, d: draw_header_footer(c, d, filename),
              onLaterPages=lambda c, d: draw_header_footer(c, d, filename))

    return FileResponse(pdf_path, filename=f"{filename}_Report.pdf", media_type="application/pdf")


@router.get("/charts/{report_id}")
async def get_report_charts(report_id: str):
    """
    Returns all charts for a report as base64-encoded PNG strings.
    Used by the frontend dashboard and report page to display live charts.
    """
    if report_id not in reports_db:
        raise HTTPException(status_code=404, detail="Report not found")

    report_data = reports_db[report_id]
    charts = build_charts(report_data)

    result = []
    for ch in charts:
        img_bytes = ch["buf"].read()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        result.append({
            "title": ch["title"],
            "interpretation": ch["interpretation"],
            "image": f"data:image/png;base64,{b64}"
        })

    return {"charts": result}
