"""Exercise the customer estimator in Chromium with a disposable demo database."""
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import WSGIRequestHandler, make_server

from demo import create_demo_app


class QuietHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        if str(code).startswith("5"):
            super().log_request(code, size)


class EstimateFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        resources = ExitStack()
        cls.addClassCleanup(resources.close)
        directory = resources.enter_context(TemporaryDirectory())
        app = create_demo_app(Path(directory) / "demo.sqlite3")
        server = make_server("127.0.0.1", 0, app, request_handler=QuietHandler)
        cls.addClassCleanup(server.server_close)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        cls.addClassCleanup(worker.join)
        cls.addClassCleanup(server.shutdown)
        cls.base_url = f"http://127.0.0.1:{server.server_port}"
        playwright = resources.enter_context(sync_playwright())
        cls.browser = playwright.chromium.launch()
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(self.base_url + "/") else route.abort())
        self.page = context.new_page()
        self.page.goto(f"{self.base_url}/section-preview")
        self.project_type = self.page.get_by_role("combobox", name="Project type")
        self.result = self.page.locator("#estimate-result")

    def preview(self):
        self.page.get_by_role("button", name="Preview my estimate").click()
        expect(self.result).to_be_visible()

    def expect_total(self, label, amount):
        expect(self.result.get_by_text(label, exact=True)).to_be_visible()
        expect(self.result.get_by_text(amount, exact=True).first).to_be_visible()

    def open_breakdown(self):
        self.result.get_by_text("Pricing breakdown", exact=True).click()
        expect(self.result.get_by_text("Pricing basis", exact=True)).to_have_count(0)
        expect(self.result.get_by_text("Estimate before driving", exact=True)).to_have_count(0)

    def test_single_family_services_and_contact_preview(self):
        self.page.get_by_role("spinbutton", name="Main enclosed area").fill("2500")
        self.page.get_by_role("spinbutton", name="Attached garage area").fill("300")
        self.page.get_by_role("checkbox", name="Site plan").check()
        self.page.get_by_role("checkbox", name="Energy code documents (WSEC)").check()
        expect(self.page.get_by_role("textbox", name="Project address")).to_have_count(0)
        self.preview()
        self.expect_total("Estimated total", "$5,720.00")
        self.open_breakdown()
        for label in ("Drafting", "Additional services"):
            expect(self.result.get_by_role("heading", name=label, exact=True)).to_be_visible()
        for text in ("Main enclosed area · 2500 sq ft × $1.65/sq ft", "$4,125.00",
                     "Attached garage area · 300 sq ft × $1.65/sq ft", "$495.00",
                     "Standard residential site plan", "$750.00", "Energy code documents (WSEC)",
                     "$350.00", "Additional meetings and site visits, as needed", "$90.00/hr"):
            expect(self.result.get_by_text(text, exact=True)).to_be_visible()

        contact_name = self.result.get_by_role("textbox", name="Full name")
        expect(contact_name).to_be_hidden()
        self.result.get_by_role("button", name="Like what you see? Take the next step!").click()
        expect(contact_name).to_be_focused()
        expect(self.result.get_by_role("textbox", name="Project address")).to_have_count(0)
        submit = self.result.get_by_role("button", name="Submit demo inquiry")
        submit.click()
        expect(contact_name).to_be_focused()
        expect(submit).to_be_visible()
        contact_name.fill("   ")
        self.result.get_by_role("textbox", name="Email").fill("client@example.com")
        submit.click()
        expect(contact_name).to_be_focused()
        expect(submit).to_be_visible()
        contact_name.fill("Example Client")
        original_url = self.page.url
        submit.click()
        expect(self.result.get_by_text("Demo inquiry complete.", exact=False)).to_be_focused()
        expect(self.page).to_have_url(original_url)
        self.expect_total("Estimated total", "$5,720.00")
        self.page.goto(self.base_url + "/")
        expect(self.page.get_by_role("heading", name="Your first estimate starts here.")).to_be_visible()

    def test_multi_family_to_detached_garage_excludes_hidden_attached_area(self):
        self.project_type.select_option(label="Multi-family (2–4 units)")
        expect(self.page.get_by_text("Include the enclosed area of every unit", exact=False)).to_be_visible()
        self.page.get_by_role("spinbutton", name="Main enclosed area").fill("2000")
        self.page.get_by_role("spinbutton", name="Attached garage area").fill("400")
        self.preview()
        self.expect_total("Estimated total", "$3,360.00")

        self.project_type.select_option(label="Detached garage / shop")
        expect(self.result).to_be_hidden()
        expect(self.page.locator('[name="attached_garage_sqft"]')).to_be_disabled()
        expect(self.page.get_by_role("spinbutton")).to_have_count(1)
        self.page.get_by_role("spinbutton", name="Enclosed garage or shop area").fill("1000")
        self.preview()
        self.expect_total("Estimated total", "$1,100.00")
        self.open_breakdown()
        expect(self.result.get_by_text("Enclosed garage or shop area · 1000 sq ft × $1.10/sq ft")).to_be_visible()

    def test_remodel_areas_on_mobile_and_unchecking_stale_area(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.project_type.select_option(label="Addition / Remodel")
        area_options = (
            ("Add enclosed space", "250"),
            ("Remodel interior space", "100"),
            ("Add a porch or deck", "200"),
        )
        expect(self.page.get_by_role("spinbutton")).to_have_count(0)
        for label, area in area_options:
            self.page.get_by_role("checkbox", name=label, exact=True).check()
            self.page.get_by_role("spinbutton", name=f"{label} Approximate area (sq ft)").fill(area)
        self.page.get_by_role("checkbox", name="Site plan").check()
        self.preview()
        # Of the 200 porch sq ft, 150 are in the first bracket and 50 in the second.
        self.expect_total("Estimated total range", "$2,981.25–$3,768.75")
        self.open_breakdown()
        expect(self.result.get_by_text("$2,231.25–$3,018.75", exact=True)).to_be_visible()
        for text in ("Project setup", "Add enclosed space · 250 sq ft × $5.00/sq ft",
                     "Remodel interior space · 100 sq ft × $5.00/sq ft",
                     "Add a porch or deck · 150 sq ft × $3.00/sq ft",
                     "Add a porch or deck · 50 sq ft × $1.50/sq ft"):
            expect(self.result.get_by_text(text, exact=True)).to_be_visible()

        self.page.get_by_role("checkbox", name="Add a porch or deck", exact=True).uncheck()
        expect(self.result).to_be_hidden()
        expect(self.page.locator('[name="porch_sqft"]')).to_be_disabled()
        self.preview()
        self.expect_total("Estimated total range", "$2,535.00–$3,165.00")

    def test_missing_area_and_other_project_show_review_instead_of_total(self):
        self.project_type.select_option(label="Addition / Remodel")
        self.page.get_by_role("checkbox", name="Add a porch or deck", exact=True).check()
        self.page.get_by_role("checkbox", name="Site plan").check()
        self.preview()
        self.expect_total("Estimate status", "Needs review")
        expect(self.result.get_by_text("Enter approximate square footage", exact=False)).to_be_visible()
        expect(self.result.get_by_text("Partial subtotal: $750.00", exact=False)).to_be_visible()

        self.project_type.select_option(label="Other")
        expect(self.page.get_by_role("checkbox", name="Add a porch or deck")).to_be_hidden()
        self.page.get_by_role("textbox", name="Describe the work you need").fill("Review an existing drawing set.")
        self.preview()
        self.expect_total("Estimate status", "Needs review")
        expect(self.result.get_by_text("Review an existing drawing set.", exact=True)).to_be_visible()
        expect(self.result.get_by_text("Estimated total", exact=False)).to_have_count(0)
        expect(self.result.get_by_text("Round-trip driving", exact=False)).to_have_count(0)

    def test_invalid_area_can_be_corrected(self):
        main_area = self.page.get_by_role("spinbutton", name="Main enclosed area")
        main_area.fill("0")
        self.page.get_by_role("button", name="Preview my estimate").click()
        expect(self.page.get_by_role("alert")).to_have_text("Enclosed area must be greater than zero.")
        expect(self.result).to_be_hidden()

        main_area.fill("1000")
        self.preview()
        self.expect_total("Estimated total", "$1,650.00")


if __name__ == "__main__":
    unittest.main()
