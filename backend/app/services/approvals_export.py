"""Exports de la file d'approbation §XXI (retour Ed 2026-07-12) — CSV + PDF.

Même scope que GET /approvals (reviewer = org entière ; soumetteur = SES demandes).
`rows` = liste de dicts préparés par l'endpoint : resource_name, type, soumetteur,
dates, statut, valideur, dernier motif de décision. Français v1 (comme les rapports
exécutif/campagne). reportlab importé paresseusement (comme report_pdf.py).
"""

from __future__ import annotations

import csv
from io import BytesIO, StringIO

STATUS_LABELS = {
    "pending_review": "En attente",
    "changes_requested": "Modifications demandées",
    "approved": "Approuvée",
    "rejected": "Rejetée",
    "published": "Publiée",
    "cancelled": "Annulée",
}

_HEADERS = ["ID", "Ressource", "Type", "Soumis par", "Soumis le", "Échéance",
            "Statut", "Décidé par", "Décidé le", "Publié le", "Motif / commentaire"]


def _fmt_dt(v) -> str:
    return v.strftime("%Y-%m-%d %H:%M") if v else ""


def _row_values(r: dict) -> list[str]:
    return [
        str(r["id_request"]),
        r.get("resource_name") or f"#{r['resource_id']}",
        r.get("resource_type") or "",
        r.get("submitted_by_name") or "",
        _fmt_dt(r.get("submitted_at")),
        _fmt_dt(r.get("due_date")),
        STATUS_LABELS.get(r["status"], r["status"]),
        r.get("reviewed_by_name") or "",
        _fmt_dt(r.get("reviewed_at")),
        _fmt_dt(r.get("published_at")),
        (r.get("decision_comment") or "").replace("\n", " ").strip(),
    ]


def approvals_csv(rows: list[dict]) -> str:
    buf = StringIO()
    w = csv.writer(buf, delimiter=";")  # ; = ouverture directe Excel FR
    w.writerow(_HEADERS)
    for r in rows:
        w.writerow(_row_values(r))
    return buf.getvalue()


def build_approvals_pdf(*, org_name: str, rows: list[dict], generated_at: str = "",
                        status_filter: str | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    accent = colors.HexColor("#4875B4")
    ink = colors.HexColor("#1C1E2A")
    muted = colors.HexColor("#6B7280")
    line = colors.HexColor("#E5E7EB")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Approbations — {org_name}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=ink, fontSize=16,
                        spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=muted)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, textColor=ink,
                          leading=10)

    story: list = [Paragraph(f"Demandes d'approbation — {org_name}", h1)]
    sub = f"Généré le {generated_at}" if generated_at else ""
    if status_filter:
        sub += f" · statut : {STATUS_LABELS.get(status_filter, status_filter)}"
    sub += f" · {len(rows)} demande(s)"
    story.append(Paragraph(sub, small))
    story.append(Spacer(1, 6 * mm))

    data = [_HEADERS]
    for r in rows:
        vals = _row_values(r)
        # Paragraph pour les colonnes texte longues (wrap) — les autres restent str
        vals[1] = Paragraph(vals[1], cell)
        vals[10] = Paragraph(vals[10], cell)
        data.append(vals)
    widths = [10, 42, 18, 30, 24, 22, 30, 30, 24, 24, 60]
    table = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, line),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()
