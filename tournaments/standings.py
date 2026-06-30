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
