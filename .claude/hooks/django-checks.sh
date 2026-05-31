#!/usr/bin/env bash
# Stop hook: prima che un task si consideri chiuso, verifica che il progetto Django sia sano.
#   1) nessuna migrazione mancante (modelli allineati allo schema)
#   2) la test suite passa
# No-op totale (exit 0, nessun blocco) se manage.py o python non esistono → non rompe un progetto vuoto.
# Se un check fallisce, emette {"decision":"block","reason":...} così il lavoro non si chiude con bug.
set -u

# Esegui dalla root del progetto (cwd dell'hook). Niente manage.py = niente Django ancora.
[ -f manage.py ] || exit 0

# Usa SEMPRE il python del venv del progetto (../reabita_venv); fallback su PATH.
VENV="${PUNTOSECCO_VENV:-../reabita_venv}"
PY="$VENV/bin/python"
[ -x "$PY" ] || PY=python
command -v "$PY" >/dev/null 2>&1 || PY=python3
command -v "$PY" >/dev/null 2>&1 || exit 0

reasons=""

# 1) Migrazioni mancanti: --check esce !=0 se ci sono modifiche ai modelli senza migrazione.
if ! "$PY" manage.py makemigrations --check --dry-run >/tmp/ps_migrations.log 2>&1; then
  reasons="${reasons}• Migrazioni mancanti: modelli modificati senza migrazione. Esegui 'python manage.py makemigrations'.\n"
fi

# 2) Test suite.
if ! "$PY" manage.py test >/tmp/ps_tests.log 2>&1; then
  reasons="${reasons}• Test falliti. Ultime righe:\n$(tail -n 25 /tmp/ps_tests.log)\n"
fi

# Nessun problema → lascia chiudere il task.
[ -z "$reasons" ] && exit 0

# Problemi → blocca lo Stop (richiede jq; se assente, fallback su exit 2 con messaggio su stderr).
if command -v jq >/dev/null 2>&1; then
  jq -n --arg r "$reasons" '{decision:"block", reason:("Definition of Done non soddisfatta:\n"+$r)}'
  exit 0
else
  printf 'Definition of Done non soddisfatta:\n%b' "$reasons" >&2
  exit 2
fi
