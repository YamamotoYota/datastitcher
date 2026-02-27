# テストデータセット

## ファイル一覧
- `01_customers.csv`: 顧客マスタ（受注側に未マッチ顧客が1件入るように調整）
- `02_orders.csv`: 受注データ（`C005` は顧客マスタに存在しない）
- `03_payments.csv`: 入金データ（`O9999` は受注に存在しない）
- `04_events_for_asof.csv`: asof 結合の左テーブル（`event_time`）
- `05_price_timeline_for_asof.csv`: asof 結合の右テーブル（`rate_time`, `cust_id`）
- `06_union_sales_jan.csv`: 縦連結のベーステーブル
- `07_union_sales_feb_variant.csv`: 列名差分ありの縦連結対象（`cust_id/date/amt/sales_channel`）
- `08_composite_left.csv`, `09_composite_right.csv`: 複合キー結合の検証ペア

## 推奨の動作確認
1. 多段結合
   - ベース: `02_orders.csv`
   - 手順1: `01_customers.csv` を `customer_id` で left 結合
   - 手順2: `03_payments.csv` を `order_id` で left 結合
   - `C005` と `O9999` が未マッチ抽出されることを確認
2. asof 結合
   - ベース: `04_events_for_asof.csv`
   - 手順1: 種別=`join` + 方式=`asof`
   - 左キー=`event_time`, 右キー=`rate_time`
   - 左by=`customer_id`, 右by=`cust_id`
   - 方向=`backward`, 許容幅=`10min`
3. 縦連結
   - ベース: `06_union_sales_jan.csv`
   - 手順1: `07_union_sales_feb_variant.csv` を縦連結
   - 自動提案で `cust_id->customer_id`, `date->order_date`, `amt->amount` が候補になることを確認
   - `sales_channel` と `memo` を新規列保持または手動再対応で確認
