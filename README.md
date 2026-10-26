# おおさかeコレクション IIIFマニフェスト修正ツール

Ubuntu / Python 3.9以降。追加パッケージ不要です。
画像の取得・GitHubへの公開は行いません。

## 実行

ZIPを展開し、osaka_manifest_fix.py と urls.txt のあるフォルダで実行します。

```bash
python3 osaka_manifest_fix.py urls.txt
```

urls.txt はUTF-8で、1行に公式マニフェストURLを1件ずつ記載します。
空行、先頭が # のコメント、重複URLは無視します。
初期状態では「啓迪集 1」のURLを1件記載しています。

```text
https://da.library.pref.osaka.jp/api/items/01-0024654/manifest.json
```

## 出力

- output/manifests/01-0024654.json : 修正後のマニフェスト
- output/originals/01-0024654.json : 取得した元データ（JSONとして再整形）
- output/reports/01-0024654.json : 取得日時、修正前後、出力の整合性確認用スナップショット
- output/errors.jsonl : エラー履歴（追記）

パスは実行時のカレントディレクトリ基準です。完了済みで整合性が確認できた出力は再取得しません。
失敗した資料は次回再試行します。元サイトの更新を反映するには次を実行します。

```bash
python3 osaka_manifest_fix.py urls.txt --refresh
python3 osaka_manifest_fix.py urls.txt --output result
```

## 修正内容

大阪府立図書館の IIIF Presentation API v3 に対応します。
既知の誤った body.id が、同じ画像の service URLと対応するときだけ修正します。

```text
修正前: https://da.library.pref.osaka.jp/api/items/01-0024654/contents/画像ID.jp2/full/full/0/default.jpg
修正後: https://da.library.pref.osaka.jp/api/contents/画像ID.jp2/full/full/0/default.jpg
```

body.service は一切変更しません。タイル配信・拡大表示は保持されます。
既存の書誌情報、帰属表示、ページ順、寸法、Manifest / Canvas / Annotation のIDも保持します。
修正がある資料には metadata に「非公式修正版の情報」と元URLを追加します。
すでに正常な資料は変更せず出力し、修正版とは表示しません。
未知のURL・画像構造では、部分的に修正した資料を出力せずエラーとして記録します。
過去に成功したファイルがある場合、再取得失敗時もそのファイルは残ります。

既存IDを保持するローカル修正版です。別URLで公開するためのID変更は行いません。
元データ・画像の再利用条件は提供元の案内を確認してください。
本ツールの配布は元データや画像の利用許諾を付与するものではありません。

## 通信

逐次取得、通信間隔は5〜10秒のランダム待機。最大3回（初回を含む）。
429および一部のサーバーエラーを再試行し、Retry-Afterがある場合は優先します。
画像やinfo.jsonにはアクセスしません。JSON構造と既知のURL対応を検証するツールです。
Ctrl+Cで停止し、同じコマンドで再開できます。同じ出力先での同時実行は避けてください。
エラーがあれば終了コード1、すべて成功・スキップなら0です。

## 検証

添付された「啓迪集 1」のマニフェスト（92 Canvas）で、92画像URLの修正、
service・既存情報の保持、再修正で変更が増えないこと、未知URLの拒否を確認しています。

## ライセンス

MITライセンスの適用対象は本リポジトリのスクリプトです。大阪府立図書館が提供するマニフェスト、メタデータおよび画像の利用条件を変更するものではありません。
