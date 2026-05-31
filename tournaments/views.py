import datetime
import io
import json

import segno
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .awards import champion, podium, team_achievements, tournament_awards
from .bracket_svg import render_bracket_svg
from .brackets import seed_brackets
from .models import Match, ScoreLog, Team, Tournament
from .scheduling import generate_group_stage, slot_start
from .scoring import record_match_score, record_walkover, sets_from_post
from .setup import create_tournament, draw_groups
from .standings import group_standings
from .stats import tournament_stats

staff_required = user_passes_test(lambda u: u.is_staff)


def _tournament(slug):
    return get_object_or_404(Tournament, slug=slug)


def _ko_qs(tournament):
    return tournament.matches.filter(phase__in=[Match.Phase.GOLD, Match.Phase.SILVER])


# --- Helper di presentazione --------------------------------------------------
def build_schedule_grid(tournament):
    """Griglia campi × slot. Le partite a 2 slot occupano due righe (rowspan)."""
    courts = list(tournament.courts.order_by("number"))
    matches = (
        tournament.matches.exclude(slot_index=None)
        .select_related("court", "team_a", "team_b", "group")
        .prefetch_related("sets")
    )
    start = {}  # (slot, court_id) -> match che inizia lì
    occupied = set()  # tutte le celle coperte (inizio + continuazione)
    max_slot = -1
    for m in matches:
        start[(m.slot_index, m.court_id)] = m
        for s in range(m.slot_index, m.slot_index + m.slot_span):
            occupied.add((s, m.court_id))
            max_slot = max(max_slot, s)

    rows = []
    for slot in range(max_slot + 1):
        cells = []
        for c in courts:
            m = start.get((slot, c.id))
            if m:
                cells.append({"kind": "match", "match": m, "span": m.slot_span})
            elif (slot, c.id) in occupied:
                cells.append(
                    {"kind": "skip"}
                )  # coperta dal rowspan della partita sopra
            else:
                cells.append({"kind": "empty"})
        rows.append(
            {"slot": slot, "time": slot_start(tournament, slot), "cells": cells}
        )

    # Vista mobile: partite raggruppate per slot (solo quelle che iniziano lì).
    by_slot = {}
    for (slot, _court_id), m in start.items():
        by_slot.setdefault(slot, []).append(m)
    slots = [
        {
            "slot": s,
            "time": slot_start(tournament, s),
            "matches": sorted(
                by_slot[s], key=lambda mm: mm.court.number if mm.court else 0
            ),
        }
        for s in sorted(by_slot)
    ]
    return courts, rows, slots


def bracket_data(tournament, phase):
    qs = (
        _ko_qs(tournament)
        .filter(phase=phase)
        .select_related("team_a", "team_b", "court")
    )
    return {
        "quarti": list(qs.filter(round_label="Quarti").order_by("bracket_pos")),
        "semifinali": list(qs.filter(round_label="Semifinale").order_by("bracket_pos")),
        "finale": qs.filter(round_label="Finale").first(),
        "terzo": qs.filter(round_label="Finale 3°/4°").first(),
    }


def live_context(tournament):
    sel = ("court", "team_a", "team_b", "group")
    live = list(
        tournament.matches.filter(status=Match.Status.LIVE)
        .select_related(*sel)
        .prefetch_related("sets")
        .order_by("court__number")
    )
    upcoming = list(
        tournament.matches.filter(
            status=Match.Status.SCHEDULED, slot_index__isnull=False
        )
        .select_related(*sel)
        .prefetch_related("sets")
        .order_by("slot_index", "court__number")[:8]
    )
    return {"live_matches": live, "upcoming": upcoming}


# --- Viste --------------------------------------------------------------------
def dashboard(request, slug):
    t = _tournament(slug)
    groups = [(g, group_standings(g)) for g in t.groups.all()]
    return render(
        request,
        "tournaments/dashboard.html",
        {"t": t, "groups": groups, "champion": champion(t), **live_context(t)},
    )


