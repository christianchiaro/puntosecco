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


# Finali che assegnano i piazzamenti, in ordine: (round_label, posizione del vincente).
# Il perdente prende la posizione successiva. Le 5°/6° e 7°/8° esistono solo nel
# gold (consolazione dei perdenti dei quarti); nel silver ci sono solo le prime due.
_PLACEMENT_FINALS = [
    ("Finale", 1),
    ("Finale 3\xb0/4\xb0", 3),
    ("Finale 5\xb0/6\xb0", 5),
    ("Finale 7\xb0/8\xb0", 7),
]


def phase_classification(tournament, phase):
    """Classifica del tabellone: lista ordinata di {pos, team} (team None se non deciso).

    Gold -> 1°-8° (con la consolazione), silver -> 1°-4°. Ogni finale assegna due
    posizioni: vincente = pos, perdente = pos+1.
    """
    by_label = {
        m.round_label: m
        for m in tournament.matches.filter(phase=phase).select_related(
            "team_a", "team_b", "winner"
        )
    }
    ranking = []
    for label, top in _PLACEMENT_FINALS:
        m = by_label.get(label)
        if not m:
            continue
        ranking.append({"pos": top, "team": m.winner})
        ranking.append({"pos": top + 1, "team": m.loser})
    return ranking


def final_classification(tournament):
    """Classifiche finali separate per tabellone, per la pagina dedicata."""
    return {
        "gold": phase_classification(tournament, Match.Phase.GOLD),
        "silver": phase_classification(tournament, Match.Phase.SILVER),
    }


def team_achievements(team):
    """Badge di merito guadagnati giocando (più coppie possono averli)."""
    badges = []
    matches = team.tournament.matches.filter(
        Q(team_a=team) | Q(team_b=team), status=Match.Status.DONE
    ).prefetch_related("sets")
    cappotto = rimonta = False
    for m in matches:
        is_a = m.team_a_id == team.id
        sets = list(m.sets.all())
        for s in sets:
            mine, theirs = (s.games_a, s.games_b) if is_a else (s.games_b, s.games_a)
            if mine == 6 and theirs == 0:
                cappotto = True
        if m.is_two_set_match and m.winner_id == team.id and sets:
            first_side = sets[0].winner_side
            if (
                first_side and (first_side == "a") != is_a
            ):  # primo set perso, match vinto
                rimonta = True

    if cappotto:
        badges.append({"icon": "🎾", "label": "Cappotto", "desc": "Set vinto 6-0"})
    if rimonta:
        badges.append(
            {"icon": "🔥", "label": "Rimonta", "desc": "Vinta dopo aver perso un set"}
        )
    if team.group_id:
        me = next(
            (r for r in group_standings(team.group) if r["team"].id == team.id), None
        )
        if me and me["rank"] == 1 and me["played"] > 0 and me["wins"] == me["played"]:
            badges.append(
                {
                    "icon": "🛡️",
                    "label": "Imbattuti",
                    "desc": "1ª nel girone, nessuna sconfitta",
                }
            )
    return badges


def tournament_awards(tournament):
    """Per la pagina Albo d'oro: podio + premi speciali + coppie con badge di merito."""
    st = tournament_stats(tournament)
    specials = []
    if st["best_attack"]:
        specials.append(
            {
                "icon": "💣",
                "label": "Bomber",
                "team": st["best_attack"]["team"],
                "value": f"{st['best_attack']['gf']} game fatti",
            }
        )
    if st["best_defense"]:
        specials.append(
            {
                "icon": "🧱",
                "label": "Miglior difesa",
                "team": st["best_defense"]["team"],
                "value": f"{st['best_defense']['ga']} game subiti",
            }
        )
    if st["most_wins"]:
        specials.append(
            {
                "icon": "🏅",
                "label": "Più vittorie",
                "team": st["most_wins"]["team"],
                "value": f"{st['most_wins']['wins']} vinte",
            }
        )

    team_badges = []
    for team in tournament.teams.all():
        badges = team_achievements(team)
        if badges:
            team_badges.append({"team": team, "badges": badges})

    return {
        "podium": podium(tournament),
        "specials": specials,
        "team_badges": team_badges,
    }
