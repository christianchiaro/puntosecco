# Regole del torneo (`tournaments/`)

Caricate solo quando si lavora qui. Sono le regole di dominio di Punto Secco.

## Formato (default, parametrico nel modello `Tournament`)
- **12 coppie, 3 gironi (A-C) da 4**, 4 campi, slot da 25 min.
- **Gironi**: girone all'italiana → 6 partite/girone, 18 totali. Partita = **1 set**; sul 6-6 si gioca il **Punto Secco** (un solo punto, non un tie-break a punti - è la specialità del torneo). `slot_span=1`.
- **Knockout gold (8 squadre)**: prime 2 di ogni girone + 2 migliori terze (wild card) → quarti → semifinali → finale + 3°/4°. I **perdenti dei quarti** giocano la **consolazione 5°-8°** (2 semifinali → finale 5°/6° + 7°/8°), così tutte le 8 coppie hanno un piazzamento univoco.
- **Knockout silver (4 squadre)**: peggior terza + 3 quarte → semifinali → finale + 3°/4° (niente quarti, niente consolazione).
- Partita knockout = **1 set**, come i gironi (`slot_span=1`) - **eccetto** le finali
  1°/2° di **gold e silver** e la finale 3°/4° del **solo gold**, che si giocano
  **2 set + super tie-break a 10 se 1-1** (`slot_span=2`). La finale 3°/4° del **silver**
  resta 1 set. Unica fonte di verità: `Match.TWO_SET_MATCHES` (set di coppie
  `(phase, round_label)`) / `Match.is_two_set_match` in `models.py`, usata anche da
  `brackets.py` (slot_span alla creazione), `scoring.py` (validazione formato punteggio)
  e `_score_form.html` (quali input mostrare).
- **Classifica finale** (`/classifica/`, `awards.phase_classification`): divisa per tabellone - gold 1°-8°, silver 1°-4°.

## Timing
Slot assegnati dinamicamente da `schedule_knockout`. Per il formato a 12 (default, inizio
14:00): gironi 5 slot + knockout 5 slot (quarti 1, semifinali silver + consolazione 1,
semifinali gold + finali consolazione 1, finalissime 2) = **10 slot totali → fine torneo
alle 18:10**. Verificato empiricamente eseguendo lo scheduler, non calcolato a mano.

## Vincoli scheduler (`scheduling.py`) - coperti da test
- ogni coppia gioca tutte le altre del girone una volta;
- una coppia mai su due campi nello stesso slot; un campo una sola partita per slot;
- knockout: rispettare `slot_span` di ogni partita (1 o 2 a seconda del turno - vedi sopra;
  una partita blocca campo+coppie per `slot_span` slot consecutivi).

## Punteggio (`scoring.py`, modello `MatchSet`)
- Il punteggio vive nei `MatchSet` figli (1 per la maggior parte delle partite, fino a 3 per le finali - vedi `Match.is_two_set_match`; il 3° è il super TB, con i punti in `games_*`).
- Vincitore set: più game; a parità (6-6) decide il **Punto Secco** - un punto secco, non un tie-break
  tradizionale. `tiebreak_a`/`tiebreak_b` valgono 1 (vince)/0 (perde), non un punteggio reale; form:
  `set{i}_ps` = "a"/"b". Display: `MatchSet.display` mostra `"7-6 (PS)"`, mai un finto punteggio.
  Vincitore partita: più set vinti.
- `record_match_score(match, sets)` è l'unica via per registrare un risultato (crea i set, calcola il vincitore, segna DONE).

## Classifica girone - tiebreaker (in ordine)
1) vittorie → 2) scontro diretto → 3) differenza game → 4) game fatti.

## Seeding gold/silver
Incrocio per evitare le prime tra loro fino alla semifinale: **A1-B2, B1-A2, C1-D2, D1-C2** (gold);
stesso schema con 3ª/4ª per il silver.

## Moduli & flussi
- `setup.py`: `create_tournament` (torneo + campi + gironi) e `draw_groups` (sorteggio). Usati dalle viste
  `new_tournament` / `manage` (login **staff**) e dall'iscrizione pubblica `register`.
- `awards.py`: podio, achievement (Cappotto/Rimonta/Imbattuti), premi (Bomber…) per dashboard/Albo d'oro.
- **Walkover**: `scoring.record_walkover(match, winner)` → `Match.walkover=True`, vincitore senza set (`score_display="W.O."`).
- **Integrità knockout**: ri-segnare una partita già "consumata" azzera a cascata i risultati a valle
  (`brackets.advance_bracket` → `_set_slot`); il numero di partite azzerate è in `match._downstream_reset`.
- **Tabelloni generici** (`brackets.py`): `seed_brackets` supporta wild card. Se 2*num_groups
  non e' potenza di 2, completa il gold con le migliori terze classificate (vittorie/diff/gf).
  Esempio: 3 gironi x 4 = gold 8 (top-2x3 + 2 migliori terze), silver 4 (peggior terza + 3 quarte).
  Vincolo: `silver_size = total_teams - gold_size` deve essere 0 o potenza di 2.
- **Accountability** (`ScoreLog`): ogni modifica al punteggio è loggata (azione + dettaglio + IP) in
  `views._log_score`; registro pubblico `/registro/` (IP solo in admin). Iscrizione con honeypot antispam.
- **Modalità TV** (`/tv/`): kiosk standalone (no nav), polling 30s + **scene rotanti** ogni 15s
  (campi → classifiche → podio) con ticker "prossime" sempre visibile.
- **Celebrazioni**: la view manda eventi `celebrate`/`champion` via header `HX-Trigger`; i gestori JS
  (coriandoli `canvas-confetti`, overlay campione) stanno in `base.html`, registrati una volta sola.
