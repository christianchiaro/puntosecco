# Regole del torneo (`tournaments/`)

Caricate solo quando si lavora qui. Sono le regole di dominio di Punto Secco.

## Formato (default, parametrico nel modello `Tournament`)
- **12 coppie, 3 gironi (A-C) da 4**, 4 campi, slot da 25 min.
- **Gironi**: girone all'italiana → 6 partite/girone, 18 totali. Partita = **1 set** con tie-break. `slot_span=1`.
- **Knockout gold (8 squadre)**: prime 2 di ogni girone + 2 migliori terze (wild card) → quarti → semifinali → finale + 3°/4°.
- **Knockout silver (4 squadre)**: peggior terza + 3 quarte → semifinali → finale + 3°/4° (niente quarti).
- Partita knockout = **2 set + super tie-break a 10 se 1-1**. `slot_span=2` (occupa 2 slot).

## Timing (entra esatto nei 14 slot)
Gironi 6 slot (3 turni × 2 slot) + quarti 4 + semifinali 2 + finali/3°-4° 2 = **14 slot**.

## Vincoli scheduler (`scheduling.py`) - coperti da test
- ogni coppia gioca tutte le altre del girone una volta;
- una coppia mai su due campi nello stesso slot; un campo una sola partita per slot;
- knockout: rispettare `slot_span=2` (una partita blocca campo+coppie per 2 slot consecutivi).

## Punteggio (`scoring.py`, modello `MatchSet`)
- Il punteggio vive nei `MatchSet` figli (1 per i gironi, fino a 3 nel knockout; il 3° è il super TB, con i punti in `games_*`).
- Vincitore set: più game; a parità decide il tie-break. Vincitore partita: più set vinti.
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
