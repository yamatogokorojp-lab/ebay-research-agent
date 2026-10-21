"""Rakuten Ichiba and Yahoo Shopping API clients. No scraping or fabricated inventory."""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from urllib.parse import quote
import requests

class SourcingApiError(Exception):
    pass

@dataclass
class Offer:
    marketplace: str
    title: str
    item_price_jpy: int
    item_url: str
    inventory_status: str  # verified_api, unknown (unknown NOT accepted)
    shipping_jpy: int | None = None
    match_status: str = '要確認'
    note: str = ''

    def row(self):
        d=asdict(self)
        d['表示価格JPY'] = self.item_price_jpy
        d['価格+送料JPY'] = (self.item_price_jpy+self.shipping_jpy) if self.shipping_jpy is not None else None
        return d


def _get(url: str, params: dict) -> dict:
    try:
        response=requests.get(url, params=params,timeout=18,headers={'User-Agent':'eBayResearchAgent/2.0'})
        response.raise_for_status()
        payload=response.json()
        if not isinstance(payload,dict):
            raise SourcingApiError('APIの応答形式が不正です')
        return payload
    except (requests.RequestException, ValueError) as exc:
        raise SourcingApiError(f'API通信に失敗: {exc}') from exc


def rakuten_search(keyword:str, app_id:str, access_key:str='', hits:int=30) -> list[Offer]:
    if not app_id: raise SourcingApiError('楽天のApplication IDが未設定です')
    params={'applicationId':app_id,'keyword':keyword,'hits':min(30,max(1,hits)),
            'availability':1,'sort':'+itemPrice','format':'json'}
    if access_key: params['accessKey']=access_key
    data=_get('https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601',params)
    if 'error' in data: raise SourcingApiError(f"楽天API: {data.get('error_description',data['error'])}")
    found=[]
    for entry in data.get('Items',[]):
        obj=entry.get('Item',entry)
        if not isinstance(obj,dict): continue
        # API availability=1 requests in-stock items. Reject explicit unavailable.
        stock=obj.get('availability')
        if stock is not None and str(stock).lower() in ('0','false','no'): continue
        price=obj.get('itemPrice'); url=obj.get('itemUrl')
        if not price or not url: continue
        postage=obj.get('postageFlag')
        shipping=0 if str(postage)=='0' else None
        found.append(Offer('楽天市場',str(obj.get('itemName','')),int(float(price)),str(url),
                           'verified_api',shipping,note='API在庫あり条件 / 送料は無料表示のみ確定'))
    return found


def yahoo_search(keyword:str, app_id:str, hits:int=50) -> list[Offer]:
    if not app_id: raise SourcingApiError('Yahoo!ショッピングのClient IDが未設定です')
    # API V3: itemSearch returns inStock for supported products.
    data=_get('https://shopping.yahooapis.jp/ShoppingWebService/V3/itemSearch',
              {'appid':app_id,'query':keyword,'results':min(50,max(1,hits)),'sort':'+price'})
    if 'Error' in data or 'error' in data:
        raise SourcingApiError('Yahoo APIからエラー応答: '+str(data.get('Error',data.get('error')))[:200])
    found=[]
    for obj in data.get('hits',[]):
        if not isinstance(obj,dict): continue
        # Do not interpret missing inStock as available.
        if obj.get('inStock') is not True and str(obj.get('inStock')).lower() not in ('true','1'): continue
        price=obj.get('price')
        if isinstance(price,dict): price=price.get('value')
        url=obj.get('url')
        if not price or not url: continue
        shipping=None
        sh=obj.get('shipping')
        # Only take 0 when it is explicitly a free-shipping code, not an unverified estimate.
        if isinstance(sh,dict) and str(sh.get('code')) in ('1',): shipping=0
        found.append(Offer('Yahoo!ショッピング',str(obj.get('name','')),int(float(price)),str(url),
                           'verified_api',shipping,note='APIのinStock=trueのみ / 送料別途確認'))
    return found


def compact(s:str)->str:
    return re.sub(r'[^a-z0-9]+','',str(s).lower())


def match_model(offer:Offer,model:str) -> Offer:
    """Only label exact model-code containing offers; otherwise fail closed."""
    model=str(model or '').strip()
    if not model:
        offer.match_status='型番未入力・商品一致未確認'
    else:
        needle = compact(model)
        # Respect alphanumeric boundaries. Simple substring matching would accept
        # SND379P1 inside SND379P10 (a different model).
        symbols = [re.escape(c) for c in needle]
        expr = r'(?<![a-z0-9])' + r'[^a-z0-9]*'.join(symbols) + r'(?![a-z0-9])'
        exact = len(needle) >= 4 and re.search(expr, str(offer.title), flags=re.I)
        offer.match_status = '型番一致（最終確認要）' if exact else '型番不一致'
    return offer


def search_links(keyword:str)->dict[str,str]:
    q=quote(keyword,safe='')
    return {'メルカリ':f'https://jp.mercari.com/search?keyword={q}',
            'Yahoo!オークション':f'https://auctions.yahoo.co.jp/search/search?p={q}',
            '楽天':f'https://search.rakuten.co.jp/search/mall/{q}/',
            'Yahoo!ショッピング':f'https://shopping.yahoo.co.jp/search?p={q}'}