def standings(request, slug):
    t = _tournament(slug)
    groups = [(g, group_standings(g)) for g in t.groups.all()]
    return render(request, "tournaments/standings.html", {"t": t, "groups": groups})


def schedule(request, slug):
    t = _tournament(slug)
    courts, rows, slots = build_schedule_grid(t)
    return render(
        request,
        "tournaments/schedule.html",
        {"t": t, "courts": courts, "rows": rows, "slots": slots},
    )


def brackets(request, slug):
    t = _tournament(slug)
    return render(
        request,
        "tournaments/brackets.html",
        {
            "t": t,
            "gold": bracket_data(t, Match.Phase.GOLD),
            "silver": bracket_data(t, Match.Phase.SILVER),
        },
    )


def live(request, slug):
    t = _tournament(slug)
    live_url = request.build_absolute_uri(
        reverse("tournaments:live", kwargs={"slug": t.slug})
    )
    qr_data_uri = segno.make(live_url, error="m").svg_data_uri(scale=4)
    return render(
        request,
        "tournaments/live.html",
        {"t": t, "live_url": live_url, "qr_data_uri": qr_data_uri, **live_context(t)},
    )


def stats(request, slug):
    t = _tournament(slug)
    return render(
        request, "tournaments/stats.html", {"t": t, "stats": tournament_stats(t)}
    )


_BRACKET_ABBR = {
    "Sedicesimi": "R32",
    "Ottavi": "R16",
    "Quarti": "QF",
    "Semifinale": "SF",
    "Finale": "F",
}
_BRACKET_SEQ = ["Sedicesimi", "Ottavi", "Quarti", "Semifinale", "Finale"]


def _bracket_rounds(tournament, phase):
    """Turni del tabellone (escluso 3°/4°) come colonne, dal primo turno alla finale."""
    matches = list(
        tournament.matches.filter(phase=phase)
        .exclude(round_label="Finale 3°/4°")
        .select_related("team_a", "team_b")
        .prefetch_related("sets")
    )
    rounds = []
    for lbl in _BRACKET_SEQ:
        ms = sorted(
            (m for m in matches if m.round_label == lbl),
            key=lambda m: m.bracket_pos or 0,
        )
        if ms:
            rounds.append({"abbr": _BRACKET_ABBR[lbl], "matches": ms})
    return rounds


def _tv_context(tournament):
    """Per la modalità schermo campo: per ogni campo, la partita in corso e la prossima."""
    board = []
    ticker = []
    for c in tournament.courts.order_by("number"):
        sel = ("team_a", "team_b")
        # Se per errore ci fossero più partite "in corso" sullo stesso campo, prendi la più recente.
        live = (
            c.matches.filter(status=Match.Status.LIVE)
            .select_related(*sel)
            .prefetch_related("sets")
            .order_by("-slot_index")
            .first()
        )
        # "Prossima" per campo: la prima programmata dopo quella in corso (con coppie note).
        after = live.slot_index if live and live.slot_index is not None else -1
        nxt = (
            c.matches.filter(
                status=Match.Status.SCHEDULED,
                slot_index__isnull=False,
                slot_index__gt=after,
            )
            .select_related(*sel)
            .order_by("slot_index")
            .first()
        )
        board.append({"court": c, "live": live, "next": nxt})
        if nxt and nxt.team_a_id and nxt.team_b_id:
            ticker.append({"court": c, "match": nxt})

    groups = [(g, group_standings(g)) for g in tournament.groups.all()]
    champ = champion(tournament)
    has_ko = tournament.matches.filter(
        phase__in=[Match.Phase.GOLD, Match.Phase.SILVER]
    ).exists()
    return {
        "board": board,
        "ticker": ticker,
        "groups": groups,
        "champion": champ,
        "podium_data": podium(tournament) if champ else None,
        "gold_bracket_svg": (
            render_bracket_svg(_bracket_rounds(tournament, Match.Phase.GOLD))
            if has_ko
            else ""
        ),
        "silver_bracket_svg": (
            render_bracket_svg(_bracket_rounds(tournament, Match.Phase.SILVER))
            if has_ko
            else ""
        ),
    }


