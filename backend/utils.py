"""Utility helpers (PDF export, formatting)."""
import io
from typing import Any


def format_inr(amount: float) -> str:
    """Format a float as Indian Rupee string, e.g. 1,25,000.50"""
    s = f"{abs(amount):,.2f}"
    parts = s.split(".")
    integer = parts[0].replace(",", "")
    if len(integer) > 3:
        last3 = integer[-3:]
        rest = integer[:-3]
        groups = []
        while len(rest) > 2:
            groups.append(rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.append(rest)
        groups.reverse()
        integer = ",".join(groups) + "," + last3
    result = integer + "." + parts[1]
    return ("-" if amount < 0 else "") + result


def build_pdf_report(payload: dict[str, Any]) -> bytes:
    """Generate a multi-month PDF summary using reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Average Bank Balance Report", styles["Title"]))
    elements.append(Spacer(1, 12))

    months = payload.get("months", [])
    for m in months:
        label = f"{m.get('month', '')} {m.get('year', '')}"
        elements.append(Paragraph(label, styles["Heading2"]))

        summary_data = [
            ["Metric", "Value"],
            ["5 Series Average", format_inr(m["average5"])],
            ["10 Series Average", format_inr(m["average10"])],
        ]
        t = Table(summary_data, colWidths=[200, 200])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 8))

        elements.append(Paragraph("5 Series Selected Balances", styles["Heading3"]))
        rows = [["Date", "Balance"]] + [[f"Day {k}", format_inr(v)] for k, v in m["selected_balances_5"].items()]
        t2 = Table(rows, colWidths=[200, 200])
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
        ]))
        elements.append(t2)
        elements.append(Spacer(1, 16))

    doc.build(elements)
    return buf.getvalue()
