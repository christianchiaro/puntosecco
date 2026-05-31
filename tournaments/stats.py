"""Statistiche di torneo, calcolate al volo dai risultati."""

from .models import Match
from .standings import match_games


def tournament_stats(tournament):
    matches = list(tournament.matches.select_related("team_a", "team_b", "winner"))
    played = [m for m in matches if m.status == Match.Status.DONE and m.winner_id is not None]

    teams = {
        t.id: {"team": t, "wins": 0, "played": 0, "gf": 0, "ga": 0}
        for t in tournament.teams.all()
    }
    for m in played:
        ga, gb = match_games(m)
        for tid, gf, gag in ((m.team_a_id, ga, gb), (m.team_b_id, gb, ga)):
            if tid in teams:
                teams[tid]["gf"] += gf
                teams[tid]["ga"] += gag
                teams[tid]["played"] += 1
        if m.winner_id in teams:
            teams[m.winner_id]["wins"] += 1

    rows = list(teams.values())
    for s in rows:
        s["diff"] = s["gf"] - s["ga"]

    leaderboard = sorted(rows, key=lambda s: (s["wins"], s["diff"], s["gf"]), reverse=True)
    played_rows = [s for s in rows if s["played"] > 0]
    total = len(matches)
    done = len(played)
    return {
        "total": total,
        "done": done,
        "remaining": total - done,
        "pct": round(done * 100 / total) if total else 0,
        "leaderboard": leaderboard,
        "best_attack": max(played_rows, key=lambda s: s["gf"], default=None),
        "best_defense": min(played_rows, key=lambda s: s["ga"], default=None),
        "most_wins": max(played_rows, key=lambda s: s["wins"], default=None),
    }
