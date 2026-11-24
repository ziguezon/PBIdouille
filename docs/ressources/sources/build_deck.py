# -*- coding: utf-8 -*-
"""Guide de démarrage rapide PBIdouille : deck PowerPoint (python-pptx)."""
from pathlib import Path
from PIL import Image
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.dml import MSO_LINE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree

HERE = Path(__file__).resolve().parent
PNG = HERE / "png"
CROP = HERE / "crop"
CROP.mkdir(exist_ok=True)
OUT = HERE.parents[1] / "PBIdouille - Guide de demarrage rapide.pptx"  # docs/
# un autre fichier de sortie (ex. pour comparer avant d'écraser le guide)
import os as _os
if _os.environ.get("PBID_DECK_OUT"):
    OUT = Path(_os.environ["PBID_DECK_OUT"])
OUT.parent.mkdir(exist_ok=True)

# --- palette « Dark Teal Pro » de l'app ------------------------------------
BG = RGBColor(0x0F, 0x16, 0x29)
CARD = RGBColor(0x16, 0x20, 0x32)
CARD2 = RGBColor(0x1C, 0x2A, 0x42)
LINE = RGBColor(0x2A, 0x3A, 0x55)
GREEN = RGBColor(0x56, 0xC5, 0x96)
BLUE = RGBColor(0x4F, 0xA8, 0xE8)
ORANGE = RGBColor(0xF5, 0xA6, 0x23)
# les numéros posés SUR une capture : un orange vif, qui ne se confond ni
# avec le vert du thème ni avec les boutons de l'app (même valeur que
# capture_vue.py)
REPERE = RGBColor(0xFF, 0x8A, 0x1F)
RED = RGBColor(0xE5, 0x5B, 0x5B)
LILAS = RGBColor(0xA7, 0x8B, 0xFA)       # la Radiographie, diapo 2
TEXT = RGBColor(0xE6, 0xED, 0xF3)
MUTED = RGBColor(0x9A, 0xA7, 0xB8)
DARK = RGBColor(0x0B, 0x11, 0x20)
HEAD = "Bahnschrift SemiBold"
BODY = "Segoe UI"
MONO = "Consolas"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = 13.333, 7.5


def crop(name, box, out):
    im = Image.open(PNG / (name + ".png"))
    if box:
        im = im.crop(box)
    p = CROP / (out + ".png")
    im.save(p)
    return p, im.size


def new_slide(notes=""):
    s = prs.slides.add_slide(BLANK)
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = BG
    if notes:
        s.notes_slide.notes_text_frame.text = notes
    return s


