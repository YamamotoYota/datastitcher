# DataStitcher

DataStitcher は、複数のデータソースをローカルで読み込み、結合と縦連結に特化して統合する Windows 向けのローカル Web アプリです。  
Streamlit で動作し、CSV / Excel / SQL / PI データを 1 つのテーブルにまとめて、CSV または Excel（1 シート）として出力できます。

## 主な用途

- 複数の CSV / Excel をキーで結合したい
- SQL テーブルと Excel ファイルを横持ちで統合したい
- PI DA タグや PI AF 属性を取得して他テーブルと結合したい
- 列名が少し違う表同士を union したい
- 1 対多 / 多対多の関係を、重み付き集約してから結合したい

## 現在できること

- 入力ソース
  - CSV（UTF-8 / Shift-JIS 系を含む自動判定 + 手動指定）
  - Excel（`.xlsx`, `.xls`, `.xlsm`）
  - SQL Server / MySQL / SQLite / Oracle / PostgreSQL
  - PI DA タグ
  - PI AF 属性
  - PI AF イベントフレーム
- 結合方式
  - equi join: `inner`, `left`, `right`, `outer`
  - asof join: `backward`, `forward`, `nearest`
  - union
- 補助機能
  - 複合キー
  - 列名正規化
  - 型推定 / 型上書き
  - 同名列衝突ルール
  - 未マッチ抽出
  - レシピ JSON 保存 / 読み込み
  - 実行ログ保存
- 1 対多 / 多対多向けの右テーブル事前集約
  - `first`, `last`, `sum`, `mean`, `min`, `max`, `count`
  - `weighted_sum`, `weighted_mean`
  - 数式（四則演算）による集約

## 動作環境

- Windows
- Python 3.11 以上
- ローカル実行前提

追加で必要なもの:
- SQL を使う場合: 各 DB の接続ドライバ
- PI を使う場合: PI AF Client / AF SDK 実行環境

## セットアップ

```bash
pip install -r requirements.txt
streamlit run app.py
```

起動後:
- ブラウザで `http://localhost:8501` を開く

## 実行ファイルの起動

PyInstaller で作成した実行ファイルは `dist\DataStitcher\DataStitcher.exe` です。

注意:
- `DataStitcher.exe` 単体ではなく、`dist\DataStitcher` フォルダ一式が必要です
- 起動すると内部で Streamlit サーバーを立ち上げます
- 初回起動時はローカルポート利用や Windows Defender の確認が入る場合があります

## 使い方

1. サイドバー上部で必要ならアプリ停止機能を利用
2. 入力テーブルを追加
   - ファイルはアップロード
   - SQL / PI は「外部データソース追加」から追加
3. 各テーブルで読み込み設定を調整
   - 列名正規化
   - 使用列選択
   - 型上書き
   - CSV / Excel / SQL / PI の個別設定
4. 結合手順を追加
5. 各手順で `join` または `union` を設定
6. 必要に応じて asof や右テーブル事前集約を設定
7. 実行して結果を確認し、CSV / Excel をダウンロード

## 右テーブル事前集約付き join

製品ロットと原料ロットのように、左 1 件に対して右が複数件ぶら下がるケース向けの機能です。  
通常の join の前に右テーブルをグループ単位で集約し、その集約結果を左テーブルに結合します。

例:
- 左テーブル: 製品ロット `A`
- 右テーブル: 原料ロット `A-1`, `A-2`
- 重み列: `仕込み量`
- 集約対象列: `品質値`
- 集約方式: `weighted_mean`

この場合、`品質値` は `仕込み量` を重みとした加重平均に変換されてから製品ロット `A` に結合されます。

### 数式集約

集約方式に `formula` を選ぶと、列ごとに数式を指定できます。  
使用可能な変数:

- `sum_v`
- `mean_v`
- `min_v`
- `max_v`
- `count_v`
- `sum_w`
- `mean_w`
- `sum_vw`

使用可能な演算:
- `+`
- `-`
- `*`
- `/`
- 括弧

例:

```text
sum_vw / sum_w
```

## 品質指標

各ステップで以下を表示します。

- 左入力行数 / 右入力行数 / 出力行数
- 左右マッチ率
- 左右未マッチ行数
- 多重マッチの兆候
- 行数急増警告
- 未マッチ行の CSV ダウンロード

## レシピとログ

- レシピ
  - 現在の設定を JSON で保存
  - 後で再読み込みして同じ処理を再実行
- 実行ログ
  - `logs/execution_log.jsonl`
  - 入力情報、ステップ指標、最終行列数を記録

## テスト

```bash
pytest -q
```

現在のテスト対象:
- equi join
- asof join
- union
- 右テーブル事前集約
- SQL ソースロード
- PI 設定正規化
- ソース種別定義

## 実行ファイルの作成

使用環境:
- `C:\Users\yamam\miniforge3\envs\datastitcher\python.exe`

ビルド:

```powershell
.\build_exe.ps1
```

生成物:
- `dist\DataStitcher\DataStitcher.exe`
- `dist\DataStitcher\_internal\...`

## ディレクトリ構成

```text
app.py
build_exe.ps1
launcher_datastitcher.py
DataStitcher.spec
src/
  streamlit_app.py
  source_catalog.py
  source_loader.py
  db_connectors.py
  pi_af_sdk.py
  right_aggregation.py
  join_engine.py
  join_report.py
  join_plan.py
  io_utils.py
  models.py
  recipe.py
  report.py
  column_match.py
  normalization.py
  profile.py
  errors.py
tests/
data/
dist/
logs/
```

## 制限事項

- `asof join` は `left join` のみ対応
- union の列対応推定はヒューリスティック
- pandas ベースのため、大規模データではメモリ制約あり
- PI AF SDK は実行環境依存
- fuzzy join / range join / cross join は未実装

## トラブルシュート

- CSV の文字化け
  - 文字コードを `utf-8-sig` / `cp932` などに切り替えて確認
- Excel の列名がずれる
  - ヘッダ行番号を確認
- SQL 接続できない
  - ドライバ、接続先、認証情報、ポートを確認
- PI 取得に失敗する
  - AF SDK、`pythonnet`、サーバー名、DB 名、エレメント名、属性名を確認
- 実行ファイルが起動しない
  - `dist\DataStitcher` フォルダ一式が揃っているか確認

## ライセンス

MIT License  
Copyright (c) 2026 Yamamoto Yota
