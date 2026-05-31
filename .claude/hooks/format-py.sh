#!/usr/bin/env bash
# PostToolUse: linta+formatta il file .py appena modificato.
# No-op silenzioso se: input non parsabile, file non .py, file assente, ruff/black non installati.
set -u

file="$(jq -r '.tool_input.file_path // .tool_response.filePath // empty' 2>/dev/null)"
[ -z "$file" ] && exit 0
case "$file" in
  *.py) ;;
  *)    exit 0 ;;
esac
[ -f "$file" ] || exit 0

# Gli hook girano in una shell SENZA venv attivo: punta ai binari del venv del progetto,
# con fallback sul PATH. Il venv vive in ../reabita_venv rispetto alla root del progetto.
VENV="${PUNTOSECCO_VENV:-../reabita_venv}"
RUFF="$VENV/bin/ruff";  [ -x "$RUFF" ]  || RUFF="$(command -v ruff  2>/dev/null)"
BLACK="$VENV/bin/black"; [ -x "$BLACK" ] || BLACK="$(command -v black 2>/dev/null)"

# ruff come linter (autofix), black come formatter. Ognuno gira solo se disponibile.
[ -n "$RUFF" ]  && "$RUFF"  check --fix "$file" >/dev/null 2>&1
[ -n "$BLACK" ] && "$BLACK" "$file"             >/dev/null 2>&1

exit 0