def text(slide, x, y, w, h, runs, size=16, color=TEXT, font=BODY, bold=False,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, name=None, spacing=None):
    """runs : str, ou liste de paragraphes ; un paragraphe = str ou liste de
    (texte, {options})."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = runs if isinstance(runs, list) else [runs]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        parts = para if isinstance(para, list) else [(para, {})]
        for t, o in parts:
            r = p.add_run()
            r.text = t
            f = r.font
            f.name = o.get("font", font)
            f.size = Pt(o.get("size", size))
            f.bold = o.get("bold", bold)
            f.italic = o.get("italic", False)
            f.color.rgb = o.get("color", color)
    return tb


def box(slide, x, y, w, h, fill=CARD, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
        radius=0.08, name=None, lw=1.25):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        sh.name = name
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(lw)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = radius
    sh.shadow.inherit = False
    return sh


def label_box(slide, x, y, w, h, t, fill=CARD, line=None, color=TEXT, size=14,
              bold=False, font=BODY, sub=None, subcolor=MUTED, align=PP_ALIGN.CENTER, name=None):
    sh = box(slide, x, y, w, h, fill=fill, line=line, name=name)
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.08)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = t
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.name = font
    r.font.color.rgb = color
    if sub:
        p2 = tf.add_paragraph()
        p2.alignment = align
        r2 = p2.add_run()
        r2.text = sub
        r2.font.size = Pt(max(size - 3, 10))
        r2.font.name = BODY
        r2.font.color.rgb = subcolor
    return sh


def arrow(slide, x1, y1, x2, y2, color=MUTED, w=1.5, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                   Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(w)
    ln = c.line._get_or_add_ln()
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")
    if dash:
        pd = etree.SubElement(ln, qn("a:prstDash"))
        pd.set("val", "dash")
        ln.remove(pd)
        ln.insert(1, pd)
    return c


def elbow(slide, x1, y1, x2, y2, color=MUTED, w=1.5):
    """Coude : horizontal, vertical, horizontal (trois segments)."""
    xm = (x1 + x2) / 2
    for a, b, c, d, last in ((x1, y1, xm, y1, False), (xm, y1, xm, y2, False),
                             (xm, y2, x2, y2, True)):
        if last:
            arrow(slide, a, b, c, d, color=color, w=w)
        else:
            ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(a), Inches(b),
                                            Inches(c), Inches(d))
            ln.line.color.rgb = color
            ln.line.width = Pt(w)


def badge(slide, x, y, n, color=GREEN, d=0.42, size=14):
    c = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    c.fill.solid()
    c.fill.fore_color.rgb = color
    c.line.fill.background()
    c.shadow.inherit = False
    tf = c.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = str(n)
    r.font.size = Pt(size)
    r.font.bold = True
    r.font.name = HEAD
    r.font.color.rgb = DARK
    return c


def title(slide, t, kicker=None):
    if kicker:
        text(slide, 0.6, 0.38, 10, 0.3, kicker.upper(), size=12, color=GREEN, font=HEAD)
    text(slide, 0.6, 0.62, 12.1, 0.8, t, size=32, font=HEAD, color=TEXT, name="Titre")


def picture(slide, path, x, y, w=None, h=None, border=True):
    kw = {}
    if w:
        kw["width"] = Inches(w)
    if h:
        kw["height"] = Inches(h)
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), **kw)
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(1)
    return pic


def step_list(slide, x, y, w, items, gap=0.78, size=15, color=GREEN):
    for i, (head, body) in enumerate(items):
        yy = y + i * gap
        badge(slide, x, yy, i + 1, color=color)
        text(slide, x + 0.58, yy - 0.02, w - 0.58, gap,
             [[(head, {"bold": True, "size": size})],
              [(body, {"size": size - 2, "color": MUTED})]] if body else
             [[(head, {"bold": True, "size": size})]])


# ============================================================ 1. Titre
s = new_slide("Présenter l'outil en une phrase : PBIdouille écrit automatiquement ce qui se répète "
              "dans un rapport Power BI : les mesures dérivées, les paramètres de champ et le "
              "formatage conditionnel ICP par ICP.")
box(s, 0.6, 1.9, 0.9, 0.9, fill=GREEN, shape=MSO_SHAPE.OVAL)
text(s, 0.6, 1.9, 0.9, 0.9, "🔧", size=30, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 3.0, 6.5, 1.1, "PBIdouille", size=60, font=HEAD, color=TEXT)
text(s, 0.6, 4.15, 6.5, 0.6, "Guide de démarrage rapide", size=28, font=HEAD, color=GREEN)
pt, (tw, th) = crop("onglet_mesures_generation", None, "titre")
picture(s, pt, 7.3, 2.35, w=5.6)
text(s, 0.6, 4.95, 6.3, 1.4,
     "Générer les mesures, les paramètres de champ et le formatage conditionnel "
     "d'un rapport Power BI (PBIP), sans les écrire à la main.", size=18, color=MUTED)

# ============================================================ 2. En un coup d'œil
s = new_slide("Les quatre onglets travaillent tous sur le même rapport, choisi dans la barre du "
              "haut. Le journal à droite raconte tout ce que l'outil fait. Un cinquième, "
              "Wireframe, n'existe que dans l'édition de développement. Les sources de données "
              "sont une vue de la Radiographie, Par source.")
title(s, "Un rapport, quatre onglets", "En un coup d'œil")
cards = [
    ("Mesures", "Décline chaque ICP en variations (7d avg, PY, YTD…) et écrit les paramètres de champ.", GREEN, "Σ"),
    ("Rapport", "Copie le formatage d'un ICP gabarit vers les autres. Colore les matrices.", BLUE, "◧"),
    ("Radiographie", "Fait la carte d'un rapport, de la source au visuel : d'où vient chaque "
     "table, ce qui en dépend, ce qui filtre chaque visuel.", LILAS, "◎"),
    ("ChopChop", "Repère ce que plus rien n'utilise, et exporte la liste.", RED, "×"),
]
cw, gap = (12.1 - 0.2 * (len(cards) - 1)) / len(cards), 0.2
for i, (t, d, col, ic) in enumerate(cards):
    x = 0.6 + i * (cw + gap)
    box(s, x, 1.85, cw, 3.65, fill=CARD, name="Carte " + t)
    c = box(s, x + 0.3, 2.15, 0.75, 0.75, fill=col, shape=MSO_SHAPE.OVAL)
    text(s, x + 0.3, 2.15, 0.75, 0.75, ic, size=24, color=DARK, font=HEAD, bold=True,
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.3, 3.15, cw - 0.4, 0.5, t, size=16, font=HEAD, color=col)
    text(s, x + 0.3, 3.8, cw - 0.5, 1.6, d, size=13, color=TEXT)
box(s, 0.6, 5.8, 12.1, 0.95, fill=CARD2)
text(s, 0.9, 5.8, 11.6, 0.95,
     [[("Partout : ", {"bold": True, "color": GREEN}),
       ("⚙ Réglages (le config du rapport) · 🕘 Restaurer une sauvegarde · "
        "↻ Tout recharger (relire le disque) · le journal à droite.", {})]],
     size=16, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 3. Avant de commencer
s = new_slide("Le seul réflexe à prendre : Desktop peut rester ouvert pendant une écriture, "
              "mais il ne relit les fichiers qu'à l'ouverture. Après une écriture, on le ferme SANS "
              "enregistrer et on rouvre le .pbip : enregistrer effacerait ce que l'outil a écrit.")
title(s, "Avant de commencer", "Prérequis")
pre = [("Un rapport au format PBIP", "Fichier .pbip avec ses dossiers .Report et .SemanticModel (TMDL / PBIR)."),
       ("Python 3.8 ou plus récent", "Lancer avec  py  (pas « python », parfois un faux alias Windows)."),
       ("qtpy + PyQt5 ou PySide6", "Pour l'interface. Rien d'autre à installer."),
       ("TD_Indicateurs.xlsx", "Une ligne par ICP : libellé, couleurs, ordre, attributs.")]
for i, (h, d) in enumerate(pre):
    y = 1.85 + i * 1.0
    box(s, 0.6, y, 6.6, 0.85, fill=CARD)
    text(s, 0.85, y + 0.12, 6.2, 0.7, [[(h, {"bold": True, "size": 16})], [(d, {"size": 13, "color": MUTED})]])
box(s, 7.6, 1.85, 5.1, 3.85, fill=CARD2, line=ORANGE, lw=1.5, name="Règle d'or")
text(s, 7.95, 2.1, 4.5, 0.5, "⚠  La règle d'or", size=22, font=HEAD, color=ORANGE)
text(s, 7.95, 2.75, 4.5, 2.9,
     [[("Après une écriture,", {})],
      [("fermer Desktop sans enregistrer", {"bold": True})],
      [("puis rouvrir le .pbip.", {})],
      [("", {"size": 8})],
      [("Desktop peut rester ouvert pendant l'écriture, mais il ne relit les fichiers "
        "qu'à l'ouverture : l'enregistrer ensuite effacerait ce que l'outil vient d'écrire. "
        "Enregistrer son propre travail AVANT d'écrire.", {"size": 14, "color": MUTED})]],
     size=18)
box(s, 0.6, 6.0, 12.1, 0.8, fill=CARD)
text(s, 0.9, 6.0, 11.6, 0.8,
     [[("Toujours commencer par un ", {}), ("Aperçu (dry-run)", {"bold": True, "color": GREEN}),
       (" : l'outil liste tout ce qu'il ferait, sans rien écrire. Chaque écriture réelle est sauvegardée.", {})]],
     size=15, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 4. Lancer
s = new_slide("La barre du haut est partagée par tous les onglets. L'app rouvre le dernier rapport utilisé.")
title(s, "Lancer l'app et ouvrir un rapport", "Démarrage")
p, (iw, ih) = crop("barre_ruban", (0, 0, 1245, 84), "barre")
picture(s, p, 0.6, 1.8, w=12.1)
pic_h = 12.1 * ih / iw
# repères numérotés sur la capture (coordonnées capture -> pouces)
sx = 12.1 / iw
for n, px in enumerate([66, 208, 660, 810, 973, 1178], start=1):
    badge(s, 0.6 + px * sx - 0.17, 1.8 - 0.4, n, color=REPERE, d=0.34, size=12)
text(s, 0.6, 1.8 + pic_h + 0.35, 5.6, 0.5, "Lancement", size=18, font=HEAD, color=GREEN)
box(s, 0.6, 1.8 + pic_h + 0.9, 5.6, 0.75, fill=DARK, line=LINE)
text(s, 0.85, 1.8 + pic_h + 0.9, 5.2, 0.75, "py app.py", size=20, font=MONO, color=GREEN, anchor=MSO_ANCHOR.MIDDLE)
text(s, 0.6, 1.8 + pic_h + 1.85, 5.6, 1.3,
     "Depuis le dossier de l'app. Elle rouvre le dernier rapport ; le measures_config.json "
     "est cherché à côté du .pbip.", size=14, color=MUTED)
legend = [("📂 Le rapport", "les récents, ou en ouvrir un autre"),
          ("📄 Le config", "choisir un autre measures_config.json"),
          ("⚙ Réglages", "Excel, dossiers, branches, cibles"),
          ("🕘 Restaurer", "revenir à une copie d'avant écriture"),
          ("↻ Tout recharger", "relire le disque après Desktop ou Excel"),
          ("🚀 Lancements", "afficher ou masquer le journal")]
for i, (h, d) in enumerate(legend):
    y = 1.8 + pic_h + 0.35 + i * 0.62
    badge(s, 6.8, y + 0.02, i + 1, color=REPERE, d=0.34, size=12)
    text(s, 7.3, y, 5.4, 0.6, [[(h + "  ", {"bold": True}), (d, {"color": MUTED, "size": 13})]], size=14)

# ============================================================ 5. Section Mesures
def section(num, t, sub, col, notes):
    s = new_slide(notes)
    text(s, 0.6, 2.3, 3, 1.4, num, size=96, font=HEAD, color=col)
    text(s, 0.6, 3.75, 11, 0.9, t, size=40, font=HEAD, color=TEXT)
    text(s, 0.6, 4.65, 11, 0.8, sub, size=18, color=MUTED)
    return s


section("01", "Les mesures", "Une mesure de base, toutes ses variations : générées, pas écrites.",
        GREEN, "Onglet Mesures : on décrit une variation une seule fois, l'outil l'écrit pour chaque ICP.")

# ============================================================ 6. Diagramme ramification
s = new_slide("Pour chaque mesure du dossier source (_indicateurs), l'outil crée toutes les "
              "variations et range chacune dans son dossier d'affichage, sous le dossier de la base. "
              "Une variation déclarée « branche » (YTD) devient à son tour une base : elle reçoit les "
              "autres variations, rangées sous son propre dossier (__YTD). Les cibles écrites à la main "
              "dans leur dossier (_cibles) sont déclinées de la même façon, rangées sous _cibles.")
title(s, "Comment les variations se ramifient", "Mesures")
W_ = TEXT        # bordure : écrit à la main
# en-têtes des trois zones
for x, t in ((0.45, "1 · pour chaque mesure"),
             (3.35, "2 · l'outil génère les variations"),
             (8.95, "3 · et la range dans les dossiers")):
    text(s, x, 1.5, 4.5, 0.3, t.upper(), size=11, color=GREEN, font=HEAD)

# ---- 1. dossier source : une boucle sur ses mesures
box(s, 0.4, 1.85, 2.6, 4.6, fill=DARK, radius=0.05)
text(s, 0.55, 1.97, 2.4, 0.3, [[("▾ ", {"color": MUTED}), ("_indicateurs", {"font": MONO})]],
     size=13, color=MUTED)
label_box(s, 0.55, 2.32, 2.3, 0.72, "Weight", fill=CARD, line=W_, size=18, bold=True, font=HEAD,
          sub="base · à la main", name="Base")
autres = ["Total Steps", "Average Steps", "Body Fat %", "Average Sleep…"]
for i, t in enumerate(autres):
    text(s, 0.75, 3.14 + i * 0.25, 2.1, 0.25, t, size=11, color=MUTED)
text(s, 0.75, 4.16, 2.1, 0.3, "… chacune reçoit les mêmes variations", size=10, color=MUTED)
text(s, 0.55, 4.62, 2.4, 0.3, [[("▾ ", {"color": MUTED}), ("_cibles", {"font": MONO})]],
     size=13, color=MUTED)
label_box(s, 0.55, 4.97, 2.3, 0.72, "Weight cible", fill=CARD, line=W_, size=17, bold=True,
          font=HEAD, sub="cible · à la main", name="Cible")

# ---- 2. la famille
vars_ = ["Weight 7d avg", "Weight Δ 30d", "Weight PY"]
for i, t in enumerate(vars_):
    y = 1.9 + i * 0.56
    label_box(s, 3.35, y, 2.35, 0.46, t, fill=CARD, line=GREEN, size=13)
    elbow(s, 2.85, 2.68, 3.35, y + 0.23, color=GREEN)
label_box(s, 3.35, 3.6, 2.35, 0.68, "Weight YTD", fill=CARD2, line=BLUE, size=15, bold=True,
          color=BLUE, sub="branche → devient une base", subcolor=BLUE)
elbow(s, 2.85, 2.68, 3.35, 3.94, color=BLUE)
bvars = ["Weight YTD 7d avg", "Weight YTD Δ 30d", "Weight YTD PY"]
for i, t in enumerate(bvars):
    y = 3.0 + i * 0.52
    label_box(s, 6.15, y, 2.45, 0.42, t, fill=CARD, line=GREEN, size=12)
    elbow(s, 5.7, 3.94, 6.15, y + 0.21, color=GREEN)
ct = [("Weight cible YTD", BLUE), ("Weight cible écart", GREEN)]
for i, (t, col) in enumerate(ct):
    y = 4.95 + i * 0.56
    label_box(s, 3.35, y, 2.35, 0.46, t, fill=CARD, line=col, size=13)
    elbow(s, 2.85, 5.33, 3.35, y + 0.23, color=col)
# la formule de l'écart, à côté de SA mesure
arrow(s, 5.75, 5.74, 6.1, 5.74, color=MUTED, w=1.0, dash=True)
text(s, 6.15, 5.5, 2.8, 0.55,
     [[("écart", {"bold": True, "color": GREEN}), (" = {kpiRef} − {baseRef}", {"font": MONO, "size": 11})],
      [("= [Weight] − [Weight cible]", {"font": MONO, "size": 11, "color": MUTED})]], size=12)

# ---- 3. les dossiers d'affichage (displayFolder), comme dans le volet Données
box(s, 8.95, 1.85, 3.95, 4.6, fill=DARK, radius=0.03)
arbo = [  # (niveau, texte, couleur ou None pour un dossier)
    (0, "_indicateurs", None), (1, "Weight", W_),
    (1, "_7d avg", None), (2, "Weight 7d avg", GREEN),
    (1, "_Δ 30d", None), (2, "Weight Δ 30d", GREEN),
    (1, "_PY", None), (2, "Weight PY", GREEN),
    (1, "__YTD", None), (2, "Weight YTD", BLUE),
    (2, "_7d avg", None), (3, "Weight YTD 7d avg", GREEN),
    (2, "_Δ 30d  ·  _PY  …", "…"),
    (0, "_cibles", None), (1, "Weight cible", W_),
    (1, "__YTD", None), (2, "Weight cible YTD", BLUE),
    (1, "_écart", None), (2, "Weight cible écart", GREEN),
]
for i, (niv, t, col) in enumerate(arbo):
    x, y = 9.08 + niv * 0.26, 1.95 + i * 0.226
    if col is None or col == "…":
        text(s, x, y, 3.6, 0.24,
             [[("▸ " if col == "…" else "▾ ", {"color": MUTED}), (t, {"font": MONO, "color": MUTED})]],
             size=11)
    else:
        text(s, x + 0.17, y, 3.4, 0.24, t, size=11, color=col)

# ---- légende + règle des dossiers
y0 = 6.7
for x, col, t in ((0.45, W_, "écrit à la main"), (2.2, GREEN, "variation"),
                  (3.55, BLUE, "branche → devient une base")):
    box(s, x, y0 + 0.04, 0.3, 0.2, fill=CARD, line=col, radius=0.15)
    text(s, x + 0.4, y0, 2.4, 0.3, t, size=12)
text(s, 6.4, y0, 2.5, 0.3, "Un seul niveau de branche.", size=11, color=MUTED)
text(s, 8.95, y0 - 0.06, 3.95, 0.5,
     [[("{baseFolder}\\_{variation}", {"font": MONO})],
      [("{baseFolder}\\__{branch}", {"font": MONO})]], size=10, color=MUTED)

# ============================================================ 7. Paramètres de champ
s = new_slide("Chaque mesure générée devient une rangée des paramètres de champ, étiquetée par "
              "Indicateur, Calcul et Branche. C'est ce qui permet à un segment de choisir ce qu'un visuel affiche. "
              "On a autant de tables qu'il en faut, chacune avec ses réglages, dans ⚙ Réglages → Paramètres de "
              "champ : ce qu'affichent ses rangées (le calcul ou l'ICP), et ce qu'elle garde (ICP, variations, "
              "branches, base, cibles). Une table filtrée garde le même ordre de tri que la complète.")
title(s, "Ce que reçoivent les paramètres de champ", "Mesures")
rows = [("Weight", "Weight", "Réel", "Réel"), ("Weight 7d avg", "Weight", "7d avg", "Réel"),
        ("Weight PY", "Weight", "PY", "Réel"), ("Weight YTD", "Weight", "Réel", "YTD"),
        ("Weight YTD PY", "Weight", "PY", "YTD"), ("Weight cible", "Weight", "Cible", "Réel"),
        ("Weight cible écart", "Weight", "Cible écart", "Réel")]
tbl = s.shapes.add_table(len(rows) + 1, 4, Inches(0.6), Inches(1.8), Inches(7.4), Inches(4.4)).table
heads = ["Mesure générée", "Indicateur", "Calcul", "Branche"]
widths = [2.6, 1.6, 1.8, 1.4]
for j, wd in enumerate(widths):
    tbl.columns[j].width = Inches(wd)
for i in range(len(rows) + 1):
    for j in range(4):
        cell = tbl.cell(i, j)
        cell.fill.solid()
        cell.fill.fore_color.rgb = CARD2 if i == 0 else (CARD if i % 2 else BG)
        val = heads[j] if i == 0 else rows[i - 1][j]
        tf = cell.text_frame
        tf.paragraphs[0].text = ""
        r = tf.paragraphs[0].add_run()
        r.text = val
        r.font.size = Pt(14)
        r.font.name = HEAD if i == 0 else BODY
        r.font.bold = False
        col = GREEN if i == 0 else TEXT
        if i and j == 3 and val == "YTD":
            col = BLUE
        r.font.color.rgb = col
        cell.margin_left = Inches(0.12)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
tblxml = tbl._tbl
tblPr = tblxml.tblPr
for a in ("firstRow", "bandRow"):
    tblPr.set(a, "0")
fams = [("par Calcul", "P_Indicateurs_parCalcul", "1 ICP, plusieurs calculs (page détail)"),
        ("par ICP", "P_Indicateurs_parKPI", "1 calcul, plusieurs ICP (comparaison)"),
        ("filtrée", "P_YTD_seul", "Seulement YTD, sans cibles")]
for i, (h, nm, d) in enumerate(fams):
    y = 1.8 + i * 1.5
    box(s, 8.4, y, 4.3, 1.3, fill=CARD)
    text(s, 8.65, y + 0.12, 3.9, 1.1,
         [[(h, {"bold": True, "color": GREEN, "size": 16})],
          [(nm, {"font": MONO, "size": 11, "color": MUTED})],
          [(d, {"size": 13})]], size=14)
text(s, 0.6, 6.45, 12, 0.6,
     "Autant de tables qu'il en faut, chacune ses réglages (⚙ Réglages). Une fois créée : relier TD_Indicateurs[mesure] → P_xxx[Indicateur].",
     size=13, color=MUTED)

# ============================================================ 8. Jetons
s = new_slide("Les jetons sont remplacés à la génération, pour chaque ICP, cible et branche. Les {jetons} "
              "viennent du modèle et de la variation, en bleu comme dans l'éditeur. Les <<jetons>>, en "
              "vert, viennent de TD_Indicateurs : n'importe quelle colonne, donc une valeur, un nom de "
              "variable ou même du DAX différent par ICP. Dans l'app, « Jetons disponibles » montre ce "
              "que vaut chaque jeton pour l'ICP ou la cible qu'on choisit.")
title(s, "Les jetons à connaître", "Mesures")

# -- {…} : KPI et cible côte à côte --
text(s, 0.6, 1.5, 6.9, 0.3, [[("{…}", {"font": MONO, "color": BLUE, "bold": True}),
                              ("   le modèle et la variation", {"color": MUTED})]], size=14)
X = (0.6, 1.95, 4.05, 5.75)
W_ = (1.35, 2.1, 1.7, 1.75)
for x, t in zip(X[2:], ("Weight YTD", "Weight cible YTD")):
    text(s, x + 0.08, 1.88, 1.7, 0.28, t, size=11, bold=True, color=TEXT)
tok = [("{base}", "la mesure traitée", "Weight YTD", "Weight cible YTD"),
       ("{baseRef}", "la même, en référence", "[Weight YTD]", "[Weight cible YTD]"),
       ("{kpi}", "l'ICP racine", "Weight", "Weight"),
       ("{kpiRef}", "l'ICP, dans la branche", "[Weight YTD]", "[Weight YTD]"),
       ("{branch}", "la branche", "YTD", "YTD"),
       ("{date}", "la colonne de dates", "'dim_Date'[Date]", "'dim_Date'[Date]")]
for i, (t, d, a, b) in enumerate(tok):
    y = 2.2 + i * 0.47
    box(s, 0.6, y, 6.9, 0.42, fill=CARD if i % 2 == 0 else BG, radius=0.12)
    text(s, X[0] + 0.1, y, W_[0], 0.42, t, size=12, font=MONO, color=BLUE, anchor=MSO_ANCHOR.MIDDLE)
    text(s, X[1] + 0.05, y, W_[1], 0.42, d, size=11.5, anchor=MSO_ANCHOR.MIDDLE)
    text(s, X[2] + 0.08, y, W_[2], 0.42, a, size=10, font=MONO, color=MUTED, anchor=MSO_ANCHOR.MIDDLE)
    diff = a != b
    text(s, X[3] + 0.08, y, W_[3], 0.42, b, size=10, font=MONO, color=BLUE if diff else MUTED,
         bold=diff, anchor=MSO_ANCHOR.MIDDLE)

# -- <<…>> : n'importe quelle colonne --
box(s, 7.8, 1.5, 4.9, 3.55, fill=CARD2, line=GREEN, lw=1.25, radius=0.04)
text(s, 8.05, 1.62, 4.45, 0.62,
     [[("<<colonne>>", {"font": MONO, "color": GREEN, "bold": True, "size": 15})],
      [("n'importe quelle colonne de TD_Indicateurs", {"size": 12.5, "bold": True})],
      [("à ajouter dans Variations → Jetons disponibles…", {"size": 10, "color": MUTED})]],
     size=13)
usages = [("une valeur", "* <<direction>>", "* 1   ou   * -1"),
          ("un texte", "& \" <<unite>>\"", "& \" kg\"   ou   & \" pas\""),
          ("un nom de variable", "VAR <<var_nom>> = …", "VAR _poids = …"),
          ("du DAX propre à l'ICP", "<<agregat>>", "AVERAGEX(…)   ou   SUMX(…)")]
for i, (u, ecrit, donne) in enumerate(usages):
    y = 2.5 + i * 0.63
    text(s, 8.05, y, 4.5, 0.6,
         [[(u, {"size": 11, "color": MUTED})],
          [(ecrit, {"font": MONO, "size": 11, "color": GREEN}),
           ("  →  ", {"size": 10, "color": MUTED}),
           (donne, {"font": MONO, "size": 10, "color": TEXT})]], size=11)

# -- des filtres propres à chaque KPI : un attribut comme un autre --
box(s, 0.6, 5.2, 12.1, 1.05, fill=CARD, radius=0.06)
text(s, 0.85, 5.36, 4.0, 0.9,
     [[("Des filtres par ICP", {"bold": True, "size": 14})],
      [("la colonne filtres porte ceux de chaque ICP", {"size": 11, "color": MUTED})]], size=13)
text(s, 4.85, 5.3, 7.7, 0.9,
     [[("CALCULATE({baseRef}, ", {"color": BLUE, "bold": True, "size": 12}),
       ("<<filtres>>", {"color": GREEN, "bold": True, "size": 12}),
       (")", {"color": BLUE, "bold": True, "size": 12})],
      [("Weight        ", {"color": MUTED}), ("ALLSELECTED('Weight LOCF')", {})],
      [("Total Steps   ", {"color": MUTED}), ("ALLSELECTED('steps'), ALLSELECTED('dim_Date')", {})]],
     size=10.5, font=MONO)

box(s, 0.6, 6.4, 12.1, 0.55, fill=CARD2)
text(s, 0.85, 6.4, 11.6, 0.55,
     [[("Dans l'app : ", {"bold": True, "color": GREEN}),
       ("Variations → Jetons disponibles… Choisir un ICP ou une cible : chaque jeton "
        "affiche sa valeur et où il se règle.", {})]],
     size=13, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 9. Éditer une variation
s = new_slide("Une variation = un gabarit de mesure. On l'écrit une fois ; l'aperçu à droite "
              "montre exactement les noms qui seront générés, en couleur : ICP, + branche, + variation.")
title(s, "Éditer une variation", "Mesures › Variations")
p, (iw, ih) = crop("onglet_mesures", (0, 82, 1240, 857), "mesures")
pw = 8.6
picture(s, p, 0.6, 1.65, w=pw)
sx = pw / iw
marks = [(30, 50), (380, 50), (380, 315), (830, 50), (830, 505)]
for n, (px, py) in enumerate(marks, start=1):
    badge(s, 0.6 + px * sx - 0.05, 1.65 + py * sx - 0.12, n, color=REPERE, d=0.36, size=12)
items = [("Les variations", "Ajouter, dupliquer, réordonner. Bibliothèque… pour en importer."),
         ("Mesure générée", "Nom ({base} 7d avg), format, dossier."),
         ("Portée", "Pour les ICP, les cibles ; types de base ; exclusions par nom."),
         ("DAX", "Écrit en clair, jetons colorés ; rouge = jeton inconnu."),
         ("Aperçu des noms", "Ce qui sera généré, avant de générer.")]
step_list(s, 9.5, 1.7, 3.3, items, gap=0.98, size=14, color=REPERE)
text(s, 0.6, 1.65 + ih * sx + 0.15, pw, 0.4, "Sauvegarder écrit le measures_config.json (copie .bak gardée).",
     size=12, color=MUTED)

# ============================================================ 10. Générer
s = new_slide("La génération écrit directement les fichiers TMDL du modèle. "
              "Elle est idempotente : relancer sans changement n'écrit rien.")
title(s, "Générer les mesures", "Mesures › Lancements")
p, (iw, ih) = crop("onglet_mesures_generation", (1248, 0, 1700, 310), "generation")
picture(s, p, 8.0, 1.75, w=4.7)
text(s, 8.0, 1.75 + 4.7 * ih / iw + 0.15, 4.7, 0.8,
     "Le panneau de génération, en tête du journal (bouton « Lancements »).", size=12, color=MUTED)
gen = [("Sauvegarder le config", "Le générateur lit le fichier, pas l'éditeur. Il le propose au besoin."),
       ("Enregistrer dans Desktop", "S'il est ouvert. Il peut le rester pendant l'écriture."),
       ("Aperçu (dry-run) → Générer", "Lire le journal : créées, mises à jour, ignorées, orphelines."),
       ("Décocher Aperçu → Générer", "Écriture réelle, sauvegarde automatique du modèle."),
       ("Fermer Desktop sans enregistrer, rouvrir", "Les mesures et les paramètres de champ sont là.")]
step_list(s, 0.6, 1.8, 7.0, gen, gap=0.92, size=16)

# ============================================================ 11. Section Rapport
section("02", "Le rapport", "Formater un ICP à la main dans Desktop : l'outil recopie sur tous les autres.",
        BLUE, "Onglet Rapport : le formatage conditionnel d'un paramètre de champ est attaché à une mesure "
              "précise ; sans propagation, il disparaît quand on change d'ICP.")

# ------------------------------------------------------------ visuels dessinés
# Un graphique en courbes, une carte et une grille, dessinés en formes
# PowerPoint (pas de capture) : on y montre des réglages précis, et ce
# qu'ils deviennent. Les exemples de groupes et de règles viennent de
# propagate_cf.Sources : ce que la grille afficherait, pas une invention.

YELLOW = RGBColor(0xF2, 0xC9, 0x4C)
VIOLET = RGBColor(0xA9, 0x8B, 0xF0)      # une couleur « par défaut » de Power BI


def melange(c, a=0.3, fond=CARD):
    """La couleur `c` posée à l'opacité `a` sur `fond`."""
    return RGBColor(*(int(fond[i] + (c[i] - fond[i]) * a) for i in range(3)))


