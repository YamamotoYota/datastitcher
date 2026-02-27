# DataStitcher

複数の `CSV` / `Excel(.xlsx)` をローカルで読み込み、結合（横方向）・時系列近傍結合（`asof`）・縦連結（`union`）で統合し、`CSV` または `Excel(1シート)` に出力する Streamlit アプリです。

## セットアップ

前提:
- Windows（VS Code から実行想定）
- Python 3.11 以上

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 使い方

1. サイドバーから `CSV / XLSX` を複数アップロード
2. 各テーブルで設定
   - CSV: 文字コード / 区切り文字 / 引用符 / ヘッダ行
   - Excel: シート / ヘッダ行
   - 列名正規化
   - 使用列選択
   - 型上書き（文字 / 数値 / 日時）
3. サイドバー「結合・縦連結の手順」で手順追加
4. 各手順で「結合（横方向）」または「縦連結（Union）」を選択
   - 結合の場合: `equi` または `asof`
   - 縦連結の場合: 列名推定結果を確認し、必要に応じて修正
5. 「処理を実行」
6. 最終結果プレビュー / 手順品質指標 / 未マッチ抽出 / ダウンロードを確認

補足:
- サイドバー「アプリ停止」から Web 画面上でサーバー停止が可能です。
- 停止後は `streamlit run app.py` を再実行すると再開できます。

## 実装済み機能

### 入力 / テーブル管理
- 複数ファイルアップロード（CSV/XLSX混在）
- Excelシート選択 / ヘッダ行指定
- CSV文字コード・区切り文字・引用符の `auto` 推定 + 手動指定
- テーブル名編集
- 使用列選択
- 列名正規化（前後空白除去 + NFKC）
- 型推定表示 + 型上書き（文字 / 数値 / 日時）

### 結合 / 時系列近傍結合 / 縦連結
- 多段手順実行（ベーステーブル → 手順1 → 手順2 ...）
- 等値結合: `Inner / Left / Right / Full outer`
- 単一キー / 複合キー
- 同名列衝突ポリシー: `left_prefer / right_prefer / keep_both`
- 時系列近傍結合（`asof join`）
  - 方向: `backward / forward / nearest`
  - 許容幅（例: `5min`, `1D`, `10`）
  - byキー（任意、左右別列名対応）
- 縦連結（`union`）
  - 列名の近似推定（自動提案）
  - ユーザによる列対応修正
  - 新規列として保持 / 除外 を選択可能
  - 出典列追加（任意）

### 品質指標 / 出力 / 再現性
- 各手順の品質指標
  - 入力行数 / 出力行数
  - マッチ行数 / 未マッチ行数（結合・asof）
  - マッチ率
  - 多重マッチ兆候（等値結合）
  - 行数増加警告
- 左未マッチ / 右未マッチのCSVダウンロード（結合・asof）
- 最終結果のCSV / Excel(1シート) ダウンロード
- Excel行数上限警告
- レシピ JSON 保存 / 読み込み
- 実行ログ保存（`logs/execution_log.jsonl`）

## テスト用データ

`data/` 配下に UI 動作確認用のCSVを同梱しています。

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
- `data/README.md`（推奨の確認手順）

## アーキテクチャ / ディレクトリ構成

```text
app.py                      # Streamlit エントリ
src/
  streamlit_app.py          # UI（session_state / サイドバー / プレビュー / 結果表示）
  models.py                 # Recipe / JoinStep / JoinPlan / report のデータクラス
  io_utils.py               # CSV/Excel読み込み、CSV自動判定、テーブル前処理
  normalization.py          # 列名正規化ヘルパー
  profile.py                # プロファイル / 型推定
  column_match.py           # 縦連結向け列対応提案ロジック
  join_engine.py            # pandas 実行エンジン（等値結合 / asof / 縦連結）
  join_plan.py              # 手順実行ファサード
  join_report.py            # 品質指標計算 + 未マッチ抽出
  recipe.py                 # Recipe JSON 保存/読込/検証
  report.py                 # CSV/Excel出力 + 実行ログ
  errors.py                 # 独自例外
requirements.txt
tests/
  test_join_engine.py       # 結合 / asof / 縦連結 / レシピの単体テスト
logs/
  execution_log.jsonl       # 実行ログ（実行時に生成）
data/
  *.csv                     # 手動確認用データ
```

## Recipe JSON 仕様（主要項目）

トップレベル:
- `version`
- `created_at`
- `tables[]`
- `join_plan`
- `output_settings`
- `ui_settings`

`join_plan.steps[]` の主要項目:
- 共通
  - `step_id`
  - `right_table_id`
  - `operation` (`join|union`)
- 結合（equi）
  - `join_algorithm` = `equi`
  - `join_type` (`inner|left|right|outer`)
  - `left_keys[]`, `right_keys[]`
  - `conflict_policy`, `suffixes`
- 時系列近傍結合（asof）
  - `join_algorithm` = `asof`
  - `join_type` = `left`（現状）
  - `left_keys[]`, `right_keys[]`（各1列）
  - `left_by_keys[]`, `right_by_keys[]`
  - `asof_direction`, `asof_tolerance`, `asof_allow_exact_matches`
  - `conflict_policy`, `suffixes`
- 縦連結（union）
  - `union_column_mapping`（右列 -> 左列 / special action）
  - `union_right_column_suffix`
  - `union_add_source_column`
  - `union_source_column_name`
  - `union_source_value`

## 制限事項（現状）

- `asof join` は `left join` のみ対応
- `union` の列名推定はヒューリスティック（誤推定時はUIで修正が必要）
- `fuzzy join` / `range join` / `cross join` は未実装
- `xls` は未対応（`xlsx` のみ）
- pandas ベースのため、大規模データではメモリ制約あり
- CSV自動推定はベストエフォート（誤判定時は手動指定）

## 例外処理

- 文字コード不一致、列欠落、キー未設定、シート名不正、asofキー型不正などは UI にエラー表示
- 詳細トレースバックは折りたたみ表示
- 例外は握りつぶさず、原因を特定しやすいメッセージを返す設計

## テスト

```bash
pytest -q
```

含まれるテスト:
- 複合キー等値結合 + 衝突解決
- Full outer join + 未マッチ抽出
- Recipe JSON roundtrip
- asof join（byキー + tolerance）
- union（列対応 + 新規列保持）

## ライセンス

MIT License

Copyright (c) 2026 Yamamoto Yota

## GitHub 公開手順（最小）

```bash
git init -b main
git add .
git commit -m "Initial release: DataStitcher"
git remote add origin <YOUR_GITHUB_REPO_URL>
git push -u origin main
```
