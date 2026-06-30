"""Tabelloni gold/silver: seeding dai gironi, scheduling a 2 slot, avanzamento vincenti.

Generico: il tabellone di ogni fase ha 2x(n gironi) coppie (gold = 1a/2a, silver = 3a/4a),
che deve essere una potenza di 2 -> 1, 2, 4 o 8 gironi. Seeding standard a incrocio: le teste
di serie (le 1a dei gironi) sono distribuite e si evitano fino in fondo al tabellone.
Supporta wild card per formati come 3 gironi x 4 squadre (gold = 8, silver = 4).
"""

from django.db.models import Q

from .models import Match
from .scheduling import slot_start
from .standings import group_ranking, group_standings, wildcard_spareggio

_ROUND_NAMES = {
    1: "Finale",
    2: "Semifinale",
    4: "Quarti",
    8: "Ottavi",
    16: "Sedicesimi",
}


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


def _ceil_power_of_two(n):
    """Smallest power of 2 >= n."""
    p = 1
    while p < n:
        p <<= 1
    return p


def _best_wild_cards(groups, standings_map, n):
    """Seleziona le n migliori terze (criteri: vittorie, diff game, game fatti, spareggio)."""
    thirds = []
    for g in groups:
        s = standings_map[g.id]
        if len(s) >= 3:
            thirds.append(s[2])
    thirds.sort(
        key=lambda s: (s["wins"], s["diff"], s["gf"], s["team"].spareggio), reverse=True
    )
    return [s["team"] for s in thirds[:n]]


def _build_phase_bracket(tournament, phase, seeds):
    """Costruisce un tabellone a eliminazione per `seeds` (lista di coppie in ordine di
    testa di serie, lunghezza potenza di 2). Crea anche la finale 3/4 posto."""
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

    # Finale 3/4 posto: i perdenti delle semifinali (il turno con 2 partite).
    semis = next((r for r in rounds if len(r) == 2), None)
    if semis:
        Match.objects.create(
            tournament=tournament,
            phase=phase,
            round_label="Finale 3\xb0/4\xb0",
            bracket_pos=2,
            slot_span=2,
            source_a=semis[0],
            source_b=semis[1],
            source_a_role=Match.SourceRole.LOSER,
            source_b_role=Match.SourceRole.LOSER,
        )

    # Consolazione 5\xb0-8\xb0: se il primo turno sono i quarti (4 partite), i 4 perdenti
    # si giocano i piazzamenti. Cosi' tutte le coppie del tabellone hanno un posto univoco.
    build_consolation(tournament, phase, rounds[0])


def build_consolation(tournament, phase, qf):
    """Crea il tabellone di consolazione 5\xb0-8\xb0 dai 4 quarti `qf`: 2 semifinali coi
    perdenti dei quarti, poi finale 5\xb0/6\xb0 e finale 7\xb0/8\xb0. No-op se non ci sono 4 quarti
    o se la consolazione esiste gia' (idempotente)."""
    if len(qf) != 4:
        return
    if tournament.matches.filter(
        phase=phase, round_label="Semifinale 5\xb0-8\xb0"
    ).exists():
        return
    loser = Match.SourceRole.LOSER
    cons_sf = []
    for pos, (a, b) in enumerate(((qf[0], qf[1]), (qf[2], qf[3])), start=1):
        cons_sf.append(
            Match.objects.create(
                tournament=tournament,
                phase=phase,
                round_label="Semifinale 5\xb0-8\xb0",
                bracket_pos=pos,
                slot_span=2,
                source_a=a,
                source_a_role=loser,
                source_b=b,
                source_b_role=loser,
            )
        )
    Match.objects.create(
        tournament=tournament,
        phase=phase,
        round_label="Finale 5\xb0/6\xb0",
        bracket_pos=1,
        slot_span=2,
        source_a=cons_sf[0],
        source_b=cons_sf[1],
    )
    Match.objects.create(
        tournament=tournament,
        phase=phase,
        round_label="Finale 7\xb0/8\xb0",
        bracket_pos=2,
        slot_span=2,
        source_a=cons_sf[0],
        source_a_role=loser,
        source_b=cons_sf[1],
        source_b_role=loser,
    )