def segment(slide, x1, y1, x2, y2, color=LINE, w=0.75, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1),
                                   Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(w)
    if dash:
        c.line.dash_style = MSO_LINE.DASH
    return c


def courbe(slide, pts, x, y, w, h, color, width=2.0, dash=False, marqueurs=False, dm=0.1):
    """Une polyligne ; pts en coordonnées 0..1 (v vers le haut) dans le cadre
    (x, y, w, h)."""
    def xy(u, v):
        return Inches(x + u * w), Inches(y + (1 - v) * h)
    x0, y0 = xy(*pts[0])
    ff = slide.shapes.build_freeform(x0, y0)
    ff.add_line_segments([xy(u, v) for u, v in pts[1:]], close=False)
    sh = ff.convert_to_shape()
    sh.fill.background()
    sh.line.color.rgb = color
    sh.line.width = Pt(width)
    if dash:
        sh.line.dash_style = MSO_LINE.DASH
    sh.shadow.inherit = False
    if marqueurs:
        for u, v in pts:
            box(slide, x + u * w - dm / 2, y + (1 - v) * h - dm / 2, dm, dm, fill=CARD,
                line=color, shape=MSO_SHAPE.OVAL, lw=1.0)
    return sh


def puce(slide, x, y, n, d=0.3, color=GREEN, size=11):
    badge(slide, x, y, n, color=color, d=d, size=size)


