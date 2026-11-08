"""Compositing déterministe : arbre résolu → HTML/CSS (Jinja2) rendu par Playwright (§4).

Le HTML est rendu par `page.set_content()` à la **résolution cible exacte** (viewport = toile),
donc le texte/prix/mentions sont **vectoriels et nets même en 4K**. Unités CSS en vw/vh/% →
résolution-agnostiques. Un auto-fit JS (fonction `__fit`, appelée par le worker avant capture)
réduit la police jusqu'à ce que chaque texte tienne dans sa zone, avec un **plancher de lisibilité**
(`min_vh`). Les données utilisateur (slogan/mentions) sont **échappées** (autoescape Jinja2).
"""

from __future__ import annotations

import jinja2

from app.services.promo import fonts

# Repli : appliqué quand le thème ne nomme aucune police (ou une police inutilisable).
_FONT_STACK = "'Inter','Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


def _stage_stack(theme: dict) -> str:
    """Pile de polices de la toile, dérivée de la police du THÈME (charte de marque comprise).

    ⚠️ Avant P3.4 cette pile était figée sur Inter alors que `fonts.used_font_faces` embarquait
    déjà les octets de la police du thème : la police était téléchargée, encodée dans la page…
    et jamais appliquée. Invisible tant que les deux templates built-in déclaraient « Inter ».
    Le nom passe par `css_family` — il vient d'une saisie (§12.7 / charte)."""
    family = fonts.css_family((theme or {}).get("font"))
    return f"'{family}',{_FONT_STACK}" if family else _FONT_STACK

_HTML = jinja2.Template(
    # autoescape=True : les textes utilisateur (slogan/mentions) sont échappés → pas
    # d'injection HTML/JS dans la page rendue par Chromium (le prix/badge sont produits par
    # notre code, sûrs).
    autoescape=True,
    source="""<!doctype html><html><head><meta charset="utf-8"><style>
{{ font_faces | safe }}
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:100vw; height:100vh; overflow:hidden; }
.stage { position:relative; width:100vw; height:100vh; overflow:hidden;
         background:{{ theme.paper }}; font-family:{{ font | safe }}; }
.bg { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.product { position:absolute; object-fit:contain; }
/* block (pas flex) : overflow:hidden ne plafonne pas scrollWidth/Height → l'auto-fit mesure
   correctement le débordement. word-break autorise la coupe des mots trop longs. */
.txt { position:absolute; overflow:hidden; display:block; line-height:1.06;
       overflow-wrap:break-word; word-break:break-word; }
.badge { position:absolute; display:flex; align-items:center; justify-content:center;
         border-radius:50%; text-align:center; transform:rotate(-8deg);
         box-shadow:0 0.6vh 1.6vh rgba(0,0,0,.25); }
/* Calques libres (Phase B) — superposés au template, transform-origin centre pour la rotation. */
.layer { position:absolute; box-sizing:border-box; transform-origin:center center;
         overflow:hidden; line-height:1.06; }
.layer > img { width:100%; height:100%; display:block; }
</style></head><body>
<div class="stage">
  {% if background_data_uri %}<img class="bg" src="{{ background_data_uri }}">{% endif %}
  {% if product_data_uri %}
  <img class="product" src="{{ product_data_uri }}" style="
    left:{{ slots.product.left }}%; top:{{ slots.product.top }}%;
    width:{{ slots.product.width }}%; height:{{ slots.product.height }}%;">
  {% endif %}
  {% for name, s in text_slots %}
  <div class="txt fit" data-vh="{{ s.font_vh }}" data-minvh="{{ s.min_vh }}" style="
    left:{{ s.left }}%; top:{{ s.top }}%; width:{{ s.width }}%;
    {% if s.height %}height:{{ s.height }}%;{% endif %}
    {% if s.font %}font-family:'{{ s.font }}',{{ font_fallback | safe }};{% endif %}
    color:{{ s.color }}; font-weight:{{ s.weight }};
    justify-content:{{ s.justify }}; text-align:{{ s.align }};
    {% if s.strike %}text-decoration:line-through; opacity:.7;{% endif %}
    {% if s.nowrap %}white-space:nowrap;{% endif %}
    ">{{ s.text }}</div>
  {% endfor %}
  {% if slots.discount %}
  <div class="badge fit" data-vh="{{ slots.discount.font_vh }}"
    data-minvh="{{ slots.discount.min_vh }}"
    style="left:{{ slots.discount.left }}%; top:{{ slots.discount.top }}%;
    width:{{ slots.discount.width }}%; height:{{ slots.discount.height }}%;
    background:{{ theme.badge_bg }}; color:{{ theme.badge_ink }};
    font-weight:{{ slots.discount.weight }};
    ">{{ slots.discount.text }}</div>
  {% endif %}
  {% for ly in layers %}
  <div class="layer" style="
    left:{{ ly.x }}%; top:{{ ly.y }}%; width:{{ ly.w }}%; height:{{ ly.h }}%;
    transform:rotate({{ ly.rotation }}deg); z-index:{{ 100 + ly.z }}; opacity:{{ ly.opacity }};
    {% if ly.type == 'text' %}
      {% if ly.font %}font-family:'{{ ly.font }}',{{ font_fallback | safe }};{% endif %}
      font-size:{{ ly.size_vh }}vh; color:{{ ly.color }}; font-weight:{{ ly.weight }};
      text-align:{{ ly.align }}; overflow-wrap:break-word; word-break:break-word;
    {% elif ly.type == 'shape' and ly.shape == 'line' %}
      background:{{ ly.stroke if ly.stroke != 'none' else ly.fill }};
      height:{{ ly.stroke_width if ly.stroke_width else 0.5 }}vh;
    {% elif ly.type == 'shape' %}
      background:{{ ly.fill }};
      {% if ly.stroke != 'none' and ly.stroke_width %}
      border:{{ ly.stroke_width }}vh solid {{ ly.stroke }};{% endif %}
      border-radius:{% if ly.shape == 'ellipse' %}50%{% else %}{{ ly.radius }}%{% endif %};
    {% endif %}
    ">
    {%- if ly.type == 'text' %}{{ ly.text }}
    {%- elif ly.type == 'image' and ly.data_uri -%}
    <img src="{{ ly.data_uri }}" style="object-fit:{{ ly.fit }};">
    {%- endif %}</div>
  {% endfor %}
</div>
<script>
window.__fit = function () {
  var vh = window.innerHeight / 100;
  document.querySelectorAll('.fit').forEach(function (el) {
    var min = parseFloat(el.dataset.minvh) || 1;
    var size = parseFloat(el.dataset.vh) || 4;
    var guard = 0;
    el.style.fontSize = (size * vh) + 'px';
    while ((el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)
           && size > min && guard < 400) {
      size -= 0.25; guard++;
      el.style.fontSize = (size * vh) + 'px';
    }
  });
};
window.__fit();
</script>
</body></html>"""
)


