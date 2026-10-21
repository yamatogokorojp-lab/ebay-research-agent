"""Optional AI critique; never fills in unverified factual data automatically."""
import json
import requests


class AIClientError(Exception):
    pass


def analyze_candidate(api_key: str, model: str, result: dict) -> str:
    if not api_key:
        raise AIClientError("OPENAI_API_KEY が未設定です。AI分析は任意の機能です。")
    safe = {k: result.get(k) for k in (
        "sku", "title", "source", "purchase_jpy", "sale_price_usd", "price_basis",
        "profit_jpy", "margin_pct", "min_price_usd", "shipping_method",
        "packed_weight_g", "sold_count_90d", "active_count_reference",
        "competitor_median_usd", "competitor_sample_size", "warnings")}
    instructions = (
        "あなたは日本から米国のeBayへ輸出するセラーのリサーチ補助AIです。"
        "入力データのみを根拠に日本語で150〜350字で評価してください。"
        "1) 販売見込み 2) 利益リスク 3) 仕入れ前の確認事項をまとめる。"
        "未入力の仕入れ価格、在庫、販売実績、原産国、関税率を捏造してはいけません。"
        "現行出品と成約実績を混同しないでください。利益は見積りと明記してください。"
    )
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "instructions": instructions,
                  "input": "以下を評価してください:\n" + json.dumps(safe, ensure_ascii=False)},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        raise AIClientError(f"AI APIの呼び出しに失敗しました。モデル名とキーを確認してください: {e}") from e
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    if chunks:
        return "\n".join(chunks)
    raise AIClientError("AIの応答に文章が含まれていませんでした。")
