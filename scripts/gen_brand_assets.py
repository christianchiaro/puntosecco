"""Genera tutti gli asset di branding dal logo sorgente.

Produce favicon (.ico + png), apple-touch-icon, icone Android/PWA (anche maskable),
versione bianca trasparente dell'emblema (per header su sfondo verde) e l'immagine OG.
Eseguire una tantum quando cambia il logo: `../reabita_venv/bin/python scratch_gen_assets.py`
"""

from PIL import Image

GREEN = (49, 85, 47)  # #31552f - verde del logo
IMG = "static/img"

src = Image.open(f"{IMG}/logo_puntosecco.png").convert("RGBA")
W, H = src.size

# --- 1. Emblema (esclude la scritta in basso): quadrato centrato ---
side = int(W * 0.84)
left = (W - side) // 2
top = int(H * 0.012)
emblem = src.crop((left, top, left + side, top + side))


def white_alpha(img):
    """Emblema bianco su trasparente: alpha derivato dalla luminanza (bianco=1, verde=0).

    Il disegno e' bianco su verde pieno: ricavo l'alpha dalla 'biancura' di ogni pixel e
    forzo il colore a bianco. Cosi i bordi anti-aliasati restano puliti su qualsiasi sfondo.
    """
    rgb = img.convert("RGB")
    px = rgb.load()
    out = Image.new("RGBA", img.size, (255, 255, 255, 0))
    op = out.load()
    g_lum = 0.299 * GREEN[0] + 0.587 * GREEN[1] + 0.114 * GREEN[2]
    span = 255 - g_lum
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, gg, b = px[x, y]
            lum = 0.299 * r + 0.587 * gg + 0.114 * b
            a = max(0.0, min(1.0, (lum - g_lum) / span))
            op[x, y] = (255, 255, 255, int(a * 255))
    return out


emblem_white = white_alpha(emblem)


def on_green(white_img, size, scale=1.0):
    """Emblema bianco trasparente composito su quadrato verde, ridimensionato a `size`."""
    canvas = Image.new("RGBA", emblem.size, GREEN + (255,))
    if scale != 1.0:
        s = int(emblem.size[0] * scale)
        small = white_img.resize((s, s), Image.LANCZOS)
        off = (emblem.size[0] - s) // 2
        canvas.alpha_composite(small, (off, off))
    else:
        canvas.alpha_composite(white_img)
    return canvas.convert("RGB").resize((size, size), Image.LANCZOS)


# --- 2. Favicon PNG + .ico multi-size ---
for s in (16, 32, 48):
    on_green(emblem_white, s).save(f"{IMG}/favicon-{s}x{s}.png")
on_green(emblem_white, 48).save(
    f"{IMG}/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)]
)

# --- 3. Apple touch icon (180, no trasparenza, full-bleed verde) ---
on_green(emblem_white, 180).save(f"{IMG}/apple-touch-icon.png")

# --- 4. Icone Android / PWA ---
on_green(emblem_white, 192).save(f"{IMG}/android-chrome-192x192.png")
on_green(emblem_white, 512).save(f"{IMG}/android-chrome-512x512.png")
# Maskable: emblema all'80% dentro la safe-zone, resto verde pieno.
on_green(emblem_white, 512, scale=0.80).save(f"{IMG}/maskable-512x512.png")

# --- 5. Emblema bianco trasparente per la UI (header, hero) ---
emblem_white.resize((512, 512), Image.LANCZOS).save(f"{IMG}/logo-mark.png")

# --- 6. Immagine OG 1200x630 (link condivisi): logo intero su verde ---
og = Image.new("RGB", (1200, 630), GREEN)
full_white = white_alpha(src)
target_h = 580
scale = target_h / H
lw = int(W * scale)
full_r = full_white.resize((lw, target_h), Image.LANCZOS)
og_rgba = og.convert("RGBA")
og_rgba.alpha_composite(full_r, ((1200 - lw) // 2, (630 - target_h) // 2))
og_rgba.convert("RGB").save(f"{IMG}/og.png")

print("Asset generati in", IMG)
