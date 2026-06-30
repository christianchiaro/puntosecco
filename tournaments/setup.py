"""Creazione torneo e sorteggio gironi (operazioni da organizzatore)."""

import random

from django.utils.text import slugify

from .models import Court, Group, Tournament


def unique_slug(name):
    base = slugify(name) or "torneo"
    slug, n = base, 2
    while Tournament.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_tournament(name, date, num_courts=4, num_groups=3, teams_per_group=4):
    """Crea il torneo con i suoi campi e gironi (vuoti)."""
    t = Tournament.objects.create(
        name=name,
        slug=unique_slug(name),
        date=date,
        num_courts=num_courts,
        num_groups=num_groups,
        teams_per_group=teams_per_group,
        status=Tournament.Status.SETUP,
    )
    for n in range(1, num_courts + 1):
        Court.objects.create(tournament=t, number=n)
    for i in range(num_groups):
        Group.objects.create(tournament=t, name=chr(ord("A") + i))
    return t


def draw_groups(tournament, *, rng=random):
    """Sorteggia le coppie nei gironi (casuale). Azzera calendario e stato → SETUP.

    Le coppie oltre la capienza (num_gironi × coppie_per_girone) restano senza girone.
    """
    teams = list(tournament.teams.all())
    rng.shuffle(teams)
    groups = list(tournament.groups.order_by("name"))
    cap = tournament.teams_per_group

    tournament.matches.all().delete()
    for i, team in enumerate(teams):
        gi = i // cap
        team.group = groups[gi] if gi < len(groups) else None
        team.seed = (i % cap) + 1 if gi < len(groups) else None
        team.save(update_fields=["group", "seed"])

    tournament.status = Tournament.Status.SETUP
    tournament.save(update_fields=["status"])
