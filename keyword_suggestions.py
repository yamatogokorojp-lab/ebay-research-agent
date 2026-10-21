"""Offline suggestions, NOT verified eBay sale ranking or sales activity."""
from __future__ import annotations

CATEGORY_TERMS = {
    "腕時計": ["vintage watch", "quartz watch", "chronograph", "automatic watch", "watch Japan"],
    "カメラ": ["digital camera", "film camera", "compact camera", "camera lens", "camera Japan"],
    "ゴルフ": ["golf club", "golf putter", "fairway wood", "golf accessories", "golf Japan"],
    "オーディオ": ["portable cassette player", "minidisc player", "CD player", "audio recorder", "audio Japan"],
    "ゲーム": ["retro game", "game console", "game controller", "game accessory", "game Japan"],
    "工業用品": ["industrial sensor", "precision gauge", "test equipment", "measurement tool", "industrial Japan"],
    "その他": ["vintage", "collectible", "accessories", "Japan", "rare"],
}

def suggest_keywords(category: str, brand: str, model: str) -> list[str]:
    root = category.split(" / ")[0]
    modifiers = CATEGORY_TERMS.get(root, CATEGORY_TERMS["その他"])
    brand = brand.strip()[:60]
    model = model.strip()[:80]
    prefix = " ".join(p for p in (brand, model) if p)
    candidates = ([prefix] if prefix else []) + [" ".join(p for p in (brand, term) if p) for term in modifiers]
    if model:
        candidates.extend([f"{model} Japan", f"{model} used"])
    if not brand and not model:
        candidates = modifiers
    seen = set()
    out = []
    for term in candidates:
        norm = term.strip().casefold()
        if norm and norm not in seen:
            out.append(term.strip())
            seen.add(norm)
    return out
