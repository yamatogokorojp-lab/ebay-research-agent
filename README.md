# eBay 商品リサーチ AI（Windows / MacBook 共通版）

**何が動くか:** CSVの商品候補を読み込み、米国送料無料を想定して利益・必要販売価格・配送方法を比較する。必要なキーを設定した場合のみeBay公式Browse APIで「現在の出品価格サンプル」を取得し、OpenAI APIで入力内容の分析を行う。

**まだできないこと:** テラピークの成約データの直接自動取得、メルカリからの価格・在庫自動取得、eBay自動出品、E-Lister同期。楽天/YahooのAPI対応コードはありますが実通信は未検証です。現行出品価格を成約実績と取り違えないこと。初期デモの成約数や価格は架空のデモ値です。

## Windows / MacBook の起動方法（共通アプリ）

**同じ Streamlit アプリを Windows と macOS（Apple Silicon / Intel）の両方から起動**する構成です。
端末ごとにPython 3.11〜3.13をインストールし、インターネット接続のある状態で初回セットアップしてください。

- **Windows:** フォルダ内の `run_windows.bat` をダブルクリック。`http://localhost:8501` に表示。
- **MacBook:** フォルダ内の `run_mac.command` をダブルクリック。macOS が起動をブロックした場合はFinderでControl+クリック→開く、またはターミナルで `bash run_mac.command` を実行。`http://localhost:8501` に表示。
- 各OS専用のPython環境を `.venv_windows/` と `.venv_mac/` に作るため、両端末の環境は競合しません。
- **重要:** `localhost` はそれぞれのPC内だけです。Windowsで起動した画面をMacBookから同じURLで共有したり、CSV/設定を同期したりする仕組みではありません。共通データの同期をする場合は認証付きのクラウド配備と保存先が別途必要です。
- `.env` にAPIキーを設定する場合、**キーをチャットや公開リポジトリにアップロードしない**でください。`.env.example` のコピーを作成して入力します。
- 画面の基本機能はOS共通ですが、Mac・Windows実機および楽天/Yahoo/送料変動レート取得の本番通信はまだ検証されていません。料金表は基本料金のみであり、すべての追加料金の自動更新は未完成です。

**Macのターミナルで手動起動:** `cd /path/to/ebay_research_agent_v2 && bash run_mac.command`。

## 料金サーチャージの更新（重要：公式配信URLの確認が必要）

今回、**配送業者ごとの費用を独立して扱う検証済みデータ取込機構**を追加しました。指定したHTTPSの公式料金フィードに、`rates` オブジェクト・サービス別の燃油率、繁忙期割増、通関処理費、その他費用、適用開始日・終了日、公式の出典URLがそろっている場合、アプリ画面の操作・再表示時に最大30分のキャッシュ間隔で読み直します。過去の日付、不正な単位、出典の違うドメイン、欠けた項目は**一括拒否**し、未確認を0円とは扱いません。入力済みCPaSS全項目込み見積もりには追加費用を加算しません。

**制約:** 2026年10月21日時点では各社がこのJSON構造を提供している公式エンドポイントを確認できていません。したがって `.env` の `OFFICIAL_SURCHARGE_JSON_URL` は初期状態で空で、自動料金取得は**未稼働**です。FedEx、DHL、Orange Connexの一般公開料金ページをこのフィールドに設定しても自動でパースできません。正規の配信URL・データ形式・利用許諾を確認して専用アダプターを実装し、本番通信テストに合格する必要があります。現時点ではテスト用の架空JSONを本番の料金として採用しないでください。

利用可能なJSON形式の例（説明・単体テスト用。**金額は架空**）:

```json
{"rates":{"SpeedPAK Economy":{"fuel_pct":10,"peak_jpy":200,"customs_jpy":180,"other_jpy":20,"effective_from":"2026-10-01","effective_to":"2026-10-31","source_url":"https://www.orangeconnex.jp/charges"}}}
```

