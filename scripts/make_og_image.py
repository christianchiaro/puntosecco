"""Genera l'immagine di anteprima social (Open Graph) — 1200x630, brandizzata.

Eseguita una tantum in locale; il PNG risultante è statico (niente dipendenze da font
in produzione). Rigenera con:  ../reabita_venv/bin/python scripts/make_og_image.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
GREEN = (14, 124, 102)
DARK = (10, 91, 75)
WHITE = (255, 255, 255)
SOFT = (214, 236, 229)
GOLD = (224, 192, 105)
BALL = (203, 240, 122)

ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"

img = Image.new("RGB", (W, H), GREEN)
d = ImageDraw.Draw(img)

# Barra inferiore più scura
d.rectangle([0, H - 96, W, H], fill=DARK)

# "Pallina" da padel in alto a destra
d.ellipse([W - 250, 70, W - 70, 250], fill=BALL)
d.arc([W - 250, 70, W - 70, 250], start=205, end=335, fill=GREEN, width=7)
d.arc([W - 250, 70, W - 70, 250], start=25, end=155, fill=GREEN, width=7)

eyebrow = ImageFont.truetype(ARIAL_BOLD, 40)
title = ImageFont.truetype(ARIAL_BOLD, 132)
subtitle = ImageFont.truetype(ARIAL, 54)
footer = ImageFont.truetype(ARIAL_BOLD, 34)

d.text((84, 150), "TORNEO DI PADEL", font=eyebrow, fill=GOLD)
d.text((80, 212), "Punto Secco", font=title, fill=WHITE)
# Sottolineatura oro
d.rectangle([88, 372, 470, 384], fill=GOLD)
d.text((84, 410), "16 coppie · 4 gironi · gold & silver", font=subtitle, fill=SOFT)
d.text((84, H - 70), "Classifiche · Calendario · Tabelloni · Live", font=footer, fill=WHITE)

out = Path(__file__).resolve().parent.parent / "static" / "img" / "og.png"
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out, "PNG")
print(f"Creato {out} ({out.stat().st_size} byte)")
