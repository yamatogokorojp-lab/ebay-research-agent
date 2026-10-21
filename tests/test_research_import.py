import unittest
from research_import import is_terapeak_csv, convert_terapeak_rows

class ResearchImportTests(unittest.TestCase):
    def test_import(self):
        rows = [{'sku':'OCR-001','title':'A watch','average_sold_price':'1582.24','currency':'JPY','total_sold':'2'},
                {'sku':'OCR-001','title':'B watch','average_sold_price_usd':'14','currency':'JPY'}]
        self.assertTrue(is_terapeak_csv(rows))
        sources, sales = convert_terapeak_rows(rows, 158.224)
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]['purchase_jpy'], '')
        self.assertEqual(sales[0]['reference_sold_price_usd'], '10.0')
        self.assertNotIn('sold_count_90d', sales[0])
        self.assertEqual(sources[1]['sku'], sales[1]['sku'])
        self.assertNotEqual(sources[1]['sku'], sources[0]['sku'])

    def test_missing_data_skipped(self):
        sources, sales = convert_terapeak_rows([{'title': ''}, {'title':'Item', 'average_sold_price':'oops'}], 150)
        self.assertEqual(len(sources), 1)
        self.assertNotIn('reference_sold_price_usd', sales[0])
