"""Best-effort OCR of user-provided Product Research screenshots.

No eBay credentials, scraping, network calls, or external OCR API.
Do not treat OCR estimates as validated sold transaction records.
"""
from __future__ import annotations
import io
import re
from collections import defaultdict

import pandas as pd
from PIL import Image, ImageOps

OUTPUT_COLUMNS = ["sku", "ebay_query", "title", "average_sold_price", "currency", "average_shipping", "total_sold", "source_image", "review_status"]


class OCRUnavailable(RuntimeError):
    pass


def ocr_tokens(image_bytes: bytes) -> pd.DataFrame:
    try:
        import pytesseract
    except ImportError as exc:
        raise OCRUnavailable("pytesseractがインストールされていません") from exc
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.verify()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError("画像ファイルを読み込めません") from exc
    if image.width * image.height > 22_000_000:
        raise ValueError("画像が大きすぎます。画面を分割するか縮小してください")
    image = ImageOps.autocontrast(image.convert("L"))
    if image.width < 1800:
        ratio = min(3.0, 2048 / image.width)
        image = image.resize((int(image.width * ratio), int(image.height * ratio)))
    try:
        words = pytesseract.image_to_data(image, output_type=pytesseract.Output.DATAFRAME, config="--psm 11")
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRUnavailable("OCR実行環境にTesseractがありません。packages.txtを確認してください") from exc
    words = words.dropna(subset=["text"]).copy()
    words["text"] = words["text"].astype(str).str.strip()
    words = words[words["text"] != ""]
    words["cx"] = words["left"] + words["width"] / 2
    words["cy"] = words["top"] + words["height"] / 2
    words.attrs["width"] = image.width
    words.attrs["height"] = image.height
    return words


def _text(words: pd.DataFrame) -> str:
    return " ".join(words.sort_values(["top", "left"])["text"].astype(str))


def _price(text: str):
    # Product Research may show USD, JPY, GBP, EUR etc. Never infer USD from a bare number.
    # In small currency cells Tesseract commonly confuses digit 1 with l/I/|.
    # Only normalize the number immediately following an explicit currency sign.
    text = re.sub(r"((?:US\s*\$|\$|¥|￥|£|€)\s*)([\dIl|,]+(?:\.[\dIl|]{1,2})?)",
                  lambda m: m.group(1) + m.group(2).translate(str.maketrans("Il|", "111")), text)
    m = re.search(r"(US\s*\$|\$|¥|￥|£|€)\s*([\d,]+(?:\.\d{1,2})?)", text)
    if not m:
        return "", ""
    symbol = m.group(1).replace(" ", "")
    ccy = "USD" if "$" in symbol else "JPY" if symbol in ("¥", "￥") else "GBP" if symbol == "£" else "EUR"
    return m.group(2).replace(",", ""), ccy


