# apple-refurb-watch

Apple 整備済みストア (日本) を 1 分間隔で監視し、欲しい Mac が在庫に並んだ瞬間に **GitHub Issue を作成 → iPhone の GitHub Mobile アプリにプッシュ通知** を飛ばすシステム。

## 監視対象

| カテゴリ | 条件 |
|----------|------|
| **Mac Studio** | 全モデル (128GB 以上は ⭐ 強調) |
| **Mac mini**   | 全モデル |
| **MacBook Pro** | **メモリ 128GB のモデルのみ** |

## 仕組み

```
GitHub Actions (cron: */15 * * * *)
  └─ check.py を起動 (1ジョブ約30秒)
       └─ Apple 整備済みストアを並列スクレイピング
            - https://www.apple.com/jp/shop/refurbished/mac
            - ?f=macstudio / ?f=macmini / ?f=macbookpro (フォールバック)
       └─ state/known_products.json と差分比較
       └─ 新着があれば → gh issue create で Issue 作成
       └─ state.json を git commit & push
                 └─ GitHub Mobile に通知 → iPhone のロック画面表示 (数秒以内)
```

- **15 分間隔**で実行。Private リポジトリの無料枠 (月 2000 分) に収まる。
- 1 ジョブ約 30 秒 × 4 回/時 × 24h × 30日 = 約 1,440 分/月。
- 検出から通知まで **最大 15-20 分** の遅延の可能性あり。
- より低遅延が必要な場合は Public リポジトリにして cron を `*/5 * * * *` に変更 (無料無制限)。

## セットアップ手順

### 1. GitHub に Public リポジトリを作成

```bash
cd /Users/R/claudecode/apple-refurb-watch

git init -b main
git add .
git commit -m "init: apple refurbished watcher"

# GitHub で新規リポジトリ "apple-refurb-watch" を作成 (Public)
git remote add origin git@github.com:<あなたのユーザー名>/apple-refurb-watch.git
git push -u origin main
```

### 2. Actions の設定

リポジトリの **Settings → Actions → General**:

- **Workflow permissions** を `Read and write permissions` に変更
- **Allow GitHub Actions to create and approve pull requests** にチェック (不要だが念の為)

`Settings → Actions → Workflows` で `Watch Apple Refurbished Store` が表示されることを確認。

### 3. ラベル作成 (任意)

```bash
gh label create refurb-new --color "00ff00" --description "Apple refurb new arrival"
```

なくても動く (フォールバックでラベルなし Issue を作成)。

### 4. iPhone 側のセットアップ

1. App Store から **GitHub** アプリ (公式) をインストール
2. 自分のアカウントでサインイン
3. **Settings → Notifications → Enable Push Notifications** をオンに
4. リポジトリページ → **Watch → Custom → Issues** にチェック

これで Issue が作られた瞬間、iPhone のロック画面に通知が飛んでくる。タップで Apple の商品ページに直接ジャンプ。

### 5. 動作テスト

```bash
# Actions の "Run workflow" ボタンから手動実行
gh workflow run watch.yml --field iterations=1 --field interval=1

# 完了を待ってログ確認
gh run list --workflow watch.yml --limit 1
gh run view --log $(gh run list --workflow watch.yml --limit 1 --json databaseId --jq '.[0].databaseId')
```

ログに `watched=0 known=0 new=0` のような出力が出れば正常。今は Mac Studio/mini/MBP 128GB が在庫切れなので、新着が出るまで Issue は作られない。

## ローカル動作確認

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# GITHUB_REPOSITORY 未設定なら dry-run (Issue 作成しない)
CHECK_ITERATIONS=1 CHECK_INTERVAL_SEC=1 python scripts/check.py
```

## カスタマイズ

### 監視ルールを変更したい

`scripts/parser.py` の `is_watched()` を編集する。例えば「MacBook Pro 64GB 以上を監視」にしたいなら:

```python
def is_watched(product: Product) -> bool:
    if product.category not in WATCHED_CATEGORIES:
        return False
    if product.category == "macbookpro":
        return normalize_memory_gb(product.memory) >= 64  # 128 → 64
    return True
```

### 通知が頻繁すぎる場合

`scripts/check.py` の `CHECK_INTERVAL_SEC` を 120 などに増やす。または cron を `*/10 * * * *` に変更。

## ファイル構成

```
apple-refurb-watch/
├── .github/workflows/watch.yml   # 5分cron で check.py を起動
├── scripts/
│   ├── parser.py                 # HTML → 商品リスト (tiles配列を抽出)
│   └── check.py                  # 並列fetch + 差分検出 + Issue作成 + 状態保存
├── state/
│   └── known_products.json       # 既知のpartNumber一覧 (Actionsが自動コミット)
├── requirements.txt              # aiohttp, certifi
├── .gitignore
└── README.md
```

## 検出ロジックの詳細

1. Apple の整備済みストア HTML 内の `"tiles":[...]` 配列を抽出
2. 各商品から `partNumber`, `title`, `currentPrice`, `refurbClearModel`, `tsMemorySize` 等を取り出す
3. 監視ルール (上記) に合致する商品の `partNumber` セットを作成
4. `state/known_products.json` の `known_part_numbers` と差分計算 → 新規 partNumber を抽出
5. 新規があれば `gh issue create` で Issue 作成
6. 全ての current partNumber を `known_part_numbers` に union → state を commit & push

商品の「消失」(売り切れ) は通知しない。気にする場合は state から定期的に消失分を除外するロジックを足せる。

## トラブルシューティング

- **何も通知が来ない** → 監視対象の在庫がそもそもゼロの可能性が高い。Actions のログで `total=22 watched=0` を確認。
- **`gh issue create` がエラー** → Settings → Actions の Workflow permissions が Read only になっていないか確認。
- **Actions が動かない** → Public リポジトリか確認 (Private だと無料分 2000 分で枯渇)。Settings → Actions → Workflows で workflow が有効化されているか確認。
- **重複通知** → state.json が commit されていない可能性。Actions ログの「Commit state changes」ステップを確認。
