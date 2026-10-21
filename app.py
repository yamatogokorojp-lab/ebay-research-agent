"""Cross-platform Streamlit UI for Windows and macOS."""
from __future__ import annotations

import io
import os
from pathlib import Path
from public_access import RequestBudget
from urllib.parse import quote as url_quote
from dataclasses import asdict

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from ai_client import AIClientError, analyze_candidate
from engine import Settings, evaluate_all, number, yes
from fx import usd_jpy_rate, FxError
from sourcing_api import rakuten_search, yahoo_search, match_model, search_links, SourcingApiError
from rates_us import quote_us_all, shipping_base
from fee_updates import fetch_verified_fees, FeeUpdateError
from category_fees import (validate_schedule, category_rate, CategoryFeeError,
                           reconcile_category_context, category_choice_is_current)

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
# Cloud deployment: Streamlit secrets never appear in UI, logs or Git.
try:
    deployment_secrets = dict(st.secrets)
except Exception:  # No secrets.toml in a local/default installation.
    deployment_secrets = {}
for secret_name in ("RAKUTEN_APP_ID",
                    "RAKUTEN_ACCESS_KEY", "YAHOO_CLIENT_ID", "OPENAI_API_KEY",
                    "OPENAI_MODEL", "OFFICIAL_SURCHARGE_JSON_URL", "ENABLE_PUBLIC_AI"):
    if secret_name in deployment_secrets and isinstance(deployment_secrets[secret_name], str):
        os.environ[secret_name] = deployment_secrets[secret_name]

@st.cache_resource

def public_budget():
    return RequestBudget()

def require_api_budget():
    if not public_budget().allow():
        st.error("APIへのアクセスが集中しています。時間をおいて再検索してください。 / Rate limit reached; please try again later.")
        st.stop()

st.set_page_config(page_title="eBay商品リサーチAI", page_icon="📦", layout="wide")
head, language_panel = st.columns([5, 1])
with language_panel:
    language = st.selectbox("言語 / Language", ["日本語", "English"], key="ui_language")
ENGLISH = language == "English"

def tr(japanese, english):
    return english if ENGLISH else japanese
with head:
    st.title(tr("📦 eBay 商品リサーチ AI", "📦 eBay Product Research AI"))
st.caption(tr("CSV・eBay検索リンク・楽天/Yahoo在庫あり仕入れ検索・PDF基本運賃比較・利益試算（最新の追加料金は要確認）",
              "CSV research · eBay search links · in-stock Rakuten/Yahoo sourcing · PDF base freight · estimated profit (live surcharges not verified)"))
st.warning(tr("CSV未アップロード時は**架空のデモデータ**です。実在庫やeBayの成約実績を示しません。楽天/YahooのAPIが未設定なら検索できません。",
              "Without a CSV upload, **sample figures are fictitious**. They are NOT eBay sold history or verified inventory. Shopping APIs require provider credentials."), icon="⚠️")
if ENGLISH:
    st.info("English interface is being rolled out. Some detail fields are still in Japanese; Chrome Translate can translate remaining labels.")



def load_records(content: bytes, required: list[str]) -> list[dict]:
    errors = []
    for encoding in ("utf-8-sig", "cp932", "utf-8"):
        try:
            frame = pd.read_csv(io.BytesIO(content), encoding=encoding, dtype=str, keep_default_na=False)
            frame.columns = [str(x).strip() for x in frame.columns]
            missing = [x for x in required if x not in frame.columns]
            if missing:
                raise ValueError(f"必要な列がありません: {', '.join(missing)}")
            if len(frame) > 5000:
                raise ValueError("初期版は最大5,000行までです")
            data = frame.to_dict(orient="records")
            if len({str(x.get('sku', '')).strip() for x in data}) != len(data):
                raise ValueError("skuが重複しています。サイズ違いはSKUを分けてください")
            return data
        except UnicodeDecodeError as ex:
            errors.append(str(ex))
            continue
    raise ValueError(errors[0] if errors else "CSVの読込に失敗しました")


@st.cache_data(ttl=1800, show_spinner=False)
def current_fx():
    return usd_jpy_rate()


@st.cache_data(ttl=1800, show_spinner=False)
def load_fee_feed(feed_url: str):
    return fetch_verified_fees(feed_url)

fee_feed_url = os.getenv('OFFICIAL_SURCHARGE_JSON_URL','').strip()
fee_rates = {}
fee_error = None
if fee_feed_url:
    try:
        fee_rates = load_fee_feed(fee_feed_url)
    except FeeUpdateError as exc:
        fee_error = str(exc)

fx_live = None
fx_error = None
try:
    fx_live = current_fx()
except FxError as exc:
    fx_error = str(exc)