def tv(request, slug):
    """Pagina kiosk a tutto schermo per il monitor a bordo campo (standalone, senza nav)."""
    t = _tournament(slug)
    return render(request, "tournaments/tv.html", {"t": t, **_tv_context(t)})


def tv_board(request, slug):
    t = _tournament(slug)
    return render(
        request, "tournaments/partials/_tv_board.html", {"t": t, **_tv_context(t)}
    )


def live_board(request, slug):
    """Partial ricaricato in polling dalla pagina live."""
    t = _tournament(slug)
    return render(
        request, "tournaments/partials/_live_board.html", {"t": t, **live_context(t)}
    )


def team_detail(request, slug, team_id):
    t = _tournament(slug)
    team = get_object_or_404(Team, pk=team_id, tournament=t)
    matches = list(
        t.matches.filter(Q(team_a=team) | Q(team_b=team))
        .select_related("court", "team_a", "team_b", "group")
        .order_by("slot_index")
    )
    next_match = next(
        (
            m
            for m in matches
            if m.status != Match.Status.DONE and m.slot_index is not None
        ),
        None,
    )
    return render(
        request,
        "tournaments/team_detail.html",
        {
            "t": t,
            "team": team,
            "matches": matches,
            "next_match": next_match,
            "achievements": team_achievements(team),
        },
    )


def albo(request, slug):
    t = _tournament(slug)
    return render(
        request, "tournaments/albo.html", {"t": t, "awards": tournament_awards(t)}
    )


def score_log(request, slug):
    """Registro pubblico delle modifiche ai punteggi (trasparenza). IP non mostrato."""
    t = _tournament(slug)
    logs = t.score_logs.select_related("match__team_a", "match__team_b")[:100]
    return render(request, "tournaments/registro.html", {"t": t, "logs": logs})


# --- Iscrizione pubblica -----------------------------------------------------
def register(request, slug):
    """Iscrizione pubblica di una coppia (solo in fase di setup)."""
    t = _tournament(slug)
    open_for_signup = t.status == Tournament.Status.SETUP
    error = done = None
    # Honeypot antispam: i bot compilano il campo nascosto "website" → ignoriamo il POST.
    is_bot = bool((request.POST.get("website") or "").strip())
    if request.method == "POST" and open_for_signup and not is_bot:
        name = (request.POST.get("name") or "").strip()
        p1 = (request.POST.get("player1") or "").strip()
        p2 = (request.POST.get("player2") or "").strip()
        if not (name and p1 and p2):
            error = "Compila nome coppia e i due giocatori."
        else:
            Team.objects.create(tournament=t, name=name, player1=p1, player2=p2)
            done = name
    return render(
        request,
        "tournaments/register.html",
        {"t": t, "open_for_signup": open_for_signup, "error": error, "done": done},
    )


# --- Creazione + gestione (organizzatore, login staff) -----------------------
@login_required
@staff_required
def new_tournament(request):
    error = None
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        date = (request.POST.get("date") or "").strip()
        try:
            parsed = datetime.date.fromisoformat(date)
        except ValueError:
            parsed = None
        if not name or parsed is None:
            error = "Inserisci nome e una data valida."
        else:
            t = create_tournament(name=name, date=parsed)
            return redirect("tournaments:manage", slug=t.slug)
    return render(request, "tournaments/new_tournament.html", {"error": error})


