"""Best-effort OCR of user-provided Product Research screenshots.

No eBay credentials, scraping, network calls, or external OCR API.
Do not treat OCR estimates as validated sold transaction records.
"""
from __future__ import annotations
import io
import re

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
    if image.width < 1200:
        ratio = min(2.0, 1400 / image.width)
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
    return words


def _text(words: pd.DataFrame) -> str:
    return " ".join(words.sort_values(["top", "left"])["text"].astype(str))


def _price(text: str):
    # Product Research may show USD, JPY, GBP, EUR etc. Never infer USD from a bare number.
    m = re.search(r"(US\s*\$|\$|¥|￥|£|€)\s*([\d,]+(?:\.\d{1,2})?)", text)
    if not m:
        return "", ""
    symbol = m.group(1).replace(" ", "")
    ccy = "USD" if "$" in symbol else "JPY" if symbol in ("¥", "￥") else "GBP" if symbol == "£" else "EUR"
    return m.group(2).replace(",", ""), ccy


def extract_rows(words: pd.DataFrame, filename: str) -> list[dict]:
    """Extract the visible table only, using the 'Fixed price' row anchors.

    Other Product Research screenshot designs may not be recognized and should
    use the manual correction interface. Never manufacture missing values.
    """
    if words.empty:
        return []
    width = words.attrs.get("width", max(words["left"] + words["width"]))
    anchors = []
    fixed = words[words["text"].str.lower().str.fullmatch(r"fixed", na=False)]
    price_tokens = words[words["text"].str.lower().str.fullmatch(r"price", na=False)]
    for _, w in fixed.iterrows():
        following = price_tokens[(abs(price_tokens["cy"] - w["cy"]) < 18) & (price_tokens["left"] > w["left"]) & (price_tokens["left"] < w["left"] + 125)]
        if not following.empty and w["cx"] > width * .48:
            anchors.append(float(w["cy"]))
    anchors = sorted(set(round(y, 0) for y in anchors))
    rows = []
    for idx, fixed_y in enumerate(anchors):
        prior = anchors[idx - 1] if idx else None
        next_ = anchors[idx + 1] if idx + 1 < len(anchors) else None
        above = (fixed_y - prior) if prior else ((next_ - fixed_y) if next_ else 105)
        below = (next_ - fixed_y) if next_ else above
        # Row title/price is above the Fixed price sublabel, shipping sublabel also below.
        lo = fixed_y - max(60, above * .83)
        hi = fixed_y + min(45, below * .37)
        band = words[(words["cy"] >= lo) & (words["cy"] <= hi)]
        title_text = _text(band[(band["cx"] >= width * .13) & (band["cx"] < width * .46)])
        price_text = _text(band[(band["cx"] >= width * .58) & (band["cx"] < width * .76)])
        ship_text = _text(band[(band["cx"] >= width * .76) & (band["cx"] < width * .91)])
        sold_text = _text(band[(band["cx"] >= width * .92)])
        price, ccy = _price(price_text)
        shipping, ship_ccy = _price(ship_text)
        if ccy and ship_ccy and ccy != ship_ccy:
            shipping = ""
        sold_matches = re.findall(r"\b\d{1,6}\b", sold_text)
        sold = sold_matches[0] if sold_matches else ""
        title_text = re.sub(r"\s+", " ", title_text).strip()
        # Avoid exporting false positives based on a lone price token.
        if len(title_text) < 8:
            continue
        rows.append({"sku": f"OCR-{len(rows)+1:03d}", "ebay_query": "", "title": title_text,
                     "average_sold_price": price, "currency": ccy, "average_shipping": shipping,
                     "total_sold": sold, "source_image": filename, "review_status": "要確認"})
    return rows


def parse_screenshot(content: bytes, filename: str) -> tuple[list[dict], str]:
    words = ocr_tokens(content)
    rows = extract_rows(words, filename)
    raw = _text(words)
    return rows, raw
