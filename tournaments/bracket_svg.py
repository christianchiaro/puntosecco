"""Rende un tabellone a eliminazione come SVG preciso (coordinate calcolate).

Usato dalla modalità TV: niente trucchi CSS, linee e box allineati al pixel.
"""

import html

BOX_W = 250
ROW_H = 38
BOX_H = ROW_H * 2
LABEL_H = 26
COL_GAP = 80
V_GAP = 46
PAD = 18

INK = "#eafff7"
WIN = "#2bb99a"
MUTE = "#8fb3a8"
LINE = "#2f5145"
BOXBG = "#12241e"
FONT = "system-ui,-apple-system,sans-serif"


def _name(team):
    if not team:
        return "-"
    n = team.name
    return html.escape(n if len(n) <= 22 else n[:21] + "…")


def render_bracket_svg(rounds):
    """`rounds`: lista di {abbr, matches} dal primo turno alla finale. Ritorna stringa SVG."""
    if not rounds or not rounds[0]["matches"]:
        return ""

    n0 = len(rounds[0]["matches"])
    pitch = BOX_H + LABEL_H + V_GAP

    # Centro verticale di ogni partita: round 0 equispaziato, poi punto medio della coppia.
    centers = [[PAD + LABEL_H + i * pitch + BOX_H / 2 for i in range(n0)]]
    for r in range(1, len(rounds)):
        prev = centers[r - 1]
        centers.append(
            [
                (prev[2 * j] + prev[2 * j + 1]) / 2
                for j in range(len(rounds[r]["matches"]))
            ]
        )

    ncol = len(rounds)
    width = PAD * 2 + ncol * BOX_W + (ncol - 1) * COL_GAP
    height = PAD + LABEL_H + n0 * pitch

    def x_of(r):
        return PAD + r * (BOX_W + COL_GAP)

    p = [
        f'<svg class="tv-bracket-svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        'preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">'
    ]

    # Connettori (sotto i box): stub orizzontali + verticale della coppia + ingresso al turno dopo.
    for r in range(ncol - 1):
        rightx = x_of(r) + BOX_W
        midx = rightx + COL_GAP / 2
        nextx = x_of(r + 1)
        for j in range(len(centers[r + 1])):
            ca, cb, cm = centers[r][2 * j], centers[r][2 * j + 1], centers[r + 1][j]
            p.append(
                f'<path d="M{rightx:.0f},{ca:.0f} H{midx:.0f} M{rightx:.0f},{cb:.0f} H{midx:.0f} '
                f'M{midx:.0f},{ca:.0f} V{cb:.0f} M{midx:.0f},{cm:.0f} H{nextx:.0f}" '
                f'fill="none" stroke="{LINE}" stroke-width="2"/>'
            )

    # Box + testi.
    for r, rnd in enumerate(rounds):
        xr = x_of(r)
        for i, m in enumerate(rnd["matches"]):
            cy = centers[r][i]
            top = cy - BOX_H / 2
            p.append(
                f'<text x="{xr + 2:.0f}" y="{top - 8:.0f}" fill="{MUTE}" font-size="13" '
                f'font-family="{FONT}">{html.escape(rnd["abbr"])} · Game {i + 1}</text>'
            )
            p.append(
                f'<rect x="{xr:.0f}" y="{top:.0f}" width="{BOX_W}" height="{BOX_H}" rx="7" '
                f'fill="{BOXBG}" stroke="{LINE}"/>'
            )
            p.append(
                f'<line x1="{xr:.0f}" y1="{top + ROW_H:.0f}" x2="{xr + BOX_W:.0f}" '
                f'y2="{top + ROW_H:.0f}" stroke="{LINE}"/>'
            )
            rows = [
                (m.team_a, m.team_a_id, m.sets_a),
                (m.team_b, m.team_b_id, m.sets_b),
            ]
            for ri, (team, tid, sets) in enumerate(rows):
                ty = top + ri * ROW_H + ROW_H / 2 + 6
                win = m.is_played and m.winner_id == tid
                color = WIN if win else INK
                weight = "700" if win else "400"
                p.append(
                    f'<text x="{xr + 14:.0f}" y="{ty:.0f}" fill="{color}" font-size="17" '
                    f'font-weight="{weight}" font-family="{FONT}">{_name(team)}</text>'
                )
                if m.is_played:
                    p.append(
                        f'<text x="{xr + BOX_W - 14:.0f}" y="{ty:.0f}" fill="{color}" font-size="17" '
                        f'font-weight="{weight}" text-anchor="end" font-family="{FONT}">{sets}</text>'
                    )

    p.append("</svg>")
    return "".join(p)