@login_required
@staff_required
def manage(request, slug):
    t = _tournament(slug)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_team":
            name = (request.POST.get("name") or "").strip()
            p1 = (request.POST.get("player1") or "").strip()
            p2 = (request.POST.get("player2") or "").strip()
            if name and p1 and p2:
                Team.objects.create(tournament=t, name=name, player1=p1, player2=p2)
        elif action == "del_team":
            Team.objects.filter(tournament=t, id=request.POST.get("team_id")).delete()
        elif action == "draw":
            draw_groups(t)
        elif action == "schedule":
            generate_group_stage(t)
            t.status = Tournament.Status.GROUP
            t.save(update_fields=["status"])
        elif action == "brackets":
            seed_brackets(t)
            t.status = Tournament.Status.KNOCKOUT
            t.save(update_fields=["status"])
        return redirect("tournaments:manage", slug=t.slug)

    groups = [(g, list(g.teams.all())) for g in t.groups.order_by("name")]
    unassigned = list(t.teams.filter(group__isnull=True))
    group_done = (
        t.matches.filter(phase=Match.Phase.GROUP).exists()
        and not t.matches.filter(phase=Match.Phase.GROUP)
        .exclude(status=Match.Status.DONE)
        .exists()
    )
    return render(
        request,
        "tournaments/manage.html",
        {
            "t": t,
            "groups": groups,
            "unassigned": unassigned,
            "team_count": t.teams.count(),
            "has_schedule": t.matches.filter(phase=Match.Phase.GROUP).exists(),
            "group_done": group_done,
        },
    )


# --- Inserimento punteggi (aperto a tutti) -----------------------------------
def score_panel(request, slug):
    t = _tournament(slug)
    matches = (
        t.matches.select_related("court", "team_a", "team_b", "group")
        .prefetch_related("sets")
        .order_by("slot_index", "court__number", "bracket_pos")
    )
    return render(
        request,
        "tournaments/score_panel.html",
        {"t": t, "matches": matches, "open_id": request.GET.get("open")},
    )


def _score_form_context(t, match, error=None):
    existing = {s.number: s for s in match.sets.all()}
    return {
        "t": t,
        "match": match,
        "error": error,
        "s1": existing.get(1),
        "s2": existing.get(2),
        "s3": existing.get(3),
    }


def _dependent_matches(match):
    """Partite del knockout alimentate da questa (per il refresh OOB)."""
    deps = list(match.feeds_a.all()) + list(match.feeds_b.all())
    seen, unique = set(), []
    for d in deps:
        if d.id not in seen:
            seen.add(d.id)
            unique.append(d)
    return unique


def _log_score(t, match, action, detail, request):
    """Registra una modifica al punteggio (con IP) per accountability."""
    fwd = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    ip = fwd or request.META.get("REMOTE_ADDR") or None
    ScoreLog.objects.create(
        tournament=t, match=match, action=action, detail=detail[:200], ip=ip
    )


def _refresh_status(t):
    """Aggiorna lo stato del torneo in base alle finali: DONE se entrambe concluse,
    altrimenti torna a KNOCKOUT (es. dopo un ri-punteggio che azzera una finale)."""
    finals = t.matches.filter(
        round_label="Finale", phase__in=[Match.Phase.GOLD, Match.Phase.SILVER]
    )
    complete = finals.exists() and not finals.exclude(status=Match.Status.DONE).exists()
    if complete and t.status != Tournament.Status.DONE:
        t.status = Tournament.Status.DONE
        t.save(update_fields=["status"])
    elif not complete and t.status == Tournament.Status.DONE:
        t.status = Tournament.Status.KNOCKOUT
        t.save(update_fields=["status"])


def _celebration(match):
    """(livello coriandoli, nome campione|None) per il salvataggio di un risultato."""
    if not match.is_played:
        return None, None
    if match.phase == Match.Phase.GOLD and match.round_label == "Finale":
        return "champion", match.winner.name if match.winner else None
    if match.round_label in ("Finale", "Semifinale"):
        return "big", None
    if match.is_knockout:
        return "medium", None
    return "small", None