def graphique(slide, x, y, w, h, kpi=None, style=True, decal=0.0, cadre=LINE, mini=False,
              puces=False):
    """Le graphique en courbes du rapport : YTD et YTD PY d'un KPI. `style` :
    les réglages du gabarit (① marqueurs sur YTD, ② pointillé coloré sur
    YTD PY), sinon les défauts de Power BI. `mini` : sans légende ni mois."""
    box(slide, x, y, w, h, fill=CARD, line=cadre, radius=0.04)
    if kpi:
        text(slide, x + 0.15, y + 0.08, w - 0.3, 0.3, kpi, size=11 if mini else 13,
             bold=True, font=HEAD)
    c_ytd, c_py = (GREEN, ORANGE) if style else (BLUE, VIOLET)
    if not mini:
        lx, ly = x + w - 1.45, y + 0.2
        segment(slide, lx, ly, lx + 0.28, ly, color=c_ytd, w=2)
        if style:
            box(slide, lx + 0.09, ly - 0.05, 0.1, 0.1, fill=CARD, line=c_ytd, shape=MSO_SHAPE.OVAL)
        text(slide, lx + 0.33, ly - 0.09, 0.4, 0.2, "YTD", size=8, color=MUTED)
        segment(slide, lx + 0.72, ly, lx + 1.0, ly, color=c_py, w=1.25 if style else 2, dash=style)
        text(slide, lx + 1.05, ly - 0.09, 0.45, 0.2, "PY", size=8, color=MUTED)
    if mini:
        px, py, pw, ph = x + 0.2, y + (0.42 if kpi else 0.1), w - 0.35, h - (0.55 if kpi else 0.2)
    else:
        px, py, pw, ph = x + 0.3, y + 0.55, w - 0.5, h - 0.95
    for f in (0.0, 0.5):
        segment(slide, px, py + ph * f, px + pw, py + ph * f, color=LINE, w=0.5)
    segment(slide, px, py + ph, px + pw, py + ph, color=MUTED, w=0.75)
    if not mini:
        for u, m in ((0.0, "janv."), (0.5, "avr."), (1.0, "juil.")):
            text(slide, px + u * pw - 0.25, py + ph + 0.04, 0.5, 0.2, m, size=8, color=MUTED,
                 align=PP_ALIGN.CENTER)
    us = [i / 6 for i in range(7)]
    ytd = [0.08, 0.22, 0.35, 0.49, 0.62, 0.78, 0.92]
    pyv = [0.06, 0.16, 0.30, 0.40, 0.50, 0.62, 0.74]
    ytd = [min(0.97, v + decal * (i % 2)) for i, v in enumerate(ytd)]
    courbe(slide, list(zip(us, pyv)), px, py, pw, ph, c_py,
           width=1.25 if style else (1.5 if mini else 2.0), dash=style)
    courbe(slide, list(zip(us, ytd)), px, py, pw, ph, c_ytd,
           width=(1.75 if mini else 2.25) if style else (1.5 if mini else 2.0),
           marqueurs=style, dm=0.07 if mini else 0.1)
    if puces:
        d = 0.22 if mini else 0.3
        puce(slide, px + pw - 0.45 - d, py + (1 - ytd[-1]) * ph - d - 0.02, 1, d=d,
             size=9 if mini else 11)
        puce(slide, px + pw - d / 2, py + (1 - pyv[-1]) * ph + 0.04, 2, d=d,
             size=9 if mini else 11)
    return (px, py, pw, ph, ytd, pyv)


