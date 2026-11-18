import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app import create_app
from scope_review import revision_scope_inputs


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "test.sqlite3"
        self.app = create_app(self.db)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def submit(self, path="/new", **changes):
        page = self.client.get(path)
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        data = {"csrf": csrf, "name": "Sample Client", "email": "sample@example.com", "title": "Sample house",
                    "project_type": "single_family", "main_sqft": "2500", "attached_garage_sqft": "300",
                    "site_plan": "on", "wsec": "on"}
        data.update(changes)
        data = {key: value for key, value in data.items() if value is not None}
        return self.client.post(path, data=data)

    def test_revision_uses_current_rules_and_preserves_original(self):
        original = self.submit(wsec=None)
        path = f"{original.location}/revise"
        form = self.client.get(path)
        self.assertIn('value="2500"', form.text)
        self.assertRegex(form.text, r'name="site_plan"\s+checked')
        self.assertNotRegex(form.text, r'name="wsec"\s+checked')
        self.assertIn("Saved estimates <small>(1)", self.client.get("/").text)
        with patch("pricing.RATES", {"single_family": Decimal("2.00")}), patch(
                "pricing.NEW_BUILD_RULES_VERSION", "new-build-v3"):
            revision = self.submit(path, main_sqft="3000", wsec=None)
        self.assertEqual(revision.status_code, 302)
        self.assertNotEqual(revision.location, original.location)

        client = create_app(self.db).test_client()
        for url, total, version, area, linked in (
            (original.location, "$5,370.00", "new-build-v2", "2,500", revision.location),
            (revision.location, "$7,350.00", "new-build-v3", "3,000", original.location),
        ):
            page = client.get(url)
            self.assertIn(total, page.text)
            self.assertIn(version, page.text)
            self.assertIn(f"{area} sq ft", page.text)
            self.assertIn(f'href="{linked}"', page.text)

    def test_revision_prefills_known_and_unknown_selected_areas(self):
        original = self.submit(project_type="remodel", enclosed_sqft_included="on",
                               complexity="complex", scope="Add living space and a porch",
                               enclosed_sqft="250", porch_sqft_included="on",
                               project_address="")
        form = self.client.get(f"{original.location}/revise")
        self.assertIn("Add living space and a porch", form.text)
        self.assertRegex(form.text, r'name="enclosed_sqft"[^>]*value="250"')
        self.assertRegex(form.text, r'name="porch_sqft_included"[^>]*checked')
        self.assertRegex(form.text, r'name="porch_sqft"[^>]*value=""')

    def test_revision_requires_an_existing_parent(self):
        self.assertEqual(self.client.get("/estimates/999/revise").status_code, 404)

    def test_legacy_revision_retains_known_area_and_full_length_description(self):
        description = "a" * 3000
        scope = {
            "description": description,
            "quantities": {
                "addition_sqft": {"label": "Addition area", "value": "75", "unit": "sq ft"},
                "garage_sqft": {"label": "Garage area", "value": None, "unit": "sq ft"},
            },
        }
        inputs = revision_scope_inputs(scope)
        self.assertEqual(inputs["scope"], description)
        self.assertEqual(inputs["enclosed_sqft"], "")
        self.assertIn("Addition area: 75 sq ft", inputs["prior_scope_note"])
        saved = self.submit(project_type="remodel", **inputs)
        self.assertEqual(saved.status_code, 302)

    def test_save_reopen_and_keep_original_pricing(self):
        preview = self.preview()
        self.assertEqual(preview.status_code, 200)
        self.assertIn("Your first estimate", self.client.get("/").text)
        response = self.submit()
        self.assertEqual(response.status_code, 302)
        saved = self.client.get(response.location)
        for expected in ("$5,720.00", "$4,125.00", "$495.00", "$750.00", "$350.00",
                         "Main enclosed area · 2500 sq ft × $1.65/sq ft",
                         "Attached garage area · 300 sq ft × $1.65/sq ft"):
            with self.subTest(expected=expected):
                self.assertIn(expected, preview.text)
                self.assertIn(expected, saved.text)
        self.assertIn("<h3>Drafting</h3>", preview.text)
        self.assertNotIn('class="pricing-basis"', preview.text)
        self.assertNotIn("new-build-v2", preview.text)
        self.assertIn("new-build-v2", self.pricing_basis(saved))

        with patch("pricing.RATES", {"single_family": Decimal("2.00")}), patch(
                "pricing.NEW_BUILD_RULES_VERSION", "new-build-v3"):
            # A fresh app instance demonstrates data survives application restart.
            self.client = create_app(self.db).test_client()
            updated_preview = self.preview()
            reopened = self.client.get(response.location)
        self.assertIn("$6,700.00", updated_preview.text)
        self.assertIn("$5,720.00", reopened.text)
        self.assertEqual(self.pricing_basis(saved), self.pricing_basis(reopened))
        self.assertIn("Sample house", self.client.get("/").text)

    def pricing_basis(self, response):
        match = re.search(r'<section class="pricing-basis"[^>]*>.*?</section>',
                          response.text, re.S)
        self.assertIsNotNone(match, "Missing pricing basis")
        return match.group()

    def test_legacy_estimate_reopens_without_assigned_version(self):
        inquiry = {"title": "Legacy house", "name": "Sample Client", "email": "sample@example.com",
                       "project_type": "single_family", "main_sqft": "1000", "attached_garage_sqft": "200",
                       "site_plan": True, "wsec": False}
        snapshot = {"items": [{"description": "Original drafting", "amount": "1234.56"}],
                        "total": "1234.56", "notes": []}
        legacy_db = Path(self.temp.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy_db)) as connection, connection:
            connection.execute("""CREATE TABLE estimates (
                id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
                inquiry TEXT NOT NULL, snapshot TEXT NOT NULL)""")
            connection.execute("INSERT INTO estimates (created_at, inquiry, snapshot) VALUES (?, ?, ?)",
                               ("2026-01-01T00:00:00+00:00", json.dumps(inquiry), json.dumps(snapshot)))
        client = create_app(legacy_db).test_client()
        page = client.get("/estimates/1")
        self.assertEqual(page.status_code, 200)
        self.assertIn("$1,234.56", page.text)
        self.assertIn("Legacy estimate", page.text)
        self.assertIn("1000 sq ft", page.text)
        self.assertIn("200 sq ft", page.text)
        self.assertIn("Site plan requested</dt><dd>Yes", page.text)
        self.assertNotIn("new-build-v2", page.text)
        self.assertIn('href="/estimates/1/revise"', page.text)

    def test_invalid_request_does_not_save(self):
        self.assertEqual(self.submit(main_sqft="-4").status_code, 400)
        self.assertIn("Your first estimate", self.client.get("/").text)

    def test_unrepresentable_price_is_rejected_in_preview_and_save(self):
        self.assertEqual(self.preview(main_sqft="1e1000000").status_code, 400)
        self.assertEqual(self.submit(main_sqft="1e1000000").status_code, 400)
        self.assertIn("Your first estimate", self.client.get("/").text)

    def test_remodel_has_no_total_and_keeps_addon_request(self):
        response = self.submit(project_type="remodel", main_sqft="")
        page = self.client.get(response.location)
        self.assertIn("Needs review", page.text)
        self.assertIn("Partial subtotal", page.text)
        self.assertIn("$1,100.00", page.text)
        self.assertNotIn("$5,720", page.text)

    def test_notes_are_escaped(self):
        response = self.submit(details="<script>alert(1)</script>")
        page = self.client.get(response.location)
        self.assertNotIn("<script>", page.text)
        self.assertIn("&lt;script&gt;", page.text)

    def test_missing_token_is_rejected(self):
        self.assertEqual(self.client.post("/new", data={}).status_code, 400)

    def test_preview_can_be_refreshed_after_server_restart(self):
        page = self.client.get("/new")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        data = {"csrf": csrf, "project_type": "single_family", "main_sqft": "1000"}
        self.assertEqual(self.client.post("/section-preview", data=data).status_code, 200)

        restarted = create_app(self.db).test_client()
        cookie = self.client.get_cookie(self.app.config["SESSION_COOKIE_NAME"])
        restarted.set_cookie(cookie.key, cookie.value)
        refreshed = restarted.post("/section-preview", data=data)
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn("$1,650.00", refreshed.text)
        self.assertEqual(restarted.post("/new", data=data).status_code, 400)
        self.assertIn("Your first estimate starts here.", restarted.get("/").text)

    def test_unknown_estimate(self):
        self.assertEqual(self.client.get("/estimates/999").status_code, 404)

    def preview(self, **changes):
        data = {
            "project_type": "single_family",
            "main_sqft": "2500", "attached_garage_sqft": "300", "site_plan": "on", "wsec": "on"}
        data.update(changes)
        data = {key: value for key, value in data.items() if value is not None}
        return self.client.post("/section-preview", data=data)

    def test_zero_attached_garage_area_is_omitted_from_pricing_basis(self):
        result = self.submit(attached_garage_sqft="0e-1000")
        self.assertEqual(result.status_code, 302)
        self.assertNotIn("Attached garage area", self.pricing_basis(self.client.get(result.location)))

    def test_section_preview_calculates_without_creating_lead(self):
        response = self.preview()
        self.assertEqual(response.status_code, 200)
        self.assertIn("$5,720.00", response.text)
        self.assertIn("Your first estimate", self.client.get("/").text)

    def test_remodel_has_same_range_in_preview_and_saved_estimate(self):
        scope = {"project_type": "remodel", "affected_sqft_included": "on",
                     "site_plan": "on", "wsec": None, "affected_sqft": "220"}
        preview = self.preview(**scope)
        self.assertIn("Your first estimate", self.client.get("/").text)
        saved = self.submit(**scope)
        self.assertEqual(saved.status_code, 302)
        reopened = self.client.get(saved.location)
        for page in (preview, reopened):
            for expected in ("$1,232.50–$1,667.50", "$1,982.50–$2,417.50",
                             "Estimated total range", "Remodel interior space", "220 sq ft"):
                self.assertIn(expected, page.text)
            self.assertNotIn("Draft total", page.text)
        self.assertIn("<h3>Drafting</h3>", preview.text)
        self.assertIn("<span>Standard residential site plan</span>", preview.text)
        self.assertIn("Project setup", preview.text)
        self.assertIn("Project setup", reopened.text)
        self.assertIn("Rates include on-site measurements", preview.text)
        self.assertIn("addition-remodel-v2", reopened.text)

    def test_drawing_availability_is_not_asked_or_used_for_new_estimates(self):
        for route in ("/section-preview", "/new"):
            self.assertNotIn('name="drawing_source"', self.client.get(route).text)
        scope = {"project_type": "remodel", "affected_sqft_included": "on", "affected_sqft": "220",
                     "complexity": "simple", "drawing_source": "obsolete"}
        preview = self.preview(**scope)
        saved = self.submit(**scope)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(saved.status_code, 302)
        for page in (preview, self.client.get(saved.location)):
            self.assertNotIn("Existing drawings", page.text)
            self.assertNotIn("Confirm what existing drawings are available.", page.text)

    def test_mixed_addition_fills_brackets_with_enclosed_area_first(self):
        scope = {"project_type": "remodel", "enclosed_sqft_included": "on",
                     "enclosed_sqft": "800", "porch_sqft": "400", "porch_sqft_included": "on"}
        preview = self.preview(**scope)
        self.assertEqual(preview.status_code, 200)
        self.assertIn("$3,570.00–$4,830.00", preview.text)
        saved = self.client.get(self.submit(**scope).location)
        self.assertEqual(saved.text.count("Add a porch or deck · 200 sq ft × $1.50/sq ft"), 2)

    def test_area_labels_and_quantities_match_in_preview_and_saved_snapshot(self):
        scope = {"project_type": "remodel", "enclosed_sqft_included": "on", "enclosed_sqft": "125",
                     "affected_sqft_included": "on", "affected_sqft": "375",
                     "porch_sqft_included": "on", "porch_sqft": "120"}
        expected = {
            "enclosed_sqft": ("Add enclosed space", "125", "5.00", "625.00"),
            "affected_sqft": ("Remodel interior space", "375", "5.00", "1875.00"),
            "porch_sqft": ("Add a porch or deck", "120", "1.50", "180.00"),
        }
        preview = self.preview(**scope)
        saved = self.submit(**scope)
        self.assertEqual(saved.status_code, 302)
        with closing(sqlite3.connect(self.db)) as db:
            inquiry, snapshot = map(json.loads, db.execute("SELECT inquiry, snapshot FROM estimates").fetchone())
        self.assertNotIn("main_sqft", inquiry)
        self.assertNotIn("attached_garage_sqft", inquiry)
        reopened = self.client.get(saved.location)
        for key, (label, quantity, rate, amount) in expected.items():
            line = f"{label} · {quantity} sq ft × ${rate}/sq ft"
            self.assertIn(line, preview.text)
            self.assertIn(line, reopened.text)
            self.assertIn({"description": line, "amount": amount}, snapshot["items"])
            self.assertEqual(snapshot["review"]["scope"]["quantities"][key],
                             {"label": label, "unit": "sq ft", "value": quantity})

    def test_unselected_area_does_not_affect_price(self):
        page = self.preview(project_type="remodel", enclosed_sqft_included="on",
                            enclosed_sqft="250", porch_sqft="160")
        self.assertIn("$1,360.00–$1,840.00", page.text)
        self.assertNotIn('name="work_type"', page.text)
        self.assertNotIn('name="complexity"', page.text)

    def test_detached_garage_has_one_area_input_and_preserves_rate(self):
        garage = {"project_type": "detached_garage", "main_sqft": "800",
                      "attached_garage_sqft": None, "site_plan": None, "wsec": None}
        page = self.preview(**garage)
        self.assertEqual(page.status_code, 200)
        self.assertIn("$880.00", page.text)
        self.assertIn("Enter the total enclosed square footage of the detached garage or shop.", page.text)
        self.assertRegex(page.text, r'name="attached_garage_sqft"[^>]*\sdisabled')
        saved = self.client.get(self.submit(**garage).location)
        self.assertNotIn('class="pricing-basis"', page.text)
        basis = self.pricing_basis(saved)
        self.assertIn("Enclosed garage or shop area</dt><dd>800 sq ft", basis)
        self.assertNotIn("Main enclosed area", basis)
        self.assertNotIn("Attached garage area", basis)

    def test_addition_with_unknown_selected_area_shows_only_known_fees(self):
        scope = {"project_type": "remodel", "enclosed_sqft_included": "on", "enclosed_sqft": "250",
                     "porch_sqft_included": "on", "porch_sqft": "", "complexity": "simple",
                     "scope": "Extend the living room."}
        saved = self.submit(**scope)
        self.assertEqual(saved.status_code, 302)
        for page in (self.preview(**scope), self.client.get(saved.location)):
            for expected in ("250 sq ft", "Not yet known", "Enter approximate square footage for “Add a porch or deck.”",
                             "Extend the living room.", "Partial subtotal: $1,100.00"):
                self.assertIn(expected, page.text)
            self.assertNotIn("Estimated total range", page.text)

    def test_exterior_only_project_has_a_range(self):
        page = self.preview(project_type="remodel", porch_sqft_included="on", porch_sqft="160")
        self.assertEqual(page.status_code, 200)
        self.assertIn("$705.50–$954.50", page.text)

    def test_other_keeps_scope_for_review(self):
        scope = {"project_type": "other", "scope": "Review a residential drawing set."}
        for page in (self.preview(**scope), self.client.get(self.submit(**scope).location)):
            self.assertEqual(page.status_code, 200)
            self.assertIn("Review a residential drawing set.", page.text)
            self.assertIn("Confirm the services needed", page.text)

    def test_old_travel_charge_remains_visible_when_reopened(self):
        saved = self.submit()
        self.assertEqual(saved.status_code, 302)
        with closing(sqlite3.connect(self.db)) as db, db:
            inquiry, snapshot = map(json.loads, db.execute(
                "SELECT inquiry, snapshot FROM estimates WHERE id = 1").fetchone())
            inquiry["project_address"] = "101 Example Lane, Example, WA"
            snapshot.pop("drafting_item_count")
            snapshot["travel"] = {"origin": "Laurel, WA", "minutes": "60", "rate": "90.00",
                                      "amount": "90.00", "total": "5810.00"}
            db.execute("UPDATE estimates SET inquiry = ?, snapshot = ? WHERE id = 1",
                       (json.dumps(inquiry), json.dumps(snapshot)))

        reopened = self.client.get(saved.location)
        self.assertIn("Estimated total including driving", reopened.text)
        self.assertIn("$5,810.00", reopened.text)
        self.assertIn("101 Example Lane", reopened.text)
        revision = self.client.get(saved.location + "/revise")
        self.assertNotIn("101 Example Lane", revision.text)

    def test_new_estimates_ignore_address_from_older_forms(self):
        address = "101 Example Lane, Example, WA"
        preview = self.preview(project_address=address)
        saved = self.client.get(self.submit(project_address=address).location)
        for page in (preview, saved):
            self.assertIn("$5,720.00", page.text)
            self.assertIn("$90.00/hr", page.text)
            self.assertNotIn("Round-trip driving", page.text)
            self.assertNotIn(address, page.text)


if __name__ == "__main__":
    unittest.main()
