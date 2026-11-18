"""Capture review scopes without turning calibration examples into prices."""
from decimal import Decimal

from pricing import AREA_FIELDS, AREA_RULES_VERSION, area, area_drafting, fixed_services

WORK_TYPES = {
    "edits": "Modify existing plans",
    "existing": "Create existing-condition plans",
    "interior": "Remodel existing space",
    "addition": "Design an addition",
    "exterior": "Design a porch or deck",
    "unsure": "Something else / not sure",
}
LEGACY_DRAWING_SOURCES = {
    "cad": "Usable CAD",
    "pdf": "Accurate PDF",
    "partial": "Incomplete drawings or sketches",
    "none": "No usable drawings",
    "unsure": "Not sure",
}
COMPLEXITIES = {"simple": "Straightforward", "complex": "Complex", "unsure": "Not sure"}
MAX_SCOPE_LENGTH = 3000


def add_revision_context(inputs, note):
    updated_scope = "\n".join(part for part in (inputs["scope"], note) if part)
    if len(updated_scope) <= MAX_SCOPE_LENGTH:
        inputs["scope"] = updated_scope
    else:
        inputs["prior_scope_note"] = "\n".join(filter(None, (inputs.get("prior_scope_note"), note)))


def revision_scope_inputs(scope):
    """Prefill current area fields from a saved scope without altering history."""
    inputs = {"scope": scope.get("description", "")}
    quantities = scope.get("quantities", {})
    if scope.get("work_type") in ("edits", "existing"):
        summary = [WORK_TYPES[scope["work_type"]]]
        summary.extend(f"{q['label']}: {q['value']} {q['unit']}"
                       for q in quantities.values() if q["value"] is not None)
        add_revision_context(inputs, " · ".join(summary))
        inputs["project_type"] = "other"
        return inputs

    for current, former in (
        ("enclosed_sqft", ("addition_sqft", "garage_sqft")),
        ("affected_sqft", ()),
        ("porch_sqft", ("covered_sqft", "uncovered_sqft")),
    ):
        selected = [quantities[key] for key in (current, *former) if key in quantities]
        if selected:
            inputs[current + "_included"] = "on"
            if any(quantity["value"] is None for quantity in selected):
                inputs[current] = ""
                known = [f"{quantity['label']}: {quantity['value']} {quantity['unit']}"
                         for quantity in selected if quantity["value"] is not None]
                if known:
                    add_revision_context(inputs, "Recorded area from prior estimate: " + " · ".join(known))
            else:
                inputs[current] = str(sum(Decimal(quantity["value"]) for quantity in selected))
    return inputs


def review_estimate(values):
    """Price selected areas or explain what is missing."""
    area_based = values["project_type"] == "remodel"
    description = values.get("scope", "").strip()
    if len(description) > MAX_SCOPE_LENGTH:
        raise ValueError("Keep the scope description to 3,000 characters or fewer.")
    quantities = {}
    reasons = []
    if area_based:
        for key, label, _ in AREA_FIELDS:
            if not values.get(key + "_included"):
                continue
            raw = values.get(key, "").strip()
            quantity = area(raw) if raw else None
            if quantity is not None and quantity <= 0:
                raise ValueError(f"Enter a square footage greater than zero for “{label}.”")
            quantities[key] = {"label": label, "unit": "sq ft", "value": str(quantity) if quantity is not None else None}
            if quantity is None:
                reasons.append(f"Enter approximate square footage for “{label}.”")
    elif not description:
        reasons.append("Describe the work you need.")

    items = fixed_services("site_plan" in values, "wsec" in values)
    fixed_total = sum((amount for _, amount in items), Decimal(0))
    estimate_range = None
    drafting_item_count = 0
    if area_based:
        if quantities and all(q["value"] is not None for q in quantities.values()):
            drafting = area_drafting({key: Decimal(quantity["value"]) for key, quantity in quantities.items()})
            drafting_item_count = len(drafting)
            subtotal = sum(amount for _, amount in drafting)
            low = (subtotal * Decimal("0.85")).quantize(Decimal("0.01"))
            high = (subtotal * Decimal("1.15")).quantize(Decimal("0.01"))
            estimate_range = {
                "version": AREA_RULES_VERSION,
                "drafting_low": str(low),
                "drafting_high": str(high),
                "low": str(low + fixed_total),
                "high": str(high + fixed_total),
            }
            items = drafting + items
        elif not quantities:
            reasons.append("Select at least one area and enter its approximate square footage.")
    else:
        reasons.append("Confirm the services needed before estimating the remaining work.")
    return {
        "items": items,
        "total": None,
        "notes": [],
        "estimate_range": estimate_range,
        "drafting_item_count": drafting_item_count,
        "review": {
            "scope": {"description": description, "quantities": quantities},
            "reasons": reasons,
            "partial_subtotal": str(fixed_total) if items and estimate_range is None else None,
        },
    }
