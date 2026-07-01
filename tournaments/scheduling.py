"""Generazione del calendario della fase a gironi.

Vincoli garantiti:
- ogni coppia gioca tutte le altre del proprio girone una volta (girone all'italiana);
- una coppia non gioca due partite nello stesso slot temporale;
- un campo ospita una sola partita per slot;
- le partite riempiono SEMPRE tutti i campi disponibili quando possibile (scheduling
  greedy "primo slot libero", non a blocchi per turno - vedi generate_group_stage).
"""

import datetime

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

    Scheduling greedy "primo slot libero": ogni partita viene assegnata al primo slot
    in cui entrambe le coppie sono libere, riempiendo sempre tutti i campi disponibili.
    Con un numero di gironi che non divide esattamente i campi (es. 3 gironi x 2
    partite/turno su 4 campi), un blocco "un turno = uno slot sincronizzato per tutti
    i gironi" lascerebbe campi vuoti a ogni turno incompleto; questo approccio invece
    non spreca mai un campo se esiste una partita valida per riempirlo.
    Tra piu' partite pronte nello stesso slot, preferisce quelle la cui coppia non ha
    gia' giocato nello slot immediatamente precedente (riduce, senza eliminarlo del
    tutto, il rischio di due turni consecutivi senza pausa: con gironi che non sono
    multiplo dei campi, alcuni turni di fila senza pausa sono matematicamente
    inevitabili se si vogliono riempire sempre tutti i campi).

    Ritorna il numero di slot temporali occupati dalla fase a gironi.
    """
    groups = list(tournament.groups.order_by("name"))
    courts = list(tournament.courts.order_by("number"))
    if not groups or not courts:
        raise ValueError("Servono gironi e campi prima di generare il calendario.")
    num_courts = len(courts)

    # Calcola i turni round-robin per ciascun girone (per l'etichetta T1/T2/... - una
    # coppia deve comunque finire il proprio turno N prima di iniziare il turno N+1,
    # lo garantisce automaticamente la disponibilita' per-coppia qui sotto).
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

    # Coda delle partite da programmare. I gironi ruotano ad ogni turno cosi' nessun
    # girone e' sempre "in coda" quando i campi si riempiono (equita' tra gironi).
    pending = []
    for r in range(max_rounds):
        rotated = groups[r % len(groups) :] + groups[: r % len(groups)]
        for g in rotated:
            rr = group_rounds[g.id]
            if r < len(rr):
                for a, b in rr[r]:
                    pending.append((g, f"T{r + 1}", a, b))

    team_free_at = {}
    team_last_slot = {}
    new_matches = []
    slot = 0
    max_slot_used = -1
    while pending:
        ready = [
            i
            for i, (g, label, a, b) in enumerate(pending)
            if team_free_at.get(a, 0) <= slot and team_free_at.get(b, 0) <= slot
        ]
        if not ready:
            slot += 1
            continue
        ready.sort(
            key=lambda i: (
                team_last_slot.get(pending[i][2]) == slot - 1
                or team_last_slot.get(pending[i][3]) == slot - 1,
                i,
            )
        )
        chosen, used_teams = [], set()
        for i in ready:
            if len(chosen) >= num_courts:
                break
            _, _, a, b = pending[i]
            if a in used_teams or b in used_teams:
                continue  # eviterebbe una coppia impegnata due volte nello stesso slot
            chosen.append(i)
            used_teams.add(a)
            used_teams.add(b)
        if not chosen:
            slot += 1
            continue
        for court_idx, i in enumerate(chosen):
            g, label, a, b = pending[i]
            new_matches.append(
                Match(
                    tournament=tournament,
                    phase=Match.Phase.GROUP,
                    group=g,
                    round_label=label,
                    court=courts[court_idx],
                    slot_index=slot,
                    scheduled_start=slot_start(tournament, slot),
                    team_a_id=a,
                    team_b_id=b,
                )
            )
            team_free_at[a] = team_free_at[b] = slot + 1
            team_last_slot[a] = team_last_slot[b] = slot
        max_slot_used = max(max_slot_used, slot)
        chosen_set = set(chosen)
        pending = [m for i, m in enumerate(pending) if i not in chosen_set]
        slot += 1

    Match.objects.bulk_create(new_matches)
    return max_slot_used + 1
