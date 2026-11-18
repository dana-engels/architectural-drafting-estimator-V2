"""Local estimate manager. Run with python app.py; not a public client portal."""
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for

from pricing import (
    AREA_FIELDS,
    ATTACHED_AREA_LABEL,
    DETACHED_AREA_LABEL,
    HOURLY_RATE,
    MAIN_AREA_LABEL,
    SITE_PLAN_FEE,
    SITE_PLAN_LABEL,
    WSEC_FEE,
    WSEC_LABEL,
    estimate,
)
from scope_review import (
    COMPLEXITIES,
    LEGACY_DRAWING_SOURCES,
    WORK_TYPES,
    review_estimate,
    revision_scope_inputs,
)

PROJECTS = {"single_family": "Single-family residence", "multi_family": "Multi-family (2–4 units)",
            "detached_garage": "Detached garage / shop", "remodel": "Addition / Remodel", "other": "Other"}


def calculate_estimate(values):
    if values.get("project_type") in ("remodel", "other"):
        return review_estimate(values)
    return estimate(values.get("project_type"), values.get("main_sqft") or 0,
                    values.get("attached_garage_sqft") or 0,
                    "site_plan" in values, "wsec" in values)


def format_sqft(value):
    quantity = Decimal(value)
    if not quantity:
        return "0"
    # Fixed-point formatting can expand a compact scientific input into a huge string.
    if quantity.as_tuple().exponent < -12 or quantity.adjusted() > 12:
        return str(quantity)
    return format(quantity, ",f")


