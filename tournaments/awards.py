"""Podio, achievement e premi - tutto calcolato dai risultati (nessuna modifica al DB)."""

from django.db.models import Q

from .models import Match
from .standings import group_standings
from .stats import tournament_stats


def _phase_podium(tournament, phase):
    finale = tournament.matches.filter(phase=phase, round_label="Finale").first()
    terzo = tournament.matches.filter(phase=phase, round_label="Finale 3°/4°").first()
    res = {"first": None, "second": None, "third": None, "fourth": None}
    if finale and finale.is_played:
        res["first"] = finale.winner
        res["second"] = finale.loser
    if terzo and terzo.is_played:
        res["third"] = terzo.winner
        res["fourth"] = terzo.loser
    return res


def podium(tournament):
    return {
        "gold": _phase_podium(tournament, Match.Phase.GOLD),
        "silver": _phase_podium(tournament, Match.Phase.SILVER),
    }


def champion(tournament):
    """La coppia campione = vincente della finale gold (None se non ancora decisa)."""
    return podium(tournament)["gold"]["first"]


def team_achievements(team):
    """Badge di merito guadagnati giocando (più coppie possono averli)."""
    badges = []
    matches = (
        team.tournament.matches.filter(Q(team_a=team) | Q(team_b=team), status=Match.Status.DONE)
        .prefetch_related("sets")
    )
    cappotto = rimonta = False
    for m in matches:
        is_a = m.team_a_id == team.id
        sets = list(m.sets.all())
        for s in sets:
            mine, theirs = (s.games_a, s.games_b) if is_a else (s.games_b, s.games_a)
            if mine == 6 and theirs == 0:
                cappotto = True
        if m.is_knockout and m.winner_id == team.id and sets:
            first_side = sets[0].winner_side
            if first_side and (first_side == "a") != is_a:  # primo set perso, match vinto
                rimonta = True

    if cappotto:
        badges.append({"icon": "🎾", "label": "Cappotto", "desc": "Set vinto 6-0"})
    if rimonta:
        badges.append({"icon": "🔥", "label": "Rimonta", "desc": "Vinta dopo aver perso un set"})
    if team.group_id:
        me = next((r for r in group_standings(team.group) if r["team"].id == team.id), None)
        if me and me["rank"] == 1 and me["played"] > 0 and me["wins"] == me["played"]:
            badges.append({"icon": "🛡️", "label": "Imbattuti", "desc": "1ª nel girone, nessuna sconfitta"})
    return badges


def tournament_awards(tournament):
    """Per la pagina Albo d'oro: podio + premi speciali + coppie con badge di merito."""
    st = tournament_stats(tournament)
    specials = []
    if st["best_attack"]:
        specials.append({"icon": "💣", "label": "Bomber", "team": st["best_attack"]["team"], "value": f"{st['best_attack']['gf']} game fatti"})
    if st["best_defense"]:
        specials.append({"icon": "🧱", "label": "Miglior difesa", "team": st["best_defense"]["team"], "value": f"{st['best_defense']['ga']} game subiti"})
    if st["most_wins"]:
        specials.append({"icon": "🏅", "label": "Più vittorie", "team": st["most_wins"]["team"], "value": f"{st['most_wins']['wins']} vinte"})

    team_badges = []
    for team in tournament.teams.all():
        badges = team_achievements(team)
        if badges:
            team_badges.append({"team": team, "badges": badges})

    return {"podium": podium(tournament), "specials": specials, "team_badges": team_badges}
