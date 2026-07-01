from datetime import time

from django.db import models


class Tournament(models.Model):
    """Un'edizione del torneo. Parametrico: campi/slot/gironi configurabili."""

    class Status(models.TextChoices):
        SETUP = "setup", "Setup"
        GROUP = "group", "Fase a gironi"
        KNOCKOUT = "knockout", "Eliminazione diretta"
        DONE = "done", "Concluso"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    date = models.DateField()
    start_time = models.TimeField(default=time(14, 0))
    num_courts = models.PositiveSmallIntegerField(default=4)
    slot_minutes = models.PositiveSmallIntegerField(default=25)
    num_groups = models.PositiveSmallIntegerField(default=3)
    teams_per_group = models.PositiveSmallIntegerField(default=4)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.SETUP
    )

    class Meta:
        ordering = ["-date", "name"]

    def __str__(self):
        return self.name

    @property
    def num_teams(self):
        return self.num_groups * self.teams_per_group


class Court(models.Model):
    tournament = models.ForeignKey(
        Tournament, related_name="courts", on_delete=models.CASCADE
    )
    number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=50, blank=True)

    class Meta:
        unique_together = [("tournament", "number")]
        ordering = ["tournament", "number"]

    def __str__(self):
        return self.name or f"Campo {self.number}"


class Group(models.Model):
    tournament = models.ForeignKey(
        Tournament, related_name="groups", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=2)  # A, B, C, D

    class Meta:
        unique_together = [("tournament", "name")]
        ordering = ["tournament", "name"]

    def __str__(self):
        return f"Girone {self.name}"


class Team(models.Model):
    """La coppia di padel."""

    tournament = models.ForeignKey(
        Tournament, related_name="teams", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=120)
    player1 = models.CharField(max_length=80)
    player2 = models.CharField(max_length=80)
    seed = models.PositiveSmallIntegerField(null=True, blank=True)
    group = models.ForeignKey(
        Group, null=True, blank=True, related_name="teams", on_delete=models.SET_NULL
    )
    # Esito spareggio tra terze a pari merito per l'ultimo posto gold: più alto = passa.
    # Conta solo come ultimo criterio quando vittorie/diff/game sono identici.
    spareggio = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["group__name", "seed", "name"]

    def __str__(self):
        return self.name


