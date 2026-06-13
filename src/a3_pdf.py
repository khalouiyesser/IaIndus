"""
a3_pdf.py — Génération du rapport Digital A3 au format PDF.

Reprend la charte visuelle du DSL Agent (navy / cyan / accents) et produit un
document A3 structuré en 8 sections PDCA + plan d'action prioritisé.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Palette ──────────────────────────────────────────────────────────────────
NAVY = colors.HexColor("#0F1E35")
BLUE = colors.HexColor("#1B6FD8")
CYAN = colors.HexColor("#0090C0")
GREEN = colors.HexColor("#009B5E")
PURPLE = colors.HexColor("#8040B0")
ORANGE = colors.HexColor("#E8620A")
RED = colors.HexColor("#D63B3B")
LIGHT = colors.HexColor("#F0F4FA")
GREY = colors.HexColor("#607898")
DARKTXT = colors.HexColor("#1A2438")

# ── Sections A3 (clé du rapport -> titre + phase + couleur) ──────────────────
SECTIONS = [
    ("background", "1-2 · Background & Current Condition", "PLAN", BLUE),
    ("target", "3-4 · Target Condition & CTQ", "PLAN", BLUE),
    ("rootcause", "5 · Root Cause Analysis", "DO", GREEN),
    ("countermeasures", "6-7 · Countermeasures & Action Plan", "DO", GREEN),
    ("control", "8 · Results Monitoring & Follow-up", "CHECK", PURPLE),
]

PRIORITY_COLORS = {"HIGH": RED, "MEDIUM": ORANGE, "LOW": GREEN}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontSize=16, textColor=NAVY,
            spaceAfter=2, leading=19,
        ),
        "subtitle": ParagraphStyle(
            "st", parent=base["Normal"], fontSize=9.5, textColor=GREY, leading=13,
        ),
        "sec_title": ParagraphStyle(
            "sec", parent=base["Heading2"], fontSize=11, textColor=colors.white,
            leading=14, spaceAfter=0,
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontSize=9, textColor=DARKTXT,
            leading=13.5, alignment=TA_LEFT, spaceAfter=2,
        ),
        "meta_l": ParagraphStyle(
            "ml", parent=base["Normal"], fontSize=7, textColor=GREY, leading=9,
        ),
        "meta_v": ParagraphStyle(
            "mv", parent=base["Normal"], fontSize=9.5, textColor=NAVY,
            leading=12, fontName="Helvetica-Bold",
        ),
        "act": ParagraphStyle(
            "a", parent=base["Normal"], fontSize=8.5, textColor=DARKTXT, leading=12,
        ),
        "tool": ParagraphStyle(
            "to", parent=base["Normal"], fontSize=7.5, textColor=CYAN,
            leading=10, fontName="Helvetica-Oblique",
        ),
        "pri": ParagraphStyle(
            "p", parent=base["Normal"], fontSize=7.5, textColor=colors.white,
            leading=10, fontName="Helvetica-Bold", alignment=1,
        ),
    }


def _header_block(report: dict, kpis: dict, st: dict) -> list:
    flow = []
    title = report.get("problem_title", "Industrial Problem A3")
    summary = report.get("problem_summary", "")
    sigma = str(report.get("sigma_level", "—"))
    dpmo = report.get("dpmo", "—")
    domain = report.get("domain", "—")

    # Bandeau titre + sigma
    head_tbl = Table(
        [[
            Paragraph(f"<b>Digital A3 — {title}</b>", st["title"]),
            Paragraph(f"<font size=18 color='#E8620A'><b>{sigma}</b></font><br/>"
                      f"<font size=7 color='#607898'>SIGMA LEVEL</font>", st["subtitle"]),
        ]],
        colWidths=[125 * mm, 45 * mm],
    )
    head_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    flow.append(head_tbl)
    if summary:
        flow.append(Paragraph(summary, st["subtitle"]))
    flow.append(Spacer(1, 4))
    flow.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1A2F4A")))
    flow.append(Spacer(1, 6))

    # Bandeau méta KPI
    meta_cells = [[
        Paragraph("DOMAIN", st["meta_l"]),
        Paragraph("DPMO", st["meta_l"]),
        Paragraph("DATE", st["meta_l"]),
        Paragraph("STATUS", st["meta_l"]),
    ], [
        Paragraph(str(domain), st["meta_v"]),
        Paragraph(f"{dpmo:,}" if isinstance(dpmo, (int, float)) else str(dpmo), st["meta_v"]),
        Paragraph(datetime.now().strftime("%d/%m/%Y"), st["meta_v"]),
        Paragraph("DRAFT", st["meta_v"]),
    ]]
    meta = Table(meta_cells, colWidths=[42.5 * mm] * 4)
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C8D6E8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#C8D6E8")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow.append(meta)
    flow.append(Spacer(1, 8))
    return flow


def _section_block(key: str, label: str, phase: str, color, content: str, st: dict) -> Table:
    """Construit une section A3 : bandeau coloré + corps texte."""
    header = Table(
        [[Paragraph(label, st["sec_title"]),
          Paragraph(phase, ParagraphStyle("ph", parent=st["pri"], fontSize=7.5))]],
        colWidths=[140 * mm, 30 * mm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]))

    body_txt = (content or "—").replace("\n", "<br/>")
    body = Table([[Paragraph(body_txt, st["body"])]], colWidths=[170 * mm])
    body.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E2F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]))

    wrapper = Table([[header], [body]], colWidths=[170 * mm])
    wrapper.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return wrapper


def _action_plan(actions: list, st: dict) -> list:
    flow = [Spacer(1, 4),
            Paragraph("<b>PRIORITIZED ACTION PLAN</b>",
                      ParagraphStyle("ap", parent=st["body"], fontSize=10,
                                     textColor=NAVY, spaceAfter=4))]
    head_style = ParagraphStyle("ah", parent=st["act"], textColor=colors.white,
                                fontName="Helvetica-Bold")
    rows = [[Paragraph("PRIO", st["pri"]),
             Paragraph("Action", head_style),
             Paragraph("Tool", head_style)]]
    for a in actions or []:
        pri = str(a.get("priority", "MEDIUM")).upper()
        rows.append([
            Paragraph(pri, st["pri"]),
            Paragraph(a.get("action", "—"), st["act"]),
            Paragraph(a.get("tool", "—"), st["tool"]),
        ])
    tbl = Table(rows, colWidths=[18 * mm, 102 * mm, 50 * mm])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E2F0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i, a in enumerate(actions or [], start=1):
        pri = str(a.get("priority", "MEDIUM")).upper()
        style.append(("BACKGROUND", (0, i), (0, i), PRIORITY_COLORS.get(pri, ORANGE)))
        if i % 2 == 0:
            style.append(("BACKGROUND", (1, i), (-1, i), LIGHT))
    tbl.setStyle(TableStyle(style))
    flow.append(tbl)
    return flow


def build_a3_pdf(report: dict[str, Any], kpis: dict[str, Any]) -> bytes:
    """Construit le PDF A3 et retourne les octets."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"A3 - {report.get('problem_title', 'Report')}",
    )
    st = _styles()
    flow: list = []
    flow += _header_block(report, kpis, st)

    for key, label, phase, color in SECTIONS:
        flow.append(_section_block(key, label, phase, color, report.get(key, ""), st))
        flow.append(Spacer(1, 6))

    flow += _action_plan(report.get("actions", []), st)
    flow.append(Spacer(1, 10))
    flow.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#C8D6E8")))
    flow.append(Paragraph(
        "Generated by DSL Agent — Data Sigma Lean 4.0 · "
        "Proof of concept · fictitious data for demonstration",
        ParagraphStyle("ft", parent=st["meta_l"], fontSize=7, alignment=1)))

    doc.build(flow)
    buf.seek(0)
    return buf.read()
