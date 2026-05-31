"""Tabelloni gold/silver: seeding dai gironi, scheduling a 2 slot, avanzamento vincenti.

Generico: il tabellone di ogni fase ha 2×(n° gironi) coppie (gold = 1ª/2ª, silver = 3ª/4ª),
che deve essere una potenza di 2 → 1, 2, 4 o 8 gironi. Seeding standard a incrocio: le teste
di serie (le 1ª dei gironi) sono distribuite e si evitano fino in fondo al tabellone.
"""

from .models import Match
from .scheduling import slot_start
from .standings import group_ranking

_ROUND_NAMES = {
    1: "Finale",
    2: "Semifinale",
    4: "Quarti",
    8: "Ottavi",
    16: "Sedicesimi",
}
_ROUND_SEQUENCE = ["Sedicesimi", "Ottavi", "Quarti", "Semifinale"]


def _round_name(num_matches):
    return _ROUND_NAMES.get(num_matches, f"Turno ({num_matches})")


def _seed_order(n):
    """Ordine standard degli slot di un tabellone a eliminazione (n potenza di 2)."""
    order = [1]
    while len(order) < n:
        m = len(order) * 2 + 1
        order = [x for s in order for x in (s, m - s)]
    return order


def _group_stage_slots(tournament):
    last = (
        tournament.matches.filter(phase=Match.Phase.GROUP)
        .order_by("-slot_index")
        .values_list("slot_index", flat=True)
        .first()
    )
    return 0 if last is None else last + 1


def _is_power_of_two(n):
    return n >= 2 and (n & (n - 1)) == 0


