import unittest
from engine import Settings, evaluate, evaluate_all, min_price_usd, shipping_quotes


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.row = {"sku": "A", "title": "Test Product", "purchase_jpy": "4500",
                    "target_price_usd": "90", "economy_shipping_jpy": "3800",
                    "fedex_shipping_jpy": "6500", "dhl_shipping_jpy": "7000",
                    "has_battery": "no", "packed_weight_g": "300"}

    def test_positive_profit_and_target_floor(self):
        result = evaluate(self.row, {}, {}, self.settings)
        self.assertIsNotNone(result["profit_jpy"])
        self.assertEqual(result["shipping_method"], "SpeedPAK Economy")
        floor = result["min_price_usd"]
        self.assertGreater(floor, 0)
        test_row = dict(self.row, target_price_usd=str(floor))
        next_result = evaluate(test_row, {}, {}, self.settings)
        self.assertGreaterEqual(next_result["margin_pct"], self.settings.target_margin_pct - 0.02)

    def test_battery_excludes_economy(self):
        self.row["has_battery"] = "yes"
        result = evaluate(self.row, {}, {}, self.settings)
        self.assertEqual(result["shipping_method"], "SpeedPAK FedEx")
        opts = shipping_quotes(self.row, self.settings, 90)
        self.assertFalse(opts[0]["eligible"])

    def test_duty_included_does_not_double_count(self):
        a = evaluate(self.row, {}, {}, self.settings)
        b = evaluate(self.row, {}, {}, Settings(quote_includes_duties=True))
        self.assertGreater(b["profit_jpy"], a["profit_jpy"])
        self.assertEqual(b["breakdown"]["duty_jpy"], 0)
        self.assertEqual(b["breakdown"]["economy_import_fee_jpy"], 0)

    def test_no_invented_shipping(self):
        row = {"sku": "A", "title": "Test", "purchase_jpy": "1000", "target_price_usd": "50"}
        result = evaluate(row, {}, {}, self.settings)
        self.assertIsNone(result["profit_jpy"])

    def test_sales_exact_sku_only(self):
        results = evaluate_all([self.row], [{"sku": "B", "sold_count_90d": 55}], {}, self.settings)
        self.assertIsNone(results[0]["sold_count_90d"])

    def test_custom_fee_override_in_min_price(self):
        standard = min_price_usd(10000, self.settings, "DHL")
        higher = min_price_usd(10000, self.settings, "DHL", 25)
        self.assertGreater(higher, standard)


if __name__ == "__main__":
    unittest.main()
