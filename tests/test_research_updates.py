from keyword_suggestions import suggest_keywords
from terapeak_ocr import add_usd_conversions
import pandas as pd

def test_keywords():
    items = suggest_keywords("腕時計 / Watches", "SEIKO", "SND379P1")
    assert "SEIKO SND379P1" in items
    assert "SEIKO chronograph" in items
    assert len(items) == len(set(items))

def test_conversion():
    frame = pd.DataFrame([{"currency": "JPY", "average_sold_price": "327", "average_shipping": "0"}, {"currency": "USD", "average_sold_price": "25.75", "average_shipping": "5"}, {"currency": "EUR", "average_sold_price": "25", "average_shipping": "5"}])
    result = add_usd_conversions(frame, 150)
    assert result.loc[0, "average_sold_price_usd"] == 2.18
    assert result.loc[0, "average_shipping_usd"] == 0
    assert result.loc[1, "average_sold_price_usd"] == 25.75
    assert result.loc[2, "average_sold_price_usd"] == ""
