from django.shortcuts import render
from django.utils import timezone

from tournaments.models import Tournament


def home(request):
    tournaments = Tournament.objects.all()  # ordinati per data desc (Meta del modello)
    return render(request, "core/home.html", {"tournaments": tournaments})


def about(request):
    return render(request, "core/about.html")


def orario(request):
    # Ritorna LO STESSO partial che home.html include: DOM identico per costruzione.
    return render(request, "core/partials/_orario.html", {"now": timezone.localtime()})
