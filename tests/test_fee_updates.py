import unittest
from datetime import datetime, timezone
from unittest.mock import patch, Mock
from fee_updates import validate_fee_feed, fetch_verified_fees, FeeUpdateError
from engine import Settings, shipping_quotes, evaluate

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)

def payload():
    return {'rates': {'SpeedPAK Economy': {'fuel_pct': 10, 'peak_jpy': 200,
          'customs_jpy': 180, 'other_jpy': 20, 'effective_from': '2026-10-01',
          'effective_to': '2026-10-31',
          'source_url': 'https://www.orangeconnex.jp/charges'}}}

class FeeTests(unittest.TestCase):
    def test_validate_accepted(self):
        result = validate_fee_feed(payload(), NOW)
        self.assertEqual(result['SpeedPAK Economy']['fuel_pct'], 10)
    def test_missing_fee_fails_closed(self):
        doc = payload(); del doc['rates']['SpeedPAK Economy']['peak_jpy']
        with self.assertRaises(FeeUpdateError): validate_fee_feed(doc, NOW)
    def test_expired_fee_rejected(self):
        doc = payload(); doc['rates']['SpeedPAK Economy']['effective_to'] = '2026-10-20'
        with self.assertRaises(FeeUpdateError): validate_fee_feed(doc, NOW)
    def test_fake_official_source_rejected(self):
        doc = payload(); doc['rates']['SpeedPAK Economy']['source_url'] = 'https://orangeconnex.jp.fake-site.com/'
        with self.assertRaises(FeeUpdateError): validate_fee_feed(doc, NOW)
    @patch('fee_updates.requests.get')
    def test_fetch_requires_official_feed(self, get):
        res=Mock(); res.json.return_value=payload(); res.raise_for_status.return_value=None; get.return_value=res
        result=fetch_verified_fees('https://www.orangeconnex.jp/charges.json', NOW)
        self.assertEqual(result['SpeedPAK Economy']['customs_jpy'], 180)
        with self.assertRaises(FeeUpdateError): fetch_verified_fees('https://example.org/charges.json', NOW)
        self.assertEqual(get.call_count,1)
    def test_method_specific_fee_does_not_leak_to_other_carriers(self):
        settings=Settings(method_fees=validate_fee_feed(payload(),NOW))
        row={'economy_shipping_jpy':'2000','fedex_shipping_jpy':'3000','target_price_usd':'100','purchase_jpy':'1000'}
        quotes=shipping_quotes(row,settings,100)
        econ=next(x for x in quotes if x['method']=='SpeedPAK Economy')
        fedex=next(x for x in quotes if x['method']=='SpeedPAK FedEx')
        self.assertEqual(econ['additional_shipping_fees_jpy'],600)
        self.assertEqual(fedex['additional_shipping_fees_jpy'],0)
        self.assertIsNone(fedex['fees_verified_source'])
        e=evaluate(row,{}, {}, settings)
        self.assertIn('配送業者ごとの追加料金の適用額が未確認。利益は暫定値',e['warnings'] if e['shipping_method']=='SpeedPAK FedEx' else []) if e['shipping_method']=='SpeedPAK FedEx' else None
    def test_cpass_all_in_skips_fee(self):
        settings=Settings(quote_includes_duties=True,method_fees=validate_fee_feed(payload(),NOW))
        quotes=shipping_quotes({'economy_shipping_jpy': '2000'}, settings, 100)
        self.assertEqual(quotes[0]['additional_shipping_fees_jpy'],0)

if __name__=='__main__': unittest.main()