class Match(models.Model):
    """Una partita. Gironi (team fissi) o knockout (team alimentati dai vincenti)."""

    class Phase(models.TextChoices):
        GROUP = "group", "Girone"
        GOLD = "gold", "Gold"
        SILVER = "silver", "Silver"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programmata"
        LIVE = "live", "In corso"
        DONE = "done", "Finita"

    tournament = models.ForeignKey(
        Tournament, related_name="matches", on_delete=models.CASCADE
    )
    phase = models.CharField(max_length=8, choices=Phase.choices)
    group = models.ForeignKey(
        Group, null=True, blank=True, related_name="matches", on_delete=models.CASCADE
    )
    # Etichetta turno: "T1" per i gironi, "Quarti"/"Semifinale"/"Finale"/"Finale 3°-4°" per il knockout.
    round_label = models.CharField(max_length=40, blank=True)
    bracket_pos = models.PositiveSmallIntegerField(null=True, blank=True)

    # Scheduling
    court = models.ForeignKey(
        Court, null=True, blank=True, related_name="matches", on_delete=models.SET_NULL
    )
    slot_index = models.PositiveSmallIntegerField(null=True, blank=True)
    # Quanti slot temporali occupa: 1 per i gironi (un set), 2 dai quarti (due set).
    slot_span = models.PositiveSmallIntegerField(default=1)
    scheduled_start = models.DateTimeField(null=True, blank=True)

    # Coppie (null nel knockout finché non sono note)
    team_a = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        related_name="matches_as_a",
        on_delete=models.SET_NULL,
    )
    team_b = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        related_name="matches_as_b",
        on_delete=models.SET_NULL,
    )

    # Il punteggio vive nei MatchSet figli (1 set per i gironi, fino a 3 nel knockout).
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.SCHEDULED
    )
    winner = models.ForeignKey(
        Team,
        null=True,
        blank=True,
        related_name="matches_won",
        on_delete=models.SET_NULL,
    )
    # Vittoria a tavolino (ritirata dell'avversaria): vincitore senza set giocati.
    walkover = models.BooleanField(default=False)

    # Knockout: team_a viene da source_a, team_b da source_b. Il "ruolo" dice se prendere
    # il vincente (semifinale → finale) o il perdente (semifinale → finale 3°/4° posto).
    class SourceRole(models.TextChoices):
        WINNER = "winner", "Vincente"
        LOSER = "loser", "Perdente"

    source_a = models.ForeignKey(
        "self", null=True, blank=True, related_name="feeds_a", on_delete=models.SET_NULL
    )
    source_a_role = models.CharField(
        max_length=6, choices=SourceRole.choices, default=SourceRole.WINNER
    )
    source_b = models.ForeignKey(
        "self", null=True, blank=True, related_name="feeds_b", on_delete=models.SET_NULL
    )
    source_b_role = models.CharField(
        max_length=6, choices=SourceRole.choices, default=SourceRole.WINNER
    )

    @property
    def loser(self):
        if not self.is_played or self.team_a_id is None or self.team_b_id is None:
            return None
        return self.team_b if self.winner_id == self.team_a_id else self.team_a

    class Meta:
        ordering = ["slot_index", "court__number", "bracket_pos"]
        verbose_name_plural = "matches"

    def __str__(self):
        a = self.team_a.name if self.team_a else "?"
        b = self.team_b.name if self.team_b else "?"
        return f"{a} vs {b}"

    @property
    def is_played(self):
        return self.status == self.Status.DONE and self.winner_id is not None

    @property
    def is_knockout(self):
        return self.phase in (self.Phase.GOLD, self.Phase.SILVER)

    @property
    def can_be_scored(self):
        """Si può inserire il punteggio solo se entrambe le coppie sono note."""
        return self.team_a_id is not None and self.team_b_id is not None

    @property
    def sets_won(self):
        """(set vinti da A, set vinti da B) sui set registrati."""
        a = b = 0
        for s in self.sets.all():
            side = s.winner_side
            if side == "a":
                a += 1
            elif side == "b":
                b += 1
        return a, b

    @property
    def sets_a(self):
        return self.sets_won[0]

    @property
    def sets_b(self):
        return self.sets_won[1]

    @property
    def score_display(self):
        if self.walkover:
            return "W.O."
        return ", ".join(s.display for s in self.sets.all())

    @property
    def had_bagel(self):
        """Vero se in un set qualcuno ha fatto 6-0 (per il tocco 🔥)."""
        return any(
            (s.games_a == 6 and s.games_b == 0) or (s.games_b == 6 and s.games_a == 0)
            for s in self.sets.all()
        )


class MatchSet(models.Model):
    """Un set di una partita. Per il super tie-break (3° set) games_* contiene i punti del TB."""

    match = models.ForeignKey(Match, related_name="sets", on_delete=models.CASCADE)
    number = models.PositiveSmallIntegerField()  # 1, 2, 3 (3 = super tie-break)
    games_a = models.PositiveSmallIntegerField()
    games_b = models.PositiveSmallIntegerField()
    # Punto Secco (la specialità del torneo): sul 6-6 si gioca UN solo punto secco a
    # decidere il set, non un tie-break tradizionale. 1 alla coppia che lo vince, 0
    # all'altra; null se il set non è arrivato al Punto Secco (deciso nei game).
    tiebreak_a = models.PositiveSmallIntegerField(null=True, blank=True)
    tiebreak_b = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["number"]
        unique_together = [("match", "number")]

    def __str__(self):
        return f"Set {self.number}: {self.display}"

    @property
    def winner_side(self):
        if self.games_a > self.games_b:
            return "a"
        if self.games_b > self.games_a:
            return "b"
        # Parità di game: decide il Punto Secco, se presente.
        if self.tiebreak_a is not None and self.tiebreak_b is not None:
            if self.tiebreak_a > self.tiebreak_b:
                return "a"
            if self.tiebreak_b > self.tiebreak_a:
                return "b"
        return None

    @property
    def display(self):
        s = f"{self.games_a}-{self.games_b}"
        if self.tiebreak_a is not None and self.tiebreak_b is not None:
            s += " (PS)"  # deciso al Punto Secco, non un tie-break a punti
        return s


class ScoreLog(models.Model):
    """Registro delle modifiche ai punteggi (accountability per lo scoring aperto)."""

    tournament = models.ForeignKey(
        Tournament, related_name="score_logs", on_delete=models.CASCADE
    )
    match = models.ForeignKey(
        Match, null=True, related_name="logs", on_delete=models.SET_NULL
    )
    created = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20)  # risultato | parziale | walkover
    detail = models.CharField(max_length=200)  # es. "A1 vs B2: 6-4"
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.created:%H:%M} {self.detail}"
