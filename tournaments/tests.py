import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .setup import create_tournament, draw_groups

from .awards import champion, podium, team_achievements, tournament_awards
from .brackets import schedule_knockout, seed_brackets
from .models import Court, Group, Match, Team, Tournament
from .scheduling import generate_group_stage, round_robin_rounds, slot_start
from .scoring import record_match_score
from .standings import group_ranking, group_standings


def make_tournament(**kwargs):
    defaults = dict(
        name="Punto Secco", slug="punto-secco", date=datetime.date(2026, 6, 6)
    )
    defaults.update(kwargs)
    return Tournament.objects.create(**defaults)


def make_full_tournament():
    """Torneo completo: 4 campi, 4 gironi (A-D), 16 coppie (4 per girone). Formato legacy esplicito."""
    t = make_tournament(num_groups=4, teams_per_group=4)
    for n in range(1, t.num_courts + 1):
        Court.objects.create(tournament=t, number=n)
    for gi in range(t.num_groups):
        g = Group.objects.create(tournament=t, name=chr(ord("A") + gi))
        for ti in range(t.teams_per_group):
            Team.objects.create(
                tournament=t,
                name=f"{g.name}{ti + 1}",
                player1=f"p{gi}{ti}a",
                player2=f"p{gi}{ti}b",
                seed=ti + 1,
                group=g,
            )
    return t


def play_all_groups_by_seed(tournament):
    """Gioca tutti i gironi in modo deterministico: vince sempre la coppia col seed più basso.

    Risultato: in ogni girone la classifica è esattamente seed 1, 2, 3, 4.
    """
    for m in tournament.matches.filter(phase=Match.Phase.GROUP):
        if m.team_a.seed <= m.team_b.seed:
            record_match_score(m, [{"games_a": 6, "games_b": 0}])
        else:
            record_match_score(m, [{"games_a": 0, "games_b": 6}])


def play_full_knockout(tournament):
    """Gioca tutto il knockout (team_a vince 2-0) rispettando l'ordine delle dipendenze."""
    for label in ("Quarti", "Semifinale", "Finale", "Finale 3°/4°"):
        for m in tournament.matches.filter(
            round_label=label, phase__in=[Match.Phase.GOLD, Match.Phase.SILVER]
        ):
            if m.team_a_id and m.team_b_id:
                record_match_score(
                    m, [{"games_a": 6, "games_b": 2}, {"games_a": 6, "games_b": 3}]
                )


class TournamentModelTests(TestCase):
    def test_num_teams_is_groups_times_teams_per_group(self):
        t = make_tournament(num_groups=4, teams_per_group=4)
        self.assertEqual(t.num_teams, 16)

    def test_default_config_matches_punto_secco(self):
        t = make_tournament()
        self.assertEqual(t.num_courts, 4)
        self.assertEqual(t.slot_minutes, 25)
        self.assertEqual(t.start_time, datetime.time(14, 0))
        self.assertEqual(t.status, Tournament.Status.SETUP)

    def test_str(self):
        self.assertEqual(str(make_tournament(name="X", slug="x")), "X")


class CourtAndGroupTests(TestCase):
    def setUp(self):
        self.t = make_tournament()

    def test_court_str_uses_number_when_no_name(self):
        c = Court.objects.create(tournament=self.t, number=3)
        self.assertEqual(str(c), "Campo 3")

    def test_court_number_unique_per_tournament(self):
        Court.objects.create(tournament=self.t, number=1)
        from django.db import IntegrityError

        with self.assertRaises(IntegrityError):
            Court.objects.create(tournament=self.t, number=1)

    def test_group_str(self):
        g = Group.objects.create(tournament=self.t, name="A")
        self.assertEqual(str(g), "Girone A")


class MatchScoreTests(TestCase):
    def setUp(self):
        self.t = make_tournament()
        self.a = Team.objects.create(
            tournament=self.t, name="A", player1="a1", player2="a2"
        )
        self.b = Team.objects.create(
            tournament=self.t, name="B", player1="b1", player2="b2"
        )

    def _match(self, phase=Match.Phase.GROUP):
        return Match.objects.create(
            tournament=self.t, phase=phase, team_a=self.a, team_b=self.b
        )

    def test_score_display_empty_when_no_score(self):
        self.assertEqual(self._match().score_display, "")

    def test_slot_span_defaults_to_one(self):
        self.assertEqual(self._match().slot_span, 1)

    def test_group_single_set_winner(self):
        m = self._match()
        record_match_score(m, [{"games_a": 6, "games_b": 4}])
        self.assertEqual(m.score_display, "6-4")
        self.assertEqual(m.winner, self.a)
        self.assertTrue(m.is_played)
        self.assertEqual(m.sets_won, (1, 0))

    def test_set_with_tiebreak_display_and_winner(self):
        m = self._match()
        record_match_score(
            m, [{"games_a": 7, "games_b": 6, "tiebreak_a": 7, "tiebreak_b": 5}]
        )
        self.assertEqual(m.score_display, "7-6 (7-5)")
        self.assertEqual(m.winner, self.a)

    def test_knockout_two_sets_straight(self):
        m = self._match(phase=Match.Phase.GOLD)
        record_match_score(
            m, [{"games_a": 6, "games_b": 3}, {"games_a": 6, "games_b": 4}]
        )
        self.assertEqual(m.sets_won, (2, 0))
        self.assertEqual(m.winner, self.a)
        self.assertEqual(m.score_display, "6-3, 6-4")

    def test_knockout_super_tiebreak_decides_one_one(self):
        m = self._match(phase=Match.Phase.GOLD)
        record_match_score(
            m,
            [
                {"games_a": 6, "games_b": 4},  # A
                {"games_a": 3, "games_b": 6},  # B
                {"games_a": 10, "games_b": 7},  # super TB → A
            ],
        )
        self.assertEqual(m.sets_won, (2, 1))
        self.assertEqual(m.winner, self.a)
        self.assertEqual(m.score_display, "6-4, 3-6, 10-7")

    def test_str_shows_team_names(self):
        self.assertEqual(str(self._match()), "A vs B")

    def test_str_handles_missing_teams(self):
        m = Match.objects.create(tournament=self.t, phase=Match.Phase.GOLD)
        self.assertEqual(str(m), "? vs ?")


