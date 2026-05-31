# Punto Secco

Web app - **Django + HTMX + Alpine.js**. Server-rendered, hypermedia-first.

## Stack
- **Backend / templating**: Django (Python), template Django server-rendered
- **Interazioni server**: HTMX (partial render via attributi `hx-*`)
- **Stato UI locale**: Alpine.js (`x-data`, `x-show`, ...) - solo client-side leggero

## Virtualenv (OBBLIGATORIO)
Usa **sempre** il venv del progetto: `../reabita_venv` (Python 3.12). Mai il python di sistema.
Prefissa ogni comando con `../reabita_venv/bin/python` (es. `../reabita_venv/bin/python manage.py ...`).
Non installare pacchetti senza necessità: il venv ha già Django 5.1, django-htmx, whitenoise,
python-dotenv, widget-tweaks, ruff, black, segno (QR code).

## Comandi
- `../reabita_venv/bin/python manage.py runserver` - dev server
- `../reabita_venv/bin/python manage.py makemigrations` / `migrate` - migrazioni
- `../reabita_venv/bin/python manage.py test` - esegui i test
- `../reabita_venv/bin/python manage.py collectstatic` - static per il deploy
- `../reabita_venv/bin/python manage.py shell` - shell Django

## Deployment: PythonAnywhere
Target di produzione = **PythonAnywhere**. Tienilo a mente in ogni scelta:
- **WSGI**: l'app gira via il WSGI file di PythonAnywhere → `config/wsgi.py` deve restare standard.
- **Static**: serviti con **whitenoise** (`STATIC_ROOT` + `collectstatic`); niente build JS.
  HTMX e Alpine via **CDN**, nessun bundler/npm. Lo storage con manifest (nomi hashati) è
  gated da `USE_MANIFEST_STATIC=True` nel `.env` di prod (richiede `collectstatic` già eseguito);
  in dev/test resta lo storage senza manifest, altrimenti i test falliscono.
- **Config da env** (`.env` + python-dotenv): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`.
  `DEBUG=False` e `ALLOWED_HOSTS` con `*.pythonanywhere.com` in produzione. `.env` NON committato.
- **DB**: SQLite per iniziare (ok su PythonAnywhere).

## Il team (subagents in `.claude/agents/`)
Delega il lavoro all'engineer giusto invece di fare tutto in questo contesto:

| Engineer | Quando |
|----------|--------|
| **backend-engineer** | modelli, view, URL, ORM, migrazioni, form, auth |
| **frontend-engineer** | template, HTMX, Alpine.js, markup, CSS |
| **code-reviewer** | review della diff prima del commit (read-only) |
| **test-engineer** | scrive ed esegue test, verifica i fix |
| **qa-engineer** | verifica la feature nel **browser reale** come un utente, e lo dimostra |

Le **regole dettagliate** di ogni ruolo stanno dentro il rispettivo file agent → si
caricano solo quando l'agent gira, mantenendo questo contesto leggero.

## CLAUDE.md annidati
Aggiungi un `CLAUDE.md` dentro una cartella per regole locali caricate solo lì:
- `templates/CLAUDE.md` - convenzioni template/HTMX/Alpine
- `<app>/CLAUDE.md` - convenzioni della singola app Django (quando la crei)

## Workflow per ogni task (Definition of Done)
Questi passi vanno seguiti per **ogni** modifica, in ordine. Niente task è "finito"
finché non li ha superati tutti. Serve a tenere i bug al minimo.

1. **Capire** - leggi il codice esistente nella zona toccata; riusa i pattern presenti.
   Non scrivere prima di aver capito cosa c'è.
2. **Implementare** - modifica minima e coerente. Delega all'engineer giusto
   (`backend-engineer` / `frontend-engineer`).
3. **Migrazioni** - se sono cambiati i modelli: `makemigrations` + `migrate`.
   Non lasciare modelli e schema disallineati.
4. **Review** - `code-reviewer` sulla diff. Blocca su: CSRF, N+1, `|safe` su input,
   permessi mancanti, partial HTMX corretti. I rilievi 🔴/🟠 si risolvono prima di proseguire.
5. **Test** - `test-engineer` scrive/aggiorna i test ed **esegue** `manage.py test`.
   Devono passare davvero (output reale, non assunto).
6. **Verifica browser (obbligatoria per ogni nuova feature)** - il `qa-engineer` avvia l'app
   e **rifà lo user flow nel browser reale** (clic, form, invio), dimostrando con snapshot DOM +
   screenshot che funziona. Verifica anche che la navigazione **hx-boost** dia lo **stesso DOM**
   della URL aperta a freddo. Una feature non è "fatta" finché il qa-engineer non dà ✅ PASS.
7. **Riepilogo** - cosa è cambiato, cosa è stato testato, esito della verifica browser, cosa resta aperto.

> Salta un passo solo se palesemente non applicabile (es. niente migrazioni se non
> hai toccato i modelli) e dichiara esplicitamente perché lo salti.

**Enforced via hook** (`.claude/settings.json`):
- *PostToolUse* → `ruff` + `black` sui file `.py` appena modificati (no-op se non installati).
- *Stop* → blocca la chiusura del task se ci sono migrazioni mancanti o test che falliscono
  (`.claude/hooks/django-checks.sh`; no-op finché non esiste `manage.py`).

## Principi
- **Hypermedia-first**: la logica sta sul server, l'HTML è la fonte di verità.
- **hx-boost ovunque**: `<body hx-boost="true">` in `base.html`. Ogni view ritorna la
  **pagina intera** che estende `base.html`; con boost htmx scambia solo il `<body>`, quindi
  **HTTP puro e richiesta boosted producono lo stesso DOM finale**. Obiettivo invariante:
  *la stessa URL deve dare lo stesso DOM sia aperta a freddo sia raggiunta via boost*.
- **Partial = stesso file**: per un aggiornamento parziale mirato (`hx-get`/`hx-post` con
  `hx-target`), la view ritorna **lo stesso `_partial.html`** che la pagina piena `{% include %}`.
  Mai duplicare il markup tra pagina e partial → così il DOM resta identico per costruzione.
- HTMX per ciò che tocca il server; Alpine.js *solo* per stato UI effimero.
- Niente API JSON per la UI salvo richiesta esplicita.
- "Locality of behaviour": il comportamento di un elemento è visibile nel suo markup.
- **Trattino**: usa sempre `-` (mai `—` em-dash né `–` en-dash), in tutto il testo UI, messaggi e docs.