def _build_phase_bracket(tournament, phase, seeds):
    """Costruisce un tabellone a eliminazione per `seeds` (lista di coppie in ordine di
    testa di serie, lunghezza potenza di 2). Crea anche la finale 3°/4° posto."""
    n = len(seeds)
    order = _seed_order(n)

    # Primo turno: accoppia secondo l'ordine standard (1 vs n, 2 vs n-1, ...).
    rounds = [[]]
    for pos, k in enumerate(range(0, n, 2), start=1):
        rounds[0].append(
            Match.objects.create(
                tournament=tournament,
                phase=phase,
                round_label=_round_name(n // 2),
                bracket_pos=pos,
                slot_span=2,
                team_a=seeds[order[k] - 1],
                team_b=seeds[order[k + 1] - 1],
            )
        )
    # Turni successivi: i vincenti delle due partite precedenti si affrontano.
    while len(rounds[-1]) > 1:
        prev = rounds[-1]
        cur = []
        for pos, i in enumerate(range(0, len(prev), 2), start=1):
            cur.append(
                Match.objects.create(
                    tournament=tournament,
                    phase=phase,
                    round_label=_round_name(len(prev) // 2),
                    bracket_pos=pos,
                    slot_span=2,
                    source_a=prev[i],
                    source_b=prev[i + 1],
                )
            )
        rounds.append(cur)

    # Finale 3°/4° posto: i perdenti delle semifinali (il turno con 2 partite).
    semis = next((r for r in rounds if len(r) == 2), None)
    if semis:
        Match.objects.create(
            tournament=tournament,
            phase=phase,
            round_label="Finale 3°/4°",
            bracket_pos=2,
            slot_span=2,
            source_a=semis[0],
            source_b=semis[1],
            source_a_role=Match.SourceRole.LOSER,
            source_b_role=Match.SourceRole.LOSER,
        )


def seed_brackets(tournament):
    """Crea le partite di gold e silver dai risultati dei gironi e le programma.

    Richiede che TUTTE le partite dei gironi siano concluse e un numero di gironi
    che dia un tabellone potenza di 2 (1, 2, 4 o 8 gironi).
    """
    group_matches = tournament.matches.filter(phase=Match.Phase.GROUP)
    if not group_matches.exists():
        raise ValueError("Genera prima la fase a gironi.")
    if group_matches.exclude(status=Match.Status.DONE).exists():
        raise ValueError("Tutte le partite dei gironi devono essere concluse.")

    groups = list(tournament.groups.order_by("name"))
    if not _is_power_of_two(2 * len(groups)):
        raise ValueError(
            f"Formato non supportato: con {len(groups)} gironi il tabellone non è una "
            "potenza di 2. Servono 1, 2, 4 o 8 gironi."
        )
    ranking = {g.id: group_ranking(g) for g in groups}

    tournament.matches.filter(phase__in=[Match.Phase.GOLD, Match.Phase.SILVER]).delete()

    # Gold = 1ª di ogni girone (teste di serie) poi 2ª; Silver = 3ª poi 4ª.
    gold = [ranking[g.id][0] for g in groups] + [ranking[g.id][1] for g in groups]
    _build_phase_bracket(tournament, Match.Phase.GOLD, gold)
    if all(len(ranking[g.id]) >= 4 for g in groups):
        silver = [ranking[g.id][2] for g in groups] + [ranking[g.id][3] for g in groups]
        _build_phase_bracket(tournament, Match.Phase.SILVER, silver)

    schedule_knockout(tournament)


def _knockout_round_groups(tournament):
    """Turni knockout in ordine di gioco (gold e silver in parallelo). Finale e
    finale 3°/4° posto giocano insieme nello stesso turno."""
    present = set(
        tournament.matches.filter(
            phase__in=[Match.Phase.GOLD, Match.Phase.SILVER]
        ).values_list("round_label", flat=True)
    )
    groups = [[lbl] for lbl in _ROUND_SEQUENCE if lbl in present]
    finals = [lbl for lbl in ("Finale", "Finale 3°/4°") if lbl in present]
    if finals:
        groups.append(finals)
    return groups


def schedule_knockout(tournament):
    """Assegna campo, slot e orario alle partite knockout, rispettando slot_span=2.

    Ritorna il numero totale di slot occupati (gironi + knockout).
    """
    courts = list(tournament.courts.order_by("number"))
    slot = _group_stage_slots(tournament)

    for labels in _knockout_round_groups(tournament):
        matches = list(
            tournament.matches.filter(
                phase__in=[Match.Phase.GOLD, Match.Phase.SILVER], round_label__in=labels
            ).order_by("phase", "bracket_pos")
        )
        # Spezza in blocchi grandi quanto i campi; ogni blocco occupa slot_span slot.
        for start in range(0, len(matches), len(courts)):
            chunk = matches[start : start + len(courts)]
            span = max(m.slot_span for m in chunk)
            for idx, m in enumerate(chunk):
                m.court = courts[idx]
                m.slot_index = slot
                m.scheduled_start = slot_start(tournament, slot)
                m.save(update_fields=["court", "slot_index", "scheduled_start"])
            slot += span
    return slot


def advance_bracket(match):
    """Propaga vincente/perdente di `match` nelle partite che ne dipendono.

    Se un team cambia in una partita a valle che era GIÀ stata giocata, quel risultato
    non è più valido: viene azzerato a cascata (set, vincitore, stato → programmata).
    Imposta `match._downstream_reset` = quante partite a valle sono state azzerate.
    """
    match._downstream_reset = 0
    if not match.is_played:
        return
    for dep in match.feeds_a.all():
        team = (
            match.loser if dep.source_a_role == Match.SourceRole.LOSER else match.winner
        )
        match._downstream_reset += _set_slot(dep, "team_a", team)
    for dep in match.feeds_b.all():
        team = (
            match.loser if dep.source_b_role == Match.SourceRole.LOSER else match.winner
        )
        match._downstream_reset += _set_slot(dep, "team_b", team)


def _set_slot(dep, field, team):
    """Mette `team` nello slot `field` (team_a/team_b) di `dep`.

    Se il valore cambia e `dep` aveva già un risultato, lo azzera e invalida a cascata
    tutto ciò che dipendeva da `dep`. Ritorna quante partite ha azzerato.
    """
    team_id = team.id if team else None
    if getattr(dep, f"{field}_id") == team_id:
        return 0  # nessun cambiamento

    setattr(dep, field, team)
    had_result = (
        dep.status == Match.Status.DONE
        or dep.winner_id is not None
        or dep.sets.exists()
    )
    reset = 0
    if had_result:
        dep.sets.all().delete()
        dep.winner = None
        dep.status = Match.Status.SCHEDULED
        reset = 1
    dep.save()

    if reset:  # i risultati a valle di dep non sono più validi
        for d in dep.feeds_a.all():
            reset += _set_slot(d, "team_a", None)
        for d in dep.feeds_b.all():
            reset += _set_slot(d, "team_b", None)
    return reset
