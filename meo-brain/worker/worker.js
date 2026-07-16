/**
 * MEOブレイン バックエンド (Cloudflare Worker)
 *
 * エンドポイント:
 *   POST /diagnose     … AI詳細診断レポート生成 (Claude API)
 *   POST /sales-email  … 営業提案メール文の生成 (Claude API) ※営業モード用
 *   POST /rank         … Googleマップ検索順位チェック (Google Places API New)
 *   GET  /health       … 死活監視
 *
 * 必要な環境変数 (wrangler secret put で設定):
 *   ANTHROPIC_API_KEY    … Claude APIキー (必須: /diagnose, /sales-email)
 *   GOOGLE_MAPS_API_KEY  … Places API (New) が有効なAPIキー (必須: /rank)
 *   ALLOWED_ORIGINS      … 許可するオリジンのカンマ区切りリスト
 *                          例 "https://example.co.jp,https://www.example.co.jp"
 *                          未設定なら "*"(開発用。本番では必ず設定すること)
 *   CLAUDE_MODEL         … 使用モデル。省略時 "claude-opus-4-8"
 *                          (コスト最優先なら "claude-haiku-4-5" も可)
 */

const ANTHROPIC_VERSION = "2023-06-01";
const DEFAULT_MODEL = "claude-opus-4-8";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = corsHeaders(request, env);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (url.pathname === "/health") {
      return json({ ok: true }, 200, cors);
    }
    if (request.method !== "POST") {
      return json({ error: "method_not_allowed" }, 405, cors);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: "invalid_json" }, 400, cors);
    }

    try {
      switch (url.pathname) {
        case "/diagnose":
          return json(await diagnose(body, env), 200, cors);
        case "/sales-email":
          return json(await salesEmail(body, env), 200, cors);
        case "/rank":
          return json(await rank(body, env), 200, cors);
        default:
          return json({ error: "not_found" }, 404, cors);
      }
    } catch (e) {
      console.error(e);
      return json({ error: "internal_error", message: String(e.message || e) }, 500, cors);
    }
  },
};

/* ---------------- CORS ---------------- */
function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = (env.ALLOWED_ORIGINS || "*").split(",").map(s => s.trim());
  const allow = allowed.includes("*") ? "*" : (allowed.includes(origin) ? origin : allowed[0] || "");
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(data, status, cors) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
  });
}