def seed_brackets(tournament):
    """Crea le partite di gold e silver dai risultati dei gironi e le programma.

    Supporta formati con wild card: se 2*num_groups non e' potenza di 2, completa il gold
    con le migliori terze classificate e manda le rimanenti in silver.
    Richiede che TUTTE le partite dei gironi siano concluse.
    """
    group_matches = tournament.matches.filter(phase=Match.Phase.GROUP)
    if not group_matches.exists():
        raise ValueError("Genera prima la fase a gironi.")
    if group_matches.exclude(status=Match.Status.DONE).exists():
        raise ValueError("Tutte le partite dei gironi devono essere concluse.")

    groups = list(tournament.groups.order_by("name"))
    num_groups = len(groups)
    total_teams = tournament.num_teams

    gold_size = _ceil_power_of_two(num_groups * 2)
    silver_size = total_teams - gold_size

    if gold_size > total_teams:
        raise ValueError(
            f"Formato non supportato: con {num_groups} gironi servirebbero {gold_size} "
            f"squadre in gold ma il torneo ne ha solo {total_teams}."
        )
    if silver_size > 0 and not _is_power_of_two(silver_size):
        raise ValueError(
            f"Formato non supportato: con {num_groups} gironi il silver avrebbe "
            f"{silver_size} squadre (non una potenza di 2)."
        )

    wild_cards_needed = gold_size - num_groups * 2

    ranking = {g.id: group_ranking(g) for g in groups}
    standings_map = (
        {g.id: group_standings(g) for g in groups} if wild_cards_needed > 0 else {}
    )

    if wild_cards_needed > 0:
        pending = wildcard_spareggio(groups, standings_map)
        if pending:
            names = " / ".join(t.name for t in pending["teams"])
            raise ValueError(
                "C'è uno spareggio da risolvere prima di generare i tabelloni: "
                f"{names} sono a pari merito per l'ultimo posto gold."
            )

    tournament.matches.filter(phase__in=[Match.Phase.GOLD, Match.Phase.SILVER]).delete()

    top1 = [ranking[g.id][0] for g in groups]
    top2 = [ranking[g.id][1] for g in groups]

    if wild_cards_needed > 0:
        wild_cards = _best_wild_cards(groups, standings_map, wild_cards_needed)
        gold = top1 + top2 + wild_cards
    else:
        gold = top1 + top2

    _build_phase_bracket(tournament, Match.Phase.GOLD, gold)

    if silver_size > 0:
        gold_ids = {t.id for t in gold}
        silver_thirds = []
        silver_fourths = []
        for g in groups:
            rank = ranking[g.id]
            if len(rank) >= 3 and rank[2].id not in gold_ids:
                silver_thirds.append(rank[2])
            if len(rank) >= 4:
                silver_fourths.append(rank[3])
        silver = silver_thirds + silver_fourths
        _build_phase_bracket(tournament, Match.Phase.SILVER, silver[:silver_size])

    schedule_knockout(tournament)


def _knockout_round_groups(tournament):
    """Blocchi del knockout in ordine di gioco. Ogni blocco gioca in contemporanea,
    riempiendo i campi. Ritorna liste di selettori `(phase|None, round_label)`
    (phase None = entrambi i tabelloni).

    Pianificazione (riempie 4 campi a turno, finalissime a chiudere):
      quarti
      → semifinali SILVER + semifinali di consolazione (5°-8°)
      → semifinali GOLD + finali di consolazione (5°/6° e 7°/8°)
      → finali 1°/2° e 3°/4° di entrambi i tabelloni.
    Le semifinali silver (indipendenti dai quarti gold) anticipano per liberare l'ultimo
    turno alle sole finalissime; le finali di consolazione si giocano un turno prima.
    """
    gold, silver = Match.Phase.GOLD, Match.Phase.SILVER
    present = set(
        tournament.matches.filter(phase__in=[gold, silver]).values_list(
            "phase", "round_label"
        )
    )
    labels = {label for _, label in present}
    has_consolation = any(
        label in ("Semifinale 5\xb0-8\xb0", "Finale 5\xb0/6\xb0", "Finale 7\xb0/8\xb0")
        for label in labels
    )

    blocks = []
    for label in ("Sedicesimi", "Ottavi", "Quarti"):
        if label in labels:
            blocks.append([(None, label)])

    if has_consolation:
        secondary = []  # semifinali silver + semifinali di consolazione
        if (silver, "Semifinale") in present:
            secondary.append((silver, "Semifinale"))
        if "Semifinale 5\xb0-8\xb0" in labels:
            secondary.append((None, "Semifinale 5\xb0-8\xb0"))
        if secondary:
            blocks.append(secondary)
        gold_semi = []  # semifinali gold + finali di consolazione
        if (gold, "Semifinale") in present:
            gold_semi.append((gold, "Semifinale"))
        gold_semi += [
            (None, label)
            for label in ("Finale 5\xb0/6\xb0", "Finale 7\xb0/8\xb0")
            if label in labels
        ]
        if gold_semi:
            blocks.append(gold_semi)
    elif "Semifinale" in labels:
        blocks.append([(None, "Semifinale")])

    finals = [
        (None, label) for label in ("Finale", "Finale 3\xb0/4\xb0") if label in labels
    ]
    if finals:
        blocks.append(finals)
    return blocks


def schedule_knockout(tournament):
    """Assegna campo, slot e orario alle partite knockout, rispettando slot_span=2.

    Ritorna il numero totale di slot occupati (gironi + knockout).
    """
    courts = list(tournament.courts.order_by("number"))
    slot = _group_stage_slots(tournament)

    for block in _knockout_round_groups(tournament):
        q = Q()
        for phase, label in block:
            q |= (
                Q(round_label=label)
                if phase is None
                else Q(phase=phase, round_label=label)
            )
        matches = list(
            tournament.matches.filter(q).order_by("round_label", "phase", "bracket_pos")
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

    Se un team cambia in una partita a valle che era GIA' stata giocata, quel risultato
    non e' piu' valido: viene azzerato a cascata (set, vincitore, stato -> programmata).
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

    Se il valore cambia e `dep` aveva gia' un risultato, lo azzera e invalida a cascata
    tutto cio' che dipendeva da `dep`. Ritorna quante partite ha azzerato.
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

    if reset:  # i risultati a valle di dep non sono piu' validi
        for d in dep.feeds_a.all():
            reset += _set_slot(d, "team_a", None)
        for d in dep.feeds_b.all():
            reset += _set_slot(d, "team_b", None)
    return reset
