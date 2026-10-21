"""Basic US parcel tariffs from user's four 2026 PDFs, via verified CSV catalog.

Only base shipping here. Do not pretend surcharges, destination zoning, duties, and taxes
are included in the basic rate; these must be input or separately confirmed.
"""
from pathlib import Path
from math import ceil
import csv

DATA=Path(__file__).resolve().parent/'data/pdf_shipping_rate_catalog_us.csv'

SERVICE_ZONES={
    'SpeedPAK Economy':'US_MAINLAND_48',
    'Orange Connex Economy':'US_MAINLAND_48',
    'SpeedPAK DHL Express Worldwide':'US_ZONE_10',
}

def catalog():
    with DATA.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def shipment_weight_kg(g, length=None,width=None,height=None,service=''):
    if not g or float(g)<=0: return None
    kg=float(g)/1000
    if all(x is not None and float(x)>0 for x in (length,width,height)):
        divisor=8000 if service in ('SpeedPAK Economy','Orange Connex Economy') else 5000
        kg=max(kg,float(length)*float(width)*float(height)/divisor)
    return kg


def shipping_base(service:str,zone:str,weight_g:float,dimensions:tuple|None=None,has_battery=False):
    d=dimensions or (None,None,None)
    if has_battery and service in ('SpeedPAK Economy','Orange Connex Economy'):
        return None,'電池あり：Economyサービス不可'
    if service in ('SpeedPAK Economy','Orange Connex Economy') and all(x is not None and float(x)>0 for x in d):
        ss=sorted(map(float,d),reverse=True)
        if ss[0]>66 or ss[0]+2*(ss[1]+ss[2])>274:
            return None,'米国Economyのサイズ制限を超過'
    effective=shipment_weight_kg(weight_g,*d,service=service)
    if effective is None: return None,'梱包後重量を入力してください'
    candidates=[x for x in catalog() if x['service']==service and x['zone']==zone and
                float(x['weight_ceiling_kg'])>=effective-1e-9]
    if not candidates:return None,'料金表の適用範囲外。重量・配送地域を確認'
    row=min(candidates,key=lambda x:float(x['weight_ceiling_kg']))
    return {'service':service,'zone':zone,'billable_kg':round(effective,4),
            'bracket_kg':float(row['weight_ceiling_kg']),
            'base_jpy':int(row['base_shipping_jpy']),
            'source':row['source_pdf'],'page':int(row['source_page'])},None


def quote_us_all(weight_g,dimensions=None,has_battery=False,fedex_zone='未指定'):
    result=[]
    services=[('SpeedPAK Economy','US_MAINLAND_48'),('Orange Connex Economy','US_MAINLAND_48'),
              ('SpeedPAK DHL Express Worldwide','US_ZONE_10')]
    if fedex_zone in ('US_WEST','US_OTHER'):
        services.append(('SpeedPAK FedEx FICP',fedex_zone))
    else:
        services.extend([('SpeedPAK FedEx FICP','US_WEST'),('SpeedPAK FedEx FICP','US_OTHER')])
    for service,zone in services:
        rate,error=shipping_base(service,zone,weight_g,dimensions,has_battery)
        if rate:
            rate['note']='基本料金のみ。燃油・混雑期・関税/税金・通関処理手数料は別途。'
            if service=='SpeedPAK FedEx FICP' and fedex_zone=='未指定':
                rate['note']+=' FedEx地域は未指定のため参考値（自動採用しない）。'
            result.append(rate)
    return result
