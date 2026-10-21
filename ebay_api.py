"""Official eBay Buy Browse API search for CURRENT offers (not historical sold data)."""
from __future__ import annotations

import base64
import statistics
import time
import requests

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


class EbayApiError(Exception):
    pass


def get_app_token(client_id: str, client_secret: str) -> str:
    if not client_id or not client_secret:
        raise EbayApiError("eBay Client ID / Client Secret を .env に設定してください")
    pair = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    try:
        response = requests.post(TOKEN_URL, headers={"Authorization": f"Basic {pair}",
                                                    "Content-Type": "application/x-www-form-urlencoded"},
                                 data={"grant_type": "client_credentials",
                                       "scope": "https://api.ebay.com/oauth/api_scope"}, timeout=25)
        response.raise_for_status()
        return response.json()["access_token"]
    except (requests.RequestException, KeyError, ValueError) as e:
        raise EbayApiError(f"OAuthトークン取得失敗: {e}") from e


def search_current_listings(token: str, query: str, limit: int = 30) -> dict:
    if not query.strip():
        raise EbayApiError("英語検索キーワードが空です")
    try:
        response = requests.get(
            BROWSE_URL,
            headers={"Authorization": f"Bearer {token}",
                     "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                     "Accept": "application/json"},
            params={"q": query[:100], "limit": min(50, max(1, limit)),
                    "filter": "buyingOptions:{FIXED_PRICE}"}, timeout=25,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as e:
        raise EbayApiError(f"Browse API検索失敗: {e}") from e

    delivered_prices = []
    for item in payload.get("itemSummaries", []):
        price = item.get("price") or {}
        if price.get("currency") != "USD":
            continue
        try:
            amount = float(price["value"])
        except (KeyError, TypeError, ValueError):
            continue
        shipping = None
        for opt in item.get("shippingOptions", []) or []:
            fee = opt.get("shippingCost") or {}
            if fee.get("currency") == "USD" and fee.get("value") is not None:
                try:
                    shipping = float(fee["value"])
                    break
                except (ValueError, TypeError):
                    pass
        # Not all search results expose a shipping rate for the destination.
        # Base price only if missing; this remains a rough market reference.
        delivered_prices.append(amount + (shipping or 0.0))
    return {"market_median_usd": round(statistics.median(delivered_prices), 2) if delivered_prices else None,
            "count": len(delivered_prices), "search_total": payload.get("total"),
            "checked_at": int(time.time()), "query": query,
            "caveat": "広い検索語の現行出品価格サンプル。成約価格・同一商品件数・正確な米国到着総額を保証しません。"}


def discover_active_offers(token: str, queries: list[str], limit_each: int = 12) -> list[dict]:
    """Create provisional source research rows from active eBay offers.

    These are neither sold transactions nor verified opportunities. Acquisition cost
    and supplier URL intentionally remain blank.
    """
    discovered = []
    seen = set()
    for query in queries[:5]:
        if not query.strip():
            continue
        try:
            resp = requests.get(
                BROWSE_URL,
                headers={"Authorization": f"Bearer {token}",
                         "X-EBAY-C-MARKETPLACE-ID": "EBAY_US", "Accept": "application/json"},
                params={"q": query[:100], "limit": min(50, max(1, limit_each)),
                        "filter": "buyingOptions:{FIXED_PRICE}"}, timeout=25,
            )
            resp.raise_for_status()
            items = resp.json().get("itemSummaries", [])
        except (requests.RequestException, ValueError) as err:
            raise EbayApiError(f"商品候補検索に失敗しました ({query}): {err}") from err
        for listing in items:
            title = str(listing.get("title") or "").strip()
            currency = (listing.get("price") or {}).get("currency")
            if not title or currency != "USD":
                continue
            identifier = (listing.get("itemId") or title.casefold())
            if identifier in seen:
                continue
            seen.add(identifier)
            price = (listing.get("price") or {}).get("value")
            discovered.append({
                "sku": f"DISC{len(discovered)+1:04d}", "title": title,
                "brand": "", "model": "", "source": "仕入れ先未調査", "source_url": "",
                "purchase_jpy": "", "domestic_shipping_jpy": "", "packed_weight_g": "",
                "packed_length_cm": "", "packed_width_cm": "", "packed_height_cm": "",
                "economy_shipping_jpy": "", "fedex_shipping_jpy": "", "dhl_shipping_jpy": "",
                "ems_shipping_jpy": "", "ems_eligible": "no", "has_battery": "要確認",
                "country_of_origin": "未確認", "target_price_usd": "", "category_fee_pct": "",
                "extra_fees_jpy": "", "ebay_query": query,
                "reference_active_price_usd": price, "reference_condition": listing.get("condition", ""),
                "reference_ebay_url": listing.get("itemWebUrl", ""),
                "notes": "eBay現行出品を元に生成。成約実績・仕入れ在庫は未確認。",
            })
    return discovered


def suggest_categories(token: str, query: str, limit: int = 8) -> list[dict]:
    """Use the US Taxonomy API to suggest categories (NOT fee percentages).

    Category suggestions are not definitive. Require seller selection before
    choosing a fee schedule: one product title may match multiple categories.
    """
    if not token or not query.strip():
        raise EbayApiError('eBay認証または商品名がありません')
    root = 'https://api.ebay.com/commerce/taxonomy/v1'
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    try:
        root_resp = requests.get(f'{root}/get_default_category_tree_id',
                                 headers=headers, params={'marketplace_id': 'EBAY_US'}, timeout=25)
        root_resp.raise_for_status()
        tree_id = str(root_resp.json()['categoryTreeId'])
        if not tree_id.isdigit():
            raise EbayApiError('カテゴリー階層IDが不正です')
        suggestions_resp = requests.get(
            f'{root}/category_tree/{tree_id}/get_category_suggestions',
            headers=headers, params={'q': query[:100]}, timeout=25)
        suggestions_resp.raise_for_status()
        payload = suggestions_resp.json()
    except (requests.RequestException, ValueError, KeyError, TypeError) as err:
        raise EbayApiError(f'eBay Taxonomy APIに接続できません: {err}') from err
    output = []
    seen = set()
    for candidate in payload.get('categorySuggestions', [])[:max(1, min(limit, 20))]:
        category = candidate.get('category', {})
        cat_id = str(category.get('categoryId', '')).strip()
        if not cat_id.isdigit() or cat_id in seen:
            continue
        seen.add(cat_id)
        breadcrumbs = [str(b.get('categoryName', '')).strip()
                       for b in candidate.get('categoryTreeNodeAncestors', [])
                       if b.get('categoryName')]
        output.append({'category_id': cat_id, 'name': str(category.get('categoryName', '')),
                       'path': ' > '.join([*breadcrumbs, str(category.get('categoryName', ''))]),
                       'marketplace': 'EBAY_US'})
    return output