def score_match(request, slug, match_id):
    t = _tournament(slug)
    match = get_object_or_404(Match, pk=match_id, tournament=t)

    if request.method == "POST":
        action = request.POST.get("action")

        # Walkover (ritirata): vittoria a tavolino senza set.
        if action in ("wo_a", "wo_b") and match.can_be_scored:
            winner = match.team_a if action == "wo_a" else match.team_b
            record_walkover(match, winner)
            _log_score(t, match, "walkover", f"{match} - W.O.: {winner.name}", request)
            reset_count = getattr(match, "_downstream_reset", 0)
            match.refresh_from_db()
            if match.is_knockout:
                _refresh_status(t)
            resp = render(
                request,
                "tournaments/partials/_score_result.html",
                {"t": t, "match": match, "dependents": _dependent_matches(match)},
            )
            msg = f"Walkover: vince {winner.name}"
            if reset_count:
                msg += f" - azzerate {reset_count} partite a valle"
            resp["HX-Trigger"] = json.dumps({"toast": {"message": msg}})
            return resp

        partial = action == "partial"
        try:
            sets = sets_from_post(match, request.POST, partial=partial)
        except ValueError as e:
            return render(
                request,
                "tournaments/partials/_score_form.html",
                _score_form_context(t, match, error=str(e)),
            )
        record_match_score(match, sets, finalize=not partial)
        reset_count = getattr(match, "_downstream_reset", 0)
        match.refresh_from_db()
        if partial:
            _log_score(t, match, "parziale", f"{match}: {match.score_display}", request)
            # Parziale: solo la riga aggiornata, la partita resta in corso.
            resp = render(
                request,
                "tournaments/partials/_score_row.html",
                {"t": t, "match": match, "flash": True},
            )
            resp["HX-Trigger"] = json.dumps({"toast": {"message": "Parziale salvato"}})
            return resp
        if match.is_knockout:
            _refresh_status(t)
        _log_score(t, match, "risultato", f"{match}: {match.score_display}", request)
        # Finale: riga aggiornata + (OOB) le partite dipendenti popolate dall'avanzamento.
        resp = render(
            request,
            "tournaments/partials/_score_result.html",
            {"t": t, "match": match, "dependents": _dependent_matches(match)},
        )
        level, champion = _celebration(match)
        msg = "Punteggio salvato"
        if reset_count:
            msg = f"Salvato - azzerate {reset_count} partite a valle (risultato cambiato)."
        triggers = {"toast": {"message": msg}, "celebrate": {"level": level}}
        if champion:
            triggers["champion"] = {"team": champion}
        resp["HX-Trigger"] = json.dumps(triggers)
        return resp

    # GET: form di inserimento (con prefill), oppure (cancel) la riga in sola lettura.
    if request.GET.get("cancel"):
        return render(
            request, "tournaments/partials/_score_row.html", {"t": t, "match": match}
        )
    return render(
        request, "tournaments/partials/_score_form.html", _score_form_context(t, match)
    )


def set_match_status(request, slug, match_id):
    """Segna una partita 'in corso' o la riporta 'programmata'."""
    t = _tournament(slug)
    match = get_object_or_404(Match, pk=match_id, tournament=t)
    new_status = request.POST.get("status")
    if new_status in (Match.Status.LIVE, Match.Status.SCHEDULED):
        match.status = new_status
        match.save(update_fields=["status"])
    resp = render(
        request, "tournaments/partials/_score_row.html", {"t": t, "match": match}
    )
    label = "In corso" if match.status == Match.Status.LIVE else "Programmata"
    resp["HX-Trigger"] = json.dumps({"toast": {"message": f"Stato: {label}"}})
    return resp


# --- Pagina partita + OG image -----------------------------------------------


def match_detail(request, slug, match_id):
    t = _tournament(slug)
    match = get_object_or_404(
        Match.objects.select_related(
            "team_a", "team_b", "court", "group"
        ).prefetch_related("sets"),
        pk=match_id,
        tournament=t,
    )
    match_url = request.build_absolute_uri(
        reverse(
            "tournaments:match_detail", kwargs={"slug": t.slug, "match_id": match.id}
        )
    )
    og_image_url = request.build_absolute_uri(
        reverse(
            "tournaments:match_og_image", kwargs={"slug": t.slug, "match_id": match.id}
        )
    )
    qr_data_uri = segno.make(match_url, error="m").svg_data_uri(scale=4)
    return render(
        request,
        "tournaments/match_detail.html",
        {
            "t": t,
            "match": match,
            "qr_data_uri": qr_data_uri,
            "og_image_url": og_image_url,
        },
    )