def _color(theme: dict, ref) -> str:
    """Résout une couleur : clé du theme (ink/accent/paper) ou hex littéral."""
    if isinstance(ref, str) and ref in theme:
        return theme[ref]
    return ref or theme.get("ink", "#1D2B3A")


def build_html(
    resolved: dict, background_data_uri: str | None, product_data_uri: str | None,
    font_faces_css: str = "",
) -> str:
    """Construit le HTML du composite à partir de l'arbre résolu + les images (data URIs).

    `font_faces_css` = bloc `@font-face` base64 (construit par `fonts.font_face_css` dans le worker,
    qui fait l'I/O) — embarque les polices utilisées → rendu déterministe."""
    theme = resolved["theme"]
    slots = resolved["slots"]
    align_to_justify = {"left": "flex-start", "center": "center", "right": "flex-end"}

    text_slots = []
    for name in ("slogan", "original_price", "price", "mentions"):
        s = slots.get(name)
        if not s:
            continue
        align = s.get("align", "left")
        text_slots.append((name, {
            "left": s["left"], "top": s["top"], "width": s["width"],
            "height": s.get("height"), "font_vh": s["font_vh"], "min_vh": s["min_vh"],
            "color": _color(theme, s.get("color")), "weight": s.get("weight", 600),
            # nom de famille (override), sinon None → police du thème. Sanitisé : il finit dans un
            # `style="…"`, où l'échappement HTML ne protège PAS d'une injection CSS.
            "font": fonts.css_family(s.get("font")),
            "align": align, "justify": align_to_justify.get(align, "flex-start"),
            "strike": name == "original_price",
            "nowrap": name in ("price", "original_price"),
            "text": s["text"],
        }))

    # Calques (Phase B) : même sanitisation de la famille que les slots.
    layers = [{**ly, "font": fonts.css_family(ly.get("font"))}
              for ly in (resolved.get("layers") or [])]

    return _HTML.render(
        theme=theme, font=_stage_stack(theme), font_fallback=_FONT_STACK,
        font_faces=font_faces_css,
        background_data_uri=background_data_uri, product_data_uri=product_data_uri,
        slots=slots, text_slots=text_slots, layers=layers,
    )
