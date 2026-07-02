# Animazioni Lottie - premiazioni

Animazioni delle **Noto Animated Emoji** di Google, scaricate da
`https://fonts.gstatic.com/s/e/notoemoji/latest/<codepoint>/lottie.json`
e servite in locale via whitenoise (nessuna dipendenza CDN a runtime).

Licenza: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) -
Google, [Noto Animated Emoji](https://googlefonts.github.io/noto-emoji-animation/).

Gold = premi veri; Silver = sfotto' bonario, via via piu' carino salendo di posizione.

| File | Emoji | Codepoint | Uso (premiazioni) |
|------|-------|-----------|-------------------|
| trophy.json | 🏆 | 1f3c6 | Gold 1° posto (campione) |
| medal-silver.json | 🥈 | 1f948 | Gold 2° posto |
| medal-bronze.json | 🥉 | 1f949 | Gold 3° posto |
| fire.json | 🔥 | 1f525 | Gold 4° posto |
| biceps.json | 💪 | 1f4aa | Gold 5°/6° posto |
| clap.json | 👏 | 1f44f | Gold 7° posto |
| poop.json | 💩 | 1f4a9 | ultimo posto di ogni tabellone (Gold 8°, Silver 4°) |
| clown.json | 🤡 | 1f921 | Silver 3° posto |
| snail.json | 🐌 | 1f40c | Silver 2° posto |
| crown.json | 👑 | 1f451 | Silver 1° posto ("re del Silver") |
| medal-gold.json | 🥇 | 1f947 | (riserva, non piu' usata) |
| party.json | 🎉 | 1f389 | (riserva, non ancora usata) |
| raising-hands.json | 🙌 | 1f64c | (riserva, non ancora usata) |
| confetti-ball.json | 🎊 | 1f38a | (riserva, non ancora usata) |
| sweat-smile.json | 😅 | 1f605 | (riserva, non ancora usata) |
| smiling-tear.json | 🥲 | 1f972 | (riserva, non ancora usata) |
| turtle.json | 🐢 | 1f422 | (riserva, non ancora usata) |

La mappatura piazzamento → animazione vive in `tournaments/views.py::_premio_anim`.