def sparkline(slide, x, y, w, h, color=GREEN):
    box(slide, x, y, w, h, fill=DARK, radius=0.1)
    courbe(slide, [(0, 0.3), (0.2, 0.55), (0.4, 0.4), (0.6, 0.7), (0.8, 0.6), (1, 0.85)],
           x + 0.06, y + 0.06, w - 0.12, h - 0.12, color, width=1.25)


def tuile(slide, x, y, w, h, kpi, valeur, ref1=None, ref2=None, detail="", monte=True,
          cadre=LINE, forme=True):
    """Une tuile de carte, compacte. `forme` : le style du gabarit (valeur en
    gras, image, deux étiquettes de référence et un détail) ; sinon ce que
    Power BI montre sans lui : la valeur, et rien d'autre."""
    box(slide, x, y, w, h, fill=CARD, line=cadre, radius=0.05)
    text(slide, x + 0.15, y + 0.1, w - 1.1, 0.25, kpi, size=10, color=MUTED)
    if not forme:
        text(slide, x + 0.15, y + 0.35, w - 0.3, 0.45, valeur, size=18, font=BODY,
             color=MUTED)
        text(slide, x + 0.15, y + h - 0.42, w - 0.3, 0.3,
             "ni étiquettes, ni détail, ni image", size=9, color=melange(MUTED, 0.6),
             font=BODY)
        return None
    text(slide, x + 0.15, y + 0.32, w - 1.1, 0.45, valeur, size=20, bold=True, font=HEAD)
    sparkline(slide, x + w - 0.95, y + 0.14, 0.8, 0.45)
    ylig = y + 0.85
    segment(slide, x + 0.15, ylig, x + w - 0.15, ylig, color=LINE)
    yr = ylig + 0.07
    col_w = (w - 0.3) / 2
    for i, (titre_r, val_r) in enumerate((ref1, ref2)):
        xx = x + 0.15 + i * col_w
        text(slide, xx, yr, col_w, 0.22, titre_r, size=9, color=MUTED)
        text(slide, xx, yr + 0.18, col_w, 0.28, val_r, size=11, bold=True)
    text(slide, x + 0.15, yr + 0.44, col_w + 0.4, 0.25, detail, size=9,
         color=GREEN if monte else RED)
    return ylig, yr, col_w


# ============================================================ 12a. Graphique : pour chaque KPI cible
s = new_slide("Le gabarit, Total Steps, est formaté à la main dans Desktop : ① les marqueurs, sur la "
              "série « Total Steps YTD », ② le pointillé coloré, sur « Total Steps YTD PY ». Chaque "
              "réglage vise UNE mesure. Propager prend ces réglages et les recopie, dans le même "
              "visuel, pour CHAQUE ICP cible : Weight, Body Fat %, Average Steps… En dessous, ce qui "
              "arrive sans propagation : le segment passe à Weight, les réglages visent toujours "
              "les mesures de Total Steps, et Weight s'affiche avec les défauts de Power BI.")
title(s, "Comment le formatage se propage", "Rapport")
text(s, 0.6, 1.42, 12.1, 0.4,
     [[("Propager prend les réglages du gabarit et les recopie ", {}),
       ("sur chaque ICP cible", {"bold": True}), (", dans le même visuel.", {})]],
     size=15, color=MUTED)
text(s, 0.6, 1.95, 4, 0.3, "1 · LE GABARIT, FORMATÉ À LA MAIN", size=11, color=GREEN, font=HEAD)
text(s, 6.2, 1.95, 6.5, 0.3, "2 · LES MÊMES RÉGLAGES, SUR CHAQUE ICP CIBLE", size=11,
     color=GREEN, font=HEAD)

# 1. le gabarit
gx, gy, gw, gh = 0.6, 2.3, 3.85, 2.25
graphique(s, gx, gy, gw, gh, "Total Steps", style=True, cadre=GREEN, puces=True)
for i, (attr, mesure) in enumerate((("marqueurs, bordure", "[Total Steps YTD]"),
                                     ("couleur, pointillé, 1 px", "[Total Steps YTD PY]"))):
    yy = 4.72 + i * 0.5
    puce(s, 0.6, yy, i + 1, d=0.28)
    text(s, 0.98, yy - 0.04, 3.5, 0.5,
         [[(attr + "  ", {"size": 12}), ("sur ", {"size": 10, "color": MUTED}),
           (mesure, {"size": 10, "font": MONO, "color": GREEN})]], size=12)

