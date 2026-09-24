import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, PageBreak, Image, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from fastapi.responses import FileResponse

from app.api.chart_builder import build_charts

BRAND_DARK   = colors.HexColor("#111111")
BRAND_ACCENT = colors.HexColor("#1A56DB")
BRAND_BORDER = colors.HexColor("#E5E7EB")
BRAND_MUTED  = colors.HexColor("#6B7280")

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


def _render_dynamic_sections(story, ai_report, stats, charts_list, h1, h2, body, caption, callout):
    """Renders dynamic reportSections from the AI report.
    Returns True if dynamic sections were rendered, False to fall back to legacy."""
    report_sections = ai_report.get("reportSections", [])
    if not report_sections or not isinstance(report_sections, list):
        return False

    section_num = 3  # Start at 3 (after Methodology and Executive Summary)

    for section in report_sections:
        sec_type = section.get("type", "narrative")
        sec_title = section.get("title", "Analysis")

        story += [
            Paragraph(f"{section_num}. {sec_title}", h1),
            HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
            Spacer(1, 8),
        ]

        if sec_type == "data_overview":
            content = section.get("content", "")
            if content:
                story.append(Paragraph(content, body))
            story.append(Spacer(1, 12))

        elif sec_type == "findings_group":
            narrative = section.get("narrative", "")
            if narrative:
                story.append(Paragraph(narrative, body))
                story.append(Spacer(1, 10))

            findings = section.get("findings", [])
            for i, f in enumerate(findings, 1):
                title_t = f.get("title") or f"Finding {i}"
                detail = f.get("detail") or ""
                conf = f.get("confidence") or 0
                effect = f.get("effect_size") or ""
                practical = f.get("practical_significance") or ""

                story.append(Paragraph(f"{i}. {title_t}", h2))
                if detail:
                    story.append(Paragraph(detail, body))
                if effect:
                    story.append(Paragraph(f"<b>Effect Size:</b> {effect}", callout))
                if practical:
                    story.append(Paragraph(f"<i>Practical Significance:</i> {practical}", caption))
                if conf:
                    story.append(Paragraph(f"<i>AI confidence: {conf}%</i>", caption))
                story.append(Spacer(1, 8))

        elif sec_type == "trend_analysis":
            content = section.get("content", "")
            if content:
                story.append(Paragraph(content, body))
            story.append(Spacer(1, 12))

        elif sec_type == "data_table":
            headers = section.get("headers", [])
            rows = section.get("rows", [])
            if headers and rows:
                table_data = [[Paragraph(f"<b>{h}</b>", body) for h in headers]]
                for r in rows:
                    table_data.append([Paragraph(str(c), body) for c in r])
                
                # Calculate column widths
                col_width = (A4[0] - 100) / len(headers)
                t = Table(table_data, colWidths=[col_width] * len(headers))
                t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_DARK),
                    ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
                    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
                    ("FONTSIZE",      (0, 0), (-1, -1), 9),
                    ("TOPPADDING",    (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("GRID",          (0, 0), (-1, -1), 0.4, BRAND_BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
                ]))
                story.append(t)
                story.append(Spacer(1, 16))

        elif sec_type == "comparison":
            content = section.get("content", "")
            if content:
                story.append(Paragraph(content, body))
            story.append(Spacer(1, 12))

        elif sec_type == "anomalies":
            anomalies = section.get("anomalies", [])
            for a in anomalies:
                sev = str(a.get("severity", "medium")).upper()
                desc = a.get("description", "")
                impact = a.get("businessImpact", "")
                story.append(Paragraph(f"<b>{a.get('column', 'Unknown')}  [{sev}]</b>", body))
                if desc:
                    story.append(Paragraph(desc, body))
                if impact:
                    story.append(Paragraph(f"Business impact: {impact}", caption))
                story.append(Spacer(1, 6))

        elif sec_type == "recommendations":
            recs = section.get("recommendations", [])
            for i, rec in enumerate(recs, 1):
                priority = str(rec.get("priority", "Medium")).upper()
                story.append(Paragraph(
                    f"{i}. {rec.get('action', '')}  <font color='#1A56DB'>[{priority}]</font>", h2))
                if rec.get("rationale"):
                    story.append(Paragraph(rec["rationale"], body))
                if rec.get("expected_outcome"):
                    story.append(Paragraph(
                        f"<i>Expected outcome:</i> {rec['expected_outcome']}", caption))
                story.append(Spacer(1, 8))

        elif sec_type == "narrative":
            content = section.get("content", "")
            if content:
                story.append(Paragraph(content, body))
            story.append(Spacer(1, 12))

        section_num += 1

    return True


