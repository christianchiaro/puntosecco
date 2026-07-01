import datetime

from django.test import TestCase
from django.urls import reverse

from tournaments.models import Tournament


class HomeViewTests(TestCase):
    def test_home_returns_200_and_uses_template(self):
        resp = self.client.get(reverse("core:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "core/home.html")

    def test_home_lists_tournaments_with_links(self):
        t = Tournament.objects.create(
            name="Coppa Test", slug="coppa-test", date=datetime.date(2026, 7, 1)
        )
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, "Coppa Test")
        self.assertContains(
            resp, reverse("tournaments:dashboard", kwargs={"slug": t.slug})
        )

    def test_home_without_tournaments_shows_placeholder(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, "Nessun torneo")

    def test_home_contains_brand(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, "Punto Secco")

    def test_home_body_has_hx_boost(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, 'hx-boost="true"')

    def test_home_is_full_page_even_for_htmx_request(self):
        # Invariante hx-boost: non cambiamo il rendering in base a request.htmx
        # per le pagine intere → la richiesta boosted resta una pagina completa.
        resp = self.client.get(reverse("core:home"), HTTP_HX_REQUEST="true")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "<body")


class AboutViewTests(TestCase):
    def test_about_returns_200_and_uses_template(self):
        resp = self.client.get(reverse("core:about"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "core/about.html")

    def test_about_contains_heading(self):
        resp = self.client.get(reverse("core:about"))
        self.assertContains(resp, "Chi siamo")

    def test_about_mentions_second_edition(self):
        # Racconta la crescita del torneo: siamo alla seconda edizione.
        resp = self.client.get(reverse("core:about"))
        self.assertContains(resp, "seconda edizione")

    def test_about_gallery_has_eight_items(self):
        resp = self.client.get(reverse("core:about"))
        self.assertEqual(resp.content.decode().count("gallery__item"), 8)

    def test_about_gallery_contains_all_eight_images(self):
        resp = self.client.get(reverse("core:about"))
        image_names = [
            "gruppo-fondatori.jpg",
            "premiazione.jpg",
            "amici-in-campo.jpg",
            "locandina-no-rules.jpg",
            "locandina-own-the-court.jpg",
            "locandina-no-second-chances.jpg",
            "locandina-one-tournament.jpg",
            "locandina-one-point-all-in.jpg",
        ]
        for name in image_names:
            self.assertContains(resp, f"/static/img/chi-siamo/{name}")


class RegolamentoViewTests(TestCase):
    def test_regolamento_returns_200_and_uses_template(self):
        resp = self.client.get(reverse("core:regolamento"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "core/regolamento.html")

    def test_regolamento_mentions_punto_secco_rule(self):
        # La specialità del torneo: punto secco al posto del tie-break sul 6-6.
        resp = self.client.get(reverse("core:regolamento"))
        self.assertContains(resp, "Punto Secco")
        self.assertContains(resp, "6-6")

    def test_regolamento_super_tiebreak_unchanged(self):
        # Il super tie-break (3° set knockout) resta un tie-break a punti, non il PS.
        resp = self.client.get(reverse("core:regolamento"))
        self.assertContains(resp, "super tie-break ai 10 punti")

    def test_regolamento_linked_from_nav(self):
        resp = self.client.get(reverse("core:home"))
        self.assertContains(resp, reverse("core:regolamento"))


class OrarioPartialTests(TestCase):
    def test_orario_returns_200_and_uses_partial_template(self):
        resp = self.client.get(reverse("core:orario"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "core/partials/_orario.html")

    def test_orario_contains_label(self):
        resp = self.client.get(reverse("core:orario"))
        self.assertContains(resp, "Orario server")

    def test_orario_is_a_fragment_not_a_full_page(self):
        # Un partial è SOLO il frammento: niente <html>/<body>.
        resp = self.client.get(reverse("core:orario"))
        body = resp.content.decode()
        self.assertNotIn("<html", body)
        self.assertNotIn("<body", body)
        self.assertIn('id="orario"', body)
