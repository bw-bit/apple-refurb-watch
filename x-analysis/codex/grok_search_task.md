# Codex タスク: Grok検索でX界隈の伸びポストを収集する

あなた（Codex）の仕事は、Grok の Live Search を使って界隈の伸びポストを集め、
検証済みJSONとして保存することです。作業ディレクトリは `x-analysis/` です。

## 手順

1. `config.yml` を読み、テーマ・お手本アカウント・期間・件数上限を確認する
2. `python3 scripts/grok_search.py` を実行する（環境変数 `XAI_API_KEY` が必要）
3. 出力された `data/niche_posts.json` を検証する:
   - 各エントリに `url` があるか。`https://x.com/` 形式でないものは `"verified": false` にする
   - 同一URL・ほぼ同一本文の重複を除去する
   - エンゲージメント数値が明らかに不自然（捏造っぽい丸数字の羅列など）なら `"verified": false` にする
4. 検証後のJSONを `data/niche_posts.json` に上書き保存する
5. `data/niche_posts_report.md` に結果サマリを書く:
   - 収集件数 / verified件数 / 除外件数と理由

## 厳守ルール

- **存在しないポスト・数字を絶対に作らない。** 1件も取れなかった場合は、
  `data/niche_posts.json` を `{"posts": [], "note": "取得できず。対象ポストを手で貼ってください"}` にして正直に報告する
- X へのログイン・スクレイピング・bot操作は行わない。使ってよいのは xAI API 経由の検索だけ
- `XAI_API_KEY` が無い場合はスクリプトを実行せず、その旨をレポートに書いて終了する
