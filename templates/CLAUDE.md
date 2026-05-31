# Regole template (`templates/`)

Caricate solo quando si lavora qui. Per il dettaglio completo vedi l'agent `frontend-engineer`.

## Struttura
- `base.html` - layout root con i `{% block %}`.
- `<app>/` - template per pagina, una cartella per app Django.
- `<app>/partials/` - frammenti per HTMX, prefisso `_` (es. `_card_prodotto.html`).

## Regole rapide
- **hx-boost**: `base.html` ha `<body hx-boost="true">`. Tutte le pagine estendono `base.html`
  e ritornano HTML completo → HTTP puro e navigazione boosted danno lo **stesso DOM**.
- I partial NON estendono `base.html`: sono solo il frammento sostituito da `hx-swap`.
- **Stesso file per pagina e partial**: la pagina piena fa `{% include "app/partials/_x.html" %}`
  e la view di update ritorna lo **stesso** `_x.html`. Mai duplicare il markup.
- CSRF token presente per ogni richiesta non-GET (form boostati lo ereditano da `{% csrf_token %}`;
  per hx-* senza form usa l'`hx-headers` con `X-CSRFToken` impostato sul `<body>` in base.html).
- Alpine solo per stato UI (toggle/modali); i dati del server arrivano via HTMX.