with st.sidebar:
    st.header(tr("⚙️ 計算設定", "⚙️ Profit settings"))
    if fx_live:
        st.caption(f"自動取得の参照為替（取引時レートではありません）: 1 USD = {fx_live['rate']:.3f} JPY / 公開元: {fx_live['source']} / 元データ更新: {fx_live['updated']}")
        fx = fx_live["rate"]
        if st.button("為替を再取得"):
            current_fx.clear()
            st.rerun()
    else:
        st.warning("為替自動取得に失敗。手入力値は仮定です。")
        st.caption(fx_error or "通信状況を確認してください")
        fx = st.number_input("為替 USD/JPY（手入力・仮定）", min_value=50.0, max_value=300.0, value=158.0, step=0.5)
    ebay_fee = st.number_input("eBay販売手数料 %（試算）", min_value=0.0, max_value=45.0, value=20.0, step=0.25)
    ad_fee = st.number_input(tr("広告費 %", "Advertising fee %"), min_value=0.0, max_value=50.0, value=5.0, step=0.5)
    duty = st.number_input("米国関税 %（試算）", min_value=0.0, max_value=100.0, value=12.5, step=0.5)
    target = st.number_input(tr("目標利益率 %", "Target profit margin %"), min_value=-20.0, max_value=70.0, value=10.0, step=1.0)
    fixed_fee = st.number_input("注文あたりeBay固定手数料 USD（仮定）", min_value=0.0, max_value=5.0, value=0.40, step=0.1)
    quote_includes = st.checkbox("入力送料は関税・割増金・通関費用をすべて含む総額（CPaSS等）", value=False,
                                 help="チェックするとこのツールによる関税とEconomy通関手数料の加算を止めます。送料の各見積は同じ条件で入力してください。")
    st.caption("PDFの送料は基本運賃のみ。CPaSS等の全項目込み見積もりを使う場合は、該当する送料をCSVに入力して上のチェックをONにしてください。PDF運賃はこの場合自動補完しません。追加料金の最新値は個別確認が必要です。")
    st.markdown("**配送業者別の追加料金・自動更新状態**")
    if fee_rates:
        st.success(f"料金情報を{len(fee_rates)}種類取得し、適用期間を検証しました（実際の請求額ではありません）。")
        st.dataframe(pd.DataFrame([
            {'配送サービス': method, '燃油%': rec['fuel_pct'], '混雑時円': rec['peak_jpy'],
             '通関処理円': rec['customs_jpy'], 'その他円': rec['other_jpy'],
             '適用終了日': rec['effective_to'], '確認日時': rec['checked_at'], '出典': rec['source_url']}
            for method, rec in fee_rates.items()
        ]), hide_index=True, use_container_width=True)
        if st.button('公式料金データを再取得'):
            load_fee_feed.clear()
            st.rerun()
    elif fee_error:
        st.warning(f"料金の自動更新に失敗。以前の値を最新として採用しません: {fee_error}")
    else:
        st.info('公式の機械可読料金URLが未確認・未設定です。追加料金の自動更新は現在無効です。')
    st.caption('自動取得は公式提供元のHTTPS JSON料金フィードが確認できた場合のみ有効です。PDFや一般のHTMLページの金額を推測して上書きしません。アプリ起動中の操作時に最大30分キャッシュします。')
    st.markdown("**自動データがない配送方法に適用する暫定入力（全社共通の仮定値）**")
    fuel = st.number_input("燃油割増 %（基本運賃に対する仮定）", min_value=0.0, max_value=150.0, value=0.0, step=0.5)
    peak = st.number_input("混雑時割増 円", min_value=0.0, value=0.0, step=100.0)
    processing = st.number_input("指定関税処理手数料 円", min_value=0.0, value=0.0, step=100.0)
    other_surcharge = st.number_input("その他配送追加料金 円", min_value=0.0, value=0.0, step=100.0)
    economy_fee = st.number_input("Economy輸入関連固定費 円（確認値のみ）", min_value=0.0, value=0.0, step=50.0)
    economy_processing_pct = st.number_input("Economy関税処理加算率 %（確認値のみ）", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
    fedex_zone = st.selectbox("FedEx米国地域（不明なら未指定）", ["未指定", "US_WEST", "US_OTHER"])
    st.caption("関税12.5%はユーザー指定の試算率です。品目・原産国で実際の税額が変わる可能性があります。")
    st.divider()
    st.markdown("**外部APIの設定**")
    st.text("eBay: API不要（検索リンク方式・販売アカウント非連携）")
    st.text("OpenAI: " + ("公開版では無効" if os.getenv("ENABLE_PUBLIC_AI", "false").lower() != "true" else ("キー設定済" if os.getenv("OPENAI_API_KEY") else "未設定")))
    st.text("楽天: " + ("キー設定済" if os.getenv("RAKUTEN_APP_ID") else "未設定"))
    st.text("Yahoo!: " + ("キー設定済" if os.getenv("YAHOO_CLIENT_ID") else "未設定"))

settings = Settings(fx_jpy_per_usd=fx, ebay_fee_pct=ebay_fee, ad_fee_pct=ad_fee,
                    us_duty_pct=duty, fixed_ebay_fee_usd=fixed_fee,
                    target_margin_pct=target, quote_includes_duties=quote_includes,
                    fuel_surcharge_pct=fuel, peak_surcharge_jpy=peak, customs_handling_jpy=processing,
                    other_shipping_surcharge_jpy=other_surcharge, economy_import_fee_jpy=economy_fee,
                    economy_duty_processing_pct=economy_processing_pct, method_fees=fee_rates)

st.subheader(tr("0. 売れ筋リサーチ用キーワード生成", "0. Generate Product Research keywords"))
st.caption(tr("ジャンル・ブランド・型番からテラピーク用の英語検索候補を作ります。売れた実績を自動判定するものではありません。", "Generate English keyword candidates from category, brand and model. These suggestions do not prove actual sales."))
category = st.selectbox(tr("商品ジャンル", "Product category"), ["腕時計 / Watches", "カメラ / Cameras", "ゴルフ / Golf", "オーディオ / Audio", "ゲーム / Gaming", "工業用品 / Industrial", "その他 / Other"], key="keyword_category")
brand = st.text_input(tr("ブランド（英語・任意）", "Brand (English, optional)"), value="SEIKO", key="keyword_brand").strip()
model = st.text_input(tr("型番・商品名（英語・任意）", "Model / product (English, optional)"), key="keyword_model").strip()
from keyword_suggestions import suggest_keywords
suggestions = suggest_keywords(category, brand, model)
if suggestions:
    st.caption(tr("候補をコピーし、テラピークの検索欄に貼り付けてください。", "Copy candidates into Product Research."))
    st.code("\n".join(suggestions), language=None)
    keyword_text = "\n".join(suggestions)
else:
    keyword_text = ""
st.subheader(tr("0.1 テラピーク（Product Research）を開く", "0.1 Open Terapeak (Product Research)"))
st.link_button(tr("テラピークを開く ↗", "Open Terapeak ↗"), "https://www.ebay.com/sh/research")
st.caption(tr("eBayの販売アカウントはアプリと連携しません。検索語は自動送信されないため、上からコピーしてください。", "No eBay account integration; copy a suggested query into the Terapeak search field."))
if suggestions:
    candidate_rows = []
    for index, q in enumerate(suggestions, start=1):
        candidate_rows.append({"sku": f"RESEARCH-{index:03d}", "title": q, "brand": brand, "model": model, "source": "", "source_url": "", "purchase_jpy": "", "domestic_shipping_jpy": "", "packed_weight_g": "", "packed_length_cm": "", "packed_width_cm": "", "packed_height_cm": "", "economy_shipping_jpy": "", "fedex_shipping_jpy": "", "dhl_shipping_jpy": "", "ems_shipping_jpy": "", "ems_eligible": "", "has_battery": "", "country_of_origin": "", "target_price_usd": "", "category_fee_pct": "", "extra_fees_jpy": "", "ebay_query": q})
    st.download_button(tr("検索ワードから仕入れ候補CSVを保存", "Download keyword candidate CSV"), pd.DataFrame(candidate_rows).to_csv(index=False).encode("utf-8-sig"), file_name="keyword_candidate_template.csv", mime="text/csv")

# Screenshot OCR is deliberately separate from the sales reference CSV importer:
# row-level Product Research screenshots may contain averages and summaries, not
# single transaction records. Users review and optionally download OCR rows.
st.subheader(tr("0.2 テラピークのスクショ → CSV【表の位置認識 v2】", "0.2 Terapeak screenshots → CSV [table-aware v2]"))
st.caption(tr("テラピークの結果一覧が映ったPNG/JPG画像を複数枚まとめてアップロード（枚数・CSV行数の固定上限なし）。商品名・平均成約価格・平均送料・販売数をOCRで読み取り、確認後にCSVへ保存します。画像によっては抽出できません。", "Upload multiple PNG/JPG screenshots (no fixed image or CSV row count limit) of the Product Research results table. OCR attempts titles, average sold price, average shipping and units sold. Review all fields before exporting."))
ocr_converted_rows = None
screenshot_files = st.file_uploader(tr("スクリーンショットを選択（PNG/JPG）", "Choose screenshot images (PNG/JPG)"), type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="terapeak_screenshots")
if screenshot_files:
    from terapeak_ocr import parse_screenshot, OUTPUT_COLUMNS, OCRUnavailable, add_usd_conversions
    extracted_rows, raw_parts = [], []
    for screenshot_file in screenshot_files:
        if screenshot_file.size > 10 * 1024 * 1024:
            st.warning(f"{screenshot_file.name}: 10MBを超えるためスキップ")
            continue
        try:
            found, raw = parse_screenshot(screenshot_file.getvalue(), screenshot_file.name)
            extracted_rows.extend(found)
            raw_parts.append(f"### {screenshot_file.name}\n{raw}")
        except (ValueError, OCRUnavailable) as exc:
            st.warning(f"{screenshot_file.name}: {exc}")
    # A scroll may overlap adjacent screenshots. Remove only exact normalized
    # title/price/quantity matches; avoid merging different actual listings.
    seen_rows, unique_rows = set(), []
    for item in extracted_rows:
        key = (" ".join(str(item.get("title", "")).casefold().split()),
               str(item.get("average_sold_price", "")),
               str(item.get("average_shipping", "")),
               str(item.get("total_sold", "")))
        if key not in seen_rows:
            seen_rows.add(key)
            unique_rows.append(item)
    extracted_rows = unique_rows
    if extracted_rows:
        st.info(tr(f"読み取り候補：{len(extracted_rows)}件（出力件数の上限なし）。重複や誤認識を確認してからCSVに保存してください。", f"Extracted {len(extracted_rows)} candidate rows (no export row limit). Review duplicates and OCR mistakes before saving."))
        for i, row in enumerate(extracted_rows, 1):
            row["sku"] = f"OCR-{i:03d}"
        st.warning(tr("OCRの価格・販売件数は誤認識の可能性があります。画像と照合してください。", "OCR can misread prices and counts; verify with the images."))
        reviewed = st.data_editor(pd.DataFrame(extracted_rows, columns=OUTPUT_COLUMNS), num_rows="dynamic", use_container_width=True, key="terapeak_ocr_editor")
        converted = add_usd_conversions(reviewed, fx)
        ocr_converted_rows = converted
        st.caption(tr(f"CSVにUSD換算を付与（1 USD = {fx:.3f} JPY）。為替の取得日時・参照元は左側で確認してください。", f"USD conversion added using 1 USD = {fx:.3f} JPY. See sidebar for FX source/time."))
        st.download_button(tr("確認したテラピーク結果をCSVで保存", "Download reviewed Terapeak CSV"),
                           converted.to_csv(index=False).encode("utf-8-sig"), file_name="terapeak_screenshot_ocr.csv", mime="text/csv")
    else:
        st.warning(tr("この画像形式は自動で表を認識できませんでした。下の編集表に商品名や価格を入力すれば、撮り直さずCSVを保存できます。OCR全文も下で確認できます。", "This screenshot layout was not recognized automatically. Enter or paste values in the editable table below and export CSV without taking another screenshot. Raw OCR text is also available below."))
        st.caption(tr("空欄は推測して補完しません。平均成約価格・販売数などは元の画像で確認して入力してください。", "Blank values are never guessed; confirm sold prices and quantities against the original image."))
        manual_template = pd.DataFrame([{column: "" for column in OUTPUT_COLUMNS}])
        manual_template.loc[0, "sku"] = "OCR-001"
        manual_template.loc[0, "source_image"] = ", ".join(f.name for f in screenshot_files)
        manual_template.loc[0, "review_status"] = "手動確認"
        manual_rows = st.data_editor(manual_template, num_rows="dynamic", use_container_width=True, key="terapeak_ocr_manual_editor")
        rows_with_data = manual_rows[manual_rows["title"].astype(str).str.strip().ne("")]
        if not rows_with_data.empty:
            ocr_converted_rows = add_usd_conversions(rows_with_data, fx)
            st.download_button(tr("確認・入力したデータをCSVで保存", "Download manually reviewed CSV"),
                               add_usd_conversions(rows_with_data, fx).to_csv(index=False).encode("utf-8-sig"),
                               file_name="terapeak_screenshot_reviewed.csv", mime="text/csv")
        else:
            st.caption(tr("まずtitle（商品名）の列に1件以上入力すると、CSV保存ボタンが表示されます。", "Enter at least one title to enable CSV download."))
    if raw_parts:
        with st.expander(tr("OCRで読み取った全文（誤認識あり）", "Raw OCR text (may contain errors)")):
            st.text_area("OCR", value="\n\n".join(raw_parts), height=250)
            st.download_button(tr("OCR全文をテキスト保存", "Download raw OCR text"), "\n\n".join(raw_parts).encode("utf-8"), file_name="terapeak_raw_ocr.txt", mime="text/plain")
st.caption(tr("OCRで読み取った商品を下の仕入れ検索に直接引き継げます。仕入れ価格・在庫は別途取得するまで未確認のままです。", "OCR products can flow directly to sourcing. Purchase price and stock remain unverified until separately sourced."))

st.subheader(tr("1. 商品データを取り込む・仕入れ検索につなぐ", "1. Import items and connect to sourcing"))
from research_import import is_terapeak_csv, convert_terapeak_rows

if "import_terapeak" not in st.session_state:
    st.session_state.import_terapeak = True
if ocr_converted_rows is not None and not ocr_converted_rows.empty:
    st.checkbox(tr("上のスクショから抽出した商品を仕入れ検索へ自動連携", "Automatically send screenshot items to sourcing"), key="import_terapeak")
    st.info(tr("OCR結果を仕入れ検索に引き継ぎます。仕入れ価格は未取得であり、利益は確定表示しません。", "OCR rows feed sourcing. Purchase cost is missing and profit will remain unavailable."))
left, right = st.columns(2)
with left:
    source_file = st.file_uploader(tr("仕入れ候補CSV または テラピークCSV", "Sourcing CSV or Terapeak CSV"), type=["csv"], key="sources")
    st.download_button(tr("仕入れ候補テンプレートを取得", "Download sourcing template"), (BASE / "data/sourcing_template.csv").read_bytes(), file_name="sourcing_template.csv", mime="text/csv")
with right:
    sales_file = st.file_uploader(tr("成約参考CSV（任意）", "Sold reference CSV (optional)"), type=["csv"], key="sales")
    st.download_button(tr("成約参考テンプレートを取得", "Download sold-data template"), (BASE / "data/sales_template.csv").read_bytes(), file_name="sales_template.csv", mime="text/csv")

try:
    auto_sales = []
    if source_file is not None:
        incoming = pd.read_csv(io.BytesIO(source_file.getvalue()), dtype=str, keep_default_na=False).to_dict("records")
        if is_terapeak_csv(incoming):
            source_rows, auto_sales = convert_terapeak_rows(incoming, fx)
            st.success(tr(f"テラピークCSVを認識：{len(source_rows)}件を仕入れ検索へ連携しました。", f"Terapeak CSV recognized: {len(source_rows)} items sent to sourcing."))
        else:
            source_rows = load_records(source_file.getvalue(), ["sku", "title", "purchase_jpy"])
    elif ocr_converted_rows is not None and st.session_state.import_terapeak:
        source_rows, auto_sales = convert_terapeak_rows(ocr_converted_rows.to_dict("records"), fx)
        st.success(tr(f"スクショから{len(source_rows)}件を仕入れ検索へ直接連携しました。CSVを再アップロードする必要はありません。", f"{len(source_rows)} screenshot items connected directly; no CSV re-upload required."))
    else:
        source_rows = load_records((BASE / "data/sourcing_sample.csv").read_bytes(), ["sku", "title", "purchase_jpy"])
    if sales_file is not None:
        sales_rows = load_records(sales_file.getvalue(), ["sku"])
    elif auto_sales:
        sales_rows = auto_sales
    elif source_file is None and ocr_converted_rows is None:
        sales_rows = load_records((BASE / "data/sales_sample.csv").read_bytes(), ["sku"])
    else:
        sales_rows = []
except Exception as err:
    st.error(f"CSVエラー: {err}")
    st.stop()

if source_file is None and not auto_sales:
    st.info("仕入れ候補CSVやスクショが未入力のため、デモ商品を使用しています。", icon="ℹ️")
if not source_rows:
    st.warning("有効な商品がありません。テラピークの表を確認してください。")
    st.stop()
if auto_sales:
    st.warning(tr("OCR販売情報は参考値です。仕入れ価格・在庫・国際送料がそろうまで利益は計算できません。", "OCR sales data is provisional. Profit cannot be calculated until purchase price and international shipping are supplied."))

# Use PDF-listed basic freight as a fallback ONLY for rows with no explicit quote.
# An explicit shipping quotation is never overwritten. FedEx zone must be set by seller.
from copy import deepcopy
source_rows = deepcopy(source_rows)
for src in source_rows:
    weight = number(src.get("packed_weight_g"))
    if not weight or weight <= 0 or quote_includes:
        continue
    dims = tuple(number(src.get(k)) for k in ("packed_length_cm", "packed_width_cm", "packed_height_cm"))
    battery = yes(src.get("has_battery"))
    options = [
        ("SpeedPAK Economy", "US_MAINLAND_48", "economy_shipping_jpy"),
        ("SpeedPAK DHL Express Worldwide", "US_ZONE_10", "dhl_shipping_jpy"),
    ]
    if fedex_zone != "未指定":
        options.append(("SpeedPAK FedEx FICP", fedex_zone, "fedex_shipping_jpy"))
    # Orange Connex Economy is shown in the PDF comparison but not used as SpeedPAK Economy in profit.
    for service, zone, field in options:
        if number(src.get(field), 0) > 0:
            continue
        shipping_quote, err = shipping_base(service, zone, weight, dims, battery)
        if shipping_quote:
            src[field] = str(shipping_quote["base_jpy"])
            src.setdefault("_shipping_pdf_sources", {})[field] = f"{shipping_quote['source']} p.{shipping_quote['page']}"

# Search selected source SKUs at the configured official shopping APIs; update price in profit rankings.
if "shopping_offers" not in st.session_state:
    st.session_state.shopping_offers = {}
if "purchase_choices" not in st.session_state:
    st.session_state.purchase_choices = {}

st.subheader(tr("2. 楽天・Yahoo! 在庫あり仕入れ候補の自動検索", "2. Search in-stock Rakuten / Yahoo products"))
st.caption("両社の公式APIで検索。在庫ありだけ取得。型番を含まない商品は最安値候補に採用しません。メルカリは検索リンクのみ。")
search_labels = {f"{row['sku']} | {row['title']}": row for row in source_rows}
search_selection = st.selectbox(tr("検索する商品", "Select product to search"), options=list(search_labels), key="shopping_selection")
chosen_row = search_labels[search_selection]
chosen_sku = str(chosen_row['sku']).strip()
default_keyword = " ".join(filter(None, [str(chosen_row.get('brand','')).strip(), str(chosen_row.get('model','')).strip()])) or str(chosen_row['title'])
col_keyword, col_model = st.columns([3, 2])
with col_keyword:
    buying_keyword = st.text_input(tr("楽天・Yahoo検索ワード", "Rakuten / Yahoo keywords"), value=default_keyword, key=f"keyword_{chosen_sku}")
with col_model:
    buying_model = st.text_input(tr("必須：照合する正確な型番", "Required: exact model number"), value=str(chosen_row.get('model','')), key=f"model_{chosen_sku}")
links = search_links(buying_keyword)
st.markdown("　".join(f"[{label}]({link})" for label,link in links.items()))
if st.button(tr("楽天・YahooをAPIで検索（在庫ありのみ）", "Search Rakuten / Yahoo (in stock only)"), type="primary"):
    require_api_budget()
    if not buying_model.strip():
        st.error("型番を入力してください。型番がない場合はリンクから手動確認してください。")
    else:
        retrieved = []
        errors = []
        rakuten_id = os.getenv('RAKUTEN_APP_ID','').strip()
        yahoo_id = os.getenv('YAHOO_CLIENT_ID','').strip()
        if not rakuten_id and not yahoo_id:
            st.error("楽天またはYahooのAPIキーが未設定です。公開版はStreamlitのSettings → Secretsで設定してください。検索リンクは上の欄から利用できます。")
        else:
            for marketplace, func, key in [
                ('楽天', lambda: rakuten_search(buying_keyword, rakuten_id, os.getenv('RAKUTEN_ACCESS_KEY','')), rakuten_id),
                ('Yahoo', lambda: yahoo_search(buying_keyword, yahoo_id), yahoo_id),
            ]:
                if not key:
                    errors.append(marketplace+": APIキー未設定")
                    continue
                try:
                    retrieved.extend([match_model(offer, buying_model) for offer in func()])
                except (SourcingApiError, ValueError, TypeError) as ex:
                    errors.append(f"{marketplace}: {ex}")
            if not errors or retrieved:
                st.session_state.shopping_offers[chosen_sku] = {"keyword": buying_keyword, "model": buying_model, "offers": [asdict(offer) for offer in retrieved]}
                st.session_state.purchase_choices.pop(chosen_sku, None)
                st.success(f"在庫あり候補{len(retrieved)}件を取得。型番一致候補のみ仕入れ比較に使います。")
            else:
                st.error("検索が正常終了しなかったため、仕入れ価格は変更しません。")
            for error in errors:
                st.warning(error)

saved_search = st.session_state.shopping_offers.get(chosen_sku, {})
if saved_search and (saved_search.get('keyword') != buying_keyword or saved_search.get('model') != buying_model):
    st.info('検索語または型番が変更されました。新しい条件で再検索してください。')
    saved_search = {}
all_offers = saved_search.get('offers', [])
matching_offers = [o for o in all_offers if o['match_status'].startswith('型番一致')]
matching_offers.sort(key=lambda x: (x['item_price_jpy'], x['marketplace']))
if all_offers:
    st.caption(f"型番一致 {len(matching_offers)}件 / 不一致 {len(all_offers)-len(matching_offers)}件。商品価格順で表示しています。送料不明の場合、支払総額の最安値とは限りません。")
    if matching_offers:
        cheapest = matching_offers[0]
        st.metric("型番一致・在庫あり商品の最安商品価格（送料別）", f"¥{cheapest['item_price_jpy']:,}")
        display_frame = pd.DataFrame([{'サイト': x['marketplace'], '商品': x['title'],
                        '商品価格円': x['item_price_jpy'], '送料円（不明は空欄）': x['shipping_jpy'],
                        '合計円（判明分のみ）': x['item_price_jpy']+x['shipping_jpy'] if x['shipping_jpy'] is not None else None,
                        '型番': x['match_status'], '在庫': x['inventory_status'], '商品URL': x['item_url']}
                      for x in matching_offers])
        st.dataframe(display_frame, use_container_width=True, hide_index=True, column_config={'商品URL':st.column_config.LinkColumn('仕入れページ')})
        choices_to_use = ['適用しない'] + [f"{i+1}. {o['marketplace']} ¥{o['item_price_jpy']:,} | {o['title'][:42]}" for i,o in enumerate(matching_offers)]
        selection = st.selectbox('利益一覧に採用する仕入れ先', choices_to_use, key=f'select_supplier_{chosen_sku}')
        if st.button('選んだ仕入れ価格を利益計算に反映'):
            if selection == '適用しない':
                st.session_state.purchase_choices.pop(chosen_sku, None)
                st.info('仕入れ価格の上書きを解除しました。')
            else:
                chosen_offer = matching_offers[choices_to_use.index(selection)-1]
                st.session_state.purchase_choices[chosen_sku] = chosen_offer
                st.success('選んだ商品価格を利益ランキングに反映しました。仕入れ送料と最終在庫を確認してください。')
    else:
        st.warning('型番一致する在庫あり商品はありません。自動的に仕入れ価格を採用しません。')

for src in source_rows:
    confirmed = st.session_state.purchase_choices.get(str(src['sku']).strip())
    if confirmed:
        src['purchase_jpy'] = str(confirmed['item_price_jpy'])
        src['source'] = confirmed['marketplace']
        src['source_url'] = confirmed['item_url']
        if confirmed.get('shipping_jpy') is not None:
            src['domestic_shipping_jpy'] = str(confirmed['shipping_jpy'])
        src['_purchase_api_checked'] = True

st.subheader(tr("PDF料金表：米国向け基本送料を比較", "Compare US base shipping rates from PDFs"))
st.caption('2026年版の4種類のPDFに記載された基本運賃。燃油・混雑期・関税・通関費用等を含みません。EMSは日本郵便公式料金ページから別途確認してください。')
if quote_includes:
    st.warning('全項目込み送料モード中はPDFの基本送料を利益計算へ自動採用しません。CSVに全項目込み金額を入れてください。')
shipping_weight = number(chosen_row.get('packed_weight_g'))
if shipping_weight and shipping_weight > 0:
    shipping_dims = tuple(number(chosen_row.get(k)) for k in ('packed_length_cm','packed_width_cm','packed_height_cm'))
    base_quotes = quote_us_all(shipping_weight, shipping_dims, yes(chosen_row.get('has_battery')), fedex_zone)
    if base_quotes:
        st.dataframe(pd.DataFrame(base_quotes)[['service','zone','billable_kg','bracket_kg','base_jpy','note','source','page']],use_container_width=True,hide_index=True)
        st.caption('FedExの地域未指定時は両地域を参考表示するだけで利益計算へ自動採用しません。サイズ・危険物・配達可能地域は要確認。')
else:
    st.info('この商品の基本運賃を表示するには、仕入れ候補CSVに梱包後重量（packed_weight_g）を入力してください。')
st.markdown('[日本郵便の国際郵便公式料金表（EMSなど）](https://www.post.japanpost.jp/send/oversea/charge/)')

if "live_market" not in st.session_state:
    st.session_state.live_market = {}

sales_map = {str(r.get("sku", "")).strip(): r for r in sales_rows}
st.subheader(tr("3. テラピークで成約相場を確認（API不要）", "3. Open Product Research (Terapeak) (no API)"))
st.caption(tr("テラピークを開いて検索語を手入力してください。成約履歴・販売件数は自動取得しません。", "Open Product Research and enter a search term manually. Sold listing data and counts are not automatically fetched."))
eb_link_rows=[]
for src in source_rows[:50]:
    sku = str(src.get('sku','')).strip()
    matching = sales_map.get(sku, {})
    query = (matching.get('ebay_query') or src.get('ebay_query') or
             ' '.join(x for x in (src.get('brand', ''), src.get('model', '')) if x).strip() or src.get('title', ''))
    eb_link_rows.append({'SKU':sku,'商品名':src.get('title',''),'テラピークURL':'https://www.ebay.com/sh/research','検索語':str(query)})
if eb_link_rows:
    st.dataframe(pd.DataFrame(eb_link_rows), use_container_width=True, hide_index=True,
                 column_config={'テラピークURL': st.column_config.LinkColumn('テラピークを開く')})

st.subheader(tr("3.5. eBayカテゴリー手動確認・カテゴリー別販売手数料", "3.5. Manual category checks and category-specific fees"))
st.caption("eBay APIは使用しません。eBayサイト上で正しいカテゴリーIDを確認し、CSVのカテゴリー情報や自己確認済み料率表を管理してください。未確認のIDやカテゴリー別料率を自動で決めません。")
if "category_suggestions" not in st.session_state:
    st.session_state.category_suggestions = {}
if "category_choices" not in st.session_state:
    st.session_state.category_choices = {}
if "category_fingerprints" not in st.session_state:
    st.session_state.category_fingerprints = {}
invalidated = reconcile_category_context(
    source_rows, st.session_state.category_fingerprints,
    st.session_state.category_suggestions, st.session_state.category_choices,
)
for changed_sku in invalidated:
    # A Streamlit text_input key survives changes to its default value.
    st.session_state.pop(f'category_query_{changed_sku}', None)
    st.session_state.pop(f'cat_choice_{changed_sku}', None)
if invalidated:
    st.info('商品名・ブランド・型番の変更、またはSKU削除を検出したため、以前のカテゴリー選択を無効にしました。')

store_plan = st.text_input("eBayストア契約区分（例: no_store。料率表の契約区分と一致させる）", value="no_store")
fee_json = st.file_uploader("eBay公式手数料表を確認して登録したJSON（任意）", type=['json'], key='ebay_fee_table')
category_fee_schedule = None
if fee_json:
    try:
        import json
        category_fee_schedule = validate_schedule(json.loads(fee_json.getvalue().decode('utf-8-sig')))
        if category_fee_schedule['store_plan'] != store_plan:
            st.warning('登録した料金表とストア契約区分が一致しません。共通20%仮定を使用します。')
            category_fee_schedule = None
        else:
            st.info(f"自己確認済み料金表: {len(category_fee_schedule['rates'])}カテゴリー / 期限 {category_fee_schedule['effective_to']}。正式なeBay請求額を保証するものではありません。")
    except (CategoryFeeError, UnicodeError, ValueError) as ex:
        st.warning(f'カテゴリー別の手数料表は使用できません: {ex}')

category_label_map = {f"{r['sku']} | {r['title']}": r for r in source_rows}
category_label = st.selectbox('カテゴリーを検索する商品', list(category_label_map), key='category_search_select')
category_row = category_label_map[category_label]
category_sku = str(category_row['sku']).strip()
category_query = st.text_input('カテゴリー検索用の商品名', value=str(category_row.get('title', '')), key=f'category_query_{category_sku}')
selected_for_query = st.session_state.category_choices.get(category_sku)
if selected_for_query and not category_choice_is_current(
    selected_for_query, category_query, st.session_state.category_fingerprints[category_sku]
):
    st.session_state.category_choices.pop(category_sku, None)
st.markdown(f"[eBayで商品名を検索してカテゴリーを確認する](https://www.ebay.com/sch/i.html?_nkw={url_quote(str(category_query or ""), safe="")})")
st.info('APIなしモードではカテゴリー候補の自動取得は無効です。手数料の計算には検証済み料率表または共通の仮定値を使用します。')

for row in source_rows:
    sku = str(row.get('sku','')).strip()
    # Never trust a CSV-provided internal override as verification.
    row.pop('_verified_fee_pct', None)
    row.pop('_selected_category_id', None)
    row.pop('_selected_category_name', None)
    selected = st.session_state.category_choices.get(sku)
    query_used = str(st.session_state.get(f'category_query_{sku}', row.get('title', '')))
    if not category_choice_is_current(selected, query_used, st.session_state.category_fingerprints[sku]):
        st.session_state.category_choices.pop(sku, None)
        selected = None
    if selected:
        row['_selected_category_id'] = selected['category_id']
        row['_selected_category_name'] = selected['name']
        rate = category_rate(category_fee_schedule, selected['category_id'], store_plan)
        if rate is not None:
            row['_verified_fee_pct'] = rate

st.caption('料率表の公式自動更新は未実装です。登録したJSONは出品者による自己確認を前提とします。eBayの契約・注文総額の算定基準・段階料率を確認できない場合、20%の仮計算です。')

results = evaluate_all(source_rows, sales_rows, st.session_state.live_market, settings)
rows = []
for item in results:
    original = next((row for row in source_rows if str(row.get('sku','')).strip() == item['sku']), {})
    rows.append({
        "送料データ": "PDF基本運賃（割増確認要）" if original.get('_shipping_pdf_sources') else "CSVの送料見積",
        "SKU": item["sku"], "商品名": item["title"], "カテゴリーID": item["ebay_category_id"], "カテゴリー": item["ebay_category_name"], "eBay手数料%": item["ebay_fee_pct_used"], "手数料根拠": item["ebay_fee_basis"], "想定売価USD": item["sale_price_usd"],
        "仕入円": item["purchase_jpy"], "配送方法": item["shipping_method"],
        "国際送料円": item["shipping_base_jpy"], "送料込み参考額円": item["shipping_quoted_total_jpy"], "利益円": item["profit_jpy"],
        "利益率%": item["margin_pct"], "目標達成最低価格USD": item["min_price_usd"],
        "90日販売件数(入力値)": item["sold_count_90d"],
        "参考消化率%": item["sell_through_proxy_pct"],
        "現行出品中央値USD": item["competitor_median_usd"],
        "判定": item["status"], "要確認事項数": len(item["warnings"]),
        "仕入れ元": item["source"], "仕入れURL": item["source_url"],
        "仕入れ価格状態": "APIで在庫確認・送料は要確認" if original.get('_purchase_api_checked') else "CSV値/未確認",
    })

st.subheader(tr("4. リサーチ結果と利益ランキング", "4. Research results & profit ranking"))
profitable = sum(r["status"] == "目標達成" for r in results)
positive = sum(r["profit_jpy"] is not None and r["profit_jpy"] > 0 for r in results)
t1, t2, t3 = st.columns(3)
t1.metric("商品候補", f"{len(results)}件")
t2.metric(f"目標利益率 {target:g}% 達成", f"{profitable}件")
t3.metric("黒字見込み", f"{positive}件")
frame = pd.DataFrame(rows)
if not frame.empty:
    frame = frame.sort_values(by=["利益円", "利益率%"], ascending=False, na_position="last")
    st.dataframe(frame, use_container_width=True, hide_index=True, column_config={
        "仕入れURL": st.column_config.LinkColumn("仕入れURL"),
        "利益率%": st.column_config.NumberColumn("利益率%", format="%.2f"),
        "利益円": st.column_config.NumberColumn("利益円", format="¥%d"),
    })
    out = io.StringIO()
    frame.to_csv(out, index=False)
    st.download_button(tr("ランキング結果をCSV保存", "Export ranking CSV"), out.getvalue().encode("utf-8-sig"),
                       file_name="ebay_research_results.csv", mime="text/csv", type="primary")

st.subheader(tr("5. 商品ごとの詳細・仕入れ検索", "5. Product details and sourcing links"))
if not results:
    st.stop()
choices = {f"{item['sku']} | {item['title']}": item for item in results}
selected = st.selectbox(tr("分析したい商品", "Product to analyze"), list(choices))
item = choices[selected]
with st.container(border=True):
    st.markdown(f"**{item['title']}**")
    st.write(f"**売価の根拠:** {item['price_basis']}")
    st.write(f"**eBayカテゴリー:** {item['ebay_category_id'] or '未確認'} / {item['ebay_category_name'] or '未確認'}。**販売手数料率:** {item['ebay_fee_pct_used']:g}% — {item['ebay_fee_basis']}")
    a, b, c = st.columns(3)
    a.metric("利益（試算）", f"¥{item['profit_jpy']:,}" if item["profit_jpy"] is not None else "未計算")
    b.metric("利益率（試算）", f"{item['margin_pct']:.2f}%" if item["margin_pct"] is not None else "未計算")
    c.metric("目標利益率に必要な売価", f"${item['min_price_usd']:.2f}" if item["min_price_usd"] is not None else "未計算")
    if item.get("breakdown"):
        with st.expander("利益の内訳を表示"):
            st.json(item["breakdown"], expanded=True)
    if item["shipping_options"]:
        st.write("**配送方法の見積比較（入力された料金のみ）**")
        st.dataframe(pd.DataFrame(item["shipping_options"]), use_container_width=True, hide_index=True)
    st.write(f"**推奨配送ポリシー候補:** {item['policy']}")
    if item["volume_weight_g_div5000"] is not None:
        st.caption(f"参考容積重量（cm³÷5,000）：{item['volume_weight_g_div5000']:.0f} g 相当。実際の換算係数・請求重量は運送会社で確認")
    if item["warnings"]:
        st.write("**要確認事項:** " + " / ".join(item["warnings"]))

    search_query = (item["ebay_query"] or item["title"]).strip()
    encoded = url_quote(search_query, safe="")
    st.write("**仕入れ候補を調べる（実在庫・価格はページ上で確認）**")
    st.markdown(
        f"[メルカリ検索](https://jp.mercari.com/search?keyword={encoded})　"
        f"[楽天市場検索](https://search.rakuten.co.jp/search/mall/{encoded}/)　"
        f"[Yahoo!ショッピング検索](https://shopping.yahoo.co.jp/search?p={encoded})"
    )
    if item["source_url"].startswith(("https://", "http://")):
        st.markdown(f"[登録済みの仕入れ元URLを開く]({item['source_url']})")
    st.caption("これらは検索リンクです。表示価格・在庫・同一型番を自動確認した結果ではありません。")

st.subheader(tr("6. AIによる仕入れ判断（任意）", "6. AI sourcing opinion (optional)"))
st.caption("AIに送るのは選択中の商品・数値・注意事項です。AIは未確認の市場情報を補完できません。OpenAI APIはChatGPTと別課金です。")
if st.button("選択した商品をAI分析", disabled=not bool(os.getenv("OPENAI_API_KEY")) or os.getenv("ENABLE_PUBLIC_AI", "false").lower() != "true"):
    require_api_budget()
    try:
        with st.spinner("入力済みデータを分析しています"):
            answer = analyze_candidate(os.getenv("OPENAI_API_KEY", ""), os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), item)
        st.markdown(answer)
    except AIClientError as err:
        st.error(str(err))
if not os.getenv("OPENAI_API_KEY"):
    st.info("AI分析を有効にする場合は、.env の OPENAI_API_KEY を設定して画面を再起動してください。")

st.divider()
st.caption("免責：PDF送料は基本運賃であり、追加料金ゼロは未確認を意味します。API在庫は取得時点の情報で実際の仕入れ可能性を保証しません。数値は意思決定の試算です。eBay実手数料、広告、関税・原産国、梱包サイズ、送料、消費税、実際の輸入通関費用を個別に確認してください。消費税還付は計算に加算していません。")