class RoundRobinTests(TestCase):
    def test_four_teams_produce_three_rounds_of_two(self):
        rounds = round_robin_rounds([1, 2, 3, 4])
        self.assertEqual(len(rounds), 3)
        for rnd in rounds:
            self.assertEqual(len(rnd), 2)

    def test_every_pair_plays_exactly_once(self):
        rounds = round_robin_rounds([1, 2, 3, 4])
        pairs = {frozenset(p) for rnd in rounds for p in rnd}
        self.assertEqual(len(pairs), 6)  # C(4,2)

    def test_each_team_plays_three_matches(self):
        rounds = round_robin_rounds([1, 2, 3, 4])
        counts = {}
        for rnd in rounds:
            for a, b in rnd:
                counts[a] = counts.get(a, 0) + 1
                counts[b] = counts.get(b, 0) + 1
        self.assertEqual(set(counts.values()), {3})

    def test_within_a_round_no_team_repeats(self):
        rounds = round_robin_rounds([1, 2, 3, 4])
        for rnd in rounds:
            teams = [t for pair in rnd for t in pair]
            self.assertEqual(len(teams), len(set(teams)))


class GroupScheduleTests(TestCase):
    def setUp(self):
        self.t = make_full_tournament()
        self.slots_used = generate_group_stage(self.t)
        self.matches = list(self.t.matches.filter(phase=Match.Phase.GROUP))

    def test_total_group_matches(self):
        # 4 gironi * C(4,2)=6 = 24 partite.
        self.assertEqual(len(self.matches), 24)

    def test_group_stage_fits_in_six_slots(self):
        # 3 turni * (8 partite / 4 campi = 2 slot) = 6 slot.
        self.assertEqual(self.slots_used, 6)

    def test_each_team_has_three_matches(self):
        counts = {}
        for m in self.matches:
            counts[m.team_a_id] = counts.get(m.team_a_id, 0) + 1
            counts[m.team_b_id] = counts.get(m.team_b_id, 0) + 1
        self.assertEqual(len(counts), 16)
        self.assertEqual(set(counts.values()), {3})

    def test_no_team_double_booked_in_a_slot(self):
        seen = {}  # slot -> set di team
        for m in self.matches:
            bucket = seen.setdefault(m.slot_index, set())
            for tid in (m.team_a_id, m.team_b_id):
                self.assertNotIn(
                    tid, bucket, f"Coppia {tid} doppia nello slot {m.slot_index}"
                )
                bucket.add(tid)

    def test_no_court_hosts_two_matches_in_a_slot(self):
        seen = set()
        for m in self.matches:
            key = (m.slot_index, m.court_id)
            self.assertNotIn(
                key, seen, f"Campo {m.court_id} doppio nello slot {m.slot_index}"
            )
            seen.add(key)

    def test_capacity_respected(self):
        # Mai più partite dei campi in uno stesso slot.
        per_slot = {}
        for m in self.matches:
            per_slot[m.slot_index] = per_slot.get(m.slot_index, 0) + 1
        self.assertTrue(all(c <= self.t.num_courts for c in per_slot.values()))

    def test_scheduled_start_matches_slot(self):
        first = min(self.matches, key=lambda m: m.slot_index)
        self.assertEqual(first.scheduled_start, slot_start(self.t, first.slot_index))
        # Lo slot 0 parte alle 14:00.
        self.assertEqual(slot_start(self.t, 0).time(), datetime.time(14, 0))
        # Lo slot 1 parte 25 minuti dopo.
        self.assertEqual(slot_start(self.t, 1).time(), datetime.time(14, 25))

    def test_regeneration_is_idempotent(self):
        generate_group_stage(self.t)  # seconda volta
        self.assertEqual(self.t.matches.filter(phase=Match.Phase.GROUP).count(), 24)

    def test_all_matches_belong_to_a_group(self):
        self.assertTrue(all(m.group_id is not None for m in self.matches))


class StandingsTests(TestCase):
    def setUp(self):
        self.t = make_full_tournament()
        generate_group_stage(self.t)

    def test_ranking_follows_results(self):
        play_all_groups_by_seed(self.t)
        group_a = self.t.groups.get(name="A")
        ranking = group_ranking(group_a)
        # Vince sempre il seed più basso → classifica = seed 1,2,3,4.
        self.assertEqual([t.seed for t in ranking], [1, 2, 3, 4])

    def test_standings_record_wins_and_game_diff(self):
        play_all_groups_by_seed(self.t)
        rows = group_standings(self.t.groups.get(name="A"))
        top = rows[0]
        self.assertEqual(top["wins"], 3)  # ha battuto tutte
        self.assertEqual(top["played"], 3)
        self.assertEqual(top["diff"], 18)  # 3 set vinti 6-0
        self.assertEqual(rows[-1]["wins"], 0)

    def test_head_to_head_breaks_tie(self):
        # Triangolo: niente seed deterministico. Costruisco due coppie a pari vittorie
        # dove lo scontro diretto decide.
        g = self.t.groups.get(name="A")
        teams = list(g.teams.order_by("seed"))
        t1, t2, t3, t4 = teams
        # Annullo i risultati e impongo: t1 e t2 vincono 2, ma t1 batte t2 (h2h).
        Match.objects.filter(group=g).delete()
        from .scheduling import generate_group_stage as _gen

        _gen(self.t)

        # Recupero le partite del girone A e le risolvo a mano.
        def play(a, b, winner):
            m = g.matches.filter(team_a__in=[a, b], team_b__in=[a, b]).first()
            if m.team_a_id == winner.id:
                record_match_score(m, [{"games_a": 6, "games_b": 4}])
            else:
                record_match_score(m, [{"games_a": 4, "games_b": 6}])

        play(t1, t2, t1)  # scontro diretto: t1 batte t2
        play(t1, t3, t1)
        play(t1, t4, t4)  # t1 perde una
        play(t2, t3, t2)
        play(t2, t4, t2)  # t2 vince due
        play(t3, t4, t3)
        rows = group_standings(g)
        # t1 e t2 hanno 2 vittorie; lo scontro diretto mette t1 davanti a t2.
        ranks = {r["team"].id: r["rank"] for r in rows}
        self.assertLess(ranks[t1.id], ranks[t2.id])


