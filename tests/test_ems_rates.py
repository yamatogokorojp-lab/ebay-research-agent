import unittest
from ems_rates import parse_ems_rate_csv, lookup_ems_rate, EMSRateError

class EMSTests(unittest.TestCase):
    def test_band(self):
        bands=parse_ems_rate_csv(b'max_weight_g,price_jpy\n500,2000\n1000,3000\n')
        self.assertEqual(lookup_ems_rate(bands, 501),3000)
        self.assertIsNone(lookup_ems_rate(bands,1001))
    def test_duplicate(self):
        with self.assertRaises(EMSRateError):
            parse_ems_rate_csv(b'max_weight_g,price_jpy\n500,2000\n500,3000\n')
