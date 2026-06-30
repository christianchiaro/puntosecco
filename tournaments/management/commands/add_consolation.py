"""Crea il tabellone di consolazione 5°-8° per un torneo i cui tabelloni erano stati
generati PRIMA dell'introduzione della consolazione.

Non distruttivo: non tocca le partite gold/silver esistenti (ne' i risultati gia'
inseriti). Crea solo le partite di consolazione mancanti, ricalcola gli slot e porta
i perdenti dei quarti gia' giocati dentro le semifinali di consolazione.

Uso:  python manage.py add_consolation <slug>
"""

from django.core.management.base import BaseCommand, CommandError

from tournaments.brackets import advance_bracket, build_consolation, schedule_knockout
from tournaments.models import Match, Tournament


class Command(BaseCommand):
    help = "Aggiunge la consolazione 5°-8° a un torneo gia' seedato (non distruttivo)."

    def add_arguments(self, parser):
        parser.add_argument("slug")

    def handle(self, *args, **opts):
        try:
            t = Tournament.objects.get(slug=opts["slug"])
        except Tournament.DoesNotExist:
            raise CommandError(f"Torneo '{opts['slug']}' non trovato.")

        created = 0
        for phase in (Match.Phase.GOLD, Match.Phase.SILVER):
            qf = list(
                t.matches.filter(phase=phase, round_label="Quarti").order_by(
                    "bracket_pos"
                )
            )
            if (
                len(qf) == 4
                and not t.matches.filter(
                    phase=phase, round_label="Semifinale 5°-8°"
                ).exists()
            ):
                build_consolation(t, phase, qf)
                created += 1

        if not created:
            self.stdout.write(
                "Niente da fare: consolazione gia' presente o nessun tabellone con quarti."
            )
            return

        # Assegna campo/slot alle nuove partite (ricalcola lo scheduling del knockout).
        schedule_knockout(t)
        # Porta i perdenti dei quarti gia' giocati nelle semifinali di consolazione.
        for m in t.matches.filter(round_label="Quarti", status=Match.Status.DONE):
            advance_bracket(m)

        self.stdout.write(
            self.style.SUCCESS(
                f"Consolazione creata per {created} tabellone/i di '{t.name}'."
            )
        )