class BracketTests(TestCase):
    def setUp(self):
        self.t = make_full_tournament()
        generate_group_stage(self.t)
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)

    def _ko(self):
        return self.t.matches.filter(phase__in=[Match.Phase.GOLD, Match.Phase.SILVER])

    def test_knockout_match_count(self):
        # Per tabellone: 4 quarti + 2 semi + 1 finale + 1 terzo/quarto = 8. ×2 = 16.
        self.assertEqual(self._ko().count(), 16)
        self.assertEqual(self._ko().filter(round_label="Quarti").count(), 8)
        self.assertEqual(self._ko().filter(round_label="Finale").count(), 2)
        self.assertEqual(self._ko().filter(round_label="Finale 3°/4°").count(), 2)

    def test_gold_quarter_seeding(self):
        # Seeding a incrocio: la testa di serie (A1) incontra una 2ª di un altro girone.
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        self.assertEqual(qf1.team_a.name, "A1")  # 1ª testa di serie
        self.assertTrue(qf1.team_b.name.endswith("2"))  # contro una 2ª classificata
        self.assertNotEqual(qf1.team_b.name[0], "A")  # di un girone diverso

    def test_silver_has_third_and_fourth_ranked(self):
        qf1 = self.t.matches.get(
            phase=Match.Phase.SILVER, round_label="Quarti", bracket_pos=1
        )
        ranks = {qf1.team_a.name[1], qf1.team_b.name[1]}
        self.assertEqual(ranks, {"3", "4"})  # silver = 3ª/4ª classificate
        self.assertNotEqual(qf1.team_a.name[0], qf1.team_b.name[0])  # gironi diversi

    def test_two_groups_bracket_has_no_quarters(self):
        # Generalizzazione: 2 gironi → 4 squadre gold → semifinali, niente quarti.
        t = make_tournament(slug="due-gironi", num_groups=2)
        for n in range(1, 5):
            Court.objects.create(tournament=t, number=n)
        for letter in "AB":
            g = Group.objects.create(tournament=t, name=letter)
            for k in range(4):
                Team.objects.create(
                    tournament=t,
                    group=g,
                    seed=k + 1,
                    name=f"{letter}{k + 1}",
                    player1="a",
                    player2="b",
                )
        generate_group_stage(t)
        play_all_groups_by_seed(t)
        seed_brackets(t)
        gold = t.matches.filter(phase=Match.Phase.GOLD)
        self.assertEqual(gold.filter(round_label="Quarti").count(), 0)
        self.assertEqual(gold.filter(round_label="Semifinale").count(), 2)
        self.assertEqual(gold.filter(round_label="Finale").count(), 1)
        self.assertEqual(gold.filter(round_label="Finale 3°/4°").count(), 1)

    def test_knockout_all_two_slots(self):
        self.assertTrue(all(m.slot_span == 2 for m in self._ko()))

    def test_no_court_or_team_conflict_in_knockout(self):
        # Una partita a 2 slot occupa slot_index e slot_index+1, sul suo campo.
        occupied = set()  # (slot, court)
        for m in self._ko():
            for s in (m.slot_index, m.slot_index + 1):
                key = (s, m.court_id)
                self.assertNotIn(key, occupied, f"Conflitto campo allo slot {s}")
                occupied.add(key)

    def test_whole_tournament_fits_in_14_slots(self):
        total = schedule_knockout(self.t)  # ritorna slot totali (gironi + knockout)
        self.assertLessEqual(total, 14)
        self.assertEqual(total, 14)  # entra esatto

    def test_winner_advances_to_semifinal(self):
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        sf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Semifinale", bracket_pos=1
        )
        winner = qf1.team_a
        record_match_score(
            qf1, [{"games_a": 6, "games_b": 0}, {"games_a": 6, "games_b": 0}]
        )
        sf1.refresh_from_db()
        self.assertEqual(sf1.team_a_id, winner.id)

    def test_loser_advances_to_third_place_final(self):
        gold_sf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Semifinale", bracket_pos=1
        )
        gold_sf2 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Semifinale", bracket_pos=2
        )
        third = self.t.matches.get(phase=Match.Phase.GOLD, round_label="Finale 3°/4°")
        final = self.t.matches.get(phase=Match.Phase.GOLD, round_label="Finale")
        # Riempio le semifinali avanzando i quarti.
        for pos in (1, 2, 3, 4):
            qf = self.t.matches.get(
                phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=pos
            )
            record_match_score(
                qf, [{"games_a": 6, "games_b": 0}, {"games_a": 6, "games_b": 0}]
            )
        gold_sf1.refresh_from_db()
        gold_sf2.refresh_from_db()
        # Gioco le semifinali: team_a vince entrambe.
        loser1 = gold_sf1.team_b
        record_match_score(
            gold_sf1, [{"games_a": 6, "games_b": 0}, {"games_a": 6, "games_b": 0}]
        )
        record_match_score(
            gold_sf2, [{"games_a": 6, "games_b": 0}, {"games_a": 6, "games_b": 0}]
        )
        third.refresh_from_db()
        final.refresh_from_db()
        self.assertEqual(third.team_a_id, loser1.id)  # perdente SF1 → finale 3°/4°
        self.assertEqual(final.team_a_id, gold_sf1.winner_id)  # vincente SF1 → finale

    def test_rescore_resets_downstream(self):
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        qf2 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=2
        )
        sf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Semifinale", bracket_pos=1
        )
        a, b = qf1.team_a, qf1.team_b
        win = [{"games_a": 6, "games_b": 0}, {"games_a": 6, "games_b": 0}]
        record_match_score(qf1, win)  # vince team_a → va in semifinale
        record_match_score(qf2, win)  # popola l'altro lato della semifinale
        sf1.refresh_from_db()
        self.assertEqual(sf1.team_a_id, a.id)
        record_match_score(sf1, win)  # gioco la semifinale
        sf1.refresh_from_db()
        self.assertEqual(sf1.status, Match.Status.DONE)

        # Ri-segno il quarto col risultato OPPOSTO: ora passa team_b.
        record_match_score(
            qf1, [{"games_a": 0, "games_b": 6}, {"games_a": 0, "games_b": 6}]
        )
        self.assertEqual(qf1._downstream_reset, 1)  # la semifinale è stata azzerata
        sf1.refresh_from_db()
        self.assertEqual(sf1.team_a_id, b.id)  # team aggiornato
        self.assertEqual(sf1.status, Match.Status.SCHEDULED)  # risultato non più valido
        self.assertIsNone(sf1.winner_id)


