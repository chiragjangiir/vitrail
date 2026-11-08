"""Rapport exécutif PDF white-label (§24.3).

reportlab importé PARESSEUSEMENT (comme pop_report) → le module reste importable même si
reportlab n'est pas installé. Le rapport reprend les KPIs de l'Executive Dashboard + la
flotte + le top contenus + l'estimation ROI, brandé aux couleurs/logo de l'org.
"""

from __future__ import annotations

from io import BytesIO


def _fmt_duration(total_sec: int) -> str:
    h, rem = divmod(int(total_sec), 3600)
    m = rem // 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m"
    return f"{total_sec}s"


def _eur(v: float) -> str:
    return f"{v:,.0f} EUR".replace(",", " ")


def build_executive_pdf(
    *,
    org_name: str,
    payload: dict,
    branding: dict,
    roi: dict | None,
    logo_bytes: bytes | None = None,
    generated_at: str = "",
) -> bytes:
    """Construit le rapport exécutif PDF. `payload` = sortie de build_executive_payload."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    try:
        accent = colors.HexColor(branding.get("primary_color") or "#4875B4")
    except (ValueError, TypeError):
        accent = colors.HexColor("#4875B4")
    ink = colors.HexColor("#1C1E2A")
    muted = colors.HexColor("#6B7280")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=branding.get("report_title") or "Rapport exécutif",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=ink, fontSize=18, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent, fontSize=12,
                        spaceBefore=12, spaceAfter=4)
    normal = styles["Normal"]
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=muted)

    story: list = []

    # ── En-tête (logo + titre + sous-titre + période) ─────────────────────────
    if logo_bytes:
        try:
            img = Image(BytesIO(logo_bytes))
            ratio = img.imageWidth / img.imageHeight if img.imageHeight else 1
            img.drawHeight = 16 * mm
            img.drawWidth = min(50 * mm, 16 * mm * ratio)
            img.hAlign = "LEFT"
            story.append(img)
            story.append(Spacer(1, 4 * mm))
        except Exception:
            pass

    story.append(Paragraph(branding.get("report_title") or "Rapport exécutif", h1))
    if branding.get("report_subtitle"):
        story.append(Paragraph(branding["report_subtitle"], normal))
    story.append(Paragraph(
        f"{org_name} — période du {payload['from_date']} au {payload['until_date']}", small))
    if generated_at:
        story.append(Paragraph(f"Généré le {generated_at}", small))
    story.append(Spacer(1, 6 * mm))

    # ── KPIs ──────────────────────────────────────────────────────────────────
    story.append(Paragraph("Indicateurs clés", h2))
    fleet = payload["fleet"]
    hs = payload["health_score"]
    kpi_rows = [
        ["Network Health Score", "—" if hs is None else f"{hs} / 100"],
        ["Uptime réseau", "—" if payload["uptime_pct"] is None else f"{payload['uptime_pct']} %"],
        ["Conformité de diffusion",
         "—" if payload["conformity_pct"] is None else f"{payload['conformity_pct']} %"],
        ["Players actifs", f"{fleet['online']} / {fleet['total']}"],
        ["Alertes actives (24 h)", str(payload["alerts_active"])],
        ["Contenu diffusé",
         f"{payload['plays_count']:,} diffusions · {_fmt_duration(payload['play_seconds'])}"
         .replace(",", " ")],
    ]
    t = Table(kpi_rows, colWidths=[75 * mm, 99 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), muted),
        ("TEXTCOLOR", (1, 0), (1, -1), ink),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#E5E7EB")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)

    # ── Flotte ────────────────────────────────────────────────────────────────
    story.append(Paragraph("Statut de la flotte", h2))
    fl = Table(
        [["En ligne", "Attention", "Hors ligne", "Maintenance"],
         [str(fleet["online"]), str(fleet["warning"]), str(fleet["offline"]),
          str(fleet["maintenance"])]],
        colWidths=[43.5 * mm] * 4,
    )
    fl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TEXTCOLOR", (0, 0), (-1, 0), muted),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (0, 1), colors.HexColor("#2E7D32")),
        ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#E65100")),
        ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#C62828")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
    ]))
    story.append(fl)

    # ── Top contenus ──────────────────────────────────────────────────────────
    top = payload.get("top_content") or []
    if top:
        story.append(Paragraph("Top contenus diffusés", h2))
        rows = [["#", "Contenu", "Diffusions", "Durée"]]
        for i, c in enumerate(top, 1):
            rows.append([str(i), (c.get("media_name") or f"#{c.get('id_media')}")[:60],
                         f"{c['plays']:,}".replace(",", " "), _fmt_duration(c["seconds"])])
        tc = Table(rows, colWidths=[10 * mm, 104 * mm, 30 * mm, 30 * mm])
        tc.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), muted),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#E5E7EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tc)

    # ── ROI ───────────────────────────────────────────────────────────────────
    if roi:
        story.append(Paragraph("Estimation de la valeur réseau (ROI)", h2))
        roi_rows = [
            ["Contacts estimés sur la période", f"{roi['impressions']:,}".replace(",", " ")],
            ["Valeur réseau (CPM)", _eur(roi["network_value_eur"])],
            ["Économie papier estimée", _eur(roi["paper_savings_eur"])],
            ["ROI cumulé estimé", _eur(roi["total_roi_eur"])],
        ]
        rt = Table(roi_rows, colWidths=[95 * mm, 79 * mm])
        rt.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("TEXTCOLOR", (0, 0), (0, -1), muted),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (1, -1), (1, -1), accent),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#E5E7EB")),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(rt)
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"Hypothèses : {roi['screens']} écrans, {roi['hours_per_day']} h/j, "
            f"{roi['contacts_per_hour']} contacts/h/écran, CPM {roi['cpm_eur']} EUR, "
            f"affiche évitée {roi['paper_eur_per_month']} EUR/mois/écran, "
            f"uptime {roi['uptime_pct']} %. Valeurs indicatives.", small))

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(f"Confidentiel — {org_name}", small))

    doc.build(story)
    return buf.getvalue()