def generate_pdf_response(report_id: str, report_data: dict) -> FileResponse:
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
    dq = stats.get("data_quality", {})
    if not dq:
        dq = ai_report.get("_meta", {}).get("dataQuality", {})
    sampling_meta = stats.get("sampling", {})
    if not sampling_meta:
        sampling_meta = ai_report.get("_meta", {}).get("sampling", {})

    story += [Spacer(1, 100),
              Paragraph("AI Data Analysis Report", title_s),
              Spacer(1, 8),
              Paragraph(filename, sub_s)]
    if ai_report.get("domain"):
        story.append(Paragraph(f"Domain: {ai_report['domain']}", sub_s))

    # Quality badge on cover
    quality_score = dq.get("score", "?")
    quality_grade = dq.get("grade", "?")
    rows_val = shape.get("rows")
    if isinstance(rows_val, (int, float)):
        rows_str = f"{rows_val:,}"
    else:
        rows_str = str(rows_val) if rows_val is not None else "?"
    cols_val = shape.get("columns")
    cols_str = str(cols_val) if cols_val is not None else "?"
    story += [
        Spacer(1, 6),
        Paragraph(
            f"{rows_str} rows  ×  {cols_str} columns  "
            f"  |  Data Quality: <b>{quality_grade}</b> ({quality_score}/100)",
            ParagraphStyle("m", parent=sub_s, fontSize=11),
        ),
        Spacer(1, 70),
        HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
        Spacer(1, 12),
        Paragraph(
            f"Generated by GenQ Analytics  ·  {datetime.now().strftime('%B %d, %Y')}",
            ParagraphStyle("f", parent=caption, alignment=1),
        ),
        PageBreak(),
    ]

    # ── 1. Methodology & Data Quality ───────────────────────────────────────────
    story += [
        Paragraph("1. Methodology & Data Quality", h1),
        HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
        Spacer(1, 8),
    ]

    # Data quality breakdown table
    if dq and dq.get("score") is not None:
        story.append(Paragraph("Data Quality Assessment", h2))
        dq_rows = [
            ["Dimension", "Score", "Out of", "Description"],
            ["Completeness",  f"{dq.get('completeness', 0):.1f}", "40", "Non-null cell ratio across all columns"],
            ["Consistency",   f"{dq.get('consistency', 0):.1f}",  "35", "Penalises columns with >5% statistical outliers"],
            ["Structure",     f"{dq.get('structure', 0):.1f}",    "25", "Well-typed categorical columns with useful cardinality"],
            [f"Total  [Grade: {quality_grade}]", f"{quality_score}", "100", ""],
        ]
        dq_table = Table(dq_rows, colWidths=[1.8*inch, 0.8*inch, 0.7*inch, 3.5*inch])
        dq_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_DARK),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("BACKGROUND",    (0, -1), (-1, -1), colors.HexColor("#EFF6FF")),
            ("FONTNAME",      (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 9),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("GRID",          (0, 0), (-1, -1), 0.4, BRAND_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F9FAFB")]),
            ("ALIGN",         (1, 0), (2, -1),  "CENTER"),
        ]))
        story += [dq_table, Spacer(1, 12)]

    # Sampling methodology
    story.append(Paragraph("Analysis Methodology", h2))
    was_sampled = sampling_meta.get("wasDownsampled", False)
    sample_size_val = sampling_meta.get("sampleSize", shape.get("rows", "?"))
    if isinstance(sample_size_val, (int, float)):
        sample_size_str = f"{sample_size_val:,}"
    else:
        sample_size_str = str(sample_size_val) if sample_size_val is not None else "?"

    full_count_val = sampling_meta.get("fullRowCount", shape.get("rows", "?"))
    if isinstance(full_count_val, (int, float)):
        full_count_str = f"{full_count_val:,}"
    else:
        full_count_str = str(full_count_val) if full_count_val is not None else "?"

    method = sampling_meta.get("method", "full")

    method_labels = {
        "full": "Full dataset — all rows used for analysis",
        "time_series": "Time-series sampling — most recent 70% + periodic samples from history",
        "stratified": "Stratified sampling — proportional sample preserving class distributions",
        "random": "Random sampling — reproducible random sample (seed=42)",
    }
    method_desc = method_labels.get(method, method)

    if was_sampled:
        methodology_text = (
            f"This dataset contained <b>{full_count_str}</b> rows. "
            f"To ensure timely analysis without sacrificing accuracy, a smart sample of "
            f"<b>{sample_size_str} rows</b> was selected using the <b>{method_desc}</b> strategy. "
            f"All statistics, findings, and visualizations are derived from this representative sample. "
            f"A full-data validation pass was performed to cross-check key findings against the complete dataset."
        )
    else:
        methodology_text = (
            f"This dataset contained <b>{full_count_str}</b> rows — within the full-analysis threshold. "
            f"All statistics, findings, and visualizations are derived from the <b>complete dataset</b>."
        )
    
    # Add methodology description from AI report
    ai_methodology = ai_report.get("methodology", "")
    if ai_methodology:
        methodology_text += f"<br/><br/><b>Statistical Methods Used:</b> {ai_methodology}"
    
    story += [Paragraph(methodology_text, body), Spacer(1, 8)]

    # Validation warnings (if any)
    validation_warnings = ai_report.get("_meta", {}).get("sampling", {}).get("validationWarnings", [])
    if validation_warnings:
        story.append(Paragraph("Full-Data Validation Warnings", h2))
        story.append(Paragraph(
            "The following findings showed a >20% deviation between the analysis sample and the full dataset. "
            "Interpret these with additional caution:",
            body,
        ))
        for w in validation_warnings:
            story.append(Paragraph(
                f"<b>{w.get('finding', 'Finding')}:</b> Column '{w.get('column')}' — "
                f"sample value {w.get('sample_value')}, full-data mean {w.get('full_data_value')} "
                f"({w.get('deviation_pct')}% deviation).",
                callout,
            ))
        story.append(Spacer(1, 8))

    story.append(Spacer(1, 8))

    # ── 2. Executive Summary ────────────────────────────────────────────────────
    exec_sum = ai_report.get("executiveSummary", "")
    if exec_sum:
        story += [Paragraph("2. Executive Summary", h1),
                  HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                  Spacer(1, 8),
                  Paragraph(exec_sum, body),
                  Spacer(1, 16)]

    # ── Build charts for the PDF ────────────────────────────────────────────────
    charts_list = build_charts(report_data)

    # ── Try dynamic sections first ──────────────────────────────────────────────
    used_dynamic = _render_dynamic_sections(story, ai_report, stats, charts_list, h1, h2, body, caption, callout)

    if used_dynamic:
        # Insert visualizations section before the dynamic content (after exec summary)
        # We need to add charts as a separate section
        if charts_list:
            viz_story = [
                PageBreak(),
                Paragraph("Data Visualizations & Interpretation", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
                Paragraph(
                    "Each chart below was generated based on the actual statistical findings — "
                    "not a generic template. An interpretation paragraph follows every chart.",
                    body),
                Spacer(1, 12),
            ]
            for ch in charts_list:
                viz_story += [
                    Paragraph(ch["title"], h2),
                    Image(ch["buf"], width=6.0*inch, height=3.6*inch),
                    Spacer(1, 6),
                    Paragraph(f"Interpretation: {ch['interpretation']}", callout),
                    Spacer(1, 18),
                ]
            # Insert the visualizations before the last few items in the story
            # Find a good insertion point — after executive summary
            story.extend(viz_story)

        # Limitations section
        limitations = ai_report.get("limitations", [])
        if limitations:
            story += [
                Spacer(1, 12),
                Paragraph("Limitations & Caveats", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
            ]
            for lim in limitations:
                story.append(Paragraph(f"• {lim}", body))
            story.append(Spacer(1, 8))

    else:
        # ── LEGACY FALLBACK: Use the old fixed-section rendering ────────────────

        # Statistics table (only in legacy mode)
        num_summary = stats.get("numeric_summary", {})
        missing     = stats.get("missing_values", {})
        if num_summary:
            story += [Paragraph("3. Dataset Statistics", h1),
                      HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                      Spacer(1, 8)]
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
        story += [Paragraph("4. Data Visualizations & Interpretation", h1),
                  HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                  Spacer(1, 8),
                  Paragraph(
                      "Each chart below was chosen based on the actual structure of your dataset — "
                      "not a generic template. An interpretation paragraph follows every chart "
                      "explaining what the data is specifically showing.",
                      body),
                  Spacer(1, 12)]

        for ch in charts_list:
            story += [Paragraph(ch["title"], h2),
                      Image(ch["buf"], width=6.0*inch, height=3.6*inch),
                      Spacer(1, 6),
                      Paragraph(f"Interpretation: {ch['interpretation']}", callout),
                      Spacer(1, 18)]

        story.append(PageBreak())

        # Key Findings
        findings = ai_report.get("keyFindings", [])
        if findings:
            story += [Paragraph("5. Key Findings", h1),
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
            story += [Paragraph("6. Anomalies Detected", h1),
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
                      Paragraph("7. Recommendations", h1),
                      HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                      Spacer(1, 8)]
            for i, rec in enumerate(recs, 1):
                priority = str(rec.get("priority", "Medium")).upper()
                story.append(Paragraph(f"{i}. {rec.get('action','')}  <font color='#1A56DB'>[{priority}]</font>", h2))
                if rec.get("rationale"):
                    story.append(Paragraph(rec["rationale"], body))
                if rec.get("expected_outcome"):
                    story.append(Paragraph(f"<i>Expected outcome:</i> {rec['expected_outcome']}", caption))
                story.append(Spacer(1, 8))

    doc.build(story,
              onFirstPage=lambda c, d: draw_header_footer(c, d, filename),
              onLaterPages=lambda c, d: draw_header_footer(c, d, filename))

    return FileResponse(pdf_path, filename=f"{filename}_Report.pdf", media_type="application/pdf")
