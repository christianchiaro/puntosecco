import datetime

from django.core.management.base import BaseCommand

from tournaments.brackets import seed_brackets
from tournaments.models import Court, Group, Match, Team, Tournament
from tournaments.scheduling import generate_group_stage
from tournaments.scoring import record_match_score

# 16 coppie (32 giocatori) di fantasia.
TEAMS = [
    ("Rossi/Bianchi", "M. Rossi", "L. Bianchi"),
    ("Verdi/Neri", "A. Verdi", "G. Neri"),
    ("Gialli/Blu", "F. Gialli", "S. Blu"),
    ("Ferrari/Conti", "P. Ferrari", "D. Conti"),
    ("Greco/Marino", "R. Greco", "T. Marino"),
    ("Romano/Costa", "E. Romano", "V. Costa"),
    ("Bruno/Gallo", "C. Bruno", "N. Gallo"),
    ("Fontana/Riva", "U. Fontana", "O. Riva"),
    ("Moretti/Barbieri", "I. Moretti", "Q. Barbieri"),
    ("Lombardi/Serra", "B. Lombardi", "H. Serra"),
    ("Galli/Rizzo", "Z. Galli", "Y. Rizzo"),
    ("Mancini/Longo", "W. Mancini", "X. Longo"),
    ("Martini/Leone", "J. Martini", "K. Leone"),
    ("Pellegrini/Sala", "M. Pellegrini", "L. Sala"),
    ("Caruso/Ferri", "A. Caruso", "G. Ferri"),
    ("Vitale/Monti", "F. Vitale", "S. Monti"),
]


class Command(BaseCommand):
    help = "Crea il torneo Punto Secco a 16 squadre con calendario gironi."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="punto-secco-2026")
        parser.add_argument("--reset", action="store_true", help="Cancella e ricrea il torneo")
        parser.add_argument(
            "--simulate",
            action="store_true",
            help="Gioca i gironi (vince il seed più basso), genera i tabelloni e mette i quarti in corso",
        )

    def handle(self, *args, **opts):
        slug = opts["slug"]
        if opts["reset"]:
            Tournament.objects.filter(slug=slug).delete()
        if Tournament.objects.filter(slug=slug).exists():
            self.stdout.write(self.style.WARNING(f"'{slug}' esiste già. Usa --reset per ricrearlo."))
            return

        t = Tournament.objects.create(
            name="Punto Secco",
            slug=slug,
            date=datetime.date(2026, 6, 6),
            status=Tournament.Status.GROUP,
        )
        for n in range(1, t.num_courts + 1):
            Court.objects.create(tournament=t, number=n)

        for gi, letter in enumerate("ABCD"):
            g = Group.objects.create(tournament=t, name=letter)
            for k in range(t.teams_per_group):
                name, p1, p2 = TEAMS[gi * t.teams_per_group + k]
                Team.objects.create(
                    tournament=t, group=g, seed=k + 1, name=name, player1=p1, player2=p2
                )

        generate_group_stage(t)
        self.stdout.write(self.style.SUCCESS(f"Creato '{t.name}' ({slug}): 16 coppie, gironi generati."))

        if opts["simulate"]:
            for m in t.matches.filter(phase=Match.Phase.GROUP):
                if m.team_a.seed <= m.team_b.seed:
                    record_match_score(m, [{"games_a": 6, "games_b": 2}])
                else:
                    record_match_score(m, [{"games_a": 2, "games_b": 6}])
            seed_brackets(t)
            t.status = Tournament.Status.KNOCKOUT
            t.save(update_fields=["status"])
            # Metti "in corso" i quarti del primo slot knockout.
            first_ko_slot = (
                t.matches.filter(phase__in=[Match.Phase.GOLD, Match.Phase.SILVER])
                .order_by("slot_index")
                .values_list("slot_index", flat=True)
                .first()
            )
            t.matches.filter(round_label="Quarti", slot_index=first_ko_slot).update(
                status=Match.Status.LIVE
            )
            self.stdout.write(self.style.SUCCESS("Simulazione: gironi giocati, tabelloni generati, quarti in corso."))
