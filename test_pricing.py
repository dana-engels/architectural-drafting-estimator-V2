import unittest
from decimal import Decimal

from pricing import estimate


class PricingTests(unittest.TestCase):
    def test_single_family_with_garage_and_services(self):
        self.assertEqual(estimate("single_family", 2500, 300, True, True)["total"],
                         Decimal("5720.00"))

    def test_detached_garage_rate(self):
        self.assertEqual(estimate("detached_garage", 1000)["total"], Decimal("1100.00"))

    def test_fractional_area_rounds_to_cents(self):
        self.assertEqual(estimate("single_family", "2500.01")["total"], Decimal("4125.02"))

    def test_separate_area_lines_keep_the_original_combined_rounding(self):
        result = estimate("single_family", "1.01", "1.01")
        self.assertEqual([amount for _, amount in result["items"]], [Decimal("1.67"), Decimal("1.66")])
        self.assertEqual(result["total"], Decimal("3.33"))

    def test_multifamily_attached_garage_uses_building_rate(self):
        self.assertEqual(estimate("multi_family", 2000, 300)["total"], Decimal("3220.00"))

    def test_remodel_does_not_invent_total(self):
        self.assertIsNone(estimate("remodel")["total"])

    def test_invalid_area(self):
        for value in (-1, 0, "NaN", "Infinity", "invalid"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                estimate("single_family", value)

    def test_detached_garage_prevents_double_entry(self):
        with self.assertRaises(ValueError):
            estimate("detached_garage", 1000, 200)


if __name__ == "__main__":
    unittest.main()