複数社の自動データが揃っていない場合は、未取得の配送手段の追加料金は暫定の共通入力になります。比較した配送手段によっては実請求と乖離するため、正確な最安値や確定利益として採用しないでください。日本郵便EMS・関税率の最新情報・CPaSSの正規見積APIも別途実装と接続が必要です。

## 1. Windowsで初回起動

1. [python.org](https://www.python.org/downloads/windows/) から **Python 3.11または3.12** をインストール。`py --version` がWindowsのコマンドプロンプトで動くことを確認。
2. このZIPを解凍し、フォルダ内の **`run_windows.bat`** をダブルクリック。仮想環境の作成とPythonライブラリのインストールをして、アプリを起動します。初回はネット接続が必要です。
3. ブラウザが開かないときは http://localhost:8501 を開いてください。
4. デモデータが表示されます。**この数字は仕入れ判断に使わない**でください。

Windows PowerShellから手動起動する場合（仮想環境Activate不要）:

```powershell
cd 'C:\Users\あなたの名前\Downloads\ebay_research_agent'
py -3 -m venv .venv_windows
.\.venv_windows\Scripts\python.exe -m pip install -r requirements.txt
.\.venv_windows\Scripts\python.exe -m streamlit run app.py
```

## 2. 自分の候補で分析する（APIキーなしでもOK）

1. アプリ上で `仕入れ候補テンプレートを取得` し、Excelで開き、1行1SKUで入力。
2. 最低限 `sku`, `title`, `purchase_jpy` の3列。現実的な利益計算のために `target_price_usd`, `economy_shipping_jpy`, `fedex_shipping_jpy`, `dhl_shipping_jpy`, `packed_weight_g`, `country_of_origin` なども入れる。
3. **仕入れ先は現物のURL・値段・在庫を自分で確認**してから `source_url` に登録。メルカリは検索ページへのリンクを提供します。楽天・Yahoo!ショッピングの自動検索はAPIキー設定が必要で、API通信・在庫精度は実環境で検証してください。
4. eBay Product Research（旧Terapeak）などで調べた**成約単価と90日販売件数**を `成約参考テンプレート` に手入力し、`sku` を一致させる。Product Researchのエクスポート列名は環境で異なり得るので、生CSVはこの形式に整理してから投入してください。
5. アプリで2つのCSVを読み込み、ランキングと商品別利益内訳を確認。
6. `ランキング結果をCSV保存` で結果をエクスポート。

### 仕入れ候補の主な列

| 列 | 意味 |
| --- | --- |
| sku | 同一商品+同一サイズ/仕様に固有のコード |
| title | 英語商品名（可能なら型番付き） |
| brand, model | eBay検索用の識別子 |
| source, source_url | 仕入れ先と検証済み商品ページ |
| purchase_jpy | 商品の仕入れ価格（円） |
| domestic_shipping_jpy | 国内送料（円） |
| packed_weight_g | 梱包後重量（g） |
| packed_length_cm / packed_width_cm / packed_height_cm | 梱包サイズ（cm） |
| economy_shipping_jpy, fedex_shipping_jpy, dhl_shipping_jpy | それぞれの**実際の見積もり送料**（円） |
| ems_shipping_jpy, ems_eligible | EMS見積もりと可否確認済フラグ |
| has_battery | yes/no。yesならSpeedPAK Economyを候補から除外 |
| country_of_origin | 原産国（日本で販売されていることとは別） |
| target_price_usd | 想定するeBay出品売価（米ドル） |
| category_fee_pct | 商品ごとの販売手数料%（未入力なら画面の仮値） |
| extra_fees_jpy | その他の通関・保険・梱包等の費用（円） |
| ebay_query | eBay Browse APIで検索する英語キーワード |

### 参考成約データの列

| 列 | 意味 |
| --- | --- |
| sku | 仕入れ候補と同じSKU |
| ebay_query | 英語検索語（型番など） |
| reference_sold_price_usd | Product Research等で**確認した**参考成約単価 |
| sold_count_90d | 対象90日間の成約件数（自身で照合） |
| active_count_reference | 比較対象となる現行出品件数（自身で照合） |
| notes | 補足（販売実績出典、検索範囲、取得日など） |

**販売価格の優先順:** `target_price_usd` → 参考成約単価 → Browse APIで取得した現行出品価格の中央値。最後の方法は代替参考値であり成約価格ではありません。

## 3. eBay APIを使う（任意）

1. https://developer.ebay.com/ でeBay Developers Programアカウントを用意。
2. アプリの **Production** Client ID (App ID) と Client Secret (Cert ID) を取得。Sandboxキーはそのままでは本番のBrowse APIには使えません。
3. プロジェクトの `.env.example` をコピーしてファイル名を `.env` に変え、次を入力。

```env
EBAY_CLIENT_ID=あなたのProductionClientID
EBAY_CLIENT_SECRET=あなたのProductionClientSecret
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
```

4. `run_windows.bat` を再起動し `eBay公式APIで現行出品を検索` をクリック（1回最大20SKU）。
5. eBay Browse APIを利用するには、開発者アカウント・アプリの権限・API利用条件の確認が必要です。利用制限やエンドポイントの変更があれば https://developer.ebay.com/api-docs/buy/browse/overview.html を参照してください。

このコードは、**OAuthクライアント認証 (client credentials)** でアプリトークンを取得し、USマーケットの現在の固定価格出品を検索します。購入済み商品・売却完了データは取得しません。APIの検索総数は正確な同一商品の競合数ではありません。返品・バリエーション・出品コンディション・輸入の可否の比較は手作業で確認してください。

## 4. OpenAI AIコメントを使う（任意）

1. https://platform.openai.com/ でAPIキーと課金設定を用意。**ChatGPTの有料プランとは別のAPI利用料金**が発生します。
2. `.env` に `OPENAI_API_KEY=...` を設定。`OPENAI_MODEL` は自分のAPIアカウントで利用可能なモデルIDを指定。初期例のモデルIDが利用できなければ変更。
3. アプリを再起動、商品を1つ選択して `選択した商品をAI分析` をクリック。
4. AIへは商品の数値と未確認事項が送信されます。仕入れ先の秘密情報を送らない運用にしてください。

## 5. 利益計算ロジック

想定売価 × 入力USD/JPY = 売上円。そこから、仕入れ・国内送料・国際送料・eBay販売手数料（%と固定費）・広告費・米国関税（仮定）・Economy通関関連費用（該当時）・その他費用を差し引きます。利益率 = 利益 ÷ 売上円。

- 既定為替 **158円は説明用の仮定**で、最新の実勢レートではありません。必ず入れ替えてください。
- 販売手数料13.25%、固定手数料0.40 USDは概算値です。カテゴリや価格、eBayの実請求明細で変更してください。
- 米国関税 **12.5%はユーザー希望の試算値**。原産国・HS/HTS・政策・通関請求により実際の適用率が異なります。
- Economyの輸入通関費245円・関税処理2.1%は**保存された過去の料金表に基づく暫定入力**です。最新レートや実見積りの内訳を優先します。
- `入力送料見積に関税・通関費用も含まれる` をONにすると、アプリ側での関税とEconomy通関費の加算を停止します。**方法ごとに含有条件が異なる見積もりを混在させない**でください。
- 為替差損、返品、輸入消費税、その他の費用は別途確認。消費税還付は計上していません。
- 体積重量(cm³/5,000)は参考値で、各社の計測ルールや端数処理、サイズ制限は本番契約・見積りで確認してください。
- 参考消化率 = 過去90日販売件数 ÷ (過去90日販売件数 + 参考現行出品件数) × 100。これは**統一条件での参考指標**であり、eBay公認のsell-through値ではありません。

## 6. セキュリティとAPI運用

- `.env` に入れたAPIキーは第三者と共有しない。画面共有時にも注意。
- ローカル起動はWindows/MacBook双方で行う設計ですが、実機動作は未確認です。PC終了時は停止。常時稼働の自動リサーチではありません。
- 仕入れ先で自動取得を拡張する場合、各サイトが提供するAPI・契約上許可された方法を使用。規約上認められないスクレイピングやCAPTCHA回避を前提にしない。
- API費用、eBayアプリの利用条件・レート制限を確認。大量処理はキャッシュ・キュー・監視ログを追加してから。
- 中古品を仕入れて反復販売する際は、古物商許可の必要性を所轄警察等に確認。

## 7. トラブル対応

- `py` が認識されない：Pythonのインストールを見直し、コマンドプロンプトを開き直す。
- Python 3.13以降でライブラリのインストールに失敗：Python 3.11または3.12に切り替えて仮想環境を作り直す。
- `localhost:8501` が開かない：黒い画面のエラーを確認し、ポートが使われていないか確かめる。
- CSV文字化け：UTF-8（BOMあり）かShift-JIS(CP932)形式で保存。
- 利益が出ない：仕入れ・想定売価・国際送料を先に見直す。空欄は自動で埋めない。
- APIが401：ProductionのClient ID/Secret、必要スコープ、許可状況を確認。
- APIが403/429：eBayアプリの権限や利用制限を確認。
- 連続検索で相場が変：英語型番が適切か、別商品・状態・送料を比較していないか確認。

## 8. 将来の拡張

第2段階: 正式な仕入れAPIを使った商品検索・重複判定・国内仕入れ価格の定期更新。第3段階: eBay APIによるSKU対応とE-Lister運用検証（出品・在庫が競合しないよう調整）。第4段階: スケジュール実行とWebダッシュボードのクラウド化。

## 9. 自動テスト

```powershell
.\.venv_windows\Scripts\python.exe -m unittest discover -s tests -v
```

## 10. eBay検索キーワードから候補を作成

eBayのProduction APIキーを設定したら、画面最上部にある「0. キーワードから新しい商品候補を探す」で英語検索語を1行ずつ入力し、検索ボタンを押します。これは**出品中の商品のタイトル・価格の参考情報**を抽出します。結果を `discovered_candidates.csv` として保存し、メルカリ・楽天・Yahoo!ショッピングなどで**自分で確認した**仕入れ価格・仕入れURL・送料・想定売価を追記します。そのCSVを「1. ファイルを読み込む」から取り込み、利益ランキングを作ります。

eBay現行出品を探すだけでは「売れている」証拠にはならないため、成約実績はProduct Research等で別途確認してください。自動候補の `reference_active_price_usd` は、出品価格の参考情報として保存されますが、**自動で想定売価には転記しません**。

## カテゴリーとeBay販売手数料の追加検証（2026-10-21）

商品名からeBay米国版のTaxonomy APIを検索し、カテゴリID候補を表示する機能を追加しました。候補の自動判定は必ずしも正確ではないため、実際の出品カテゴリーは利用者が選択する必要があります。eBay Taxonomy APIは**販売手数料率を返しません**。

確認済みの販売手数料表をJSONで読み込んだ場合に限り、選択したカテゴリーIDとストア契約区分に合う料率を仕入れ候補の利益計算へ反映します。料率表の登録は利用者による出典確認を前提とし、公式サイトからの自動更新はまだ未実装です。CSV内の`category_fee_pct`だけでは検証済みとみなしません。

必要項目: `marketplace` が `EBAY_US`、`seller_country` が `JP`、`store_plan`、eBay公式手数料表の `source_url`、`verified_by_seller=true`、`effective_from`、`effective_to`、および `rates` 配列（`category_id` 数字文字列、`percentage` 数値）。単一料率モデルに対応しない段階料金は読み込み拒否します。手数料表がない・有効期間外・ストア契約が一致しない場合は一律20%の**仮計算**を使用します。販売額の段階料金、税・送料を含む課金対象、固定手数料などを確認せずに確定利益とは扱わないでください。

## API不要版：eBay検索リンク方式（2026-10-21）

- eBay Developerアカウント、Client ID、Client Secret、eBay販売アカウント認証は不要です。
- キーワードでeBay公式検索リンクとCSVの入力テンプレート（価格欄は空欄）を生成します。
- eBay出品価格・売約実績・カテゴリー候補は**自動取得しません**。Terapeak等で確認してCSVに入力してください。
- 楽天・Yahooの在庫ありAPI自動検索には、それぞれの認証キーが引き続き必要です。設定しなくても各仕入れサイトへの検索リンクを利用できます。
- 公開時のAPIキーはStreamlit Settings → Secretsにのみ保存し、GitHubへコミットしないでください。
- eBayの出品や在庫を更新する機能はありません。
- GitHubで既存のファイルを更新するときは、このZIPの**中身**をリポジトリのルートに上書きしてコミットしてください。ZIPファイル自体を置くだけでは更新されません。


## テラピーク（Product Research）リンク版

- アプリの先頭とCSVの各商品に公式Seller Hub Product Researchへのリンク（https://www.ebay.com/sh/research）を表示します。ログインが必要な場合があります。
- 商品名はリンク先に自動入力されません。アプリの検索語をコピーしProduct Research内で検索してください。
- 成約データは自動取得せず、参考成約単価や販売件数はCSVで手動入力してください。

## 2026-10-21 UI update
- 0: Offline English keyword suggestion generation (not verified sold-data analytics), copy-all code block.
- 0.1: Single Product Research (Terapeak) link, with no eBay API authentication.
- 0.2: Multi-screenshot OCR to CSV with no fixed output row cap, plus USD-converted price and shipping columns using the displayed USD/JPY rate. Original amounts and original currency are retained. USD already in screenshots remains USD; non-JPY/non-USD values are left unconverted rather than guessed.
- Other sourcing/shipping/profit/CSV sections retained. Automatic FX may be unavailable, in which case the sidebar manual assumption applies. OCR results may require review; this is not a guarantee of full automatic extraction.


### 2026-10-21 修正：カテゴリー検索 TypeError
送料見積の変数名が urllib.parse.quote を上書きする不具合を修正。カテゴリー検索と仕入れ先検索リンクのURLエンコードは url_quote に統一しました。


## OCR表認識v2（2026-10-21）
- `terapeak_ocr.py` は商品の下に出る `Fixed price` を行アンカーに、スクリーンショット内の列位置から商品名・平均成約価格・送料・販売数を抽出します。2枚目以降でヘッダーがない場合にも対応します。
- 撮影時はProduct Researchの結果表の全幅を表示してください。複数画像の重複行はタイトル・価格・送料・販売数が完全一致する場合だけ除外します。
- スクリーンショット2枚で21行検出した検証がありますが、OCRは100%の精度を保証しません。値を推測して埋めず、ダウンロード前に画像と照合してください。
- GitHubではZIP自体ではなく解凍したファイルをリポジトリのルートに上書きしてコミットし、Streamlitを再起動してください。見出し `表の位置認識 v2` で反映状況を確認できます。

## Product Research CSV → sourcing integration (2026-10-22)

- Screenshot OCR results directly feed the sourcing workflow when the checkbox is selected; no re-upload is necessary.
- The sourcing uploader also accepts `terapeak_screenshot_ocr.csv` and detects its columns automatically.
- A compatible sourcing item and sold-price reference share the same SKU. `average_sold_price_usd` is used as **reference** price, not as a verified sale of your own item.
- Product Research's per-listing `total_sold` is preserved only as a note; it is not mistaken for a 90-day market-wide sold count.
- Sourcing prices, verified stock, shipping costs and origin remain blank until actually established. Incomplete costs must never produce a confirmed profit.
- The original sourcing CSV format and optional sold-reference CSV importer remain supported.