# Propager : pour chaque
fl = box(s, 4.65, 2.3, 1.35, 3.25, fill=GREEN, shape=MSO_SHAPE.RIGHT_ARROW)
fl.adjustments[0] = 0.62
fl.adjustments[1] = 0.32
text(s, 4.68, 2.3, 1.0, 3.25,
     [[("Propager", {"bold": True, "size": 14, "font": HEAD})],
      [("", {"size": 6})],
      [("pour", {"size": 11})], [("chaque", {"size": 11})], [("ICP cible", {"size": 11})],
      [("", {"size": 6})],
      [("① ② copiés", {"size": 10})]],
     size=11, color=DARK, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# 2. les cibles
cibles = [("Weight", 0.03), ("Body Fat %", -0.02), ("Average Steps", 0.04),
          ("Average Sleep Duration", 0.0)]
for i, (k, dec) in enumerate(cibles):
    x = 6.2 + (i % 2) * 3.3
    y = 2.3 + (i // 2) * 1.65
    graphique(s, x, y, 3.15, 1.55, k, style=True, decal=dec, cadre=GREEN if i == 0 else LINE,
              mini=True, puces=True)
lbl = label_box(s, 6.2 + 0.85, 2.38, 1.05, 0.24, "← le segment", fill=GREEN,
                color=DARK, size=9, bold=True)

# la boucle, en clair
box(s, 0.6, 5.72, 12.1, 0.5, fill=CARD2)
text(s, 0.85, 5.72, 11.6, 0.5,
     [[("pour chaque ICP cible K :   ", {"font": BODY, "bold": True, "color": GREEN, "size": 13}),
       ("① [Total Steps YTD] → [K YTD]", {}), ("      ", {}),
       ("② [Total Steps YTD PY] → [K YTD PY]", {})]],
     size=12, font=MONO, color=TEXT, anchor=MSO_ANCHOR.MIDDLE)

# sans propagation
box(s, 0.6, 6.35, 12.1, 0.72, fill=CARD, line=melange(RED, 0.6, BG))
graphique(s, 0.72, 6.43, 1.35, 0.56, None, style=False, decal=0.03, mini=True)
text(s, 2.25, 6.35, 10.3, 0.72,
     [[("Sans propagation", {"bold": True, "color": RED}),
       (" : le segment passe à Weight, mais les réglages visent toujours ", {}),
       ("[Total Steps YTD]", {"font": MONO, "size": 11, "color": ORANGE}), (" et ", {}),
       ("[Total Steps YTD PY]", {"font": MONO, "size": 11, "color": ORANGE}),
       (". Weight s'affiche avec les défauts de Power BI.", {})]],
     size=12, color=TEXT, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 12b. La carte
s = new_slide("Une carte montre plusieurs ICP, une tuile chacun. Avant : seule la tuile Weight, le "
              "gabarit, est formatée ; Total Steps et Body Fat % n'ont que leur valeur. Les réglages "
              "d'une tuile visent SA mesure, et ce qu'ils affichent (la valeur d'une étiquette, son "
              "détail, l'image) sont eux aussi des mesures de l'ICP. Propager réécrit les deux, pour "
              "chaque tuile. Après : la même carte, chaque tuile formatée avec ses propres mesures.")
title(s, "La carte se propage aussi", "Rapport")
text(s, 0.6, 1.42, 12.1, 0.4,
     [[("Chaque tuile est un ICP. Ses étiquettes, son détail et son image sont ", {}),
       ("des mesures de cet ICP", {"bold": True}), (" : elles changent avec lui.", {})]],
     size=15, color=MUTED)

CW = 2.42                                   # largeur d'une tuile
VALEURS = [("Weight", "72,4 kg", ("PY", "71,8"), ("Δ 30d", "−0,6"), "▲ 0,8 % YoY", True),
           ("Total Steps", "312 480", ("PY", "298 150"), ("Δ 30d", "+4 210"), "▲ 4,8 % YoY", True),
           ("Body Fat %", "21,3 %", ("PY", "22,1 %"), ("Δ 30d", "−0,4"), "▼ 3,6 % YoY", False)]


def carte(slide, y, entete, apres):
    text(slide, 0.6, y - 0.32, 7.9, 0.3, entete, size=11, color=GREEN, font=HEAD)
    box(slide, 0.6, y, 7.9, 1.86, fill=DARK, line=LINE, radius=0.04)
    for i, (k, val, r1, r2, det, monte) in enumerate(VALEURS):
        x = 0.72 + i * (CW + 0.12)
        forme = apres or i == 0
        res = tuile(slide, x, y + 0.1, CW, 1.66, k, val, r1, r2, det, monte,
                    cadre=GREEN if (apres or i == 0) else LINE, forme=forme)
        if i == 0 and not apres:
            ylig, yr, col_w = res
            d = 0.22
            puce(slide, x + 0.15 + 0.22, yr - 0.02, 2, d=d, size=9)            # titre
            puce(slide, x + 0.15 + 0.5, yr + 0.2, 1, d=d, size=9)              # valeur PY
            puce(slide, x + 0.15 + col_w + 0.5, yr + 0.2, 1, d=d, size=9)      # valeur Δ 30d
            puce(slide, x + 0.15 + 1.05, yr + 0.45, 3, d=d, size=9)            # détail
            puce(slide, x + CW - 0.27, y + 0.1 + 0.05, 4, d=d, size=9)         # image


carte(s, 2.25, "1 · AVANT : SEUL LE GABARIT, WEIGHT, EST FORMATÉ", False)
carte(s, 4.55, "3 · APRÈS PROPAGER : CHAQUE TUILE, SES PROPRES MESURES", True)
fl = box(s, 6.45, 4.12, 0.6, 0.42, fill=GREEN, shape=MSO_SHAPE.DOWN_ARROW)
text(s, 7.12, 4.13, 1.4, 0.4, "Propager", size=13, bold=True, font=HEAD, color=GREEN,
     anchor=MSO_ANCHOR.MIDDLE)

# 2. ce qui est réécrit, pour chaque tuile
bx, bw = 8.85, 3.85
text(s, bx, 1.93, bw, 0.3, "2 · CE QUE PROPAGER RÉÉCRIT", size=11, color=GREEN, font=HEAD)
box(s, bx, 2.25, bw, 4.16, fill=CARD2)
text(s, bx + 0.2, 2.36, bw - 0.3, 0.3,
     [[("pour chaque tuile K", {"bold": True, "color": GREEN}),
       ("  (Total Steps, Body Fat %)", {"color": MUTED, "size": 10})]], size=12)
lignes = [
    (None, "la tuile visée", [("[Weight]", "[K]")]),
    (1, "étiquettes : valeur", [("[Weight PY]", "[K PY]"), ("[Weight Δ 30d]", "[K Δ 30d]")]),
    (2, "étiquette : titre", [("« PY »", None)]),
    (3, "détail", [("[Weight YoY %]", "[K YoY %]")]),
    (4, "image", [("[Weight sparkline]", "[K sparkline]")]),
]
yy = 2.78
for n, attr, paires in lignes:
    if n:
        puce(s, bx + 0.15, yy + 0.01, n, d=0.26)
    text(s, bx + 0.52, yy, bw - 0.6, 0.25, attr, size=11, bold=True)
    yy += 0.26
    for avant, apres in paires:
        if apres is None:
            text(s, bx + 0.52, yy, bw - 0.6, 0.22,
                 [[(avant, {"font": MONO}), ("  un texte : recopié tel quel", {"color": MUTED})]],
                 size=10)
        else:
            text(s, bx + 0.52, yy, bw - 0.6, 0.22,
                 [[(avant, {"color": MUTED}), ("  →  ", {"color": MUTED}), (apres, {"color": GREEN})]],
                 size=10.5, font=MONO)
        yy += 0.23
    yy += 0.14

box(s, 0.6, 6.6, 12.1, 0.5, fill=CARD2)
text(s, 0.85, 6.6, 11.6, 0.5,
     [[("Un miroir : ", {"bold": True, "color": GREEN}),
       ("ce que le gabarit ne porte plus est retiré des autres tuiles (retirer l'image de Weight "
        "la retire partout). Le détail a sa propre colonne dans la grille des sources.", {})]],
     size=12, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 12c. Gabarits et groupes
s = new_slide("Exemple à dix ICP, en trois ensembles. Le gabarit de base, Average Steps, est formaté en "
              "entier ; les ICP sans groupe le copient. Le groupe Sommeil a son gabarit, Average "
              "Sleep Duration : il reçoit d'abord la base, puis ses propres réglages l'emportent, "
              "réglage par réglage (ici ②, la couleur) ; ses ICP copient le résultat. Le groupe Poids "
              "est indépendant : son gabarit, Weight, ne reçoit rien de la base.")
title(s, "Qui copie qui : gabarits et groupes", "Rapport")
text(s, 0.6, 1.42, 12.1, 0.4,
     [[("Chaque ICP copie ses réglages d'un gabarit. Un groupe a le sien, ", {}),
       ("posé par-dessus la base", {"bold": True}), (" : réglage par réglage, le sien l'emporte.", {})]],
     size=15, color=MUTED)

ORIG = {"base": GREEN, "sommeil": BLUE, "poids": ORANGE}


def puces_origine(slide, x, y, origines):
    for i, o in enumerate(origines):
        c = box(slide, x + i * 0.34, y, 0.28, 0.28, fill=ORIG[o], radius=0.2)
        tf = c.text_frame
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p_ = tf.paragraphs[0]
        p_.alignment = PP_ALIGN.CENTER
        r = p_.add_run()
        r.text = str(i + 1)
        r.font.size = Pt(10)
        r.font.bold = True
        r.font.name = HEAD
        r.font.color.rgb = DARK


def famille(slide, y, tag, gabarit, sous, couleur, origines, membres, note=None):
    text(slide, 0.6, y - 0.3, 3.5, 0.28, tag, size=10, color=couleur, font=HEAD)
    box(slide, 0.6, y, 3.2, 0.95, fill=CARD2, line=couleur, lw=1.5)
    text(slide, 0.78, y + 0.07, 2.9, 0.3, gabarit, size=13, bold=True, font=HEAD, color=couleur)
    text(slide, 0.78, y + 0.33, 2.9, 0.25, sous, size=9.5, color=MUTED)
    puces_origine(slide, 0.78, y + 0.6, origines)
    yc, ybus = y + 0.47, y - 0.13
    xs = [4.55 + i * 2.72 for i in range(len(membres))]
    segment(slide, 3.8, yc, 4.2, yc, color=couleur, w=1.5)
    segment(slide, 4.2, yc, 4.2, ybus, color=couleur, w=1.5)
    segment(slide, 4.2, ybus, xs[-1] + 1.25, ybus, color=couleur, w=1.5)
    for x, m in zip(xs, membres):
        arrow(slide, x + 1.25, ybus, x + 1.25, y, color=couleur, w=1.5)
        box(slide, x, y, 2.5, 0.95, fill=CARD)
        text(slide, x + 0.18, y + 0.1, 2.2, 0.3, m, size=13, bold=True)
        puces_origine(slide, x + 0.18, y + 0.55, origines)
    if note:
        text(slide, 3.95, y - 0.3, 2.8, 0.28, note, size=10, color=MUTED)


famille(s, 2.25, "SANS GROUPE", "Average Steps", "gabarit de base · à la main", GREEN,
        ["base"] * 3, ["Total Steps", "Calories", "Active Minutes"])
famille(s, 3.85, "GROUPE SOMMEIL", "Average Sleep Duration", "gabarit du groupe · ② à la main",
        BLUE, ["base", "sommeil", "base"], ["Sleep Score", "Time in Bed"])
arrow(s, 3.55, 3.2, 3.55, 3.85, color=GREEN, dash=True)
text(s, 1.95, 3.38, 1.53, 0.25, "reçoit d'abord la base", size=9, color=MUTED, align=PP_ALIGN.RIGHT)
famille(s, 5.45, "GROUPE POIDS · INDÉPENDANT", "Weight", "gabarit du groupe · ①②③ à la main",
        ORANGE, ["poids"] * 3, ["Body Fat %", "BMI"])
text(s, 9.95, 5.45, 2.75, 0.95, "Indépendant : son gabarit ne reçoit rien de la base. Tout "
     "vient de Weight.", size=11, color=MUTED, anchor=MSO_ANCHOR.MIDDLE)

box(s, 0.6, 6.6, 12.1, 0.55, fill=CARD2)
text(s, 0.85, 6.6, 11.7, 0.55,
     [[("Réglages du Réel : ", {"bold": True}), ("① marqueurs  ② couleur de la série  ③ épaisseur", {}),
       ("      couleur = d'où il vient : ", {"color": MUTED}),
       ("base", {"bold": True, "color": GREEN}), ("  ·  ", {"color": MUTED}),
       ("gabarit Sommeil", {"bold": True, "color": BLUE}), ("  ·  ", {"color": MUTED}),
       ("gabarit Poids", {"bold": True, "color": ORANGE})]],
     size=12, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 12d. Qui l'emporte, variation par variation
s = new_slide("La grille des sources décide case par case : pour cet ICP et cette variation, de qui "
              "copier. Une colonne, ce sont les réglages qui visent les mesures de cette variation : "
              "le PY, c'est la série pointillée. Les mêmes dix ICP : « Tous les ICP » donne le PY de "
              "Total Steps à tout le monde, les groupes le recevant par leur gabarit (sauf Poids, "
              "indépendant) ; le groupe Sommeil prend son YoY % de Weight ; Calories garde son "
              "YoY % à la main. Ces cases sont celles que calcule l'outil.")
title(s, "Qui l'emporte, variation par variation", "Rapport")
text(s, 0.6, 1.42, 12.1, 0.4,
     [[("Une case = un ICP × une variation : ", {}), ("de qui copier", {"bold": True}),
       (". Une colonne = les réglages qui visent cette variation.", {})]],
     size=15, color=MUTED)

YELLOW = VIOLET      # Total Steps : distinct de Weight (orange) une fois fondu
COLS = [("Réel", "la série, ses marqueurs"), ("PY", "la série pointillée"),
        ("YoY %", "l'étiquette YoY %")]
# (libellé, est-ce une ligne de règle, [cases]) ; une case = (texte, couleur, gras)
G, A = "Gabarit", "À la main"
LIGNES = [
    ("Tous les ICP", True, [None, ("Total Steps", YELLOW, True), None]),
    ("Average Steps · base", False, [(G, GREEN, True), ("Total Steps", YELLOW, False),
                                     (G, GREEN, True)]),
    ("Total Steps", False, [("Average Steps", GREEN, False), (G, YELLOW, True),
                            ("Average Steps", GREEN, False)]),
    ("Calories", False, [("Average Steps", GREEN, False), ("Total Steps", YELLOW, False),
                         (A, MUTED, True)]),
    ("Active Minutes", False, [("Average Steps", GREEN, False), ("Total Steps", YELLOW, False),
                               ("Average Steps", GREEN, False)]),
    ("Groupe Sommeil", True, [None, None, ("Weight", ORANGE, True)]),
    ("Average Sleep Duration", False, [("Gabarit, sur la base", BLUE, True),
                                       ("Gabarit, sur Total Steps", BLUE, True),
                                       ("Weight", ORANGE, False)]),
    ("Sleep Score", False, [("Avg Sleep Duration", BLUE, False),
                            ("Avg Sleep Duration", BLUE, False), ("Weight", ORANGE, False)]),
    ("Time in Bed", False, [("Avg Sleep Duration", BLUE, False),
                            ("Avg Sleep Duration", BLUE, False), ("Weight", ORANGE, False)]),
    ("Groupe Poids · indép.", True, [None, None, None]),
    ("Weight", False, [(G, ORANGE, True), ("Total Steps", YELLOW, False), (G, ORANGE, True)]),
    ("Body Fat %", False, [("Weight", ORANGE, False), ("Total Steps", YELLOW, False),
                           ("Weight", ORANGE, False)]),
    ("BMI", False, [("Weight", ORANGE, False), ("Total Steps", YELLOW, False),
                    ("Weight", ORANGE, False)]),
]
x0, wk, wv = 0.6, 2.3, 1.8
y0, hh, hr = 1.95, 0.5, 0.335
for j, (v, sous) in enumerate(COLS):
    xx = x0 + wk + j * wv
    box(s, xx, y0, wv - 0.04, hh - 0.04, fill=CARD2, shape=MSO_SHAPE.RECTANGLE)
    text(s, xx + 0.08, y0 + 0.03, wv - 0.16, 0.45,
         [[(v, {"bold": True, "size": 12})], [(sous, {"size": 8.5, "color": MUTED})]],
         size=12, align=PP_ALIGN.CENTER)
for i, (lib, regle, cases) in enumerate(LIGNES):
    yy = y0 + hh + i * hr
    text(s, x0 + (0.05 if regle else 0.18), yy, wk - 0.2, hr, lib, size=10,
         bold=regle, color=MUTED if regle else TEXT, anchor=MSO_ANCHOR.MIDDLE)
    if regle:
        segment(s, x0, yy, x0 + wk + 3 * wv - 0.04, yy, color=LINE, w=0.75)
    for j, c in enumerate(cases):
        xx = x0 + wk + j * wv
        if c is None:
            if regle:
                continue
            c = ("", CARD, False)
        t, col, gras = c
        fond = melange(col, 0.36) if not regle else CARD2
        box(s, xx, yy + 0.02, wv - 0.04, hr - 0.04, fill=fond,
            line=col if regle else None, shape=MSO_SHAPE.RECTANGLE, lw=1.25)
        text(s, xx + 0.05, yy, wv - 0.1, hr, t, size=8.5 if len(t) > 18 else 9.5, bold=gras,
             color=col if regle else TEXT, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# l'échelle
lx, lw_ = 8.6, 4.1
text(s, lx, 1.95, lw_, 0.3, "QUI L'EMPORTE, DU PLUS FORT AU PLUS FAIBLE", size=11, color=GREEN,
     font=HEAD)
echelle = [
    ("La case", "Calories · YoY % : à la main."),
    ("Le groupe, pour une variation", "Sommeil · YoY % : copie Weight."),
    ("Tous les ICP, pour une variation", "PY : copie Total Steps. Un groupe le reçoit par son "
                                         "gabarit, sauf s'il est indépendant (Poids)."),
    ("Le gabarit du groupe", "Sleep Score : copie Average Sleep Duration."),
    ("Le gabarit de base", "Tout le reste : copie Average Steps."),
]
yy = 2.35
for i, (h_, d_) in enumerate(echelle):
    puce(s, lx, yy, i + 1, d=0.32)
    text(s, lx + 0.45, yy - 0.04, lw_ - 0.45, 0.85,
         [[(h_, {"bold": True, "size": 12})], [(d_, {"size": 10.5, "color": MUTED})]], size=12)
    yy += 0.88
text(s, lx, 6.85, lw_, 0.3, "Une case en gras : une règle posée là, ou un gabarit.", size=9.5,
     color=MUTED)

# ============================================================ 13. Grille des sources
s = new_slide("La grille dit, case par case, de quel ICP chaque ICP copie chaque variation. "
              "Sélectionner des cases (clic-glisser, ou un en-tête), choisir « Copier depuis », Appliquer, Enregistrer.")
title(s, "La grille des sources", "Rapport › Grille des sources…")
p, (iw, ih) = crop("grille_sources", (0, 85, 1500, 820), "grille")
pw = 8.4
picture(s, p, 0.6, 1.7, w=pw)
leg = [("Lignes = ICP, colonnes = variations", "Les groupes et « Tous les ICP » en tête."),
       ("Gabarit", "Formaté à la main dans Desktop, copié par les autres."),
       ("Un nom", "La case copie cet ICP (en gras : règle posée sur cette ligne)."),
       ("À la main", "Rien n'est copié dans cette case."),
       ("Enregistrer", "propagation.json, partagé par les rapports du dossier.")]
step_list(s, 9.3, 1.75, 3.5, leg, gap=0.95, size=14, color=BLUE)

# ============================================================ 14. Propager & colorer
s = new_slide("Propager clone le formatage ; Colorer applique les couleurs par ICP de TD_Indicateurs "
              "aux matrices qui l'ont demandé. « Propager puis colorer » enchaîne les deux.")
title(s, "Propager et colorer", "Rapport")
p, (iw, ih) = crop("onglet_rapport", (0, 82, 1240, 499), "rapport")
picture(s, p, 0.6, 1.75, w=7.4)
prop = [("Formater le gabarit dans Desktop", "Puis enregistrer. Desktop peut rester ouvert."),
        ("Vérifier la grille des sources", "Qui copie quoi, groupes compris."),
        ("Aperçu → Propager", "Le journal liste chaque clone ; « Verbeux » pour le détail."),
        ("Décocher Aperçu → Propager", "Puis fermer Desktop sans enregistrer, et rouvrir."),
        ("Colorer (optionnel)", "Couleurs fond/texte par ICP, lues dans TD_Indicateurs.")]
step_list(s, 8.45, 1.8, 4.3, prop, gap=0.92, size=14, color=BLUE)
text(s, 0.6, 1.75 + 7.4 * ih / iw + 0.2, 7.4, 0.8,
     [[("Le gabarit est maître : ", {"bold": True, "color": GREEN}),
       ("on corrige toujours le gabarit, jamais un clone : il serait remplacé au prochain passage.", {})]],
     size=14)

# ============================================================ 15. Outils complémentaires
s = new_slide("ChopChop liste ce qui ne sert plus : ni visuel, ni autre mesure, ni autre requête. "
              "Dans cette version, il analyse et exporte : le ménage se fait ensuite, à la main, "
              "avec la liste.")
title(s, "ChopChop : ce que plus rien n'utilise", "Ménage")
p, (iw, ih) = crop("onglet_chopchop", (0, 82, 1240, 912), "chopchop")
pw = 7.6
picture(s, p, 0.6, 1.7, w=pw)
cc = [("Mesures", "Ni visuel, ni autre mesure utilisée ne s'en sert."),
      ("Colonnes", "Ni visuel, ni relation, ni mesure utilisée."),
      ("Tables entières", "Rien d'extérieur ne s'appuie dessus."),
      ("Power Query compris", "Une table qu'une autre requête fusionne ou ajoute est épargnée, toutes colonnes."),
      ("Exporter…", "La liste, pour décider du ménage à tête reposée.")]
step_list(s, 8.6, 1.75, 4.2, cc, gap=0.98, size=14, color=RED)

# ============================================================ 16. Filets de sécurité
s = new_slide("Rien n'est écrit sans trace : aperçu d'abord, sauvegarde horodatée de tout ce qui est "
              "réécrit, restauration possible, et le journal qui raconte chaque action.")
title(s, "Les filets de sécurité", "Bonnes pratiques")
safe = [("Aperçu (dry-run)", "Coché par défaut partout : on voit tout, rien n'est écrit.", GREEN, "👁"),
        ("Sauvegardes", "Chaque écriture copie les fichiers touchés sous _backupsPBIdouille\\, horodatés.", BLUE, "▣"),
        ("Restauration", "🕘 Restaurer une sauvegarde, en haut : revenir à une copie, avec d'où elle vient.", ORANGE, "↺"),
        ("Le journal", "Chaque run : heure, verdict, durée, avertissements ⚠ en jaune.", GREEN, "☰")]
for i, (h, d, col, ic) in enumerate(safe):
    x = 0.6 + (i % 2) * 6.15
    y = 1.85 + (i // 2) * 2.15
    box(s, x, y, 5.95, 1.9, fill=CARD)
    box(s, x + 0.3, y + 0.35, 0.8, 0.8, fill=col, shape=MSO_SHAPE.OVAL)
    text(s, x + 0.3, y + 0.35, 0.8, 0.8, ic, size=22, color=DARK, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 1.35, y + 0.3, 4.4, 1.5, [[(h, {"bold": True, "size": 18, "font": HEAD, "color": col})],
                                           [(d, {"size": 14})]], size=14)
box(s, 0.6, 6.25, 12.1, 0.6, fill=CARD2)
text(s, 0.9, 6.25, 11.6, 0.6,
     [[("Après Desktop ou Excel : ", {"bold": True, "color": GREEN}),
       ("↻ Tout recharger relit le disque sans fermer l'app (il signale d'abord ce qui n'est pas enregistré).", {})]],
     size=14, anchor=MSO_ANCHOR.MIDDLE)

# ============================================================ 17. En cas de pépin
s = new_slide("Les quatre questions qui reviennent. La documentation détaillée est dans le dossier docs.")
title(s, "En cas de pépin", "Aide-mémoire")
faq = [("Le formatage disparaît quand je change d'ICP", "L'ICP n'a pas été propagé : vérifier la grille, puis Propager."),
       ("Une mesure n'est pas générée", "Lire le journal : base exclue par la portée, attribut <<…>> absent de l'Excel, ou nom en collision."),
       ("Ce que l'outil a écrit a disparu", "Desktop a été enregistré après l'écriture. Relancer l'écriture, puis fermer Desktop sans enregistrer et rouvrir."),
       ("L'outil ne voit pas ma nouvelle colonne Excel", "↻ Tout recharger (ou le bouton ↻ des Réglages).")]
for i, (q, a) in enumerate(faq):
    y = 1.8 + i * 1.18
    box(s, 0.6, y, 12.1, 1.02, fill=CARD)
    text(s, 0.9, y, 0.5, 1.02, "?", size=26, font=HEAD, color=GREEN, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 1.5, y + 0.14, 10.9, 0.85, [[(q, {"bold": True, "size": 16})], [(a, {"size": 14, "color": MUTED})]], size=15)
text(s, 0.6, 6.65, 12, 0.4, "Documentation détaillée : le dossier docs, à côté de l'app.", size=13, color=MUTED)

prs.save(str(OUT))
print("écrit :", OUT, ",", len(prs.slides), "diapos")
