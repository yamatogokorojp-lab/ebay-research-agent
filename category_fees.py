"""Strict category fee mapping. Rates are supplied only by a reviewed fee schedule.

The eBay Taxonomy API suggests *categories*, not seller-specific fee rates. A
rate must never be fabricated from a category label or an eBay Browse listing.
This module stores the applicable fee schedule separately from the category
classification and rejects expired or incomplete schedules.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse


class CategoryFeeError(ValueError):
    pass


def _ebay_official_url(value: str) -> bool:
    p = urlparse(str(value))
    return p.scheme == 'https' and p.hostname in {'www.ebay.com', 'ebay.com', 'export.ebay.com'} and not p.username and not p.password


def validate_schedule(document: Any, *, today: date | None = None) -> dict:
    """Validate an explicitly reviewed seller-specific fee table.

    Document fields: marketplace='EBAY_US', seller_country='JP',
    store_plan, source_url, verified_by_seller=True, effective_from,
    effective_to, rates:[{category_id, percentage}].  This is an *estimate*
    based on a manually reviewed schedule, not an eBay API response.
    """
    today = today or date.today()
    if not isinstance(document, dict):
        raise CategoryFeeError('手数料表はJSONオブジェクトである必要があります')
    if document.get('marketplace') != 'EBAY_US' or document.get('seller_country') != 'JP':
        raise CategoryFeeError('米国eBay/日本出品者の手数料表ではありません')
    if not document.get('verified_by_seller') is True:
        raise CategoryFeeError('最新のeBay公式手数料表と照合した確認が必要です')
    if not _ebay_official_url(document.get('source_url', '')):
        raise CategoryFeeError('出典にeBay公式URLが必要です')
    try:
        start, end = date.fromisoformat(document['effective_from']), date.fromisoformat(document['effective_to'])
    except (KeyError, ValueError, TypeError) as ex:
        raise CategoryFeeError('適用期間の開始日と終了日が必要です') from ex
    if start > today or end < today or end < start:
        raise CategoryFeeError('カテゴリー別手数料表が適用期間外です')
    plan = str(document.get('store_plan', '')).strip()
    if not plan:
        raise CategoryFeeError('ストア契約区分が指定されていません')
    rates = document.get('rates')
    if not isinstance(rates, list) or not rates:
        raise CategoryFeeError('カテゴリー別の料率データがありません')
    clean = {}
    for entry in rates:
        if not isinstance(entry, dict):
            raise CategoryFeeError('料率データが不正です')
        category_id = str(entry.get('category_id', '')).strip()
        if not category_id.isdigit():
            raise CategoryFeeError('カテゴリーIDは数字で指定してください')
        # Do not guess tier thresholds, fixed fees or order-level exceptions.
        if any(field in entry for field in ('tier', 'minimum_fee', 'maximum_fee', 'threshold_usd')):
            raise CategoryFeeError('段階料金は現在の単一料率モデルでは扱えません')
        try:
            pct = float(entry['percentage'])
        except (KeyError, ValueError, TypeError) as ex:
            raise CategoryFeeError('販売手数料率がありません') from ex
        if not 0 <= pct <= 50 or not (pct < float('inf')):
            raise CategoryFeeError('販売手数料率が不正です')
        if category_id in clean:
            raise CategoryFeeError(f'{category_id}の料率が重複しています')
        clean[category_id] = pct
    return {'store_plan': plan, 'rates': clean, 'source_url': document['source_url'],
            'effective_from': start.isoformat(), 'effective_to': end.isoformat(),
            'basis_note': '出品者が公式表と照合した単一料率のみ。手数料の課金対象額や段階料率は別途確認。'}


def category_rate(schedule: dict | None, category_id: str, store_plan: str) -> float | None:
    if not schedule or schedule.get('store_plan') != store_plan:
        return None
    return schedule.get('rates', {}).get(str(category_id).strip())


# Streamlit keeps widget/session state between CSV uploads. A SKU alone is not
# a product identity: the user may edit/re-use a SKU for a different listing.
def category_product_fingerprint(row: dict) -> tuple[str, str, str]:
    """The category-relevant product fields, normalized for harmless whitespace."""
    return tuple(' '.join(str(row.get(k, '')).split()).casefold() for k in ('title', 'brand', 'model'))


def reconcile_category_context(
    rows: list[dict],
    previously_seen: dict,
    suggestions: dict,
    choices: dict,
) -> set[str]:
    """Invalidate old category selections when SKUs disappear or products change.

    Mutates the three state dictionaries passed by the UI and returns changed
    SKUs. Missing previous identities are treated as untrusted old state.
    """
    active = {str(row.get('sku', '')).strip(): category_product_fingerprint(row) for row in rows}
    changed = set()
    for sku in set(previously_seen) | set(suggestions) | set(choices):
        if sku not in active or previously_seen.get(sku) != active[sku]:
            suggestions.pop(sku, None)
            choices.pop(sku, None)
            changed.add(sku)
    previously_seen.clear()
    previously_seen.update(active)
    return changed


def category_choice_is_current(choice: dict | None, query: str, identity: tuple[str, str, str]) -> bool:
    """Only use a selection made for this exact search and current product."""
    return (isinstance(choice, dict)
            and choice.get('_category_query') == query.strip()
            and choice.get('_identity') == identity
            and bool(str(choice.get('category_id', '')).strip().isdigit()))
