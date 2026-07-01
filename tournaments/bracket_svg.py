"""Rende un tabellone a eliminazione come SVG preciso (coordinate calcolate).

Usato sia dalla modalità TV sia dalla pagina Tabelloni (stesso identico markup):
niente trucchi CSS, linee e box allineati al pixel.
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
WIN = "#9bcd91"
MUTE = "#9fb39a"
LINE = "#3c5232"
BOXBG = "#172414"
SET_GAP = 22
FONT = "system-ui,-apple-system,sans-serif"


def _name(team, n_sets=0):
    if not team:
        return "-"
    n = team.name
    # Lo spazio libero per il nome si restringe con più set mostrati (i punteggi
    # sono allineati a destra, ogni set occupa SET_GAP px): un limite fisso di
    # caratteri non basta, con 2-3 set il nome finirebbe a sovrapporre i punteggi.
    # Stima approssimativa ~9.5px/carattere al font-size 17 usato in _draw_box.
    available = BOX_W - 28 - n_sets * SET_GAP
    max_chars = max(8, int(available / 9.5))
    return html.escape(n if len(n) <= max_chars else n[: max_chars - 1] + "…")


def _draw_box(p, x, cy, label, match):
    """Aggiunge label + box con le due coppie a `p` (lista di frammenti SVG)."""
    top = cy - BOX_H / 2
    p.append(
        f'<text x="{x + 2:.0f}" y="{top - 8:.0f}" fill="{MUTE}" font-size="13" '
        f'font-family="{FONT}">{html.escape(label)}</text>'
    )
    p.append(
        f'<rect x="{x:.0f}" y="{top:.0f}" width="{BOX_W}" height="{BOX_H}" rx="7" '
        f'fill="{BOXBG}" stroke="{LINE}"/>'
    )
    p.append(
        f'<line x1="{x:.0f}" y1="{top + ROW_H:.0f}" x2="{x + BOX_W:.0f}" '
        f'y2="{top + ROW_H:.0f}" stroke="{LINE}"/>'
    )
    # Punteggio set per set (anche a partita IN CORSO, non solo a fine match): un
    # set ancora in gioco (es. "3-2") non ha un vincitore deciso, quindi NON va
    # contato come "set vinto" - mostrare direttamente i game evita di dichiarare
    # un vincitore prematuro che potrebbe ribaltarsi.
    sets = list(match.sets.all())
    n_sets = len(sets)
    rows = [
        (match.team_a, match.team_a_id, "games_a"),
        (match.team_b, match.team_b_id, "games_b"),
    ]
    for ri, (team, tid, games_attr) in enumerate(rows):
        ty = top + ri * ROW_H + ROW_H / 2 + 6
        win = match.is_played and match.winner_id == tid
        color = WIN if win else INK
        weight = "700" if win else "400"
        p.append(
            f'<text x="{x + 14:.0f}" y="{ty:.0f}" fill="{color}" font-size="17" '
            f'font-weight="{weight}" font-family="{FONT}">{_name(team, n_sets)}</text>'
        )
        for si, s in enumerate(sets):
            sx = x + BOX_W - 14 - (n_sets - 1 - si) * SET_GAP
            p.append(
                f'<text x="{sx:.0f}" y="{ty:.0f}" fill="{color}" font-size="17" '
                f'font-weight="{weight}" text-anchor="middle" font-family="{FONT}">'
                f"{getattr(s, games_attr)}</text>"
            )


def render_bracket_svg(rounds, third_place=None):
    """`rounds`: lista di {abbr, matches} dal primo turno alla finale.
    `third_place`: partita Finale 3°/4° opzionale, disegnata come box a se' sotto la
    finale (stessa colonna, senza connettori - riflette solo il piazzamento).
    Ritorna stringa SVG (vuota se non c'e' nulla da disegnare)."""
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
    tp_cy = None
    if third_place:
        tp_cy = centers[-1][0] + BOX_H + LABEL_H + V_GAP
        # Il box 3°/4° può ricadere già dentro il canvas esistente (bracket piccoli,
        # dove il centro della finale è vicino al centro verticale): estendo il
        # canvas solo se serve davvero, altrimenti resta spazio vuoto in fondo.
        height = max(height, tp_cy + BOX_H / 2 + PAD)

    def x_of(r):
        return PAD + r * (BOX_W + COL_GAP)

    p = [
        f'<svg class="tv-bracket-svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="xMidYMid meet" '
        'xmlns="http://www.w3.org/2000/svg">'
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

    # Box + testi di ogni turno.
    for r, rnd in enumerate(rounds):
        xr = x_of(r)
        for i, m in enumerate(rnd["matches"]):
            _draw_box(p, xr, centers[r][i], f'{rnd["abbr"]} · Game {i + 1}', m)

    if third_place:
        _draw_box(p, x_of(ncol - 1), tp_cy, "Finale 3°/4°", third_place)

    p.append("</svg>")
    return "".join(p)


def render_consolation_svg(sf_matches, finals):
    """Tabellone di consolazione 5°-8°: 2 semifinali -> 2 finali PARALLELE (non
    convergono a 1 come nel tabellone principale). `finals`: lista di (label, match).
    Ritorna stringa SVG (vuota se non ci sono semifinali)."""
    if not sf_matches:
        return ""

    n = len(sf_matches)
    pitch = BOX_H + LABEL_H + V_GAP
    centers0 = [PAD + LABEL_H + i * pitch + BOX_H / 2 for i in range(n)]
    mid = sum(centers0) / len(centers0)
    spread = (BOX_H + V_GAP) / 2
    centers1 = [mid - spread, mid + spread] if len(finals) == 2 else [mid] * len(finals)

    width = PAD * 2 + 2 * BOX_W + COL_GAP
    height = PAD + LABEL_H + n * pitch

    x0 = PAD
    x1 = PAD + BOX_W + COL_GAP
    rightx = x0 + BOX_W
    midx = rightx + COL_GAP / 2

    p = [
        f'<svg class="tv-bracket-svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="xMidYMid meet" '
        'xmlns="http://www.w3.org/2000/svg">'
    ]

    # Connettori a incrocio: ogni finale e' raggiungibile da entrambe le semifinali
    # (vince chi vince la propria SF, gioca l'altra finale chi la perde).
    for cy_final in centers1:
        for cy_sf in centers0:
            p.append(
                f'<path d="M{rightx:.0f},{cy_sf:.0f} H{midx:.0f} V{cy_final:.0f} H{x1:.0f}" '
                f'fill="none" stroke="{LINE}" stroke-width="2"/>'
            )

    for i, m in enumerate(sf_matches):
        _draw_box(p, x0, centers0[i], f"Semifinale 5°-8° · Game {i + 1}", m)
    for (label, m), cy in zip(finals, centers1):
        if m:
            _draw_box(p, x1, cy, label, m)

    p.append("</svg>")
    return "".join(p)