def extract_rows(words: pd.DataFrame, filename: str, image_bytes: bytes | None = None) -> list[dict]:
    """Read the visible Product Research result rows using column geometry.

    Works on continuation screenshots with no header. Uses the repeated
    "Fixed price" sublabel as a row anchor, rather than header detection.
    The default coordinates are measured against the entire browser screenshot.
    Unreadable monetary/count cells remain blank (never inferred).
    """
    if words.empty:
        return []
    width = float(words.attrs.get("width", max(words["left"] + words["width"])))
    fixed = words[words["text"].str.lower().str.fullmatch("fixed", na=False)]
    price_label = words[words["text"].str.lower().str.fullmatch("price", na=False)]
    anchors = []
    for _, token in fixed.iterrows():
        nearby = price_label[
            (abs(price_label["cy"] - token["cy"]) <= max(15, width * .012))
            & (price_label["left"] > token["left"])
            & (price_label["left"] < token["left"] + width * .055)
        ]
        if not nearby.empty and width * .40 < token["cx"] < width * .58:
            anchors.append(float(token["cy"]))
    anchors = sorted(set(round(y) for y in anchors))
    # Different browser zoom levels can omit either word in "Fixed price".
    # The numeric sold-price cell sits directly above that label in the
    # 44%-54% band. Accept the detected label alone when it occurs in a
    # repeated vertical run of at least two rows; never parse browser chrome.
    if len(anchors) < 2:
        loose = [round(float(t.cy)) for _, t in fixed.iterrows()
                 if width * .40 < t.cx < width * .58]
        anchors = sorted(set(loose)) if len(loose) >= 2 else anchors
    if len(anchors) < 2:
        loose = [round(float(t.cy)) for _, t in price_label.iterrows()
                 if width * .40 < t.cx < width * .58]
        anchors = sorted(set(loose)) if len(loose) >= 2 else anchors
    # Eliminate accidental toolbar matches not forming a listing-row sequence.
    if len(anchors) > 2:
        gaps = [b-a for a,b in zip(anchors, anchors[1:]) if b-a >= 35]
        if gaps:
            median_gap = sorted(gaps)[len(gaps)//2]
            anchors = [y for i,y in enumerate(anchors) if
                       (i > 0 and abs(y-anchors[i-1]-median_gap) < median_gap*.48) or
                       (i+1 < len(anchors) and abs(anchors[i+1]-y-median_gap) < median_gap*.48)]
    extracted = []
    detail_image = None
    if image_bytes is not None:
        detail_image = ImageOps.autocontrast(Image.open(io.BytesIO(image_bytes)).convert("L"))
        if detail_image.width < 1800:
            ratio = min(3.0, 2048 / detail_image.width)
            detail_image = detail_image.resize((int(detail_image.width * ratio), int(detail_image.height * ratio)))
    for i, anchor in enumerate(anchors):
        previous_gap = anchor - anchors[i - 1] if i else None
        next_gap = anchors[i + 1] - anchor if i + 1 < len(anchors) else None
        typical_gap = min([g for g in (previous_gap, next_gap) if g and 35 < g < width * .15] or [width * .036])
        # Titles may wrap into two lines, centered at the sold-price line.
        lo = anchor - min(max(typical_gap * .48, 30), 65)
        hi = anchor + min(max(typical_gap * .17, 9), 21)
        band = words[(words["cy"] >= lo) & (words["cy"] <= hi)]
        def col(left, right):
            return band[(band["cx"] >= width * left) & (band["cx"] < width * right)]
        title_words = col(.075, .325)
        # Exclude sub-labels and small UI artifacts accidentally caught in the band.
        title_words = title_words[~title_words["text"].str.lower().isin(["edit", "fixed", "price"])]
        # OCR tokens at the same visual line can have slightly different top
        # coordinates. Cluster into visual lines before joining left-to-right.
        title_lines = []
        for _, tok in title_words.sort_values(["cy", "left"]).iterrows():
            match = next((line for line in title_lines if abs(line["cy"]-tok.cy) < max(8, width*.004)), None)
            if match is None:
                match = {"cy": float(tok.cy), "items": []}
                title_lines.append(match)
            match["items"].append((float(tok.left), str(tok.text)))
        title = " ".join(" ".join(t for _,t in sorted(line["items"])) for line in sorted(title_lines, key=lambda r:r["cy"]))
        title = re.sub(r"\s+", " ", title).strip()
        # Monetary cells: isolate the primary line above the 'Fixed price' anchor.
        primary = band[(band["cy"] < anchor - 5) & (band["cy"] > anchor - max(35, typical_gap * .42))]
        def primary_text(left, right):
            return _text(primary[(primary["cx"] >= width * left) & (primary["cx"] < width * right)])
        sold_price, currency = _price(primary_text(.44, .53))
        shipping, shipping_currency = _price(primary_text(.54, .65))
        sold_text = primary_text(.65, .73)
        sold_numbers = re.findall(r"(?<![\d])\d{1,6}(?![\d])", sold_text)
        units = sold_numbers[0] if sold_numbers else ""
        # A narrow cell commonly disappears from whole-page OCR. Read just
        # that numeric cell without changing any other column or guessing.
        if not units and detail_image is not None:
            try:
                import pytesseract
                y1, y2 = max(0, int(anchor - 43)), min(detail_image.height, int(anchor - 5))
                cell = detail_image.crop((int(width * .644), y1, int(width * .735), y2))
                cell = cell.resize((cell.width * 3, cell.height * 3))
                detected = pytesseract.image_to_string(
                    cell, config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
                if re.fullmatch(r"\d{1,6}", detected):
                    units = detected
            except Exception:
                pass
        # Some currency cells are missed by whole-page OCR. Retry each cropped
        # price cell independently. Accept only values with an explicit symbol;
        # never turn arbitrary numbers into prices.
        if detail_image is not None and (not sold_price or not shipping or len(str(sold_price)) < 3 or len(str(shipping)) < 3):
            try:
                import pytesseract
                y1, y2 = max(0, int(anchor - 45)), min(detail_image.height, int(anchor - 8))
                for key, x1, x2 in (("sold", .435, .53), ("shipping", .53, .645)):
                    if (key == "sold" and sold_price) or (key == "shipping" and shipping):
                        continue
                    crop = detail_image.crop((int(width*x1), y1, int(width*x2), y2))
                    crop = crop.resize((crop.width*3, crop.height*3))
                    value, detected_ccy = _price(pytesseract.image_to_string(crop, config="--psm 6"))
                    if key == "sold" and value and (not sold_price or len(value) > len(str(sold_price))):
                        sold_price, currency = value, detected_ccy
                    elif key == "shipping" and value and (not shipping or len(value) > len(str(shipping))):
                        shipping, shipping_currency = value, detected_ccy
            except Exception:
                pass
        if currency and shipping_currency and currency != shipping_currency:
            shipping = ""
        # Some OCR render ¥0 as ¥O; explicitly normalize zero only.
        if not shipping and re.search(r"[¥￥]\s*[Oo]\b", primary_text(.54, .65)):
            shipping = "0"
        if not sold_price and re.search(r"[¥￥]\s*[Oo]\b", primary_text(.44, .53)):
            sold_price, currency = "0", "JPY"
        # Reject headers, toolbar and accidental scraps.
        if len(title) < 10 or not re.search(r"[A-Za-z]{2,}", title):
            continue
        extracted.append({
            "sku": f"OCR-{len(extracted)+1:03d}", "ebay_query": "", "title": title,
            "average_sold_price": sold_price, "currency": currency,
            "average_shipping": shipping, "total_sold": units,
            "source_image": filename, "review_status": "要確認",
        })
    return extracted

def _normalise_image(content: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(content)).convert("RGB")
    # Browser chrome at the top is irrelevant; keep screen dimensions stable
    # because extract_rows uses relative horizontal column coordinates.
    return image

def parse_screenshot(content: bytes, filename: str) -> tuple[list[dict], str]:
    words = ocr_tokens(content)
    rows = extract_rows(words, filename, content)
    # Keep the raw OCR useful: skip the browser tab/address area above the
    # result table. The structured extraction still uses original positions.
    height = float(words.attrs.get("height", 1))
    content = words[words["cy"] >= max(70, height * 0.12)]
    raw = _text(content)
    return rows, raw


def add_usd_conversions(frame: pd.DataFrame, usd_jpy: float) -> pd.DataFrame:
    """Convert JPY screenshot prices to USD, preserve originals; never guess other FX pairs."""
    if not (50 < float(usd_jpy) < 350):
        raise ValueError("USD/JPY rate out of accepted range")
    result = frame.copy()
    def convert(row, key):
        value = str(row.get(key, "")).replace(",", "").strip()
        currency = str(row.get("currency", "")).strip().upper()
        if not value or value.lower() in ("nan", "none"):
            return ""
        try:
            amount = float(value)
        except ValueError:
            return ""
        if currency == "USD":
            return round(amount, 2)
        if currency == "JPY":
            return round(amount / float(usd_jpy), 2)
        return ""
    result["average_sold_price_usd"] = result.apply(lambda row: convert(row, "average_sold_price"), axis=1)
    result["average_shipping_usd"] = result.apply(lambda row: convert(row, "average_shipping"), axis=1)
    result["usd_jpy_rate_used"] = round(float(usd_jpy), 4)
    return result
