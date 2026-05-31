"""Generazione del calendario della fase a gironi.

Vincoli garantiti:
- ogni coppia gioca tutte le altre del proprio girone una volta (girone all'italiana);
- una coppia non gioca due partite nello stesso slot temporale;
- un campo ospita una sola partita per slot;
- le partite riempiono i campi disponibili, slot dopo slot.
"""

import datetime
import math

from django.utils import timezone

from .models import Match


def round_robin_rounds(team_ids):
    """Circle method. Ritorna una lista di turni; ogni turno è una lista di coppie (a, b).

    Per N pari → N-1 turni, ogni coppia gioca una volta per turno.
    """
    teams = list(team_ids)
    if len(teams) % 2:
        teams.append(None)  # bye per numero dispari
    n = len(teams)
    arr = teams[:]
    rounds = []
    for _ in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = arr[i], arr[n - 1 - i]
            if a is not None and b is not None:
                pairs.append((a, b))
        rounds.append(pairs)
        # ruota tenendo fisso il primo elemento
        arr = [arr[0]] + [arr[-1]] + arr[1:-1]
    return rounds


def slot_start(tournament, slot_index):
    base = datetime.datetime.combine(tournament.date, tournament.start_time)
    base += datetime.timedelta(minutes=slot_index * tournament.slot_minutes)
    return timezone.make_aware(base)


def generate_group_stage(tournament):
    """(Ri)genera le partite dei gironi. Idempotente: cancella le precedenti GROUP.

    Ritorna il numero di slot temporali occupati dalla fase a gironi.
    """
    groups = list(tournament.groups.order_by("name"))
    courts = list(tournament.courts.order_by("number"))
    if not groups or not courts:
        raise ValueError("Servono gironi e campi prima di generare il calendario.")

    # Calcola i turni round-robin per ciascun girone.
    group_rounds = {}
    max_rounds = 0
    for g in groups:
        team_ids = list(g.teams.order_by("seed", "id").values_list("id", flat=True))
        if len(team_ids) < 2:
            raise ValueError(f"Il girone {g.name} ha meno di 2 coppie.")
        rr = round_robin_rounds(team_ids)
        group_rounds[g.id] = rr
        max_rounds = max(max_rounds, len(rr))

    # Reset partite gironi esistenti.
    tournament.matches.filter(phase=Match.Phase.GROUP).delete()

    new_matches = []
    slot = 0
    for r in range(max_rounds):
        # Tutte le partite di questo turno, su tutti i gironi.
        round_matches = []
        for g in groups:
            rr = group_rounds[g.id]
            if r < len(rr):
                for (a, b) in rr[r]:
                    round_matches.append((g, a, b))

        # Distribuisci sui campi; quando i campi finiscono, passa allo slot successivo.
        for idx, (g, a, b) in enumerate(round_matches):
            court = courts[idx % len(courts)]
            cur_slot = slot + idx // len(courts)
            new_matches.append(
                Match(
                    tournament=tournament,
                    phase=Match.Phase.GROUP,
                    group=g,
                    round_label=f"T{r + 1}",
                    court=court,
                    slot_index=cur_slot,
                    scheduled_start=slot_start(tournament, cur_slot),
                    team_a_id=a,
                    team_b_id=b,
                )
            )
        slot += math.ceil(len(round_matches) / len(courts))

    Match.objects.bulk_create(new_matches)
    return slot
