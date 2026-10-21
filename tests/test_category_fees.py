"""Category/fee safety regression tests (all examples are synthetic)."""
import unittest
from datetime import date

from category_fees import CategoryFeeError, validate_schedule, category_rate
from engine import Settings, evaluate

TODAY = date(2026, 10, 21)


def schedule():
    return {
        'marketplace': 'EBAY_US', 'seller_country': 'JP',
        'store_plan': 'no_store', 'source_url': 'https://www.ebay.com/help/selling/fees-credits-invoices/selling-fees',
        'verified_by_seller': True,
        'effective_from': '2026-10-01', 'effective_to': '2026-10-31',
        'rates': [{'category_id': '12345', 'percentage': 14.0}, {'category_id': '98765', 'percentage': 9.0}],
    }


class CategoryFeeScheduleTests(unittest.TestCase):
    def test_valid_schedule_and_exact_category(self):
        reviewed = validate_schedule(schedule(), today=TODAY)
        self.assertEqual(category_rate(reviewed, '12345', 'no_store'), 14.0)
        self.assertIsNone(category_rate(reviewed, '1234', 'no_store'))
        self.assertIsNone(category_rate(reviewed, '12345', 'basic'))
        self.assertEqual(category_rate(reviewed, '98765', 'no_store'), 9.0)

    def test_start_and_end_dates_are_inclusive(self):
        self.assertEqual(validate_schedule(schedule(), today=date(2026, 10, 1))['rates']['12345'], 14)
        self.assertEqual(validate_schedule(schedule(), today=date(2026, 10, 31))['rates']['12345'], 14)

    def test_expired_and_future_schedule_are_rejected(self):
        for when in (date(2026, 9, 30), date(2026, 11, 1)):
            with self.subTest(when=when), self.assertRaises(CategoryFeeError):
                validate_schedule(schedule(), today=when)

    def test_backwards_dates_are_rejected(self):
        doc = schedule(); doc['effective_to'] = '2026-09-01'
        with self.assertRaises(CategoryFeeError):
            validate_schedule(doc, today=TODAY)

    def test_wrong_country_marketplace_or_store_plan(self):
        for field, val in [('marketplace', 'EBAY_GB'), ('seller_country', 'US'), ('store_plan', '')]:
            doc = schedule(); doc[field] = val
            with self.subTest(field=field), self.assertRaises(CategoryFeeError):
                validate_schedule(doc, today=TODAY)

    def test_unverified_schedule_is_rejected(self):
        for verified in (False, 'true', 1, None):
            doc = schedule(); doc['verified_by_seller'] = verified
            with self.subTest(verified=verified), self.assertRaises(CategoryFeeError):
                validate_schedule(doc, today=TODAY)

    def test_non_ebay_and_imposter_sources_are_rejected(self):
        for url in ('http://www.ebay.com/fees', 'https://www.ebay.com.evil.test/fees',
                    'https://evil.test/@www.ebay.com', 'https://user:pass@www.ebay.com/fees'):
            doc = schedule(); doc['source_url'] = url
            with self.subTest(url=url), self.assertRaises(CategoryFeeError):
                validate_schedule(doc, today=TODAY)

    def test_duplicate_or_invalid_category_is_rejected(self):
        for replacement in ({'category_id': '12345', 'percentage': 10},
                            {'category_id': 'watch', 'percentage': 14},
                            {'category_id': '', 'percentage': 14}):
            doc = schedule(); doc['rates'].append(replacement)
            with self.subTest(replacement=replacement), self.assertRaises(CategoryFeeError):
                validate_schedule(doc, today=TODAY)

    def test_bad_percentage_is_rejected(self):
        for pct in (-1, 51, 'bad', None, float('nan'), float('inf')):
            doc = schedule(); doc['rates'][0]['percentage'] = pct
            with self.subTest(pct=pct), self.assertRaises(CategoryFeeError):
                validate_schedule(doc, today=TODAY)

    def test_tiered_schedule_is_rejected_not_guessed(self):
        for key in ('tier', 'minimum_fee', 'maximum_fee', 'threshold_usd'):
            doc = schedule(); doc['rates'][0][key] = 100
            with self.subTest(key=key), self.assertRaises(CategoryFeeError):
                validate_schedule(doc, today=TODAY)


class FeeCalculationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            'sku': 'TEST-CAT', 'title': 'Sample watch', 'target_price_usd': 100,
            'purchase_jpy': 5000, 'fedex_shipping_jpy': 3000,
            'source_url': 'https://example.test/product', 'country_of_origin': 'JP',
            'packed_weight_g': 200, 'has_battery': 'yes',
        }
        self.settings = Settings(fx_jpy_per_usd=150, ebay_fee_pct=20,
                                 ad_fee_pct=5, us_duty_pct=12.5, fixed_ebay_fee_usd=0.4)

    def test_unverified_csv_category_fee_is_ignored(self):
        row = dict(self.row, category_fee_pct=1, category_id='12345')
        result = evaluate(row, {}, {}, self.settings)
        self.assertEqual(result['ebay_fee_pct_used'], 20)
        self.assertEqual(result['ebay_fee_basis'], '共通仮定（未確認）')

    def test_reviewed_rate_changes_profit_once_and_changes_floor(self):
        reviewed = validate_schedule(schedule(), today=TODAY)
        pct = category_rate(reviewed, '12345', 'no_store')
        generic = evaluate(self.row, {}, {}, self.settings)
        matched = evaluate(dict(self.row, _selected_category_id='12345',
                                _selected_category_name='Sample', _verified_fee_pct=pct), {}, {}, self.settings)
        self.assertEqual(matched['ebay_fee_pct_used'], 14)
        # 6 percentage point discount on sale value 100 USD × 150 JPY/USD.
        self.assertEqual(matched['profit_jpy'] - generic['profit_jpy'], 900)
        self.assertLess(matched['min_price_usd'], generic['min_price_usd'])
        self.assertEqual(matched['breakdown']['ebay_fee_jpy'], round(15000 * .14 + 150*.4))
        self.assertEqual(matched['ebay_category_id'], '12345')

    def test_missing_rate_falls_back_no_accidental_reuse(self):
        reviewed = validate_schedule(schedule(), today=TODAY)
        for cat, plan in [('54321', 'no_store'), ('12345', 'basic')]:
            with self.subTest(category=cat, store_plan=plan):
                rate = category_rate(reviewed, cat, plan)
                self.assertIsNone(rate)
                row = dict(self.row, _selected_category_id=cat)
                if rate is not None:
                    row['_verified_fee_pct'] = rate
                result = evaluate(row, {}, {}, self.settings)
                self.assertEqual(result['ebay_fee_pct_used'], 20)
                self.assertEqual(result['ebay_fee_basis'], '共通仮定（未確認）')


if __name__ == '__main__':
    unittest.main()
