"""Retail Media S4 — rapport annonceur PDF white-label (§2.8, plan §4).

Même moteur/gabarit que le rapport exécutif (report_pdf.py) : reportlab importé
paresseusement, branding org (couleur/logo/titre). `payload` = sortie de
services/campaign_report.build_campaign_report. Français v1 (comme l'exécutif).
"""

from __future__ import annotations

from io import BytesIO

from app.services.report_pdf import _fmt_duration


def _n(v: int) -> str:
    return f"{v:,}".replace(",", " ")


def build_campaign_pdf(
    *,
    org_name: str,
    payload: dict,
    branding: dict,
    logo_bytes: bytes | None = None,
    generated_at: str = "",
    level: str = "player",
) -> bytes:
    """`level` (retour Ed #3) : granularité de la répartition — 'player' (défaut),
    'site' ou 'site_group' (agrégats du service, SOV servi moyen par niveau)."""
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
    line = colors.HexColor("#E5E7EB")

    camp = payload["campaign"]
    totals = payload["totals"]
    sov = payload["sov"]
    amount = payload["amount"]

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Rapport de campagne — {camp['campaign_name']}",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=ink, fontSize=18, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent, fontSize=12,
                        spaceBefore=12, spaceAfter=4)
    normal = styles["Normal"]
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=muted)

    story: list = []

    # ── En-tête ───────────────────────────────────────────────────────────────
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

    story.append(Paragraph(f"Rapport de campagne — {camp['campaign_name']}", h1))
    if camp.get("advertiser_name"):
        story.append(Paragraph(f"Annonceur : {camp['advertiser_name']}", normal))
    story.append(Paragraph(
        f"{org_name} — campagne du {camp['starts_on']} au {camp['ends_on']} · "
        f"période rapportée : {payload['period']['from']} → {payload['period']['until']}",
        small))
    if generated_at:
        story.append(Paragraph(f"Généré le {generated_at}", small))
    story.append(Spacer(1, 6 * mm))

    # ── Indicateurs de diffusion ──────────────────────────────────────────────
    story.append(Paragraph("Diffusion", h2))
    signed_pct = (round(100.0 * totals["signed_plays"] / totals["plays"], 1)
                  if totals["plays"] else 0.0)
    served = "—" if sov["served_pct"] is None else f"{sov['served_pct']} %"
    kpi_rows = [
        ["Passages diffusés", _n(totals["plays"])],
        ["Preuves signées (Ed25519)", f"{_n(totals['signed_plays'])} ({signed_pct} %)"],
        ["Temps d'antenne", _fmt_duration(totals["airtime_ms"] // 1000)],
        ["Écrans touchés", f"{totals['players_reached']} / {totals['players_targeted']} ciblés"],
        ["Part de voix servie", f"{served}  (vendue : {sov['sold_pct']} %)"],
    ]
    t = Table(kpi_rows, colWidths=[75 * mm, 99 * mm])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), muted),
        ("TEXTCOLOR", (1, 0), (1, -1), ink),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, line),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)

    # ── Montant ───────────────────────────────────────────────────────────────
    story.append(Paragraph("Montant", h2))
    model_label = {"sov": "Part de voix", "flat": "Forfait"}.get(amount["model"],
                                                                 amount["model"])
    amount_rows = [["Modèle de vente", model_label]]
    if amount["amount"] is not None:
        amount_rows.append([
            "Montant de la campagne",
            f"{amount['amount']:,.2f} {amount['currency']}".replace(",", " ")])
    if amount["cpm_indicative"] is not None:
        amount_rows.append([
            f"Équivalent CPM indicatif ({amount['cpm_rate']} {amount['currency']}/1000)",
            f"{amount['cpm_indicative']:,.2f} {amount['currency']}".replace(",", " ")])
    at = Table(amount_rows, colWidths=[95 * mm, 79 * mm])
    at.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), muted),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, -1), (1, -1), accent),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, line),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(at)

    # ── Répartition (granularité choisie : écran / site / groupe de sites) ───
    per_site = payload.get("per_site") or []
    per_site_group = payload.get("per_site_group") or []
    if level == "site" and per_site:
        title, first_col = "Répartition par site", "Site"
        dist_rows = [(s["site_name"] or "Sans site",
                      f"{s['players_reached']} écran(s) · {_n(s['plays'])}",
                      s) for s in per_site[:40]]
    elif level == "site_group" and per_site_group:
        title, first_col = "Répartition par groupe de sites", "Groupe de sites"
        dist_rows = [(g["group_name"],
                      f"{len(g['site_ids'])} site(s) · {_n(g['plays'])}",
                      g) for g in per_site_group[:40]]
        # Sites hors groupe → ligne agrégée « Autres sites »
        grouped = {sid for g in per_site_group for sid in g["site_ids"]}
        rest = [s for s in per_site if s["id_site"] not in grouped]
        if rest:
            other = {
                "plays": sum(s["plays"] for s in rest),
                "airtime_ms": sum(s["airtime_ms"] for s in rest),
                "sov_served_pct": None,
            }
            dist_rows.append(("Autres sites",
                              f"{len(rest)} site(s) · {_n(other['plays'])}", other))
    else:
        title, first_col = "Répartition par écran", "Écran"
        dist_rows = [(p["player_name"][:48], _n(p["plays"]), p)
                     for p in (payload.get("per_player") or [])[:40]]
    if dist_rows:
        story.append(Paragraph(title, h2))
        rows = [[first_col, "Passages", "Temps d'antenne", "SOV servi"]]
        for label, plays_label, obj in dist_rows:
            rows.append([
                str(label)[:48], plays_label,
                _fmt_duration(obj["airtime_ms"] // 1000),
                "—" if obj["sov_served_pct"] is None else f"{obj['sov_served_pct']} %",
            ])
        pt = Table(rows, colWidths=[74 * mm, 36 * mm, 34 * mm, 30 * mm])
        pt.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), muted),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, line),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(pt)

    # ── Par créatif ───────────────────────────────────────────────────────────
    per_creative = payload.get("per_creative") or []
    if len(per_creative) > 1:
        story.append(Paragraph("Répartition par créatif", h2))
        rows = [["Créatif", "Passages", "Temps d'antenne"]]
        for c in per_creative:
            rows.append([c["media_name"][:60], _n(c["plays"]),
                         _fmt_duration(c["airtime_ms"] // 1000)])
        ct = Table(rows, colWidths=[110 * mm, 30 * mm, 34 * mm])
        ct.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), muted),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, line),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(ct)

    # ── Par jour ──────────────────────────────────────────────────────────────
    per_day = payload.get("per_day") or []
    if per_day:
        story.append(Paragraph("Diffusion quotidienne", h2))
        rows = [["Date", "Passages", "Temps d'antenne"]]
        for d in per_day[-31:]:
            rows.append([d["date"], _n(d["plays"]), _fmt_duration(d["airtime_ms"] // 1000)])
        dt = Table(rows, colWidths=[60 * mm, 40 * mm, 74 * mm])
        dt.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), muted),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (2, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, line),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(dt)

    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "Chaque passage est adossé à une preuve de diffusion (Proof of Play) horodatée, "
        "chaînée (arbre de Merkle) et signée par l'écran (Ed25519) — vérifiable a posteriori.",
        small))
    story.append(Paragraph(f"Confidentiel — {org_name}", small))

    doc.build(story)
    return buf.getvalue()
