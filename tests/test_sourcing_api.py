import unittest
from unittest.mock import patch
from sourcing_api import rakuten_search, yahoo_search, match_model, Offer, SourcingApiError

class ApiTests(unittest.TestCase):
    @patch('sourcing_api._get')
    def test_rakuten_stock_and_order(self, get):
        get.return_value = {'Items': [
            {'Item': {'itemName':'SEIKO SND379P1', 'itemPrice': '6800', 'itemUrl':'https://item.rakuten.co.jp/a', 'availability': 1, 'postageFlag': 0}},
            {'Item': {'itemName':'SEIKO SND379P1', 'itemPrice': '1000', 'itemUrl':'https://item.rakuten.co.jp/b', 'availability': 0}},
        ]}
        result=rakuten_search('SND379P1','test-app')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_price_jpy,6800)
        self.assertEqual(get.call_args.args[1]['availability'],1)
    @patch('sourcing_api._get')
    def test_yahoo_unknown_inventory_not_treated_as_in_stock(self,get):
        get.return_value={'hits': [
            {'name':'SEIKO SND379P1', 'price': {'value':'3300'}, 'url':'https://shopping.yahoo.co.jp/a', 'inStock':False},
            {'name':'SEIKO SND379P1', 'price': {'value':'5100'}, 'url':'https://shopping.yahoo.co.jp/b', 'inStock':True},
            {'name':'SEIKO SND379P1', 'price': '100', 'url':'https://shopping.yahoo.co.jp/c'},
        ]}
        result=yahoo_search('SND379P1','key')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].item_price_jpy,5100)
    def test_model_exact_rejects_longer_code(self):
        offer=Offer('楽天','SEIKO SND379P10',9800,'https://example.com', 'verified_api')
        self.assertEqual(match_model(offer,'SND379P1').match_status,'型番不一致')
        offer.title='Seiko SND-379 P1 Good'
        self.assertIn('型番一致', match_model(offer,'SND379P1').match_status)
    def test_missing_credentials_fails(self):
        with self.assertRaises(SourcingApiError): rakuten_search('SEIKO', '')
        with self.assertRaises(SourcingApiError): yahoo_search('SEIKO', '')

if __name__=='__main__': unittest.main()
