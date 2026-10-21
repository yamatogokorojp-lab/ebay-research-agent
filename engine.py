"""eBay product research core. Standard-library only; monetary figures are estimates."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any


METHODS = (
    ("SpeedPAK Economy", "economy_shipping_jpy"),
    ("SpeedPAK FedEx", "fedex_shipping_jpy"),
    ("DHL", "dhl_shipping_jpy"),
    ("EMS", "ems_shipping_jpy"),
)


@dataclass(frozen=True)
class Settings:
    fx_jpy_per_usd: float = 158.0  # USER ENTERED ASSUMPTION, NEVER CLAIM LIVE
    ebay_fee_pct: float = 20.0  # ESTIMATE; category-dependent
    ad_fee_pct: float = 5.0
    us_duty_pct: float = 12.5  # scenario assumption, not a verified tariff rate
    fixed_ebay_fee_usd: float = 0.40  # estimate; check actual billing
    target_margin_pct: float = 10.0
    quote_includes_duties: bool = False
    economy_import_fee_jpy: float = 0.0  # not an automatic actual fee
    economy_duty_processing_pct: float = 0.0  # set only after verification
    fuel_surcharge_pct: float = 0.0
    peak_surcharge_jpy: float = 0.0
    customs_handling_jpy: float = 0.0
    other_shipping_surcharge_jpy: float = 0.0
    method_fees: dict | None = None  # validated current rates keyed by method, if available


def number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        text = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "").replace("$", "")
        if not text or text.lower() in {"nan", "none", "null", "-"}:
            return default
        return float(text)
    except (ValueError, TypeError):
        return default


def yes(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "yes", "y", "1", "あり", "有", "はい"}


def first_positive(*values: Any) -> float | None:
    for value in values:
        n = number(value)
        if n is not None and n > 0:
            return n
    return None


def manual_price(row: dict, sales: dict | None = None, live: dict | None = None):
    sales = sales or {}
    live = live or {}
    choices = (
        ("手入力の希望販売価格", row.get("target_price_usd")),
        ("Product Research等から転記した参考成約単価", sales.get("reference_sold_price_usd")),
        ("eBay現行出品価格の中央値（成約価格ではない）", live.get("market_median_usd")),
    )
    for desc, val in choices:
        price = number(val)
        if price is not None and price > 0:
            return price, desc
    return None, "価格未入力"


def shipping_quotes(row: dict, settings: Settings, sale_usd: float | None = None) -> list[dict]:
    """Compare entered or PDF-derived BASE prices plus explicitly configured fees.

    Shipping totals are NOT verified CPASS full quotes unless quote_includes_duties=True.
    Duty/tax separately accounted in evaluate() (except all-in CPASS quote).
    """
    options = []
    for method, key in METHODS:
        cost = number(row.get(key))
        if cost is None or cost <= 0:
            continue
        if method == "SpeedPAK Economy" and yes(row.get("has_battery")):
            options.append({"method": method, "quoted_jpy": cost, "estimated_total_jpy": None,
                            "eligible": False, "note": "電池あり：Economy不可"})
            continue
        if method == "EMS" and not yes(row.get("ems_eligible")):
            options.append({"method": method, "quoted_jpy": cost, "estimated_total_jpy": None,
                            "eligible": False, "note": "EMS条件未確認"})
            continue
        verified = (settings.method_fees or {}).get(method)
        fuel_pct = verified['fuel_pct'] if verified else settings.fuel_surcharge_pct
        peak_jpy = verified['peak_jpy'] if verified else settings.peak_surcharge_jpy
        customs_jpy = verified['customs_jpy'] if verified else settings.customs_handling_jpy
        other_jpy = verified['other_jpy'] if verified else settings.other_shipping_surcharge_jpy
        fuel = 0.0 if settings.quote_includes_duties else cost * fuel_pct / 100
        peak = 0.0 if settings.quote_includes_duties else peak_jpy
        misc = 0.0 if settings.quote_includes_duties else (customs_jpy + other_jpy)
        extra = fuel + peak + misc
        economy_fee = 0.0
        if method == "SpeedPAK Economy" and not settings.quote_includes_duties and (sale_usd or 0)>0:
            duty = sale_usd * settings.fx_jpy_per_usd * settings.us_duty_pct / 100
            economy_fee = settings.economy_import_fee_jpy + duty*settings.economy_duty_processing_pct/100
        options.append({"method": method, "quoted_jpy": cost,
                        "additional_shipping_fees_jpy": extra,
                        "estimated_total_jpy": cost + extra + economy_fee,
                        "eligible": True,
                        "fees_verified_source": verified['source_url'] if verified else None,
                        "note": "CPaSS全項目込み見積" if settings.quote_includes_duties else (
                            "適用期間を検証済みの料金データ" if verified else "基本運賃＋手入力の割増金仮定（未確認費用あり）")})
    if not options:
        fallback = number(row.get("intl_shipping_jpy"))
        method = str(row.get("shipping_method") or "配送方法未設定").strip()
        if fallback is not None and fallback > 0:
            restricted = method == "SpeedPAK Economy" and yes(row.get("has_battery"))
            options.append({"method": method, "quoted_jpy": fallback,
                            "additional_shipping_fees_jpy": 0 if settings.quote_includes_duties else fallback*settings.fuel_surcharge_pct/100+settings.peak_surcharge_jpy+settings.customs_handling_jpy+settings.other_shipping_surcharge_jpy,
                            "estimated_total_jpy": None if restricted else fallback + (0 if settings.quote_includes_duties else fallback*settings.fuel_surcharge_pct/100+settings.peak_surcharge_jpy+settings.customs_handling_jpy+settings.other_shipping_surcharge_jpy),
                            "eligible": not restricted,
                            "note": "電池あり：Economy不可" if restricted else "個別入力送料"})
    return options


def choose_shipping(row: dict, settings: Settings, sale_usd: float | None = None) -> tuple[dict | None, list[dict]]:
    options = shipping_quotes(row, settings, sale_usd)
    eligible = [x for x in options if x["eligible"] and x["estimated_total_jpy"] is not None]
    return min(eligible, key=lambda x: x["estimated_total_jpy"]) if eligible else None, options


def min_price_usd(costs_fixed_jpy: float, settings: Settings, method: str, ebay_fee_pct: float | None = None) -> float | None:
    ebay_rate = (settings.ebay_fee_pct if ebay_fee_pct is None else ebay_fee_pct) / 100
    duty_rate = 0 if settings.quote_includes_duties else settings.us_duty_pct / 100
    processing_rate = (duty_rate * settings.economy_duty_processing_pct / 100) if method == "SpeedPAK Economy" else 0
    total_rate = ebay_rate + settings.ad_fee_pct / 100 + duty_rate + processing_rate + settings.target_margin_pct / 100
    if total_rate >= 1 or settings.fx_jpy_per_usd <= 0:
        return None
    return ceil((costs_fixed_jpy / settings.fx_jpy_per_usd / (1 - total_rate)) * 100) / 100


def recommended_policy(weight_g: float | None, title: str) -> str:
    if weight_g is None or weight_g <= 0:
        return "重量未入力"
    if "golf club" in title.lower() and 1000 < weight_g <= 2000:
        return "1kg-2KgGolf Clubs US Free EMS（配送可否を確認）"
    if weight_g <= 500:
        return "0~500g（電池などの条件を確認）"
    if weight_g <= 1000:
        return "501g-1000g"
    if weight_g <= 2000:
        return "1001g-2000g"
    if weight_g <= 5000:
        return "2001g-5000g"
    return "5kg超：配送ポリシー別途作成"


def evaluate(row: dict, sales: dict | None, live: dict | None, settings: Settings) -> dict:
    sales = sales or {}
    live = live or {}
    sku = str(row.get("sku", "")).strip()
    title = str(row.get("title", "")).strip()
    price, price_basis = manual_price(row, sales, live)
    buy = number(row.get("purchase_jpy"))
    domestic = number(row.get("domestic_shipping_jpy"), 0.0) or 0.0
    extra = number(row.get("extra_fees_jpy"), 0.0) or 0.0
    weight = number(row.get("packed_weight_g"))
    # Apply a seller-confirmed, category-specific rate only after the app has
    # matched a selected category to a current fee schedule. CSV-supplied
    # category_fee_pct is intentionally NOT treated as verified.
    candidate_fee = number(row.get('_verified_fee_pct'))
    verified_fee = candidate_fee is not None and 0 <= candidate_fee <= 50
    ebay_fee = candidate_fee if verified_fee else settings.ebay_fee_pct
    method_info, quotes = choose_shipping(row, settings, price)
    warnings = []
    if not verified_fee:
        warnings.append(f'eBay販売手数料はカテゴリー未照合の仮定{settings.ebay_fee_pct:g}%')
    else:
        warnings.append('カテゴリー料率は登録済み公式表の自己確認値。注文総額・段階料率等は要確認')
    if price is None:
        warnings.append("eBay想定売価・参考成約単価・現行出品価格がない")
    if buy is None or buy < 0:
        warnings.append("仕入価格がない")
    if method_info is None:
        warnings.append("利用できる国際送料の入力がない")
    if method_info is not None and not settings.quote_includes_duties and not method_info.get('fees_verified_source'):
        warnings.append("配送業者ごとの追加料金の適用額が未確認。利益は暫定値")
    if not str(row.get("country_of_origin", "")).strip() or str(row.get("country_of_origin", "")).strip() == "未確認":
        warnings.append("原産国未確認。関税率の適用可否は再確認")
    if weight is None:
        warnings.append("梱包後重量が未入力")
    if not str(row.get("source_url", "")).strip():
        warnings.append("実在庫と仕入れURLは未確認")
    volume_weight_g = None
    dims = [number(row.get(k)) for k in ("packed_length_cm", "packed_width_cm", "packed_height_cm")]
    if all(n is not None and n > 0 for n in dims):
        volume_weight_g = dims[0] * dims[1] * dims[2] / 5.0  # cm^3/5000 -> kg -> g
    sold = number(sales.get("sold_count_90d"))
    active_ref = number(sales.get("active_count_reference"))
    str_ratio = None
    if sold is not None and active_ref is not None and (sold + active_ref) > 0:
        str_ratio = sold / (sold + active_ref) * 100
    output = {
        "sku": sku, "title": title, "source": str(row.get("source", "")),
        "source_url": str(row.get("source_url", "")),
        "ebay_query": str(sales.get("ebay_query") or row.get("ebay_query") or "").strip(),
        "purchase_jpy": buy, "sale_price_usd": price, "price_basis": price_basis,
        "shipping_method": method_info["method"] if method_info else "未選択",
        "shipping_base_jpy": method_info["quoted_jpy"] if method_info else None,
        "shipping_quoted_total_jpy": method_info["estimated_total_jpy"] if method_info else None,
        "shipping_options": quotes, "policy": recommended_policy(weight, title),
        "packed_weight_g": weight, "volume_weight_g_div5000": volume_weight_g,
        "sold_count_90d": sold, "active_count_reference": active_ref, "sell_through_proxy_pct": str_ratio,
        "competitor_query_total": live.get("search_total"), "competitor_sample_size": live.get("count"),
        "competitor_median_usd": number(live.get("market_median_usd")),
        "warnings": warnings, "profit_jpy": None, "margin_pct": None, "min_price_usd": None,
        "status": "要確認", "ebay_fee_pct_used": ebay_fee,
        "ebay_fee_basis": "カテゴリー別・自己確認済み料率（暫定）" if verified_fee else "共通仮定（未確認）",
        "ebay_category_id": str(row.get('_selected_category_id') or ''),
        "ebay_category_name": str(row.get('_selected_category_name') or ''),
    }
    if price is None or buy is None or buy < 0 or method_info is None:
        return output
    sale_jpy = price * settings.fx_jpy_per_usd
    delivery_jpy = method_info["quoted_jpy"]
    shipping_additional = method_info.get("additional_shipping_fees_jpy",0.0)
    ebay_fee_jpy = sale_jpy * ebay_fee / 100 + settings.fixed_ebay_fee_usd * settings.fx_jpy_per_usd
    ad_jpy = sale_jpy * settings.ad_fee_pct / 100
    duty_jpy = 0.0 if settings.quote_includes_duties else sale_jpy * settings.us_duty_pct / 100
    economy_import_jpy = 0.0
    economy_processing_jpy = 0.0
    if method_info["method"] == "SpeedPAK Economy" and not settings.quote_includes_duties and duty_jpy > 0:
        economy_import_jpy = settings.economy_import_fee_jpy
        economy_processing_jpy = duty_jpy * settings.economy_duty_processing_pct / 100
    costs_fixed = buy + domestic + extra + delivery_jpy + shipping_additional + settings.fixed_ebay_fee_usd * settings.fx_jpy_per_usd + economy_import_jpy
    minimum = min_price_usd(costs_fixed, settings, method_info["method"], ebay_fee)
    profit_jpy = sale_jpy - buy - domestic - extra - delivery_jpy - shipping_additional - ebay_fee_jpy - ad_jpy - duty_jpy - economy_import_jpy - economy_processing_jpy
    margin = profit_jpy / sale_jpy * 100 if sale_jpy else None
    output.update({
        "profit_jpy": round(profit_jpy), "margin_pct": round(margin, 2),
        "min_price_usd": minimum,
        "breakdown": {"sale_jpy": round(sale_jpy), "purchase_jpy": round(buy),
                      "domestic_shipping_jpy": round(domestic), "international_shipping_jpy": round(delivery_jpy),
                      "shipping_surcharges_and_processing_jpy": round(shipping_additional),
                      "ebay_fee_jpy": round(ebay_fee_jpy), "ad_fee_jpy": round(ad_jpy),
                      "duty_jpy": round(duty_jpy), "economy_import_fee_jpy": round(economy_import_jpy),
                      "economy_duty_processing_jpy": round(economy_processing_jpy),
                      "other_costs_jpy": round(extra)},
        "status": "目標達成" if margin >= settings.target_margin_pct else ("黒字・目標未達" if profit_jpy > 0 else "赤字"),
    })
    return output


def evaluate_all(rows: list[dict], sales_rows: list[dict], live_by_sku: dict, settings: Settings) -> list[dict]:
    sales = {str(x.get("sku", "")).strip(): x for x in sales_rows if str(x.get("sku", "")).strip()}
    return [evaluate(row,
                     sales.get(str(row.get("sku", "")).strip()),
                     live_by_sku.get(str(row.get("sku", "")).strip()),
                     settings) for row in rows]
