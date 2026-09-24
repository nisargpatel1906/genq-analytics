import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from fastapi.responses import FileResponse

from app.api.chart_builder import build_charts

# ─────────────────────────────────────────────────────────────────────────────
# Professional Design System Palette (Executive Navy & Slate — No Solid Black)
# ─────────────────────────────────────────────────────────────────────────────
BRAND_PRIMARY        = colors.HexColor("#1E3A8A")   # Deep Corporate Navy
BRAND_ACCENT         = colors.HexColor("#2563EB")   # Vibrant Blue
BRAND_DARK           = colors.HexColor("#0F172A")   # Deep Slate for Headings (NOT pitch #111111)
BRAND_TEXT           = colors.HexColor("#334155")   # Clean Slate Body Text
BRAND_MUTED          = colors.HexColor("#64748B")   # Muted Grey for Subtitles/Footers
BRAND_BORDER         = colors.HexColor("#E2E8F0")   # Soft Grey Dividers & Gridlines
BRAND_BG_ALT         = colors.HexColor("#F8FAFC")   # Alternating Table Row Background
BRAND_CALLOUT_BG     = colors.HexColor("#EFF6FF")   # Subtle Blue Callout Background
BRAND_CALLOUT_BORDER = colors.HexColor("#BFDBFE")   # Border for Callouts


