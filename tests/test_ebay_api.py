import unittest
from unittest.mock import patch, Mock
from ebay_api import discover_active_offers, search_current_listings


class EbayApiTests(unittest.TestCase):
    @patch("ebay_api.requests.get")
    def test_current_offers_are_not_sold_prices(self, mock_get):
        response = Mock()
        response.json.return_value = {"total": 250, "itemSummaries": [
            {"price": {"currency": "USD", "value": "100"},
             "shippingOptions": [{"shippingCost": {"currency": "USD", "value": "10"}}]},
            {"price": {"currency": "USD", "value": "150"}},
            {"price": {"currency": "JPY", "value": "1000"}},
        ]}
        mock_get.return_value = response
        actual = search_current_listings("dummy_token", "camera")
        self.assertEqual(actual["market_median_usd"], 130.0)
        self.assertEqual(actual["count"], 2)
        self.assertEqual(actual["search_total"], 250)
        self.assertNotIn("sold_count_90d", actual)

    @patch("ebay_api.requests.get")
    def test_discovery_does_not_invent_sourcing(self, mock_get):
        response = Mock()
        response.json.return_value = {"itemSummaries": [
            {"itemId": "v1", "title": "Camera Model A", "price": {"value": "80", "currency": "USD"},
             "itemWebUrl": "https://www.ebay.com/itm/1"},
        ]}
        mock_get.return_value = response
        rows = discover_active_offers("dummy_token", ["Camera"], 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["purchase_jpy"], "")
        self.assertEqual(rows[0]["target_price_usd"], "")
        self.assertEqual(rows[0]["source_url"], "")
        self.assertEqual(rows[0]["reference_active_price_usd"], "80")


if __name__ == "__main__":
    unittest.main()
