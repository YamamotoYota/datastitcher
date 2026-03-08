# DataStitcher

DataStitcher は、複数データソースをローカルで読み込み、  
`結合（Join）`・`時系列近傍結合（asof）`・`縦連結（union）` を実行して  
CSV / Excel（1シート）に出力する Streamlit アプリです。

## 1. できること

- ファイル入力: `CSV`, `XLSX`, `XLS`, `XLSM`
- SQL入力: SQL Server / MySQL / SQLite / Oracle / PostgreSQL
- PI入力（PI AF SDK）:
  - PI DAタグ: Snapshot / Recorded / Interpolated / Summary
  - PI AF属性: エレメント + 属性
  - PI AFイベントフレーム: テンプレート + 期間 + 分析名
- 多段処理:
  - equi join（inner / left / right / outer）
  - asof join（backward / forward / nearest）
  - union（列名推定 + 手動修正）
  - 右テーブル事前集約付き join（1対多/多対多対応）
    - 加重平均 / 重み付き合計 / 合計 / 平均 / 最小 / 最大 / 件数 / 先頭 / 末尾
    - 数式（四則演算）での集約値算出
- 品質指標:
  - 行数推移、マッチ率、未マッチ件数、多重マッチ兆候
- 出力:
  - CSV / Excel（1シート）
- 再現性:
  - レシピJSON保存・再適用
  - 実行ログ保存

## 2. クイックスタート

前提:
- Windows
- Python 3.11+
- SQL / PI を使う場合は各クライアントドライバを事前インストール

```bash
pip install -r requirements.txt
streamlit run app.py
```

起動後:
- ブラウザで `http://localhost:8501` を開く

## 3. 基本操作

1. サイドバーで入力テーブルを追加
- ファイルはアップロード
- SQL / PI は「外部データソース追加」から追加

2. 「入力テーブル」で各テーブルを設定
- 共通: 列名正規化、使用列、型上書き
- ソース別: CSV/Excel設定、SQL接続情報、PI取得条件

3. サイドバーで結合手順を作成
- 手順ごとに `join` / `union` を選択
- join の場合は `equi` / `asof` を選択
- 必要に応じて `equi` で「右テーブルを事前集約してから結合」を有効化

4. 「処理を実行」

5. 結果・品質指標を確認してダウンロード

## 4. レシピとログ

- レシピ:
  - 現在設定を JSON 出力
  - JSON 読み込みで設定を復元
- 実行ログ:
  - `logs/execution_log.jsonl` に保存
  - 入力情報・ステップ指標・最終形状を記録

## 5. テスト

```bash
pytest -q
```

現在のテスト対象:
- join / asof / union の主要挙動
- SQL ソースロード（SQLite）
- PI 設定の正規化
- ソース定義（既定値/表示名）

## 6. 実行ファイル化（PyInstaller）

```powershell
.\build_exe.ps1
```

出力:
- `dist\DataStitcher\DataStitcher.exe`

## 7. ディレクトリ構成

```text
app.py
src/
  streamlit_app.py      # UI
  source_catalog.py     # ソース種別定義・既定値
  source_loader.py      # file/sql/pi の統合ロード
  db_connectors.py      # SQL 接続
  pi_af_sdk.py          # PI AF SDK 取得
  join_engine.py        # join/asof/union 実行
  join_report.py        # 品質指標
  join_plan.py          # 実行ファサード
  io_utils.py           # CSV/Excel I/O
  models.py             # データモデル
  recipe.py             # レシピJSON
  report.py             # 出力・実行ログ
  column_match.py       # union 列推定
  normalization.py      # 列名正規化
  profile.py            # 型推定
  errors.py             # 独自例外
tests/
data/
logs/
```

## 8. 制限事項

- `asof join` は left join のみ対応
- union の列名推定はヒューリスティック（必要に応じて手修正）
- pandas ベースのため、大規模データではメモリ制約あり
- PI AF SDK の利用には `pythonnet` と AF SDK 実行環境が必要

## 9. ライセンス

MIT License  
Copyright (c) 2026 Yamamoto Yota
