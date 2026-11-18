# Architectural Drafting Estimator

A local Flask application for preparing preliminary residential drafting estimates. It calculates itemized fees for new builds, produces ranges for additions and remodels, and flags scopes that need review. Saved estimates and revisions retain their original line items in SQLite.

## Run locally

Use Python 3.10 or later.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python demo.py
```

Open the [estimate form](http://127.0.0.1:5051/section-preview). Use fictional contact details in the demo. Stopping the server discards the demo database.

| Project | Inputs | Expected result |
| --- | --- | --- |
| Single-family residence | 2,500 sq ft house, 300 sq ft attached garage, site plan and energy code documents | $5,720 |
| Addition | 250 sq ft of new enclosed space | $1,360–$1,840 |
| Interior remodel | 220 sq ft of remodeled interior space and a site plan | $1,982.50–$2,417.50 |
| Porch with unknown area | Select a porch or deck, leave its area blank, and select a site plan | Review required, with a $750 partial subtotal |

The preview can show a demo inquiry confirmation. To save an estimate, enter the same scope in the [owner form](http://127.0.0.1:5051/new). Open the saved estimate and choose **Create revision** to change the scope and calculate a new price. The earlier estimate keeps its original price.

For a persistent local database, run `.venv/bin/python app.py` and open [the owner interface](http://127.0.0.1:5050).

## How estimates work

- `pricing.py` calculates fees using decimal arithmetic. New builds use project-specific rates. Additions and remodels use progressive area pricing and a preliminary range. Those drafting rates include on-site measurements and drawings of existing and proposed conditions.
- `scope_review.py` handles scopes that need review. When a drafting price is unavailable, confirmed service fees can still appear as a partial subtotal.
- `app.py` uses the same calculation path for preview and save. Each saved record captures its inputs, line items, and pricing rule version. A revision uses current rates and links to the earlier record.
- `templates/` and `static/` contain the forms and estimate views.

The app runs locally for a single user. Inquiry confirmation is simulated. Authentication, contract delivery, and live website integration are outside this release.

## Verify

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python -m pip install ruff
.venv/bin/ruff check .
npx --yes eslint@10 static
```

For the ESLint command, use npm with Node.js 20.19 or later in the 20.x line, 22.13 or later in the 22.x line, or 24 or later.

To exercise all five project types and inquiry submission in headless Chromium, run:

```sh
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python -m playwright install --only-shell chromium
.venv/bin/python -m unittest -v browser_checks
```