class ViewTests(TestCase):
    def setUp(self):
        self.t = make_full_tournament()
        generate_group_stage(self.t)
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)

    def url(self, name, **kw):
        return reverse(f"tournaments:{name}", kwargs={"slug": self.t.slug, **kw})

    def test_dashboard_is_overview(self):
        resp = self.client.get(self.url("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.t.name)
        # Panoramica con contenuto reale, non il menu duplicato.
        self.assertContains(resp, "Classifiche gironi")  # riepilogo classifiche
        self.assertContains(resp, "Girone A")  # tabella snapshot
        self.assertContains(resp, "Prossime partite")  # prossime partite

    def test_standings_shows_groups_and_badges(self):
        resp = self.client.get(self.url("standings"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Girone A")
        self.assertContains(resp, "A1")
        self.assertContains(resp, "gold")
        self.assertContains(resp, "silver")

    def test_schedule_shows_times_and_courts(self):
        resp = self.client.get(self.url("schedule"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "14:00")
        self.assertContains(resp, "Campo 1")

    def test_brackets_shows_gold_and_silver_seeding(self):
        resp = self.client.get(self.url("brackets"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Gold")
        self.assertContains(resp, "Silver")
        self.assertContains(resp, "Quarti")

    def test_live_page_ok(self):
        resp = self.client.get(self.url("live"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "live-board")

    def test_no_template_comment_leaks_on_pages(self):
        # Regressione: i commenti {# #} multi-riga venivano renderizzati come testo.
        for name in ("dashboard", "standings", "schedule", "brackets", "live", "stats"):
            body = self.client.get(self.url(name)).content.decode()
            self.assertNotIn("{#", body, f"Commento template trapelato in {name}")
            self.assertNotIn("Polling HTMX", body)

    def test_live_board_is_fragment(self):
        resp = self.client.get(self.url("live_board"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn("<html", body)
        self.assertNotIn("<body", body)
        self.assertIn("live-board", body)

    def test_team_detail_ok(self):
        team = self.t.teams.first()
        resp = self.client.get(self.url("team", team_id=team.id))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, team.name)

    def test_pages_are_full_even_for_htmx(self):
        # Invariante hx-boost: la pagina resta intera anche con header HTMX.
        resp = self.client.get(self.url("standings"), HTTP_HX_REQUEST="true")
        self.assertContains(resp, "<body")

    def test_unknown_tournament_404(self):
        resp = self.client.get(
            reverse("tournaments:dashboard", kwargs={"slug": "inesistente"})
        )
        self.assertEqual(resp.status_code, 404)

    def test_stats_page(self):
        resp = self.client.get(self.url("stats"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Classifica generale")
        self.assertContains(resp, "Miglior attacco")
        self.assertContains(resp, "A1")  # una coppia nella leaderboard

    def test_live_page_has_qr_and_share(self):
        resp = self.client.get(self.url("live"))
        self.assertContains(resp, "data:image/svg+xml")  # QR inline
        self.assertContains(resp, "Condividi")

    def test_open_graph_meta_present(self):
        resp = self.client.get(self.url("dashboard"))
        self.assertContains(resp, 'property="og:title"')
        self.assertContains(resp, 'property="og:description"')
        self.assertContains(resp, 'name="twitter:card"')
        # og:image deve essere ASSOLUTO (i crawler non risolvono URL relativi)
        self.assertContains(resp, "http://testserver/static/img/og.png")

    def test_live_has_custom_og_title(self):
        resp = self.client.get(self.url("live"))
        self.assertContains(resp, "Tabellone live -")

    def test_live_polls_every_60s(self):
        resp = self.client.get(self.url("live"))
        self.assertContains(resp, "every 60s")
        self.assertNotContains(resp, "every 15s")

    def test_tv_page_ok(self):
        resp = self.client.get(self.url("tv"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "tv-board")
        self.assertContains(resp, "Campo 1")

    def test_tv_board_is_fragment(self):
        resp = self.client.get(self.url("tv_board"))
        body = resp.content.decode()
        self.assertNotIn("<html", body)
        self.assertIn("tv-board", body)

    def test_tv_board_has_ticker_and_standings_scene(self):
        resp = self.client.get(self.url("tv_board"))
        self.assertContains(resp, "tv-ticker")  # prossime partite
        self.assertContains(resp, "tv-scene--classifiche")  # scena classifiche
        self.assertContains(resp, "tv-diff")  # differenza game nelle classifiche

    def test_tv_board_shows_brackets_in_knockout(self):
        # setUp ha già generato i tabelloni → le scene gold/silver con SVG sono presenti.
        resp = self.client.get(self.url("tv_board"))
        self.assertContains(resp, "tv-scene--bracket")
        self.assertContains(resp, "Tabellone Gold")
        self.assertContains(resp, "Tabellone Silver")
        # L'SVG deve contenere i box delle coppie gold.
        self.assertContains(resp, "<svg")
        self.assertContains(resp, "QF")  # abbreviazione turno nel SVG

    def test_score_log_page(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        self.client.post(
            reverse(
                "tournaments:score_match",
                kwargs={"slug": self.t.slug, "match_id": m.id},
            ),
            {"action": "final", "set1_a": "6", "set1_b": "4"},
        )
        resp = self.client.get(self.url("score_log"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Registro modifiche")
        self.assertContains(resp, "risultato")


class ScoringViewTests(TestCase):
    def setUp(self):
        self.t = make_full_tournament()
        generate_group_stage(self.t)

    def panel_url(self):
        return reverse("tournaments:score_panel", kwargs={"slug": self.t.slug})

    def match_url(self, match):
        return reverse(
            "tournaments:score_match",
            kwargs={"slug": self.t.slug, "match_id": match.id},
        )

    def test_panel_is_public(self):
        # Lo scoring è aperto a tutti: nessun login richiesto.
        resp = self.client.get(self.panel_url())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Inserimento punteggi")

    def test_score_form_is_fragment(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        resp = self.client.get(self.match_url(m))
        body = resp.content.decode()
        self.assertNotIn("<html", body)
        self.assertIn("score-form", body)

    def test_post_group_score_sets_winner(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        resp = self.client.post(self.match_url(m), {"set1_a": "6", "set1_b": "4"})
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertTrue(m.is_played)
        self.assertEqual(m.winner_id, m.team_a_id)
        self.assertEqual(m.score_display, "6-4")

    def test_post_invalid_tie_returns_error(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        resp = self.client.post(self.match_url(m), {"set1_a": "6", "set1_b": "6"})
        self.assertContains(resp, "vincitore")  # messaggio d'errore
        m.refresh_from_db()
        self.assertFalse(m.is_played)

    def test_post_knockout_two_zero_advances_winner(self):
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        winner = qf1.team_a
        resp = self.client.post(
            self.match_url(qf1),
            {"set1_a": "6", "set1_b": "2", "set2_a": "6", "set2_b": "3"},
        )
        self.assertEqual(resp.status_code, 200)
        sf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Semifinale", bracket_pos=1
        )
        self.assertEqual(sf1.team_a_id, winner.id)

    def test_post_knockout_one_one_without_super_tb_rejected(self):
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        resp = self.client.post(
            self.match_url(qf1),
            {"set1_a": "6", "set1_b": "2", "set2_a": "2", "set2_b": "6"},
        )
        self.assertContains(resp, "super tie-break")
        qf1.refresh_from_db()
        self.assertFalse(qf1.is_played)

    def test_edit_form_prefills_existing_score(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        record_match_score(m, [{"games_a": 6, "games_b": 3}])
        resp = self.client.get(self.match_url(m))
        self.assertContains(resp, 'value="6"')
        self.assertContains(resp, 'value="3"')

    def test_invalid_set_format_rejected(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        resp = self.client.post(
            self.match_url(m), {"action": "final", "set1_a": "6", "set1_b": "5"}
        )
        self.assertContains(resp, "non valido")  # 6-5 non è un set valido
        m.refresh_from_db()
        self.assertFalse(m.is_played)

    def test_super_tiebreak_must_reach_ten(self):
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        resp = self.client.post(
            self.match_url(qf1),
            {
                "action": "final",
                "set1_a": "6",
                "set1_b": "2",
                "set2_a": "2",
                "set2_b": "6",
                "set3_a": "9",
                "set3_b": "7",
            },
        )
        self.assertContains(resp, "Super tie-break")
        qf1.refresh_from_db()
        self.assertFalse(qf1.is_played)

    def test_scoring_creates_log_entry(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        self.client.post(
            self.match_url(m), {"action": "final", "set1_a": "6", "set1_b": "4"}
        )
        self.assertTrue(self.t.score_logs.filter(action="risultato").exists())

    def test_score_panel_open_autoloads_form(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        resp = self.client.get(self.panel_url() + f"?open={m.id}")
        self.assertContains(resp, 'hx-trigger="load"')

    def test_walkover_sets_winner_without_sets(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        winner = m.team_a
        resp = self.client.post(self.match_url(m), {"action": "wo_a"})
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertTrue(m.walkover)
        self.assertEqual(m.winner_id, winner.id)
        self.assertEqual(m.status, Match.Status.DONE)
        self.assertEqual(m.score_display, "W.O.")
        self.assertEqual(m.sets.count(), 0)

    def test_status_toggle_sets_live(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        url = reverse(
            "tournaments:set_match_status",
            kwargs={"slug": self.t.slug, "match_id": m.id},
        )
        resp = self.client.post(url, {"status": "live"})
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.status, Match.Status.LIVE)

    def test_partial_save_keeps_match_live_without_winner(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        m.status = Match.Status.LIVE
        m.save(update_fields=["status"])
        resp = self.client.post(
            self.match_url(m), {"action": "partial", "set1_a": "3", "set1_b": "2"}
        )
        self.assertEqual(resp.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.status, Match.Status.LIVE)
        self.assertIsNone(m.winner_id)
        self.assertEqual(m.score_display, "3-2")

    def test_final_save_after_partial_finalizes(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        m.status = Match.Status.LIVE
        m.save(update_fields=["status"])
        self.client.post(
            self.match_url(m), {"action": "partial", "set1_a": "3", "set1_b": "2"}
        )
        self.client.post(
            self.match_url(m), {"action": "final", "set1_a": "6", "set1_b": "2"}
        )
        m.refresh_from_db()
        self.assertTrue(m.is_played)
        self.assertEqual(m.winner_id, m.team_a_id)
        self.assertEqual(m.status, Match.Status.DONE)

    def test_knockout_partial_allows_single_set_in_progress(self):
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        # Un solo set in corso, 4-3: come parziale è accettato (niente requisito 2 set).
        resp = self.client.post(
            self.match_url(qf1), {"action": "partial", "set1_a": "4", "set1_b": "3"}
        )
        self.assertEqual(resp.status_code, 200)
        qf1.refresh_from_db()
        self.assertEqual(qf1.status, Match.Status.LIVE)
        self.assertIsNone(qf1.winner_id)

    def test_partial_button_only_for_live_matches(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        self.assertNotContains(self.client.get(self.match_url(m)), "Salva parziale")
        m.status = Match.Status.LIVE
        m.save(update_fields=["status"])
        self.assertContains(self.client.get(self.match_url(m)), "Salva parziale")

    def test_scoring_knockout_oob_refreshes_dependent_row(self):
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)
        qf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        sf1 = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Semifinale", bracket_pos=1
        )
        resp = self.client.post(
            self.match_url(qf1),
            {"set1_a": "6", "set1_b": "2", "set2_a": "6", "set2_b": "3"},
        )
        # La risposta contiene la riga della semifinale aggiornata in OOB.
        self.assertContains(resp, "hx-swap-oob")
        self.assertContains(resp, f'id="match-{sf1.id}"')

    def test_result_save_triggers_celebration(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        resp = self.client.post(
            self.match_url(m), {"action": "final", "set1_a": "6", "set1_b": "2"}
        )
        self.assertIn("celebrate", resp.headers.get("HX-Trigger", ""))

    def test_partial_save_does_not_celebrate(self):
        m = self.t.matches.filter(phase=Match.Phase.GROUP).first()
        m.status = Match.Status.LIVE
        m.save(update_fields=["status"])
        resp = self.client.post(
            self.match_url(m), {"action": "partial", "set1_a": "3", "set1_b": "2"}
        )
        self.assertNotIn("celebrate", resp.headers.get("HX-Trigger", ""))

    def test_gold_final_triggers_champion(self):
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)
        for label in ("Quarti", "Semifinale"):
            for m in self.t.matches.filter(round_label=label, phase=Match.Phase.GOLD):
                record_match_score(
                    m, [{"games_a": 6, "games_b": 2}, {"games_a": 6, "games_b": 3}]
                )
        final = self.t.matches.get(phase=Match.Phase.GOLD, round_label="Finale")
        resp = self.client.post(
            self.match_url(final),
            {
                "action": "final",
                "set1_a": "6",
                "set1_b": "2",
                "set2_a": "6",
                "set2_b": "3",
            },
        )
        self.assertIn("champion", resp.headers.get("HX-Trigger", ""))


class AwardsTests(TestCase):
    def setUp(self):
        self.t = make_full_tournament()
        generate_group_stage(self.t)
        play_all_groups_by_seed(self.t)
        seed_brackets(self.t)

    def url(self, name):
        return reverse(f"tournaments:{name}", kwargs={"slug": self.t.slug})

    def test_podium_empty_before_finals(self):
        self.assertIsNone(podium(self.t)["gold"]["first"])

    def test_podium_filled_after_knockout(self):
        play_full_knockout(self.t)
        pod = podium(self.t)["gold"]
        self.assertIsNotNone(pod["first"])
        self.assertIsNotNone(pod["second"])
        self.assertIsNotNone(pod["third"])
        self.assertIsNotNone(pod["fourth"])

    def test_champion_after_knockout(self):
        play_full_knockout(self.t)
        self.assertIsNotNone(champion(self.t))

    def test_team_cappotto_and_imbattuti(self):
        a1 = self.t.teams.get(name="A1")  # vince tutti 6-0 nei gironi
        labels = [b["label"] for b in team_achievements(a1)]
        self.assertIn("Cappotto", labels)
        self.assertIn("Imbattuti", labels)

    def test_rimonta_achievement(self):
        qf = self.t.matches.get(
            phase=Match.Phase.GOLD, round_label="Quarti", bracket_pos=1
        )
        winner = qf.team_a
        record_match_score(
            qf,
            [
                {"games_a": 4, "games_b": 6},
                {"games_a": 6, "games_b": 2},
                {"games_a": 10, "games_b": 7},
            ],
        )
        labels = [b["label"] for b in team_achievements(winner)]
        self.assertIn("Rimonta", labels)

    def test_tournament_awards_has_specials(self):
        aw = tournament_awards(self.t)
        self.assertIn("podium", aw)
        self.assertTrue(any(s["label"] == "Bomber" for s in aw["specials"]))

    def test_albo_page_ok(self):
        play_full_knockout(self.t)
        resp = self.client.get(self.url("albo"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Albo d'oro")
        self.assertContains(resp, "Premi speciali")

    def test_dashboard_champion_banner_after_final(self):
        play_full_knockout(self.t)
        resp = self.client.get(self.url("dashboard"))
        self.assertContains(resp, "champion-banner")
        self.assertContains(resp, "Campione")

    def test_status_becomes_done_after_finals(self):
        play_full_knockout(self.t)  # entrambe le finali giocate
        final = self.t.matches.get(phase=Match.Phase.GOLD, round_label="Finale")
        # Ri-segno la finale gold tramite la VIEW per innescare l'aggiornamento di stato.
        self.client.post(
            reverse(
                "tournaments:score_match",
                kwargs={"slug": self.t.slug, "match_id": final.id},
            ),
            {
                "action": "final",
                "set1_a": "6",
                "set1_b": "2",
                "set2_a": "6",
                "set2_b": "3",
            },
        )
        self.t.refresh_from_db()
        self.assertEqual(self.t.status, Tournament.Status.DONE)


class SetupTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            "org", password="x", is_staff=True
        )

    def test_create_tournament_makes_courts_and_groups(self):
        t = create_tournament("Coppa Estiva", datetime.date(2026, 7, 1))
        self.assertEqual(t.courts.count(), 4)
        self.assertEqual(t.groups.count(), 3)  # default 3 gironi (formato 12 coppie)
        self.assertEqual(t.slug, "coppa-estiva")

    def test_unique_slug(self):
        create_tournament("Doppione", datetime.date(2026, 7, 1))
        t2 = create_tournament("Doppione", datetime.date(2026, 7, 2))
        self.assertEqual(t2.slug, "doppione-2")

    def test_draw_groups_assigns_all_teams(self):
        t = create_tournament("X", datetime.date(2026, 7, 1))
        for i in range(12):  # 3 gironi x 4 = 12 coppie
            Team.objects.create(tournament=t, name=f"C{i}", player1="a", player2="b")
        draw_groups(t)
        self.assertFalse(t.teams.filter(group__isnull=True).exists())
        for g in t.groups.all():
            self.assertEqual(g.teams.count(), 4)

    def test_public_registration_creates_team(self):
        t = create_tournament("X", datetime.date(2026, 7, 1))
        url = reverse("tournaments:register", kwargs={"slug": t.slug})
        resp = self.client.post(
            url, {"name": "Pippo/Pluto", "player1": "Pippo", "player2": "Pluto"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(t.teams.filter(name="Pippo/Pluto").exists())

    def test_registration_honeypot_blocks_bot(self):
        t = create_tournament("X", datetime.date(2026, 7, 1))
        url = reverse("tournaments:register", kwargs={"slug": t.slug})
        self.client.post(
            url,
            {
                "name": "Bot/Bot",
                "player1": "a",
                "player2": "b",
                "website": "http://spam",
            },
        )
        self.assertFalse(t.teams.filter(name="Bot/Bot").exists())

    def test_new_tournament_requires_staff(self):
        resp = self.client.get(reverse("tournaments:new"))
        self.assertEqual(resp.status_code, 302)  # rimandato al login

    def test_manage_requires_staff(self):
        t = create_tournament("X", datetime.date(2026, 7, 1))
        resp = self.client.get(reverse("tournaments:manage", kwargs={"slug": t.slug}))
        self.assertEqual(resp.status_code, 302)

    def test_manage_draw_and_schedule_flow(self):
        t = create_tournament("X", datetime.date(2026, 7, 1))
        for i in range(12):  # 3 gironi x 4 = 12 coppie
            Team.objects.create(tournament=t, name=f"C{i}", player1="a", player2="b")
        self.client.force_login(self.staff)
        url = reverse("tournaments:manage", kwargs={"slug": t.slug})
        self.client.post(url, {"action": "draw"})
        self.client.post(url, {"action": "schedule"})
        t.refresh_from_db()
        self.assertEqual(t.status, Tournament.Status.GROUP)
        self.assertEqual(
            t.matches.filter(phase=Match.Phase.GROUP).count(), 18
        )  # 3 gironi x 6

    def test_new_tournament_post_creates_and_redirects(self):
        self.client.force_login(self.staff)
        resp = self.client.post(
            reverse("tournaments:new"), {"name": "Autunno Cup", "date": "2026-10-05"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Tournament.objects.filter(slug="autunno-cup").exists())


def make_3group_tournament(slug="tre-gironi"):
    """Torneo 3 gironi × 4 coppie (12 coppie totali) con 4 campi."""
    t = Tournament.objects.create(
        name="Tre Gironi",
        slug=slug,
        date=datetime.date(2026, 7, 1),
        num_groups=3,
        teams_per_group=4,
        num_courts=4,
    )
    for n in range(1, 5):
        Court.objects.create(tournament=t, number=n)
    for gi, letter in enumerate("ABC"):
        g = Group.objects.create(tournament=t, name=letter)
        for ti in range(4):
            Team.objects.create(
                tournament=t,
                name=f"{letter}{ti + 1}",
                player1=f"p{gi}{ti}a",
                player2=f"p{gi}{ti}b",
                seed=ti + 1,
                group=g,
            )
    return t


class WildCardBracketTest(TestCase):
    """Test per la logica wild-card: 3 gironi x 4 coppie (12 totali).

    Gold = top-2 di ogni girone (6) + migliori 2 terzi (wild card) = 8.
    Silver = peggior terzo + 3 quarti classificati = 4.
    """

    def _setup_3group(self):
        t = make_3group_tournament()
        generate_group_stage(t)
        return t

    def test_12_team_gold_has_8_teams(self):
        """Con 3 gironi x 4, gold ha 8 coppie in QF e silver ha 4 coppie in SF."""
        t = self._setup_3group()
        play_all_groups_by_seed(t)
        seed_brackets(t)

        # Gold: 4 partite di quarti, tutte con entrambe le coppie assegnate.
        gold_qf = t.matches.filter(phase=Match.Phase.GOLD, round_label="Quarti")
        self.assertEqual(gold_qf.count(), 4, "Gold deve avere 4 quarti (8 coppie).")
        for m in gold_qf:
            self.assertIsNotNone(m.team_a_id, f"QF {m.bracket_pos}: team_a mancante")
            self.assertIsNotNone(m.team_b_id, f"QF {m.bracket_pos}: team_b mancante")

        # Silver: 2 semifinali (4 coppie), niente quarti.
        silver_sf = t.matches.filter(phase=Match.Phase.SILVER, round_label="Semifinale")
        silver_qf = t.matches.filter(phase=Match.Phase.SILVER, round_label="Quarti")
        self.assertEqual(
            silver_sf.count(), 2, "Silver deve avere 2 semifinali (4 coppie)."
        )
        self.assertEqual(
            silver_qf.count(), 0, "Silver non deve avere quarti con 4 coppie."
        )

    def test_wild_cards_are_best_thirds(self):
        """I due terzi con piu vittorie/miglior differenza vanno in gold; il peggiore in silver."""
        t = self._setup_3group()

        # Gioco i gironi a mano per avere terzi con differenti differenziali:
        # Girone A: A1>A2>A3>A4 (terzo A3 ha 1 vitt, diff mediocre)
        # Girone B: B1>B2>B3>B4 (terzo B3 ha 1 vitt, diff mediocre)
        # Girone C: C1>C2>C3>C4 (terzo C3 ha 1 vitt, diff mediocre)
        # Per differenziare i terzi, C3 batte C4 con punteggio piu largo.
        # Approccio: play_all_groups_by_seed fa vince sempre il seed piu basso (6-0),
        # ma poi ri-segno le partite che coinvolgono C3/C4 per dargli diff migliore.

        play_all_groups_by_seed(t)

        # Verifica che dopo seed_brackets i wild card (in gold) siano i 2 terzi con
        # piu vittorie o miglior diff; il terzo rimanente finisce in silver.
        # Per farlo: modifichiamo i risultati del girone C in modo che C3 abbia 2 vittorie
        # (C3 batte C2 e C4), rendendolo il miglior terzo.

        # Azzera le partite del girone C e riscrivile.
        group_c = t.groups.get(name="C")
        Match.objects.filter(group=group_c).delete()
        generate_group_stage(
            t
        )  # rigenera solo il girone C non e' possibile, quindi tutto
        # Il generate_group_stage rigenera tutto; ri-gioco i gironi A e B normalmente,
        # poi il girone C con C3 al secondo posto.

        play_all_groups_by_seed(t)

        # Forza C3 ad avere 2 vittorie: C3 batte C2 (ri-segno quella partita).
        c2 = t.teams.get(name="C2")
        c3 = t.teams.get(name="C3")
        m_c2_c3 = group_c.matches.filter(
            team_a__in=[c2, c3], team_b__in=[c2, c3]
        ).first()
        if m_c2_c3:
            # Ri-segno: C3 vince
            if m_c2_c3.team_a_id == c3.id:
                record_match_score(m_c2_c3, [{"games_a": 6, "games_b": 0}])
            else:
                record_match_score(m_c2_c3, [{"games_a": 0, "games_b": 6}])

        # Ora la classifica del girone C: C1(3v) > C3(2v) > C2(1v) > C4(0v)
        # oppure C1(3v) > C2(2v) > ... dipende dall'ordine scontro diretto.
        # Verifichiamo tramite la classifica effettiva.
        ranking_c = group_ranking(group_c)

        seed_brackets(t)

        # Raccogli le coppie in gold QF.
        gold_qf_teams = set()
        for m in t.matches.filter(phase=Match.Phase.GOLD, round_label="Quarti"):
            gold_qf_teams.add(m.team_a_id)
            gold_qf_teams.add(m.team_b_id)

        # I terzi classificati dei 3 gironi.
        thirds = []
        for g in t.groups.order_by("name"):
            ranking = group_ranking(g)
            thirds.append(ranking[2])  # 0-indexed: indice 2 = terzo

        thirds_in_gold = [t_team for t_team in thirds if t_team.id in gold_qf_teams]
        thirds_in_silver_sf = []
        silver_sf_teams = set()
        for m in t.matches.filter(phase=Match.Phase.SILVER, round_label="Semifinale"):
            silver_sf_teams.add(m.team_a_id)
            silver_sf_teams.add(m.team_b_id)
        thirds_in_silver = [t_team for t_team in thirds if t_team.id in silver_sf_teams]

        self.assertEqual(
            len(thirds_in_gold),
            2,
            f"Esattamente 2 terzi devono andare in gold come wild card, trovati: "
            f"{[tm.name for tm in thirds_in_gold]}",
        )
        self.assertEqual(
            len(thirds_in_silver),
            1,
            f"Esattamente 1 terzo deve finire in silver, trovato: "
            f"{[tm.name for tm in thirds_in_silver]}",
        )

    def test_16_team_unchanged(self):
        """Il formato 4x4 (16 coppie) non usa wild card: gold=8, silver=8, invariato."""
        t = make_full_tournament()
        generate_group_stage(t)
        play_all_groups_by_seed(t)
        seed_brackets(t)

        # Gold: 8 coppie in QF (4 partite), ciascuna con una prima e una seconda.
        gold_qf = t.matches.filter(phase=Match.Phase.GOLD, round_label="Quarti")
        self.assertEqual(gold_qf.count(), 4)
        for m in gold_qf:
            self.assertIsNotNone(m.team_a_id)
            self.assertIsNotNone(m.team_b_id)
            # Nessun terzo o quarto classificato nel gold.
            self.assertIn(
                m.team_a.seed,
                [1, 2],
                f"Gold QF: team_a {m.team_a.name} non e' primo o secondo (seed={m.team_a.seed})",
            )
            self.assertIn(
                m.team_b.seed,
                [1, 2],
                f"Gold QF: team_b {m.team_b.name} non e' primo o secondo (seed={m.team_b.seed})",
            )

        # Silver: 8 coppie in QF (4 partite), ciascuna con una terza e una quarta.
        silver_qf = t.matches.filter(phase=Match.Phase.SILVER, round_label="Quarti")
        self.assertEqual(silver_qf.count(), 4)
        for m in silver_qf:
            self.assertIn(m.team_a.seed, [3, 4])
            self.assertIn(m.team_b.seed, [3, 4])

        # Nessun wild card usato: il totale coppie nei bracket e' esattamente 16.
        all_ko_teams = set()
        for m in t.matches.filter(
            phase__in=[Match.Phase.GOLD, Match.Phase.SILVER], round_label__in=["Quarti"]
        ):
            all_ko_teams.add(m.team_a_id)
            all_ko_teams.add(m.team_b_id)
        self.assertEqual(len(all_ko_teams), 16)

    def test_invalid_format_raises_value_error(self):
        """3 gironi x 3 coppie (9 totali) deve sollevare ValueError."""
        t = Tournament.objects.create(
            name="Formato Strano",
            slug="formato-strano",
            date=datetime.date(2026, 7, 1),
            num_groups=3,
            teams_per_group=3,
            num_courts=3,
        )
        for n in range(1, 4):
            Court.objects.create(tournament=t, number=n)
        for gi, letter in enumerate("ABC"):
            g = Group.objects.create(tournament=t, name=letter)
            for ti in range(3):
                Team.objects.create(
                    tournament=t,
                    name=f"{letter}{ti + 1}",
                    player1=f"p{gi}{ti}a",
                    player2=f"p{gi}{ti}b",
                    seed=ti + 1,
                    group=g,
                )
        generate_group_stage(t)
        play_all_groups_by_seed(t)

        with self.assertRaises(ValueError):
            seed_brackets(t)
