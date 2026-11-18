# Architectural Drafting Estimator

A local Flask application for preparing preliminary residential drafting estimates. It calculates itemized fees for new builds, produces ranges for additions and remodels, and flags scopes that need review. Saved estimates and revisions retain their original line items in SQLite.

## Quickstart

Use Python 3.10 or later. The commands below use a macOS/Linux shell and run
from the repository root. SQLite is included with standard Python installations;
no separate database server is needed.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python demo.py
```

1. Open the [estimate form](http://127.0.0.1:5051/section-preview) and select **Single-family residence**.
2. Enter **2,500 sq ft** of main enclosed area and **300 sq ft** of attached garage area. Select **Standard residential site plan** and **Energy code documents (WSEC)**.
3. Click **Preview my estimate**. The total is **$5,720**. Open **Pricing breakdown** to see both area charges and the two fixed fees.

Follow the [new-build pricing calculation](pricing.py#L79) and its [regression test for this example](test_pricing.py#L8).

Use fictional contact details in the demo. Stopping the server discards the demo database.

### More examples

| Project | Inputs | Expected result |
| --- | --- | --- |
| Addition | 250 sq ft of new enclosed space | $1,360–$1,840 |
| Interior remodel | 220 sq ft of remodeled interior space and a site plan | $1,982.50–$2,417.50 |
| Porch with unknown area | Select a porch or deck, leave its area blank, and select a site plan | Review required, with a $750 partial subtotal |

The preview can show a demo inquiry confirmation. To save an estimate, enter the same scope in the [owner form](http://127.0.0.1:5051/new). Open the saved estimate and choose **Create revision** to change the scope and calculate a new price. The earlier estimate keeps its original price.

For a persistent local database, run `.venv/bin/python app.py` and open [the owner interface](http://127.0.0.1:5050).

## How estimates work

- `pricing.py` uses decimal arithmetic to avoid binary floating-point errors in money calculations. When an area charge is split into lines, rounding differences are allocated so the lines add up to the rounded combined charge. New builds use project-specific rates.
- `scope_review.py` calculates addition/remodel ranges and handles scopes that need review. When a drafting price is unavailable, confirmed service fees can still appear as a partial subtotal.
- `app.py` uses one calculation path so preview and save agree for the same inputs and rates. Each saved record captures its inputs, line items, and pricing rule version instead of recalculating historical prices when rates change. A revision uses current rates and links to the earlier record.
- `templates/` and `static/` contain the forms and estimate views.

The app runs locally for a single user. Inquiry confirmation is simulated. Authentication, contract delivery, and live website integration are outside this release.

### Addition and remodel ranges

Drafting starts with a $350 setup fee. Selected areas share successive pricing
brackets: new enclosed space is allocated first, remodeled interior space next,
and porch/deck space last. A bracket's rate applies only to the area in that bracket.

| Cumulative selected area | Enclosed or remodeled interior | Porch or deck |
| --- | --- | --- |
| First 500 sq ft | $5.00/sq ft | $3.00/sq ft |
| Next 500 sq ft (up to 1,000 total) | $2.50/sq ft | $1.50/sq ft |
| Above 1,000 sq ft | $1.65/sq ft | $1.50/sq ft |

The preliminary drafting range is 85%–115% of the drafting subtotal, including
setup. Selected fixed fees—$750 for the site plan and $350 for WSEC—are added
afterward, so they are not widened by the range. These drafting rates include
on-site measurements and drawings of existing and proposed conditions.
See the [bracket calculation](pricing.py#L35) and
[mixed-area regression test](test_app.py#L245).

## Verify

These optional development tools are separate from running the application.

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

On Linux, install Chromium's system dependencies too: replace the browser
installation command with
`.venv/bin/python -m playwright install --with-deps --only-shell chromium`.
Installing these system packages may require administrator access.

### Automated checks

The [CI workflow](.github/workflows/ci.yml) runs on pushes and pull requests
to `main` and can also be run manually. It uses Ubuntu 24.04, runs backend
tests on Python 3.10 and 3.14, and runs Ruff, ESLint 10 with Node 24, and the
five Chromium browser checks on Python 3.14. Backend tests include saving
estimates in temporary SQLite databases, reopening them with changed rates,
and preserving original prices and linked revisions.

Open [Actions → CI](https://github.com/dana-engels/architectural-drafting-estimator-V2/actions/workflows/ci.yml),
select a run, and open a job to see its commands and results for that commit.
Each run installs dependencies; a failed command fails its job. CI checks the
local demonstration, not production deployment or every supported environment.
