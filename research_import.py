"""Bridge Product Research screenshot CSV rows to sourcing and sold-reference data.

A missing purchase cost is never replaced with a dummy number; this is important
because zero would falsely imply a profitable sale.
"""
from __future__ import annotations
import math
from typing import Mapping


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _positive(value):
    try:
        v = float(_clean(value).replace(',', ''))
        return v if math.isfinite(v) and v > 0 else None
    except (TypeError, ValueError):
        return None


def is_terapeak_csv(records):
    if not records:
        return False
    keys = set(records[0])
    return 'title' in keys and (('average_sold_price' in keys and 'currency' in keys) or 'average_sold_price_usd' in keys) and 'purchase_jpy' not in keys


def convert_terapeak_rows(records, usd_jpy):
    """Return (sourcing rows, sales rows) with identical per-item SKU references."""
    sourcing, sales = [], []
    used = set()
    for i, record in enumerate(records, 1):
        title = _clean(record.get('title'))
        if not title or title.lower() == 'nan':
            continue
        orig_sku = _clean(record.get('sku')) or f'OCR-{i:03d}'
        sku = orig_sku
        n = 2
        while sku in used:
            sku = f'{orig_sku}-{n}'
            n += 1
        used.add(sku)
        price_usd = _positive(record.get('average_sold_price_usd'))
        if price_usd is None:
            amount = _positive(record.get('average_sold_price'))
            currency = _clean(record.get('currency')).upper()
            if amount is not None:
                if currency == 'USD':
                    price_usd = amount
                elif currency == 'JPY' and usd_jpy and usd_jpy > 0:
                    price_usd = amount / usd_jpy
        # Do not place inferred model numbers into the strict model-match field.
        sourcing.append({'sku': sku, 'title': title, 'purchase_jpy': '',
                         'ebay_query': _clean(record.get('ebay_query')) or title,
                         'source': '', 'source_url': '', 'model': ''})
        sale = {'sku': sku, 'ebay_query': title}
        if price_usd is not None:
            sale['reference_sold_price_usd'] = str(round(price_usd, 2))
        count = _positive(record.get('total_sold'))
        if count is not None:
            # Per-row 'Total sold' is not a 90-day market aggregate: don't
            # populate sold_count_90d (which would misrepresent market demand).
            sale['notes'] = f'Product Research listing total sold: {int(count)} (not market-wide count)'
        sales.append(sale)
    return sourcing, sales