def match_live(request, slug, match_id):
    """Partial ricaricato in polling dalla pagina match_detail."""
    t = _tournament(slug)
    match = get_object_or_404(
        Match.objects.select_related(
            "team_a", "team_b", "court", "group"
        ).prefetch_related("sets"),
        pk=match_id,
        tournament=t,
    )
    return render(
        request,
        "tournaments/partials/_match_live.html",
        {"t": t, "match": match},
    )


def match_og_image(request, slug, match_id):
    """Genera un'immagine PNG 640x340 per l'Open Graph della pagina partita."""
    from PIL import Image, ImageDraw, ImageFont

    t = _tournament(slug)
    match = get_object_or_404(
        Match.objects.select_related(
            "team_a", "team_b", "court", "group"
        ).prefetch_related("sets"),
        pk=match_id,
        tournament=t,
    )

    W, H = 640, 340
    BG = (14, 124, 102)  # #0e7c66
    WHITE = (255, 255, 255)
    GREY_LIGHT = (180, 200, 190)
    GREY_MID = (130, 160, 150)
    GREEN_BRIGHT = (43, 185, 154)  # #2bb99a
    RED_BADGE = (210, 64, 60)  # #d2403c
    DARK_BADGE = (8, 70, 58)

    def load_font(size, bold=False):
        paths = [
            (
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
                if bold
                else "/System/Library/Fonts/Supplemental/Arial.ttf"
            ),
            (
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
            ),
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            ),
        ]
        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_small = load_font(22)
    font_team = load_font(42, bold=True)
    font_vs = load_font(26)
    font_score = load_font(68, bold=True)
    font_badge = load_font(20, bold=True)
    font_brand = load_font(18)

    # Torneo name - top left
    draw.text((24, 18), t.name, font=font_small, fill=GREY_LIGHT)

    # Team A
    team_a_name = match.team_a.name if match.team_a else "da definire"
    team_b_name = match.team_b.name if match.team_b else "da definire"

    # Highlight winner in bright green
    col_a = (
        GREEN_BRIGHT
        if (match.winner_id and match.winner_id == match.team_a_id)
        else WHITE
    )
    col_b = (
        GREEN_BRIGHT
        if (match.winner_id and match.winner_id == match.team_b_id)
        else WHITE
    )

    center_x = W // 2
    draw.text((center_x, 60), team_a_name, font=font_team, fill=col_a, anchor="mm")
    draw.text((center_x, 108), "vs", font=font_vs, fill=GREY_MID, anchor="mm")
    draw.text((center_x, 155), team_b_name, font=font_team, fill=col_b, anchor="mm")

    # Score
    score = match.score_display or "in gioco"
    score_color = WHITE if match.status == Match.Status.DONE else GREEN_BRIGHT
    draw.text((center_x, 220), score, font=font_score, fill=score_color, anchor="mm")

    # Status badge
    if match.status == Match.Status.LIVE:
        badge_text = "IN CORSO"
        badge_fill = RED_BADGE
    elif match.status == Match.Status.DONE:
        badge_text = "FINITA"
        badge_fill = DARK_BADGE
    else:
        badge_text = "PROGRAMMATA"
        badge_fill = DARK_BADGE

    bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
    bw = bbox[2] - bbox[0] + 20
    bh = bbox[3] - bbox[1] + 10
    bx = 24
    by = H - bh - 24
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=6, fill=badge_fill)
    draw.text((bx + 10, by + 5), badge_text, font=font_badge, fill=WHITE)

    # Round label + court
    meta_parts = []
    if match.round_label:
        meta_parts.append(match.round_label)
    if match.group:
        meta_parts.append(f"Girone {match.group.name}")
    if match.court:
        meta_parts.append(str(match.court))
    if meta_parts:
        draw.text(
            (bx + bw + 16, by + 5),
            "  ".join(meta_parts),
            font=font_badge,
            fill=GREY_LIGHT,
        )

    # Brand bottom right
    draw.text(
        (W - 24, H - 24), "Punto Secco", font=font_brand, fill=GREY_MID, anchor="rs"
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    resp = HttpResponse(buf.read(), content_type="image/png")
    resp["Cache-Control"] = "no-store"
    return resp