/* ---------------- Claude API ---------------- */
async function callClaude(env, system, userText, maxTokens = 3000) {
  if (!env.ANTHROPIC_API_KEY) throw new Error("ANTHROPIC_API_KEY is not configured");
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": env.ANTHROPIC_API_KEY,
      "anthropic-version": ANTHROPIC_VERSION,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: env.CLAUDE_MODEL || DEFAULT_MODEL,
      max_tokens: maxTokens,
      system,
      messages: [{ role: "user", content: userText }],
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Claude API ${res.status}: ${errText.slice(0, 300)}`);
  }
  const data = await res.json();
  if (data.stop_reason === "refusal") {
    throw new Error("Claude declined the request");
  }
  const text = (data.content || []).filter(b => b.type === "text").map(b => b.text).join("\n");
  if (!text) throw new Error("empty response from Claude");
  return text;
}

/* ---------------- /diagnose ---------------- */
const DIAGNOSE_SYSTEM = `あなたは日本のローカルビジネス向けMEO(Googleビジネスプロフィール最適化)の専門コンサルタントです。
店舗の診断データを受け取り、その店舗専用の実践的な改善レポートをMarkdown形式で作成します。

必ず守ること:
- 出力は日本語。見出しは「#### 」、箇条書きは「- 」、強調は「**」のみ使用(表・コードブロックは使わない)
- 一般論ではなく、渡された業種・地域・キーワード・弱点に即した具体的な内容にする
- 以下の構成で書く:
  #### 総評(3〜4文で現状と勝ち筋)
  #### 最優先で取り組むべき3つの施策(それぞれ: 何を・どうやるかを手順レベルで)
  #### この店舗向けの投稿ネタ例(実際に使える投稿文を2本、120字程度で)
  #### 口コミ返信の例文(高評価向け1本・低評価向け1本)
  #### 90日後の目標イメージ
- 全体で1200字程度。誇大な成果保証はしない`;

async function diagnose(body, env) {
  const { business = {}, totalScore, categories = [], weakPoints = [] } = body;
  const userText = [
    `【店舗情報】`,
    `店舗名: ${s(business.name)} / 業種: ${s(business.type)} / 地域: ${s(business.area)} / 対策キーワード: ${s(business.kw)}`,
    ``,
    `【診断スコア】総合 ${Number(totalScore) || 0} / 100点`,
    ...categories.map(c => `- ${s(c.label)}: ${Number(c.score) || 0} / ${Number(c.max) || 0}点`),
    ``,
    `【検出された弱点(改善インパクト順)】`,
    ...weakPoints.map((w, i) => `${i + 1}. ${s(w.item)}(現状: ${s(w.current)} / 伸びしろ +${Number(w.impact) || 0}点)`),
    ``,
    `このデータをもとに改善レポートを作成してください。`,
  ].join("\n");

  const advice = await callClaude(env, DIAGNOSE_SYSTEM, userText, 3000);
  return { advice };
}

/* ---------------- /sales-email ---------------- */
const SALES_SYSTEM = `あなたはMEO対策・Web制作会社の営業担当です。
見込み客の店舗に対するMEO診断結果をもとに、初回アプローチ用の営業メールを1通作成します。

必ず守ること:
- 日本語。件名1行+本文(500〜600字)のプレーンテキスト
- 構成: 挨拶 → 診断で分かった具体的な課題(数字を1〜2個引用) → 改善するとどうなるか → 無料相談の提案 → 署名プレースホルダ
- 押し売り感を出さない。相手の店舗名・業種・地域を必ず本文に入れる
- 誇大表現・成果保証・「必ず1位」等の表現は禁止
- 出力は「件名: ...」の行から始める`;

async function salesEmail(body, env) {
  const { business = {}, totalScore, weakPoints = [], senderCompany = "" } = body;
  const userText = [
    `【見込み客の店舗】${s(business.name)}(${s(business.type)} / ${s(business.area)})`,
    `【MEO診断スコア】${Number(totalScore) || 0} / 100点`,
    `【主な課題】`,
    ...weakPoints.slice(0, 4).map(w => `- ${s(w.item)}(現状: ${s(w.current)})`),
    senderCompany ? `【差出人の会社】${s(senderCompany)}` : "",
    ``,
    `この店舗への初回営業メールを作成してください。`,
  ].join("\n");

  const email = await callClaude(env, SALES_SYSTEM, userText, 1500);
  return { email };
}

/* ---------------- /rank (Google Places API New) ---------------- */
async function rank(body, env) {
  if (!env.GOOGLE_MAPS_API_KEY) throw new Error("GOOGLE_MAPS_API_KEY is not configured");
  const keyword = s(body.keyword);
  const businessName = s(body.businessName);
  if (!keyword) throw new Error("keyword is required");

  const res = await fetch("https://places.googleapis.com/v1/places:searchText", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Goog-Api-Key": env.GOOGLE_MAPS_API_KEY,
      "X-Goog-FieldMask": "places.displayName,places.rating,places.userRatingCount",
    },
    body: JSON.stringify({
      textQuery: keyword,
      languageCode: "ja",
      regionCode: "JP",
      pageSize: 20,
    }),
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Places API ${res.status}: ${errText.slice(0, 300)}`);
  }
  const data = await res.json();
  const places = data.places || [];
  const results = places.map(p => ({
    name: p.displayName?.text || "",
    rating: p.rating ?? null,
    reviews: p.userRatingCount ?? null,
  }));

  // 店名の表記ゆれを吸収したうえで一致検索
  const norm = t => String(t).toLowerCase().replace(/[\s　・、。()()【】\[\]-]/g, "");
  const target = norm(businessName);
  let rankPos = null;
  if (target) {
    const idx = results.findIndex(r => {
      const n = norm(r.name);
      return n.includes(target) || target.includes(n);
    });
    if (idx >= 0) rankPos = idx + 1;
  }

  return { keyword, rank: rankPos, results };
}

/* ---------------- util ---------------- */
// プロンプトインジェクション緩和: 入力を短く切り詰め、制御文字を除去
function s(v) {
  return String(v ?? "").replace(/[\u0000-\u001f]/g, " ").slice(0, 200).trim();
}
