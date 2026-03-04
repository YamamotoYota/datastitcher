# DataStitcher

CSV / Excel / SQLデータベース / PI AF SDK からデータを取得し、結合（横方向）・時系列近傍結合（asof）・縦連結（union）で統合して、CSV または Excel（1シート）へ出力するローカル実行アプリです。

## セットアップ

前提:
- Windows（VS Code から実行想定）
- Python 3.11 以上
- SQL Server / PI AF SDK を使う場合は、クライアント側ドライバや PI AF Client のインストールが必要

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 実行ファイル作成（PyInstaller）

`DataStitcher.exe` を作成する場合は、以下を実行します。

```powershell
.\build_exe.ps1
```

出力先:
- `dist\DataStitcher\DataStitcher.exe`

起動後はローカルの Streamlit サーバー（既定: `http://localhost:8501`）で画面を操作します。

## 使い方

1. サイドバーから入力テーブルを追加
- ファイル: `CSV / XLSX / XLS / XLSM` をアップロード
- 外部ソース: `SQL追加 / PI DA追加 / AF属性追加 / AFイベント追加`
2. 「入力テーブル」で各テーブルを設定
- 共通: 列名正規化、使用列、型上書き
- CSV: 文字コード/区切り文字/引用符/ヘッダ行
- Excel: シート/ヘッダ行
- SQL: 接続情報、テーブル一覧取得、SQLクエリ
- PI AF SDK: 取得条件（タグ/属性/イベントフレーム）
3. サイドバー「結合・縦連結の手順」で手順追加
4. 手順ごとに結合方式（equi/asof）または縦連結を設定
5. 「処理を実行」
6. 最終結果・品質指標・未マッチ抽出を確認してダウンロード

補足:
- サイドバーの「アプリ停止」で画面からサーバー停止できます。
- 停止後は `streamlit run app.py` で再開できます。

## 実装済み機能

### 入力ソース
- ファイル
  - CSV（文字コード自動推定 + 手動指定）
  - Excel（`.xlsx`, `.xls`, `.xlsm`）
- SQLデータベース
  - SQL Server / MySQL / SQLite / Oracle Database / PostgreSQL
  - 接続テスト、テーブル一覧取得、任意SQL実行
- PI AF SDK（PI DataLink相当）
  - PI DAタグ: Snapshot / Recorded / Interpolated / Summary
  - PI AF属性: エレメント名 + 属性名で取得（PI DAタグ同様の行形式）
  - PI AFイベントフレーム: テンプレート + 対象期間 + イベント生成分析名で取得

### 結合・縦連結
- 多段手順（ベーステーブル → 手順1 → 手順2 ...）
- 等値結合: `Inner / Left / Right / Full outer`
- asof結合: `backward / forward / nearest`, `tolerance`, `byキー`
- 単一キー / 複合キー
- 同名列衝突ポリシー: `left_prefer / right_prefer / keep_both`
- 縦連結（union）
  - 列名の近似提案
  - 手動マッピング修正
  - 新規列保持 / 除外 / 出典列追加

### 品質指標・出力・再現性
- 各手順で行数、マッチ率、未マッチ、多重マッチ兆候、行数増加警告を表示
- 未マッチ行（左右）をCSVダウンロード
- 最終結果をCSV / Excel(1シート)でダウンロード
- Excel行数上限警告
- レシピ JSON 保存・再読み込み
- 実行ログ保存（`logs/execution_log.jsonl`）

## テスト用データ

`data/` に UI動作確認用データを同梱しています。

主なファイル:
- `data/01_customers.csv`
- `data/02_orders.csv`
- `data/03_payments.csv`
- `data/04_events_for_asof.csv`
- `data/05_price_timeline_for_asof.csv`
- `data/06_union_sales_jan.csv`
- `data/07_union_sales_feb_variant.csv`
- `data/08_composite_left.csv`
- `data/09_composite_right.csv`

## ディレクトリ構成

```text
app.py                      # Streamlit エントリ
src/
  streamlit_app.py          # UI（セッション状態/サイドバー/プレビュー/結果表示）
  models.py                 # Recipe/JoinPlan/JoinStep などのデータモデル
  io_utils.py               # CSV/Excel読み込み
  source_loader.py          # file/sql/pi を統合ロード
  db_connectors.py          # SQL接続・テーブル一覧・SQL実行
  pi_af_sdk.py              # PI AF SDK 取得ロジック
  column_match.py           # union 列対応提案
  join_engine.py            # pandas 結合・asof・union
  join_report.py            # 品質指標/未マッチ抽出
  recipe.py                 # レシピJSON保存/読込/検証
  report.py                 # 出力・実行ログ
  normalization.py          # 列名正規化
  profile.py                # 型推定
  errors.py                 # 独自例外
tests/
  test_join_engine.py       # 結合系テスト
  test_source_loader.py     # ソース取得（SQLite）テスト
data/
  *.csv                     # 手動検証データ
logs/
  execution_log.jsonl       # 実行ログ
```

## Recipe JSON（主要項目）

- `version`, `created_at`
- `tables[]`
  - `table_id`, `table_name`, `source_kind`, `source_file_name`
  - `csv_options` / `excel_options`
  - `source_options`（SQL/PI設定）
  - `normalize_columns`, `selected_columns`, `dtype_overrides`
- `join_plan`
- `output_settings`
- `ui_settings`

## 制限事項

- PI AF SDK は実行環境に `pythonnet` と `OSIsoft.AFSDK` が必要
- SQL接続は各DBのドライバ・ネットワーク到達性に依存
- `asof join` は `left join` のみ対応
- `union` 列名推定はヒューリスティック（必要に応じて手動修正）
- pandasベースのため大規模データではメモリ制約あり

## 例外処理

- 文字コード不一致、列欠落、キー未設定、SQL接続失敗、PI取得失敗などを UI に表示
- 詳細トレースバックは折りたたみ表示
- 例外は握りつぶさず、原因を特定しやすいメッセージを返します

## テスト

```bash
pytest -q
```

## ライセンス

MIT License

Copyright (c) 2026 Yamamoto Yota