def clean_inline_markdown(text: str) -> str:
    """Converts inline markdown (*italic*, **bold**, `code`, etc.) into ReportLab-safe XML."""
    if not text:
        return ""
    text = str(text).strip()

    # 1. Escape XML characters so ReportLab never crashes on <, >, &
    # Only escape & if not part of an existing XML entity like &amp;, &lt;, &gt;, &bull;, etc.
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|bull|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")

    # 2. Convert inline code `code`
    text = re.sub(r"`([^`\n]+)`", r'<font face="Courier" color="#1E40AF"><b>\1</b></font>', text)

    # 3. Convert bold + italic ***text*** or ___text___
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"___(.+?)___", r"<b><i>\1</i></b>", text)

    # 4. Convert bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # 5. Convert italic *text* or _text_
    # Match *...* where * is not preceded or followed by *
    text = re.sub(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    # Underscores only matched at non-word boundaries so variable names like user_id are not broken
    text = re.sub(r"(?<!\w)_([^\_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # 6. Convert strikethrough ~~text~~
    text = re.sub(r"~~(.+?)~~", r"\1", text)

    # 7. Convert links [text](url) -> <u>text</u>
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"<u>\1</u>", text)

    return text


def parse_markdown_to_flowables(
    text: str,
    body_style: ParagraphStyle,
    h2_style: ParagraphStyle,
    bullet_style: ParagraphStyle,
) -> list:
    """Parses a markdown string containing paragraphs, headings, and bullet lists
    into a list of ReportLab Flowables (Paragraph, Spacer)."""
    flowables = []
    if not text:
        return flowables

    text = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = re.split(r"\n\s*\n", text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        # Check if block is a bullet list
        is_bullet_block = all(re.match(r"^\s*[\-\*\•]\s+", line) for line in lines if line.strip())

        if is_bullet_block:
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                bullet_content = re.sub(r"^\s*[\-\*\•]\s+", "", line)
                cleaned = clean_inline_markdown(bullet_content)
                flowables.append(Paragraph(f"&bull; {cleaned}", bullet_style))
                flowables.append(Spacer(1, 2))
            flowables.append(Spacer(1, 4))
        elif block.startswith("### "):
            cleaned = clean_inline_markdown(block[4:].strip())
            flowables.append(Paragraph(cleaned, h2_style))
            flowables.append(Spacer(1, 4))
        elif block.startswith("## ") or block.startswith("# "):
            cleaned = clean_inline_markdown(re.sub(r"^#+\s*", "", block).strip())
            flowables.append(Paragraph(cleaned, h2_style))
            flowables.append(Spacer(1, 4))
        else:
            # Regular paragraph
            cleaned_lines = [clean_inline_markdown(l.strip()) for l in lines if l.strip()]
            cleaned = " ".join(cleaned_lines)
            flowables.append(Paragraph(cleaned, body_style))
            flowables.append(Spacer(1, 6))

    return flowables


def draw_header_footer(canvas, doc, title=""):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.setFillColor(BRAND_ACCENT)
    canvas.drawString(50, A4[1] - 35, "GenQ Analytics")
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(BRAND_MUTED)
    clean_title = re.sub(r"[*`]", "", title[:70])
    canvas.drawRightString(A4[0] - 50, A4[1] - 35, clean_title)
    canvas.setStrokeColor(BRAND_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(50, A4[1] - 42, A4[0] - 50, A4[1] - 42)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(50, 26, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    canvas.drawRightString(A4[0] - 50, 26, f"Page {doc.page}")
    canvas.line(50, 38, A4[0] - 50, 38)
    canvas.restoreState()


def _render_dynamic_sections(
    story, ai_report, stats, charts_list, h1, h2, body, bullet, caption, callout
):
    """Renders dynamic reportSections from the AI report."""
    report_sections = ai_report.get("reportSections", [])
    if not report_sections or not isinstance(report_sections, list):
        return False

    section_num = 3  # Start at 3 (after Methodology and Executive Summary)

    for section in report_sections:
        sec_type = section.get("type", "narrative")
        sec_title = clean_inline_markdown(section.get("title", "Analysis"))

        story += [
            Paragraph(f"{section_num}. {sec_title}", h1),
            HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
            Spacer(1, 8),
        ]

        if sec_type == "data_overview":
            content = section.get("content", "")
            if content:
                story.extend(parse_markdown_to_flowables(content, body, h2, bullet))
            story.append(Spacer(1, 8))

        elif sec_type == "findings_group":
            narrative = section.get("narrative", "")
            if narrative:
                story.extend(parse_markdown_to_flowables(narrative, body, h2, bullet))
                story.append(Spacer(1, 6))

            findings = section.get("findings", [])
            for i, f in enumerate(findings, 1):
                title_t = clean_inline_markdown(f.get("title") or f"Finding {i}")
                detail = f.get("detail") or ""
                conf = f.get("confidence") or 0
                effect = clean_inline_markdown(f.get("effect_size") or "")
                practical = clean_inline_markdown(f.get("practical_significance") or "")

                story.append(Paragraph(f"{i}. {title_t}", h2))
                if detail:
                    story.extend(parse_markdown_to_flowables(detail, body, h2, bullet))
                if effect:
                    story.append(Paragraph(f"<b>Effect Size:</b> {effect}", callout))
                if practical:
                    story.append(Paragraph(f"<i>Practical Significance:</i> {practical}", caption))
                if conf:
                    story.append(Paragraph(f"<i>AI confidence: {conf}%</i>", caption))
                story.append(Spacer(1, 6))

        elif sec_type == "trend_analysis":
            content = section.get("content", "")
            if content:
                story.extend(parse_markdown_to_flowables(content, body, h2, bullet))
            story.append(Spacer(1, 8))

        elif sec_type == "data_table":
            headers = section.get("headers", [])
            rows = section.get("rows", [])
            if headers and rows:
                table_data = [[Paragraph(f"<b>{clean_inline_markdown(str(h))}</b>", body) for h in headers]]
                for r in rows:
                    table_data.append([Paragraph(clean_inline_markdown(str(c)), body) for c in r])

                col_width = (A4[0] - 100) / len(headers)
                t = Table(table_data, colWidths=[col_width] * len(headers))
                t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_PRIMARY),
                    ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
                    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
                    ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
                    ("TOPPADDING",    (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("GRID",          (0, 0), (-1, -1), 0.5, BRAND_BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_BG_ALT]),
                ]))
                story.append(t)
                story.append(Spacer(1, 12))

        elif sec_type == "comparison":
            content = section.get("content", "")
            if content:
                story.extend(parse_markdown_to_flowables(content, body, h2, bullet))
            story.append(Spacer(1, 8))

        elif sec_type == "anomalies":
            anomalies = section.get("anomalies", [])
            for a in anomalies:
                col_name = clean_inline_markdown(a.get("column", "Unknown"))
                sev = str(a.get("severity", "medium")).upper()
                desc = a.get("description", "")
                impact = clean_inline_markdown(a.get("businessImpact", ""))
                story.append(Paragraph(f"<b>{col_name} &nbsp;[{sev}]</b>", body))
                if desc:
                    story.extend(parse_markdown_to_flowables(desc, body, h2, bullet))
                if impact:
                    story.append(Paragraph(f"Business impact: {impact}", caption))
                story.append(Spacer(1, 4))

        elif sec_type == "recommendations":
            recs = section.get("recommendations", [])
            for i, rec in enumerate(recs, 1):
                action = clean_inline_markdown(rec.get("action", ""))
                priority = str(rec.get("priority", "Medium")).upper()
                story.append(Paragraph(
                    f"{i}. {action} &nbsp;<font color='#2563EB'>[{priority}]</font>", h2
                ))
                if rec.get("rationale"):
                    story.extend(parse_markdown_to_flowables(rec["rationale"], body, h2, bullet))
                if rec.get("expected_outcome"):
                    outcome = clean_inline_markdown(rec["expected_outcome"])
                    story.append(Paragraph(f"<i>Expected outcome:</i> {outcome}", caption))
                story.append(Spacer(1, 6))

        elif sec_type == "narrative":
            content = section.get("content", "")
            if content:
                story.extend(parse_markdown_to_flowables(content, body, h2, bullet))
            story.append(Spacer(1, 8))

        section_num += 1

    return True


def generate_pdf_response(report_id: str, report_data: dict) -> FileResponse:
    ai_report   = report_data.get("report", {})
    stats       = report_data.get("stats", {})
    filename    = report_data.get("filename", "dataset")
    clean_filename = re.sub(r"[*`]", "", filename)
    pdf_path    = os.path.join(os.path.dirname(__file__), "..", "..", f"{report_id}.pdf")

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        rightMargin=50,
        leftMargin=50,
        topMargin=65,
        bottomMargin=55,
    )

    S = getSampleStyleSheet()

    # Refined styles with explicit proportional leading to prevent ANY overlap
    title_s = ParagraphStyle(
        "CoverTitle",
        parent=S["Normal"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=30,
        textColor=BRAND_PRIMARY,
        spaceAfter=10,
        alignment=1,
    )
    sub_s = ParagraphStyle(
        "CoverSub",
        parent=S["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=16,
        textColor=BRAND_MUTED,
        spaceAfter=6,
        alignment=1,
    )
    h1 = ParagraphStyle(
        "H1",
        parent=S["Normal"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=20,
        textColor=BRAND_DARK,
        spaceBefore=16,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=S["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        leading=16,
        textColor=BRAND_ACCENT,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    body = ParagraphStyle(
        "Body",
        parent=S["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14.5,
        textColor=BRAND_TEXT,
        spaceAfter=6,
    )
    bullet = ParagraphStyle(
        "Bullet",
        parent=S["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14.5,
        textColor=BRAND_TEXT,
        leftIndent=14,
        spaceAfter=3,
    )
    caption = ParagraphStyle(
        "Caption",
        parent=S["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        leading=12,
        textColor=BRAND_MUTED,
        spaceAfter=8,
    )
    callout = ParagraphStyle(
        "Callout",
        parent=S["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13.5,
        textColor=BRAND_DARK,
        leftIndent=12,
        rightIndent=12,
        backColor=BRAND_CALLOUT_BG,
        borderColor=BRAND_CALLOUT_BORDER,
        borderWidth=0.5,
        borderPadding=6,
        spaceAfter=6,
    )

    story = []

    # Metadata extraction
    shape = stats.get("shape", {})
    dq = stats.get("data_quality", {})
    if not dq:
        dq = ai_report.get("_meta", {}).get("dataQuality", {})
    sampling_meta = stats.get("sampling", {})
    if not sampling_meta:
        sampling_meta = ai_report.get("_meta", {}).get("sampling", {})

    # Robust rows and columns resolution
    rows_val = (
        shape.get("rows")
        or sampling_meta.get("fullRowCount")
        or sampling_meta.get("sampleSize")
        or len(report_data.get("data_sample", []))
    )
    if isinstance(rows_val, (int, float)):
        rows_str = f"{rows_val:,}"
    else:
        rows_str = str(rows_val) if rows_val is not None else "?"

    col_types = report_data.get("col_types", {})
    total_cols_from_types = (
        len(col_types.get("numeric", []))
        + len(col_types.get("categorical", []))
        + len(col_types.get("datetime", []))
        + len(col_types.get("binary", []))
    )
    data_sample = report_data.get("data_sample", [])
    cols_from_sample = len(data_sample[0].keys()) if data_sample and isinstance(data_sample[0], dict) else 0

    cols_val = shape.get("columns") or total_cols_from_types or cols_from_sample
    if isinstance(cols_val, (int, float)):
        cols_str = f"{cols_val:,}"
    else:
        cols_str = str(cols_val) if cols_val is not None else "?"

    quality_score = dq.get("score", "?")
    quality_grade = dq.get("grade", "?")

    # ── Cover Page ─────────────────────────────────────────────────────────────
    story += [
        Spacer(1, 90),
        Paragraph("AI Data Analysis Report", title_s),
        Spacer(1, 10),
        Paragraph(clean_filename, sub_s),
    ]
    if ai_report.get("domain"):
        clean_domain = clean_inline_markdown(ai_report["domain"])
        story.append(Paragraph(f"Domain: {clean_domain}", sub_s))

    story += [
        Spacer(1, 12),
        Paragraph(
            f"{rows_str} rows  &times;  {cols_str} columns  "
            f"  |  Data Quality: <b>{quality_grade}</b> ({quality_score}/100)",
            ParagraphStyle("CoverBadge", parent=sub_s, fontSize=10.5, leading=15, textColor=BRAND_DARK),
        ),
        Spacer(1, 80),
        HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
        Spacer(1, 12),
        Paragraph(
            f"Generated by GenQ Analytics  &middot;  {datetime.now().strftime('%B %d, %Y')}",
            ParagraphStyle("CoverFooter", parent=caption, alignment=1),
        ),
        PageBreak(),
    ]

    # ── 1. Methodology & Data Quality ───────────────────────────────────────────
    story += [
        Paragraph("1. Methodology & Data Quality", h1),
        HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
        Spacer(1, 8),
    ]

    # Data Quality Assessment Table (Corporate Navy Header — No Solid Black)
    if dq and dq.get("score") is not None:
        story.append(Paragraph("Data Quality Assessment", h2))
        dq_rows = [
            [
                Paragraph("<b>Dimension</b>", ParagraphStyle("TH", parent=body, textColor=colors.white)),
                Paragraph("<b>Score</b>", ParagraphStyle("TH_C", parent=body, textColor=colors.white, alignment=1)),
                Paragraph("<b>Out of</b>", ParagraphStyle("TH_C", parent=body, textColor=colors.white, alignment=1)),
                Paragraph("<b>Description</b>", ParagraphStyle("TH", parent=body, textColor=colors.white)),
            ],
            [
                Paragraph("Completeness", body),
                Paragraph(f"{dq.get('completeness', 0):.1f}", ParagraphStyle("C", parent=body, alignment=1)),
                Paragraph("40", ParagraphStyle("C", parent=body, alignment=1)),
                Paragraph("Non-null cell ratio across all columns", body),
            ],
            [
                Paragraph("Consistency", body),
                Paragraph(f"{dq.get('consistency', 0):.1f}", ParagraphStyle("C", parent=body, alignment=1)),
                Paragraph("35", ParagraphStyle("C", parent=body, alignment=1)),
                Paragraph("Penalises columns with >5% statistical outliers", body),
            ],
            [
                Paragraph("Structure", body),
                Paragraph(f"{dq.get('structure', 0):.1f}", ParagraphStyle("C", parent=body, alignment=1)),
                Paragraph("25", ParagraphStyle("C", parent=body, alignment=1)),
                Paragraph("Well-typed categorical columns with useful cardinality", body),
            ],
            [
                Paragraph(f"<b>Total [Grade: {quality_grade}]</b>", ParagraphStyle("TB", parent=body, textColor=BRAND_PRIMARY)),
                Paragraph(f"<b>{quality_score}</b>", ParagraphStyle("TB_C", parent=body, textColor=BRAND_PRIMARY, alignment=1)),
                Paragraph("<b>100</b>", ParagraphStyle("TB_C", parent=body, textColor=BRAND_PRIMARY, alignment=1)),
                Paragraph("Overall composite data reliability score", body),
            ],
        ]
        dq_table = Table(dq_rows, colWidths=[1.8 * inch, 0.8 * inch, 0.7 * inch, 3.5 * inch])
        dq_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_PRIMARY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("GRID",          (0, 0), (-1, -1), 0.5, BRAND_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BRAND_BG_ALT]),
            ("BACKGROUND",    (0, -1), (-1, -1), BRAND_CALLOUT_BG),
        ]))
        story += [dq_table, Spacer(1, 10)]

    # Analysis Methodology
    story.append(Paragraph("Analysis Methodology", h2))
    was_sampled = sampling_meta.get("wasDownsampled", False)
    sample_size_val = sampling_meta.get("sampleSize", rows_val)
    if isinstance(sample_size_val, (int, float)):
        sample_size_str = f"{sample_size_val:,}"
    else:
        sample_size_str = str(sample_size_val) if sample_size_val is not None else "?"

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
            f"This dataset contained **{rows_str}** rows. "
            f"To ensure timely analysis without sacrificing accuracy, a smart sample of "
            f"**{sample_size_str} rows** was selected using the **{method_desc}** strategy. "
            f"All statistics, findings, and visualizations are derived from this representative sample. "
            f"A full-data validation pass was performed to cross-check key findings against the complete dataset."
        )
    else:
        methodology_text = (
            f"This dataset contained **{rows_str}** rows — within the full-analysis threshold. "
            f"All statistics, findings, and visualizations are derived from the **complete dataset**."
        )

    ai_methodology = ai_report.get("methodology", "")
    if ai_methodology:
        methodology_text += f"\n\n**Statistical Methods Used:** {ai_methodology}"

    story.extend(parse_markdown_to_flowables(methodology_text, body, h2, bullet))
    story.append(Spacer(1, 8))

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
            w_finding = clean_inline_markdown(w.get("finding", "Finding"))
            w_col = clean_inline_markdown(str(w.get("column", "")))
            story.append(Paragraph(
                f"<b>{w_finding}:</b> Column '{w_col}' &mdash; "
                f"sample value {w.get('sample_value')}, full-data mean {w.get('full_data_value')} "
                f"({w.get('deviation_pct')}% deviation).",
                callout,
            ))
        story.append(Spacer(1, 8))

    # ── 2. Executive Summary ────────────────────────────────────────────────────
    exec_sum = ai_report.get("executiveSummary", "")
    if exec_sum:
        story += [
            Paragraph("2. Executive Summary", h1),
            HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
            Spacer(1, 8),
        ]
        story.extend(parse_markdown_to_flowables(exec_sum, body, h2, bullet))
        story.append(Spacer(1, 14))

    # ── Build Charts ────────────────────────────────────────────────────────────
    charts_list = build_charts(report_data)

    # ── Dynamic Sections or Legacy Fallback ─────────────────────────────────────
    used_dynamic = _render_dynamic_sections(
        story, ai_report, stats, charts_list, h1, h2, body, bullet, caption, callout
    )

    if used_dynamic:
        if charts_list:
            viz_story = [
                PageBreak(),
                Paragraph("Data Visualizations & Interpretation", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
                Paragraph(
                    "Each chart below was generated based on the actual statistical findings — "
                    "not a generic template. An interpretation paragraph follows every chart.",
                    body,
                ),
                Spacer(1, 10),
            ]
            for ch in charts_list:
                ch_title = clean_inline_markdown(ch.get("title", "Visualization"))
                ch_interp = clean_inline_markdown(ch.get("interpretation", ""))
                viz_story += [
                    Paragraph(ch_title, h2),
                    Image(ch["buf"], width=6.0 * inch, height=3.5 * inch),
                    Spacer(1, 5),
                    Paragraph(f"<b>Interpretation:</b> {ch_interp}", callout),
                    Spacer(1, 14),
                ]
            story.extend(viz_story)

        # Limitations section
        limitations = ai_report.get("limitations", [])
        if limitations:
            story += [
                Spacer(1, 10),
                Paragraph("Limitations & Caveats", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
            ]
            for lim in limitations:
                clean_lim = clean_inline_markdown(lim)
                story.append(Paragraph(f"&bull; {clean_lim}", bullet))
            story.append(Spacer(1, 8))

    else:
        # ── Legacy Fallback Rendering ──────────────────────────────────────────
        num_summary = stats.get("numeric_summary", {})
        missing = stats.get("missing_values", {})
        if num_summary:
            story += [
                Paragraph("3. Dataset Statistics", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
            ]
            rows = [
                [
                    Paragraph("<b>Column</b>", ParagraphStyle("TH", parent=body, textColor=colors.white)),
                    Paragraph("<b>Mean</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                    Paragraph("<b>Std Dev</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                    Paragraph("<b>Min</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                    Paragraph("<b>Max</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                    Paragraph("<b>Missing</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                ]
            ]
            for col, d in num_summary.items():
                rows.append([
                    Paragraph(clean_inline_markdown(col[:22]), body),
                    Paragraph(f"{(d.get('mean') or 0):.3f}", ParagraphStyle("C", parent=body, alignment=1)),
                    Paragraph(f"{(d.get('std') or 0):.3f}", ParagraphStyle("C", parent=body, alignment=1)),
                    Paragraph(f"{(d.get('min') or 0):.3f}", ParagraphStyle("C", parent=body, alignment=1)),
                    Paragraph(f"{(d.get('max') or 0):.3f}", ParagraphStyle("C", parent=body, alignment=1)),
                    Paragraph(str(missing.get(col, 0)), ParagraphStyle("C", parent=body, alignment=1)),
                ])
            t = Table(rows, colWidths=[1.9 * inch, 1.0 * inch, 1.0 * inch, 0.9 * inch, 0.9 * inch, 0.8 * inch])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_PRIMARY),
                ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
                ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
                ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
                ("TOPPADDING",    (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("GRID",          (0, 0), (-1, -1), 0.5, BRAND_BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_BG_ALT]),
            ]))
            story += [t, Spacer(1, 14)]

        # Visualizations
        if charts_list:
            story += [
                Paragraph("4. Data Visualizations & Interpretation", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
                Paragraph(
                    "Each chart below was chosen based on the actual structure of your dataset — "
                    "not a generic template. An interpretation paragraph follows every chart.",
                    body,
                ),
                Spacer(1, 10),
            ]
            for ch in charts_list:
                ch_title = clean_inline_markdown(ch.get("title", "Visualization"))
                ch_interp = clean_inline_markdown(ch.get("interpretation", ""))
                story += [
                    Paragraph(ch_title, h2),
                    Image(ch["buf"], width=6.0 * inch, height=3.5 * inch),
                    Spacer(1, 5),
                    Paragraph(f"<b>Interpretation:</b> {ch_interp}", callout),
                    Spacer(1, 14),
                ]
            story.append(PageBreak())

        # Key Findings
        findings = ai_report.get("keyFindings", [])
        if findings:
            story += [
                Paragraph("5. Key Findings", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
            ]
            for i, f in enumerate(findings, 1):
                title_t = clean_inline_markdown(f.get("title") or f.get("finding") or f"Finding {i}")
                detail = f.get("detail") or f.get("description") or ""
                conf = f.get("confidenceScore") or f.get("confidence") or 0
                story.append(Paragraph(f"{i}. {title_t}", h2))
                if detail:
                    story.extend(parse_markdown_to_flowables(detail, body, h2, bullet))
                if conf:
                    story.append(Paragraph(f"<i>AI confidence: {conf}%</i>", caption))
                story.append(Spacer(1, 6))

        # Anomalies
        anomalies_ai = ai_report.get("anomalies", [])
        stat_anomalies = stats.get("statistical_anomalies", [])
        if anomalies_ai or stat_anomalies:
            story += [
                Paragraph("6. Anomalies Detected", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
            ]
            if stat_anomalies:
                story.append(Paragraph("Statistically Flagged Columns (Z-score > 3σ)", h2))
                tdata = [
                    [
                        Paragraph("<b>Column</b>", ParagraphStyle("TH", parent=body, textColor=colors.white)),
                        Paragraph("<b>Outliers</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                        Paragraph("<b>Mean</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                        Paragraph("<b>Extreme</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                        Paragraph("<b>Threshold</b>", ParagraphStyle("TH", parent=body, textColor=colors.white, alignment=1)),
                    ]
                ]
                for a in stat_anomalies:
                    tdata.append([
                        Paragraph(clean_inline_markdown(str(a.get("column", ""))), body),
                        Paragraph(str(a.get("outlier_count", "")), ParagraphStyle("C", parent=body, alignment=1)),
                        Paragraph(f"{a.get('mean', 0):.3f}", ParagraphStyle("C", parent=body, alignment=1)),
                        Paragraph(f"{a.get('max_deviation_value', 0):.3f}", ParagraphStyle("C", parent=body, alignment=1)),
                        Paragraph(f"{a.get('threshold_3sigma', 0):.3f}", ParagraphStyle("C", parent=body, alignment=1)),
                    ])
                t = Table(tdata, colWidths=[1.8 * inch, 1.0 * inch, 1.1 * inch, 1.1 * inch, 1.3 * inch])
                t.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0),  BRAND_PRIMARY),
                    ("TEXTCOLOR",     (0, 0), (-1, 0),  colors.white),
                    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
                    ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
                    ("TOPPADDING",    (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("GRID",          (0, 0), (-1, -1), 0.5, BRAND_BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_BG_ALT]),
                ]))
                story += [t, Spacer(1, 10)]

            for a in anomalies_ai:
                col_name = clean_inline_markdown(a.get("column", "Unknown"))
                sev = str(a.get("severity", "medium")).upper()
                desc = a.get("description", "")
                impact = clean_inline_markdown(a.get("businessImpact", ""))
                story.append(Paragraph(f"<b>{col_name} &nbsp;[{sev}]</b>", body))
                if desc:
                    story.extend(parse_markdown_to_flowables(desc, body, h2, bullet))
                if impact:
                    story.append(Paragraph(f"Business impact: {impact}", caption))
                story.append(Spacer(1, 4))

        # Recommendations
        recs = ai_report.get("recommendations", [])
        if recs:
            story += [
                PageBreak(),
                Paragraph("7. Recommendations", h1),
                HRFlowable(width="100%", thickness=0.5, color=BRAND_BORDER),
                Spacer(1, 8),
            ]
            for i, rec in enumerate(recs, 1):
                action = clean_inline_markdown(rec.get("action", ""))
                priority = str(rec.get("priority", "Medium")).upper()
                story.append(Paragraph(
                    f"{i}. {action} &nbsp;<font color='#2563EB'>[{priority}]</font>", h2
                ))
                if rec.get("rationale"):
                    story.extend(parse_markdown_to_flowables(rec["rationale"], body, h2, bullet))
                if rec.get("expected_outcome"):
                    outcome = clean_inline_markdown(rec["expected_outcome"])
                    story.append(Paragraph(f"<i>Expected outcome:</i> {outcome}", caption))
                story.append(Spacer(1, 6))

    doc.build(
        story,
        onFirstPage=lambda c, d: draw_header_footer(c, d, clean_filename),
        onLaterPages=lambda c, d: draw_header_footer(c, d, clean_filename),
    )

    return FileResponse(pdf_path, filename=f"{clean_filename}_Report.pdf", media_type="application/pdf")