def create_app(database=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_hex(32), MAX_CONTENT_LENGTH=32 * 1024,
                      DATABASE=str(database or Path(__file__).with_name("estimates.sqlite3")))

    @contextmanager
    def database_connection():
        connection = sqlite3.connect(app.config["DATABASE"])
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    with database_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS estimates (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
            inquiry TEXT NOT NULL, snapshot TEXT NOT NULL,
            parent_id INTEGER REFERENCES estimates(id))""")
        if not any(column[1] == "parent_id" for column in db.execute("PRAGMA table_info(estimates)")):
            db.execute("ALTER TABLE estimates ADD COLUMN parent_id INTEGER REFERENCES estimates(id)")
        db.execute("CREATE INDEX IF NOT EXISTS estimates_parent_idx ON estimates(parent_id)")

    def token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(24)
        return session["csrf"]

    app.jinja_env.globals.update(csrf_token=token, projects=PROJECTS, work_types=WORK_TYPES,
                                 legacy_drawing_sources=LEGACY_DRAWING_SOURCES, complexities=COMPLEXITIES,
                                 area_fields=AREA_FIELDS, hourly_rate=HOURLY_RATE,
                                 main_area_label=MAIN_AREA_LABEL, detached_area_label=DETACHED_AREA_LABEL,
                                 attached_area_label=ATTACHED_AREA_LABEL, site_plan_label=SITE_PLAN_LABEL,
                                 wsec_label=WSEC_LABEL, site_plan_fee=SITE_PLAN_FEE, wsec_fee=WSEC_FEE)
    app.jinja_env.filters["money"] = lambda value: f"${Decimal(value):,.2f}"
    app.jinja_env.filters["sqft"] = format_sqft

    @app.before_request
    def protect_write():
        # The public estimate preview only calculates and does not change saved data.
        if request.method == "POST" and request.endpoint != "section_preview" and (
                not session.get("csrf") or request.form.get("csrf") != session["csrf"]):
            abort(400, "Please reload the form and try again.")

    @app.get("/")
    def index():
        with database_connection() as db:
            records = db.execute("SELECT id, created_at, inquiry, snapshot FROM estimates ORDER BY id DESC").fetchall()
        saved = [
            {
                "id": row[0],
                "created_at": row[1],
                "inquiry": json.loads(row[2]),
                "snapshot": json.loads(row[3]),
            }
            for row in records
        ]
        return render_template("index.html", saved=saved)

    @app.route("/section-preview", methods=["GET", "POST"])
    def section_preview():
        values = request.form.to_dict() if request.method == "POST" else {}
        result, error = None, None
        if request.method == "POST":
            try:
                result = calculate_estimate(values)
            except ValueError as exc:
                error = str(exc)
            except DecimalException:
                error = "The entered area is too large or precise to calculate a price."
        return render_template("section.html", values=values, result=result, error=error), 400 if error else 200

    @app.route("/new", methods=["GET", "POST"])
    @app.route("/estimates/<int:parent_id>/revise", methods=["GET", "POST"])
    def new(parent_id=None):
        values = {}
        if parent_id is not None:
            with database_connection() as db:
                parent = db.execute("SELECT inquiry, snapshot FROM estimates WHERE id = ?",
                                    (parent_id,)).fetchone()
            if parent is None:
                abort(404)
            if request.method == "GET":
                values = json.loads(parent[0])
                for service in ("site_plan", "wsec"):
                    if not values.get(service):
                        values.pop(service, None)
                scope = json.loads(parent[1]).get("review", {}).get("scope", {})
                values.update(revision_scope_inputs(scope))
        if request.method == "POST":
            values = request.form.to_dict()
        error = None
        if request.method == "POST":
            try:
                for key in ("name", "email", "title"):
                    values[key] = values.get(key, "").strip()
                    if not values[key] or len(values[key]) > 200:
                        raise ValueError("Name, email, and project name are required (up to 200 characters each).")
                if "@" not in values["email"] or "." not in values["email"].split("@")[-1]:
                    raise ValueError("Enter a valid email address.")
                if len(values.get("details", "")) > 5000:
                    raise ValueError("Project notes must be 5,000 characters or fewer.")
                result = calculate_estimate(values)
                snapshot = {
                    "items": [
                        {"description": description, "amount": str(amount)}
                        for description, amount in result["items"]
                    ],
                    "total": str(result["total"]) if result["total"] is not None else None,
                    "notes": result["notes"],
                    "drafting_item_count": result["drafting_item_count"],
                }
                if "pricing_basis" in result:
                    snapshot["pricing_basis"] = result["pricing_basis"]
                if "review" in result:
                    snapshot["review"] = result["review"]
                if result.get("estimate_range"):
                    snapshot["estimate_range"] = result["estimate_range"]
                # Save calculated amounts, never recalculate history with future rates.
                inquiry = {key: values.get(key, "") for key in
                           ("name", "email", "title", "project_type", "details")}
                if "pricing_basis" in result:
                    inquiry["main_sqft"] = values.get("main_sqft", "").strip()
                    if inquiry["project_type"] != "detached_garage":
                        inquiry["attached_garage_sqft"] = values.get("attached_garage_sqft", "").strip()
                inquiry.update(site_plan="site_plan" in values, wsec="wsec" in values)
                with database_connection() as db:
                    cursor = db.execute("INSERT INTO estimates (created_at, inquiry, snapshot, parent_id) VALUES (?, ?, ?, ?)",
                                        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                         json.dumps(inquiry), json.dumps(snapshot), parent_id))
                    record_id = cursor.lastrowid
                return redirect(url_for("detail", record_id=record_id))
            except ValueError as exc:
                error = str(exc)
            except DecimalException:
                error = "The entered area is too large or precise to calculate a price."
        return render_template("form.html", values=values, error=error,
                               parent_id=parent_id), 400 if error else 200

    @app.get("/estimates/<int:record_id>")
    def detail(record_id):
        with database_connection() as db:
            row = db.execute("SELECT created_at, inquiry, snapshot, parent_id FROM estimates WHERE id = ?",
                             (record_id,)).fetchone()
            if row is None:
                abort(404)
            revisions = db.execute("SELECT id FROM estimates WHERE parent_id = ? ORDER BY id DESC",
                                   (record_id,)).fetchall()
        return render_template("detail.html", record_id=record_id, created_at=row[0],
                               inquiry=json.loads(row[1]), snapshot=json.loads(row[2]),
                               parent_id=row[3], revisions=[revision[0] for revision in revisions])

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=int(os.environ.get("PORT", "5050")), debug=False)
