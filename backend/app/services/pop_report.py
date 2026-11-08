"""Génération du rapport/certificat Proof of Play en PDF (§XXIV).

Document unique et organisé couvrant un ou plusieurs players (sélection libre, par groupe ou par
site, résolue côté endpoint) : résumé global + une section par player (intégrité de chaîne,
compteurs signés/non-signés, Merkle root, tête de chaîne). Sert de preuve vérifiable à fournir à
un annonceur / pour une déclaration.

reportlab est importé PARESSEUSEMENT (dans la fonction) : le module reste importable même si la
dépendance n'est pas encore installée (fenêtre avant rebuild d'image) — seul l'appel PDF échoue.
"""

from __future__ import annotations

from io import BytesIO


def _fmt_duration(total_sec: int) -> str:
    h, rem = divmod(int(total_sec), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def build_pop_report_pdf(report: dict) -> bytes:
    """Construit le PDF à partir d'un dict structuré (voir endpoint pop.report_pdf).

    report = {
        org_name, from_date, until_date, generated_at,
        total_plays, total_screen_off, total_covered, merkle_root, scope_label,
        players: [{player_name, plays, duration_sec, screen_off, covered, signed, unsigned,
                   signature_invalid, chain_valid, chain_head, merkle_root}]
    }

    `total_plays` / `plays` = diffusions COMPTABILISÉES. Deux causes les en excluent, toutes
    deux affichées séparément et jamais ajoutées à l'antenne :
      · `screen_off` — sortie vidéo coupée (migr 0102) ;
      · `covered`    — zone recouverte par un overlay plein écran, spot de campagne P3.6 ou
        takeover VOD (migr 0125).
    Elles restent dans la chaîne et le merkle_root, qui portent sur toutes les preuves —
    c'est ce qui rend l'attestation recalculable par un tiers.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    accent = colors.HexColor("#4875B4")
    ink = colors.HexColor("#1D2B3A")
    ok = colors.HexColor("#2F855A")
    bad = colors.HexColor("#C53030")

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title="Rapport Proof of Play",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=ink, fontSize=18, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent, fontSize=13,
                        spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                           textColor=colors.HexColor("#5A6473"))

    story: list = []
    story.append(Paragraph("Rapport Proof of Play", h1))
    story.append(Paragraph(
        f"Organisation : <b>{report['org_name']}</b> &nbsp;·&nbsp; Période : "
        f"<b>{report['from_date']}</b> → <b>{report['until_date']}</b>", styles["Normal"]))
    if report.get("scope_label"):
        story.append(Paragraph(f"Périmètre : {report['scope_label']}", styles["Normal"]))
    story.append(Paragraph(f"Généré le {report['generated_at']}", small))
    story.append(Spacer(1, 8))

    # Résumé global. Les lignes « non comptées » ne s'affichent que s'il y a matière :
    # ne pas polluer un rapport nominal avec des zéros.
    summary = [["Total diffusions", str(report["total_plays"])]]
    if report.get("total_screen_off"):
        summary.append(["Dont écran coupé (non comptées)", str(report["total_screen_off"])])
    if report.get("total_covered"):
        summary.append(["Dont zone recouverte (non comptées)", str(report["total_covered"])])
    summary.append(["Players couverts", str(len(report["players"]))])
    summary.append(["Merkle root global", report.get("merkle_root") or "—"])
    # Le Merkle root est la DERNIÈRE ligne : on cible son index calculé, jamais un index
    # écrit en dur — les lignes conditionnelles ci-dessus le décalent (la police Courier
    # atterrissait sur « Players couverts » dès qu'une preuve était marquée).
    _merkle_row = len(summary) - 1
    t = Table(summary, colWidths=[45 * mm, 125 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (1, _merkle_row), (1, _merkle_row), "Courier", 7),
        ("TEXTCOLOR", (0, 0), (0, -1), ink),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F4F8")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D7DEE7")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D7DEE7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)

    # Sections par player
    for p in report["players"]:
        story.append(Paragraph(p["player_name"], h2))
        integ = ("Chaîne valide" if p["chain_valid"] else "CHAÎNE ALTÉRÉE")
        integ_color = ok if p["chain_valid"] else bad
        rows = [
            ["Diffusions", str(p["plays"]), "Durée totale", _fmt_duration(p["duration_sec"])],
            ["Signées ✓", str(p["signed"]), "Non signées", str(p["unsigned"])],
            ["Signatures invalides", str(p["signature_invalid"]), "Intégrité", integ],
        ]
        if p.get("covered"):
            rows.insert(1, ["Zone recouverte", str(p["covered"]), "", "non comptabilisées"])
        if p.get("screen_off"):
            rows.insert(1, ["Écran coupé", str(p["screen_off"]), "", "non comptabilisées"])
        pt = Table(rows, colWidths=[38 * mm, 25 * mm, 38 * mm, 69 * mm])
        pt.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("TEXTCOLOR", (0, 0), (0, -1), ink), ("TEXTCOLOR", (2, 0), (2, -1), ink),
            ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
            ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 9),
            ("TEXTCOLOR", (3, 2), (3, 2), integ_color),
            ("TEXTCOLOR", (1, 2), (1, 2), bad if p["signature_invalid"] else ink),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D7DEE7")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D7DEE7")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(pt)
        story.append(Spacer(1, 2))
        _mr = p.get("merkle_root") or "—"
        _ch = p.get("chain_head") or "—"
        story.append(Paragraph(f"Merkle root : <font face='Courier'>{_mr}</font>", small))
        story.append(Paragraph(f"Tête de chaîne : <font face='Courier'>{_ch}</font>", small))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Chaque diffusion est chaînée par hash SHA-256 (anti-altération) et, lorsque le player le "
        "supporte, signée par une clé Ed25519 propre au device. Une signature invalide ou une "
        "rupture de chaîne est signalée ci-dessus.", small))

    doc.build(story)
    return buf.getvalue()
