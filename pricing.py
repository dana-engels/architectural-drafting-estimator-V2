"""Drafting rates, area brackets, service fees, and decimal money calculations."""

from decimal import Decimal, InvalidOperation

RATES = {
    "single_family": Decimal("1.65"),
    "multi_family": Decimal("1.40"),
    "detached_garage": Decimal("1.10"),
}
HOURLY_RATE = Decimal("90.00")
NEW_BUILD_RULES_VERSION = "new-build-v2"
SITE_PLAN_FEE = Decimal("750.00")
WSEC_FEE = Decimal("350.00")
AREA_RULES_VERSION = "addition-remodel-v2"

AREA_FIELDS = (
    ("enclosed_sqft", "Add enclosed space", "Include new living space or enclosed garage area."),
    ("affected_sqft", "Remodel interior space", "Include only the rooms or portions being changed."),
    ("porch_sqft", "Add a porch or deck", "Include covered and uncovered areas."),
)
MAIN_AREA_LABEL = "Main enclosed area"
DETACHED_AREA_LABEL = "Enclosed garage or shop area"
ATTACHED_AREA_LABEL = "Attached garage area"
SITE_PLAN_LABEL = "Standard residential site plan"
WSEC_LABEL = "Energy code documents (WSEC)"


def priced_area(label, quantity, rate, prior_quantity):
    # Allocate any rounding difference inside the bracket to preserve its original subtotal.
    combined = ((prior_quantity + quantity) * rate).quantize(Decimal("0.01"))
    prior = (prior_quantity * rate).quantize(Decimal("0.01"))
    return (f"{label} · {quantity} sq ft × ${rate}/sq ft", combined - prior)


def area_drafting(areas):
    """Price successive brackets, allocating enclosed area before exterior."""
    items = [("Project setup", Decimal("350.00"))]
    used = Decimal(0)
    area_labels = {key: label for key, label, _ in AREA_FIELDS}
    for keys, rates in (
        (("enclosed_sqft", "affected_sqft"), ("5.00", "2.50", "1.65")),
        (("porch_sqft",), ("3.00", "1.50", "1.50")),
    ):
        remaining = {key: areas.get(key, Decimal(0)) for key in keys}
        for ceiling, rate_text in zip((500, 1000, None), rates, strict=True):
            rate = Decimal(rate_text)
            bracket_quantity = Decimal(0)
            for key in keys:
                available = remaining[key]
                quantity = available if ceiling is None else min(available, max(0, ceiling - used))
                if not quantity:
                    continue
                items.append(priced_area(area_labels[key], quantity, rate, bracket_quantity))
                bracket_quantity += quantity
                used += quantity
                remaining[key] -= quantity
    return items


def fixed_services(site_plan, wsec):
    items = []
    if site_plan:
        items.append((SITE_PLAN_LABEL, SITE_PLAN_FEE))
    if wsec:
        items.append((WSEC_LABEL, WSEC_FEE))
    return items


def area(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Area must be a valid number.") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Area must be a finite, nonnegative number.")
    return result


def estimate(project_type, main_sqft=0, attached_garage_sqft=0,
             site_plan=False, wsec=False):
    """Calculate new-build line items, retaining the review-only remodel fallback.

    For detached garages, main_sqft is the garage's enclosed area.
    The application routes remodels through scope_review.review_estimate for
    area-based ranges; this fallback does not calculate those ranges.
    """
    if project_type == "remodel":
        return {
            "items": [],
            "total": None,
            "drafting_item_count": 0,
            "notes": ["More project information is required before estimating hours.",
                      "Drafting and on-site services are $90/hour; hours to be determined."],
        }
    if project_type not in RATES:
        raise ValueError("Choose single_family, multi_family, detached_garage, or remodel.")
    main = area(main_sqft)
    garage = area(attached_garage_sqft)
    if project_type == "detached_garage" and garage:
        raise ValueError("Enter detached garage area in main_sqft only.")
    total_area = main + garage
    if total_area <= 0:
        raise ValueError("Enclosed area must be greater than zero.")
    rate = RATES[project_type]
    main_label = DETACHED_AREA_LABEL if project_type == "detached_garage" else MAIN_AREA_LABEL
    items = [priced_area(main_label, main, rate, Decimal(0))] if main else []
    if garage:
        items.append(priced_area(ATTACHED_AREA_LABEL, garage, rate, main))
    drafting_item_count = len(items)
    site_plan_fee = SITE_PLAN_FEE if site_plan else None
    wsec_fee = WSEC_FEE if wsec else None
    items.extend(fixed_services(site_plan, wsec))
    return {
        "items": items,
        "total": sum((cost for _, cost in items), Decimal("0.00")),
        "drafting_item_count": drafting_item_count,
        "pricing_basis": {
            "version": NEW_BUILD_RULES_VERSION,
            "main_sqft": str(main),
            "attached_garage_sqft": str(garage),
            "rate_per_sqft": str(rate),
            "site_plan_fee": str(site_plan_fee) if site_plan_fee is not None else None,
            "wsec_fee": str(wsec_fee) if wsec_fee is not None else None,
            "assumptions": [
                "The estimate uses enclosed area.",
                *(["Attached garage area uses the same rate as the main building."] if garage else []),
                "Hourly services outside the listed scope are not included.",
                "Permit submittal is not included.",
            ],
        },
        "notes": ["Draft estimate for review.",
                  "Additional hourly services: $90/hour; hours to be determined."],
    }


if __name__ == "__main__":
    result = estimate("single_family", 2500, 300, site_plan=True, wsec=True)
    for description, cost in result["items"]:
        print(f"{description}: ${cost:,.2f}")
    print(f"Draft total: ${result['total']:,.2f}")
