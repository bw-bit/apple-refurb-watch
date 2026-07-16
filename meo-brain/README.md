# MEOブレイン - 無料MEO診断ツール(ブレインシリーズ)

店舗のGoogleビジネスプロフィール(GBP)を **19項目・100点満点で自動診断** し、改善の優先順位と30日アクションプランをその場で提示する、リード獲得用の無料Webツールです。

**狙い:** 「無料診断」をフックに見込み客の課題を可視化 → 診断結果の改善を「MEO保守・運用代行・サイト制作」として受注する導線を作る。

---

## 構成

```
meo-brain/
├── index.html          # ツール本体(1ファイル完結。これを法人ドメインに置くだけで公開できる)
├── worker/
│   ├── worker.js       # AI診断・営業メール生成・順位チェック用API (Cloudflare Worker)
│   └── wrangler.toml   # Workerのデプロイ設定
└── README.md
```

### 機能一覧

| 機能 | 必要なもの | 説明 |
|---|---|---|
| 19項目の自動診断・スコアリング | **なし(HTML単体で動作)** | 5カテゴリ(基本情報/口コミ/写真・投稿/Web連携/活用度)を100点満点で採点。レーダーチャート・優先改善アクション・30日プランを自動生成 |
| レポート印刷 / PDF保存 | なし | 診断結果をそのまま提案資料として印刷可能 |
| 順位チェック(手動リンク) | なし | 対策キーワードのGoogleマップ検索リンクを自動生成 |
| 🤖 AI詳細診断レポート | Worker + Claude APIキー | 店舗専用の改善レポート(投稿文例・口コミ返信例つき)をAIが生成 |
| 🔍 順位チェック(自動) | Worker + Google Maps APIキー | Places APIで上位20件を取得し、自店の順位を判定 |
| 💼 営業メール自動作成(社内用) | Worker + Claude APIキー | `?mode=sales` 付きでアクセスすると表示。診断結果から初回アプローチメールをAIが作成 |

**重要:** AI機能・自動順位チェックが未設定でも、診断ツールとしては完全に動作します。まず `index.html` だけ公開して、後からAPIを足す運用でOKです。

---

## セットアップ

### STEP 1: `index.html` の設定を書き換える

ファイル冒頭の `CONFIG` を自社情報に変更します。

```js
const CONFIG = {
  companyName : "株式会社〇〇",             // CTA・フッターに表示
  tel         : "03-XXXX-XXXX",
  contactUrl  : "https://example.co.jp/contact/",  // 問い合わせフォームURL
  services    : ["MEO対策・運用代行", "GBP保守", "ホームページ制作", "口コミ獲得支援"],
  apiEndpoint : "",   // STEP 3 のWorker URL。空ならAI機能は自動的に非表示
};
```

### STEP 2: 法人ドメインにアップロード

`index.html` をサーバーの好きな場所に置くだけです。

```
例: https://example.co.jp/meo-brain/index.html
→ https://example.co.jp/meo-brain/ でアクセス可能
```

- レンタルサーバー(エックスサーバー等): FTP/ファイルマネージャで `public_html/meo-brain/` にアップロード
- WordPressサイトの場合もサーバー直置きでOK(テーマに組み込む必要なし)
- 外部ライブラリ・CDNを一切使わない1ファイル構成なので、置くだけで動きます

### STEP 3: AI・順位チェックAPI(Cloudflare Worker)のデプロイ

無料枠(1日10万リクエスト)で十分運用できます。

```bash
cd meo-brain/worker
npm install -g wrangler
wrangler login

# APIキーを登録
wrangler secret put ANTHROPIC_API_KEY     # https://platform.claude.com で取得
wrangler secret put GOOGLE_MAPS_API_KEY   # Google Cloudで「Places API (New)」を有効化して取得

wrangler deploy
# → https://meo-brain-api.<yourname>.workers.dev が発行される
```

デプロイ後:

1. `wrangler.toml` の `ALLOWED_ORIGINS` を自社ドメインに変更して再デプロイ
   ```toml
   ALLOWED_ORIGINS = "https://example.co.jp,https://www.example.co.jp"
   ```
2. `index.html` の `apiEndpoint` にWorker URLを設定
   ```js
   apiEndpoint : "https://meo-brain-api.xxxx.workers.dev",
   ```

#### コストの目安

- **Claude API**: 1診断あたり入力1K+出力1.5Kトークン程度。`claude-opus-4-8`(既定)で約4〜6円/回。`CLAUDE_MODEL = "claude-haiku-4-5"` にすれば1円未満/回
- **Google Places API (New) Text Search**: 月間無料枠内で数千回程度は無料(SKUにより変動。Google Cloudの予算アラート設定を推奨)
- **Cloudflare Workers**: 無料枠で十分

---

## 営業での使い方(獲得プレイブック)

### ① インバウンド(サイト訪問者のリード化)

- 法人サイトのヘッダー/ブログ記事から「無料MEO診断」へ誘導
- 診断結果の最後に自社CTA(無料相談ボタン)が自動表示される
- 診断→「この改善、自分でやるのは大変」→ 保守・代行の相談、という自然な流れを作る

### ② アウトバウンド(こちらから営業をかける)

1. 見込み客の店舗情報で **自分が代わりに診断を実行** する(GBPは公開情報なので外から確認できる)
2. `?mode=sales` を付けてアクセスすると **営業メール自動作成** が使える
   ```
   https://example.co.jp/meo-brain/?mode=sales
   ```
3. 「🖨 レポートを印刷/PDF保存」で診断レポートをそのまま **提案書として持参/添付**
4. AIが作った初回メール+診断PDFのセットで送付 → 「無料で詳しくご説明します」でアポ化

### ③ 商談での使い方

- その場で競合店を診断して比較を見せる(「上位のA店は口コミ120件、御社は8件です」)
- 順位チェックで現状の圏外/圏内を見せてから、30日プランを「弊社が代行した場合」の提案に置き換える
- クロージングの受け皿: **MEO保守(月額)→ サイト制作(Web連携カテゴリの点数が低い店に刺さる)→ 口コミ獲得支援**

### 注意事項(コンプライアンス)

- 「必ず1位になります」等の成果保証はしない(ツール・AIの出力もそのように設計済み)
- 口コミの対価提供(割引と引き換えのレビュー依頼等)はGoogleガイドライン違反。提案しないこと
- 診断スコアは自己申告に基づく簡易診断である旨をフッターに明記済み

---

## カスタマイズ

- **診断項目の追加・重み変更**: `index.html` 内の `QUESTIONS` 配列(`w` が配点。カテゴリごとの合計が `CATEGORIES` の `max` と一致するように)
- **ランク基準の変更**: `rankOf()` 関数
- **AIレポートの文面・構成**: `worker/worker.js` の `DIAGNOSE_SYSTEM` / `SALES_SYSTEM`
- **デザイン**: `:root` のCSS変数(`--primary` 等)でブランドカラーに変更可能
