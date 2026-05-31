"""Registrazione del punteggio e calcolo del vincitore.

API unica per gironi (1 set) e knockout (2 set + super tie-break al terzo se 1-1).
"""

from .models import Match, MatchSet


def set_winner_side(games_a, games_b, tiebreak_a=None, tiebreak_b=None):
    """'a' / 'b' / None (None solo se davvero indecidibile)."""
    if games_a > games_b:
        return "a"
    if games_b > games_a:
        return "b"
    if tiebreak_a is not None and tiebreak_b is not None:
        if tiebreak_a > tiebreak_b:
            return "a"
        if tiebreak_b > tiebreak_a:
            return "b"
    return None


def _validate_set_format(i, ga, gb, is_super_tb):
    """Controlla che un set concluso sia un punteggio valido. Solleva ValueError se no."""
    hi, lo = max(ga, gb), min(ga, gb)
    if is_super_tb:
        # Super tie-break: primo a 10 con almeno 2 di scarto (10-8, 11-9, ...).
        if not (hi >= 10 and hi - lo >= 2):
            raise ValueError("Super tie-break: serve almeno 10 punti con 2 di scarto.")
        return
    # Set normale: 6-0..6-4, 7-5 o 7-6.
    if not ((hi == 6 and lo <= 4) or (hi == 7 and lo in (5, 6))):
        raise ValueError(f"Set {i}: punteggio non valido (ammessi 6-0..6-4, 7-5, 7-6).")


def sets_from_post(match, post, partial=False):
    """Costruisce e valida la lista di set dai dati del form (`request.POST`).

    Campi attesi: set{i}_a, set{i}_b, set{i}_ta, set{i}_tb (i = 1..3).
    Con `partial=True` (punteggio in corso) NON si pretende un vincitore di set né
    la decisività del match: si accetta un set ancora in gioco (es. 3-2).
    Solleva ValueError con messaggio leggibile se il punteggio non è valido.
    """
    max_sets = 3 if match.is_knockout else 1
    sets = []
    for i in range(1, max_sets + 1):
        raw_a = (post.get(f"set{i}_a") or "").strip()
        raw_b = (post.get(f"set{i}_b") or "").strip()
        if raw_a == "" and raw_b == "":
            continue  # set non compilato
        if raw_a == "" or raw_b == "":
            raise ValueError(f"Set {i}: inserisci entrambi i punteggi.")
        try:
            ga, gb = int(raw_a), int(raw_b)
        except ValueError:
            raise ValueError(f"Set {i}: i punteggi devono essere numeri.")
        if ga < 0 or gb < 0:
            raise ValueError(f"Set {i}: i punteggi non possono essere negativi.")

        raw_ta = (post.get(f"set{i}_ta") or "").strip()
        raw_tb = (post.get(f"set{i}_tb") or "").strip()
        ta = int(raw_ta) if raw_ta else None
        tb = int(raw_tb) if raw_tb else None

        if not partial:
            if set_winner_side(ga, gb, ta, tb) is None:
                raise ValueError(f"Set {i}: deve esserci un vincitore (a parità di game serve il tie-break).")
            _validate_set_format(i, ga, gb, is_super_tb=(match.is_knockout and i == 3))
        sets.append({"games_a": ga, "games_b": gb, "tiebreak_a": ta, "tiebreak_b": tb})

    if not sets:
        raise ValueError("Inserisci almeno un set.")

    if not partial and match.is_knockout:
        a = sum(1 for s in sets if set_winner_side(s["games_a"], s["games_b"], s["tiebreak_a"], s["tiebreak_b"]) == "a")
        b = len(sets) - a
        if max(a, b) < 2:
            raise ValueError("Servono 2 set vinti: se è 1-1 inserisci il super tie-break.")

    return sets


def record_match_score(match, sets, finalize=True):
    """Registra i set della partita.

    `sets`: lista di dict {games_a, games_b, tiebreak_a?, tiebreak_b?} in ordine.
    Sostituisce eventuali set esistenti.
    - finalize=True: calcola il vincitore, segna DONE e fa avanzare il tabellone.
    - finalize=False (parziale): tiene la partita "in corso", nessun vincitore.
    Ritorna la partita aggiornata.
    """
    match.sets.all().delete()

    a_sets = b_sets = 0
    objs = []
    for i, s in enumerate(sets, start=1):
        ta, tb = s.get("tiebreak_a"), s.get("tiebreak_b")
        objs.append(
            MatchSet(
                match=match,
                number=i,
                games_a=s["games_a"],
                games_b=s["games_b"],
                tiebreak_a=ta,
                tiebreak_b=tb,
            )
        )
        side = set_winner_side(s["games_a"], s["games_b"], ta, tb)
        if side == "a":
            a_sets += 1
        elif side == "b":
            b_sets += 1
    MatchSet.objects.bulk_create(objs)

    match.walkover = False  # un punteggio normale annulla un eventuale W.O. precedente

    if not finalize:
        # Punteggio parziale: la partita resta in corso, senza vincitore.
        match.winner = None
        match.status = Match.Status.LIVE
        match.save(update_fields=["winner", "status", "walkover"])
        return match

    if a_sets > b_sets:
        match.winner = match.team_a
    elif b_sets > a_sets:
        match.winner = match.team_b
    else:
        match.winner = None
    match.status = Match.Status.DONE
    match.save(update_fields=["winner", "status", "walkover"])

    # Knockout: propaga vincente/perdente nelle partite dipendenti.
    from .brackets import advance_bracket

    advance_bracket(match)
    return match


def record_walkover(match, winner):
    """Vittoria a tavolino: `winner` passa senza set giocati (ritirata avversaria)."""
    match.sets.all().delete()
    match.walkover = True
    match.winner = winner
    match.status = Match.Status.DONE
    match.save(update_fields=["walkover", "winner", "status"])

    from .brackets import advance_bracket

    advance_bracket(match)
    return match
