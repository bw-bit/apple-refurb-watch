#!/usr/bin/env python3
"""xAI Grok Live Search で界隈の伸びポストを収集し、data/niche_posts.json に正規化して保存する。

スクレイピングではなく xAI 公式 API (Live Search, sources: x) を使う。
XAI_API_KEY が未設定の場合は何もせず終了コード 2 を返す。
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://api.x.ai/v1/chat/completions"


def load_config() -> dict:
    # PyYAML に依存しないよう、必要なキーだけ素朴にパースする
    text = (ROOT / "config.yml").read_text(encoding="utf-8")
    cfg = {
        "theme": "",
        "accounts": [],
        "period_days": 90,
        "max_results": 20,
        "grok_model": "grok-4",
    }
    m = re.search(r'theme:\s*"([^"]+)"', text)
    if m:
        cfg["theme"] = m.group(1)
    cfg["accounts"] = re.findall(r'-\s*"(@[^"]+)"', text)
    m = re.search(r"period_days:\s*(\d+)", text)
    if m:
        cfg["period_days"] = int(m.group(1))
    m = re.search(r"max_search_results:\s*(\d+)", text)
    if m:
        cfg["max_results"] = int(m.group(1))
    m = re.search(r'grok:\s*"([^"]+)"', text)
    if m:
        cfg["grok_model"] = m.group(1)
    return cfg


def build_prompt(cfg: dict) -> str:
    accounts = "、".join(cfg["accounts"]) or "（指定なし）"
    return f"""あなたはXの公開ポストを検索するリサーチャーです。
次のジャンルで、直近{cfg['period_days']}日で伸びている（インプレッションやブックマークが多い）
Xのポスト（長文記事・ツリーを優先）を{cfg['max_results']}件まで探してください。

- テーマ: {cfg['theme']}
- 参考になるお手本アカウント: {accounts}
- 除外: 明らかなジャンル違い、公式アカウント、広告

必ず次のJSONだけを出力してください（前後の説明文は禁止）:
{{"posts": [{{"title": "ポストの見出しまたは冒頭要約", "opening": "冒頭2〜3行の実文",
"engagement": "確認できた数値（例: 1.2万インプ）。不明なら null",
"thumbnail": "添付画像の内容。不明なら null",
"url": "https://x.com/... の実URL", "posted_at": "YYYY-MM-DD または null"}}]}}

厳守: 実在が確認できたポストだけを入れる。URLを創作しない。確認できない項目は null にする。
"""


def call_grok(cfg: dict, api_key: str) -> dict:
    from_date = (datetime.now(timezone.utc) - timedelta(days=cfg["period_days"])).strftime("%Y-%m-%d")
    body = {
        "model": cfg["grok_model"],
        "messages": [{"role": "user", "content": build_prompt(cfg)}],
        "search_parameters": {
            "mode": "on",
            "sources": [{"type": "x"}],
            "from_date": from_date,
            "max_search_results": cfg["max_results"],
            "return_citations": True,
        },
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def extract_posts(response: dict) -> list[dict]:
    content = response["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    posts = data.get("posts", [])
    citations = set(response.get("citations", []) or [])
    seen: set[str] = set()
    result = []
    for p in posts:
        url = (p.get("url") or "").strip()
        if url in seen:
            continue
        seen.add(url)
        looks_real = url.startswith("https://x.com/") or url.startswith("https://twitter.com/")
        # citation に含まれるURLは Grok が実際に参照した裏付けがある
        p["verified"] = bool(looks_real and (not citations or url in citations))
        result.append(p)
    return result


def main() -> int:
    api_key = os.environ.get("XAI_API_KEY")
    out_path = ROOT / "data" / "niche_posts.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not api_key:
        print("XAI_API_KEY が未設定のため Grok検索をスキップします", file=sys.stderr)
        return 2

    cfg = load_config()
    try:
        response = call_grok(cfg, api_key)
    except Exception as exc:  # ネットワーク/認証エラーは正直に残して落とす
        out_path.write_text(
            json.dumps({"posts": [], "note": f"Grok検索に失敗: {exc}"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Grok検索に失敗しました: {exc}", file=sys.stderr)
        return 1

    posts = extract_posts(response)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "theme": cfg["theme"],
        "posts": posts,
    }
    if not posts:
        payload["note"] = "取得できず。対象ポストを手で貼ってください"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    verified = sum(1 for p in posts if p.get("verified"))
    print(f"収集 {len(posts)} 件 (verified {verified} 件) → {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
