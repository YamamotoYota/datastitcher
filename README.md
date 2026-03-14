# DataStitcher

DataStitcher は、複数のデータソースをローカルで読み込み、横方向の結合と縦方向の連結に特化して統合する Windows 向けローカル Web アプリです。  
CSV / Excel / SQL / PI データを 1 つのテーブルにまとめ、CSV または Excel（1 シート）で出力できます。

## 想定実行環境

このリポジトリは、以下の環境を前提にしています。

- OS: Windows
- Python バージョン: 3.11 以上
- 仮想環境: `venv` / `conda` のどちらでも可
- アプリ依存ライブラリ: `pip install -r requirements.txt`
- ビルド依存ライブラリ: `pip install -r requirements-build.txt`

SQL や PI を使う場合は、別途ドライバや PI AF Client / AF SDK が必要です。

## セットアップ

### 1. 仮想環境を用意

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

`conda` を使う場合は、以下でも構いません。

```powershell
conda create -n datastitcher python=3.11
conda activate datastitcher
```

### 2. 依存ライブラリを導入

```powershell
pip install -r requirements.txt
```

## アプリの起動

```powershell
python -m streamlit run app.py
```

起動後はブラウザで `http://localhost:8501` を開きます。

## 実行ファイルの作成

### 標準手順

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

`build_exe.ps1` は次のどちらでも動くようにしてあります。

- `-PythonExe` で明示指定した Python から実行
- アクティブな `venv` / `conda` 環境の `python` から実行
- `python` または `py -3` が利用できる状態で実行
- `conda` コマンドが利用できる場合は `conda run -n datastitcher` にフォールバック

また、現在のカレントディレクトリに依存せず、スクリプト配置フォルダを基準にビルドします。

このスクリプトは以下を行います。

1. 利用可能な Python 3.11 以上を解決
2. アプリ依存が入っているかを確認
3. `requirements-build.txt` に基づいて build 依存を導入
4. `DataStitcher.spec` を使ってビルド
5. `dist\DataStitcher` 配下の実行ファイル一式を更新

ビルドに使う Python を明示したい場合:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1 -PythonExe C:\path\to\python.exe
```

### 直接 PyInstaller を使う場合

```powershell
pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean .\DataStitcher.spec
```

### 生成物

- 実行ファイル: `dist\DataStitcher\DataStitcher.exe`
- 配布に必要な一式: `dist\DataStitcher\`

注意:

- `DataStitcher.exe` 単体ではなく、`dist\DataStitcher` フォルダごと配布してください
- 実行ファイル起動時は内部で Streamlit サーバーを立ち上げます
- 実行ファイル起動時は既定ブラウザを自動で開きます
- 既定ポート `8501` が使用中の場合は、空いている次のポートへ自動で切り替えます
- 初回起動時は Windows Defender の確認が表示される場合があります

## 主な機能

### 入力ソース

- CSV
- Excel（`.xlsx`, `.xls`, `.xlsm`）
- SQL Server / MySQL / SQLite / Oracle / PostgreSQL
- PI DA タグ
- PI AF 属性
- PI AF イベントフレーム

### データ統合

- `join`
  - `inner`
  - `left`
  - `right`
  - `outer`
- `asof join`
  - `backward`
  - `forward`
  - `nearest`
- `union`

### 補助機能

- 複合キー
- 列名正規化
- 型推定 / 型上書き
- 同名列衝突ルール
- 未マッチ抽出
- レシピ JSON 保存 / 読み込み
- 実行ログ保存

### 1対多 / 多対多向けの右テーブル事前集約

右テーブルを集約してから結合できます。製品ロットと原料ロットのようなデータで、原料の仕込み量を重みにした加重平均を計算してから製品ロットに結合する用途を想定しています。

利用できる集約方式:

- `first`
- `last`
- `sum`
- `mean`
- `min`
- `max`
- `count`
- `weighted_sum`
- `weighted_mean`
- `formula`

`formula` では次の変数を利用できます。

- `sum_v`
- `mean_v`
- `min_v`
- `max_v`
- `count_v`
- `sum_w`
- `mean_w`
- `sum_vw`

例:

```text
sum_vw / sum_w
```

## 基本的な使い方

1. サイドバー最上部のアプリ停止ボタンの位置を確認
2. 入力テーブルを追加
3. 各テーブルで列名正規化、使用列、型を調整
4. 結合手順を追加
5. 手順ごとに `join` / `asof join` / `union` を設定
6. 必要に応じて右テーブル事前集約を設定
7. 実行して品質指標を確認
8. 最終結果を CSV または Excel で保存

`data\README.md` にテスト用データの確認手順を記載しています。

## 品質指標

各ステップで以下を表示します。

- 左入力行数 / 右入力行数 / 出力行数
- 左右マッチ率
- 左右未マッチ行数
- 多重マッチの兆候
- 行数急増警告
- 未マッチ行の CSV ダウンロード

## レシピとログ

### レシピ

- 現在の設定を JSON で保存
- 後で再読み込みして同じ処理を再実行

### 実行ログ

- 保存先: `logs\execution_log.jsonl`
- 記録内容:
  - 入力情報
  - ステップごとの品質指標
  - 最終行数 / 列数

## テスト

```powershell
pytest -q
```

現在のテスト対象:

- 通常 join
- asof join
- union
- 右テーブル事前集約
- SQL ソース読み込み
- PI 設定正規化
- PyInstaller 用ビルド補助

## ディレクトリ構成

```text
app.py
build_exe.ps1
requirements-build.txt
DataStitcher.spec
launcher_datastitcher.py
src/
  build_support.py
  column_match.py
  db_connectors.py
  errors.py
  io_utils.py
  join_engine.py
  join_plan.py
  join_report.py
  models.py
  normalization.py
  pi_af_sdk.py
  profile.py
  recipe.py
  report.py
  right_aggregation.py
  source_catalog.py
  source_loader.py
  streamlit_app.py
tests/
  conftest.py
data/
dist/
logs/
```

## 制限事項

- `asof join` は `left join` のみ対応
- union の列対応推定はヒューリスティック
- pandas ベースのため、大規模データではメモリ制約があります
- PI AF SDK は実行環境依存です
- fuzzy join / range join / cross join は未実装です

## トラブルシュート

### 文字化けする

- CSV の文字コードを `utf-8-sig` や `cp932` に切り替えて再確認してください

### Excel の列名がずれる

- ヘッダ行番号を確認してください

### SQL に接続できない

- ドライバ
- 接続先ホスト
- ポート
- 認証情報

を確認してください。

### PI データを取得できない

- PI AF Client / AF SDK
- `pythonnet`
- サーバー名
- データベース名
- エレメント名
- 属性名

を確認してください。

### 実行ファイルを起動できない

- `dist\DataStitcher` フォルダ一式が揃っているか確認してください
- `DataStitcher.exe` を単体で移動していないか確認してください
- アクセス先は通常 `http://localhost:8501` です。`8501` が使用中なら `8502`, `8503` のように自動で空きポートへ切り替わります
- ビルドし直す場合は、必要に応じて `build_exe.ps1 -PythonExe <python.exe>` で使用 Python を明示してください
- `http://localhost:3000` が表示される場合は古い実行ファイルです。最新版で `build_exe.ps1` を実行して `dist\DataStitcher` を作り直してください
- 実行ログに `Serving static content from the Node dev server` と出る場合も同様に古い実行ファイルです

## ライセンス

MIT License  
Copyright (c) 2026 Yamamoto Yota
