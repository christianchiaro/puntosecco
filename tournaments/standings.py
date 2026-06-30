"""Classifica di un girone.

Ordine (tiebreaker): vittorie → scontro diretto → differenza game → game fatti.
Calcolata al volo dai risultati: nessun dato duplicato nel DB.
"""

from .models import Match


def match_games(match):
    """(game totali di team_a, game totali di team_b) sommando i set giocati."""
    a = b = 0
    for s in match.sets.all():
        a += s.games_a
        b += s.games_b
    return a, b


def _live_leader(match):
    """Chi è avanti in una partita in corso (per i game). None se è in parità."""
    ga, gb = match_games(match)
    if ga > gb:
        return match.team_a_id
    if gb > ga:
        return match.team_b_id
    return None


def group_standings(group):
    """Lista ordinata di dict per ogni coppia del girone, dal 1° all'ultimo.

    Ogni dict: team, played, wins, gf (game fatti), ga (subiti), diff, live, rank.

    Classifica "live": una partita in corso CON punteggio parziale viene contata come
    risultato provvisorio (giocata + vittoria a chi è avanti + game nella differenza).
    `live=True` marca le coppie con un risultato provvisorio (la posizione può cambiare).
    """
    teams = list(group.teams.all())
    played_matches = [
        m
        for m in group.matches.filter(status=Match.Status.DONE)
        if m.winner_id is not None
    ]
    # Solo le partite in corso che hanno già un punteggio (almeno un set registrato).
    live_matches = [
        m for m in group.matches.filter(status=Match.Status.LIVE) if m.sets.exists()
    ]

    stats = {
        t.id: {"team": t, "played": 0, "wins": 0, "gf": 0, "ga": 0, "live": False}
        for t in teams
    }

    def add_games(m):
        ga, gb = match_games(m)
        if m.team_a_id in stats:
            stats[m.team_a_id]["gf"] += ga
            stats[m.team_a_id]["ga"] += gb
        if m.team_b_id in stats:
            stats[m.team_b_id]["gf"] += gb
            stats[m.team_b_id]["ga"] += ga

    for m in played_matches:
        add_games(m)
        if m.team_a_id in stats:
            stats[m.team_a_id]["played"] += 1
        if m.team_b_id in stats:
            stats[m.team_b_id]["played"] += 1
        if m.winner_id in stats:
            stats[m.winner_id]["wins"] += 1

    # Risultato provvisorio: giocata + vittoria a chi è avanti (None se in parità).
    for m in live_matches:
        add_games(m)
        leader = _live_leader(m)
        for tid in (m.team_a_id, m.team_b_id):
            if tid in stats:
                stats[tid]["played"] += 1
                stats[tid]["live"] = True
        if leader in stats:
            stats[leader]["wins"] += 1

    for s in stats.values():
        s["diff"] = s["gf"] - s["ga"]

    def head_to_head_wins(team_id, among_ids):
        """Vittorie di team_id nelle partite contro le coppie in among_ids."""
        wins = 0
        for m in played_matches:
            opponents = {m.team_a_id, m.team_b_id} - {team_id}
            if team_id in (m.team_a_id, m.team_b_id) and opponents & among_ids:
                if m.winner_id == team_id:
                    wins += 1
        return wins

    # Ordina per vittorie; dentro ogni gruppo di pari vittorie applica scontro
    # diretto (tra i pari), poi differenza game, poi game fatti.
    ordered = []
    for win_count in sorted({s["wins"] for s in stats.values()}, reverse=True):
        tied = [s for s in stats.values() if s["wins"] == win_count]
        tied_ids = {s["team"].id for s in tied}
        tied.sort(
            key=lambda s: (
                head_to_head_wins(s["team"].id, tied_ids - {s["team"].id}),
                s["diff"],
                s["gf"],
            ),
            reverse=True,
        )
        ordered.extend(tied)

    for i, s in enumerate(ordered, start=1):
        s["rank"] = i
    return ordered


def group_ranking(group):
    """Solo le coppie, dalla 1ª all'ultima."""
    return [s["team"] for s in group_standings(group)]


def _ceil_power_of_two(n):
    p = 1
    while p < n:
        p <<= 1
    return p


def gold_team_ids(groups, rows_by_group):
    """Set di team_id destinati al tabellone GOLD, secondo la stessa logica di
    `seed_brackets`: prime 2 di ogni girone + le migliori terze (wild card) fino a
    riempire il gold (potenza di 2). Tutto il resto va in silver.

    `groups`: lista di Group (ordinati per nome). `rows_by_group`: {group_id: rows}
    dove rows è l'output di `group_standings`. Provvisorio in fase a gironi.
    """
    num_groups = len(groups)
    if num_groups == 0:
        return set()
    gold_size = _ceil_power_of_two(num_groups * 2)
    wild_needed = max(0, gold_size - num_groups * 2)

    ids = set()
    thirds = []
    for g in groups:
        rows = rows_by_group[g.id]
        for r in rows[:2]:
            ids.add(r["team"].id)
        if len(rows) >= 3:
            thirds.append(rows[2])

    if wild_needed:
        # Criteri: vittorie → diff game → game fatti → esito spareggio (deciso a mano).
        thirds.sort(key=_wildcard_key, reverse=True)
        for s in thirds[:wild_needed]:
            ids.add(s["team"].id)
    return ids


def _wildcard_merit(s):
    """Merito sportivo di una terza per le wild card (senza lo spareggio manuale)."""
    return (s["wins"], s["diff"], s["gf"])


def _wildcard_key(s):
    """Ordinamento completo: merito sportivo + esito spareggio come ultimo criterio."""
    return _wildcard_merit(s) + (s["team"].spareggio,)


def wildcard_spareggio(groups, rows_by_group):
    """Spareggio pendente per l'ultimo posto gold tra le terze a pari merito.

    Ritorna {"teams": [Team, ...], "spots": n} se c'è un pari NON ancora risolto
    (le coppie contese e quanti posti gold restano da assegnare tra loro), altrimenti None.
    """
    num_groups = len(groups)
    if num_groups == 0:
        return None
    gold_size = _ceil_power_of_two(num_groups * 2)
    wild_needed = max(0, gold_size - num_groups * 2)
    if wild_needed == 0:
        return None

    thirds = [rows_by_group[g.id][2] for g in groups if len(rows_by_group[g.id]) >= 3]
    if len(thirds) <= wild_needed:
        return None  # tutte le terze entrano: nessuna contesa

    thirds.sort(key=_wildcard_key, reverse=True)
    # Nessun pari al confine sul MERITO sportivo → niente spareggio.
    if _wildcard_merit(thirds[wild_needed - 1]) != _wildcard_merit(thirds[wild_needed]):
        return None

    boundary = _wildcard_merit(thirds[wild_needed - 1])
    contested = [s for s in thirds if _wildcard_merit(s) == boundary]
    better = sum(1 for s in thirds if _wildcard_merit(s) > boundary)
    spots = wild_needed - better  # posti gold disponibili per le coppie contese
    if not (0 < spots < len(contested)):
        return None

    # Già risolto se lo spareggio separa nettamente i primi `spots`.
    contested.sort(key=lambda s: s["team"].spareggio, reverse=True)
    if contested[spots - 1]["team"].spareggio != contested[spots]["team"].spareggio:
        return None
    return {"teams": [s["team"] for s in contested], "spots": spots}
