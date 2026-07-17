# X運用 自動分析システム 計画書

「自分の過去ポスト分析 → 界隈の伸びポスト分析 → 勝ちパターンのmd資産化」を、
モデルの使い分け（司令塔=Fable5 / 重い分析=Opus / 整形=Sonnet / X検索=Grok via Codex）で
自動で回す仕組みの設計書。

---

## 1. 全体像

```
┌──────────────────────────────────────────────────────┐
│ GitHub Actions (週1 cron / 手動実行)                  │
│                                                      │
│  Phase 0  整形         Sonnet      own_posts_raw.txt │
│     │                              → own_posts.md    │
│  Phase 1  Grok検索     Codex CLI   界隈の伸びポスト   │
│     │                  + xAI API   → niche_posts.json│
│  Phase 2  重い分析     Opus        自分×界隈を比較    │
│     │                              → reports/*.md    │
│  Phase 3  資産化       Opus        勝ちパターン抽出   │
│     │                              → playbook/*.md   │
│  Phase 4  次の一手     Sonnet      タイトル案5本      │
│     │                              → reports/*.md    │
│  └─ git commit & push → GitHub Mobile に通知          │
└──────────────────────────────────────────────────────┘
```

司令塔（このリポジトリの設計・改修・プロンプト調整）は Fable5 が担当し、
定常運転は上記の安いモデルだけで回る。**Fable5 の上限を定常運転で溶かさない**のが設計方針。

## 2. モデル分担

| 役割 | 担当 | 理由 |
|------|------|------|
| 司令塔（設計・改修・skill化） | Fable5 | 大量データの構造抽出と設計が得意。定常運転には使わない |
| 重い分析（Phase 2, 3） | Claude Opus (`claude-opus-4-8`) | 比較分析・パターン抽出の品質が必要 |
| 整形・タイトル案（Phase 0, 4） | Claude Sonnet (`claude-sonnet-5`) | コピペ整形・量産系は安いモデルで十分 |
| X検索（Phase 1） | **Codex アプリ (`codex exec`) + xAI Grok API (Live Search)** | Grok は X の公開ポストを公式に検索できる唯一のAPI。実行と品質チェックを Codex に委任 |

モデルIDは `config.yml` で差し替え可能。

## 3. Grok検索を Codex に任せる方法（Phase 1）

スクレイピングは規約違反・凍結リスクがあるため**使わない**。代わりに:

1. `scripts/grok_search.py` が xAI API (`api.x.ai`) の **Live Search（sources: x）** を叩き、
   `config.yml` のテーマ・お手本アカウント・期間で公開ポストを検索する
2. `codex exec --full-auto "$(cat codex/grok_search_task.md)"` で Codex アプリに
   「スクリプト実行 → 出力JSONの検証（URL実在・重複除去・捏造チェック） → 保存」を委任する
3. 結果は `data/niche_posts.json`（タイトル / 冒頭 / 数字 / URL / 確認ステータス）に正規化

Codex 側のルール（`codex/grok_search_task.md` に記載済み）:
- URLが確認できないポストは `"verified": false` を付け、分析から除外
- 1件も取れなければ**捏造せず**「対象ポストを手で貼ってください」とレポートに書く

## 4. ディレクトリ構成

```
x-analysis/
├── PLAN.md                     # 本書
├── config.yml                  # ジャンル・お手本アカウント・モデルID
├── prompts/
│   ├── 01_format_posts.md      # アナリティクス生データ → 一覧表 (Sonnet)
│   ├── 02_analyze_own.md       # 自分の記事の辛口分析 (Opus)
│   ├── 03_analyze_niche.md     # 界隈の勝ちパターン分析 (Opus)
│   ├── 04_cross_genre.md       # ジャンル外バズの構造分析・応用 (Opus)
│   └── 05_update_playbook.md   # 分析結果 → playbook への追記提案 (Opus)
├── codex/
│   └── grok_search_task.md     # Codex に渡す Grok検索タスク
├── scripts/
│   ├── grok_search.py          # xAI Live Search 呼び出し + JSON正規化
│   └── run_pipeline.sh         # Phase 0〜4 のオーケストレーター
├── playbook/
│   └── x_win_patterns.md       # 勝ちパターン資産 (5法則を初期シード)
├── data/
│   ├── own_posts_raw.txt       # ← 自分でXアナリティクスから貼る (唯一の手作業)
│   ├── own_posts.md            # Phase 0 の出力
│   └── niche_posts.json        # Phase 1 の出力
└── reports/
    └── YYYY-MM-DD_analysis.md  # 毎回の分析レポート
```

## 5. 必要なシークレット（GitHub Settings → Secrets → Actions）

| シークレット | 用途 | 必須 |
|--------------|------|------|
| `ANTHROPIC_API_KEY` | Claude CLI (Opus/Sonnet) | ✅ |
| `XAI_API_KEY` | Grok Live Search | Phase 1 に必要（無ければ自動スキップ） |
| `OPENAI_API_KEY` | Codex CLI | Phase 1 に必要（無ければ grok_search.py を直接実行にフォールバック） |

## 6. 運用ループ

```
① data/own_posts_raw.txt にXアナリティクスをコピペ（週1、3分）
② あとは cron が勝手に回す:
   分析 → reports/ にレポート → playbook/ に勝ちパターン追記
③ レポートのタイトル案から選んで書く → 出す → 数字が出たら①へ
```

**人間の仕事は①と「書いて出す」だけ。** 分析・比較・資産化は全部自動。

## 7. 記事の「よくある失敗3つ」への対策（設計に組込済み）

| 失敗 | 対策 |
|------|------|
| ① 数字を捏造させる | 自分の実数は `own_posts_raw.txt` 必須（無ければ Phase 2 を中断）。界隈データはURL検証必須、未確認は除外 |
| ② 出して終わり | レポートに毎回「セルフ引用文案 2本」「CTA改善案」を含める（prompts/05） |
| ③ 全部Fableで上限溶かす | 定常運転は Opus/Sonnet/Grok のみ。Fable5 は設計変更時だけ |

## 8. ロードマップ

- **v1（今回）**: 手貼りデータ + Grok検索 + 週1自動分析 + playbook自動追記
- **v2**: playbook が溜まったら Claude Code の **skill 化**（「いつもの型で書いて」で発動）
- **v3**: ポスト下書きの自動生成（playbook準拠のタイトル3案+親ポスト案を毎レポートに同梱）
- **v4**: 投稿後の実数を取り込んで勝敗判定 → playbook の各パターンに勝率を記録

## 9. 注意事項

- xAI Live Search は検索ソース数に応じた従量課金（無料ではない）。`max_search_results` で上限制御
- X の自動投稿・自動スクレイピングは行わない（凍結リスク）。投稿は必ず人間が行う
- 旬ワード（法則5）は鮮度が命なので、cron 週1に加えて `workflow_dispatch` で即時手動実行できる
