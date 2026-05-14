"""Apple整備済みストアを定期チェックして、新着商品をGitHub Issueで通知する。

GitHub Actions から呼ばれる想定。1分間隔で複数イテレーション走らせる。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import ssl

import aiohttp
import certifi

# scripts/ を import path に追加 (GitHub Actions では `python scripts/check.py` で実行)
sys.path.insert(0, str(Path(__file__).parent))
from parser import (  # noqa: E402
    CATEGORY_LABELS,
    Product,
    filter_watched,
    is_highlighted,
    normalize_memory_gb,
    parse_products,
)

REFURB_URL = "https://www.apple.com/jp/shop/refurbished/mac"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / "state" / "known_products.json"
JST = timezone(timedelta(hours=9))


# ---- HTTP --------------------------------------------------------------

async def fetch_html(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        resp.raise_for_status()
        return await resp.text()


async def fetch_all_categories() -> list[Product]:
    """複数URLを並列フェッチして全商品を取得。
    現在のApple構造では1URL内に全商品が含まれるが、将来の構造変化に備えて
    フィルタURLも並列で叩いて結果をマージする(同じ商品はpartNumberで重複排除)。
    """
    urls = [
        REFURB_URL,
        f"{REFURB_URL}?f=macstudio",
        f"{REFURB_URL}?f=macmini",
        f"{REFURB_URL}?f=macbookpro",
    ]
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(
            *(fetch_html(session, u) for u in urls),
            return_exceptions=True,
        )
    products_by_pn: dict[str, Product] = {}
    errors: list[str] = []
    for url, result in zip(urls, results):
        if isinstance(result, Exception):
            errors.append(f"{url}: {result!r}")
            continue
        for p in parse_products(result):
            products_by_pn.setdefault(p.part_number, p)
    if errors and not products_by_pn:
        raise RuntimeError("All fetches failed: " + "; ".join(errors))
    if errors:
        print(f"[warn] Some fetches failed: {errors}", file=sys.stderr)
    return list(products_by_pn.values())


# ---- State ------------------------------------------------------------

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"known_part_numbers": [], "last_check_utc": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] Failed to load state, starting fresh: {e}", file=sys.stderr)
        return {"known_part_numbers": [], "last_check_utc": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---- Issue 作成 -------------------------------------------------------

def format_product_line(p: Product) -> str:
    label = CATEGORY_LABELS.get(p.category, p.category)
    mem_gb = normalize_memory_gb(p.memory)
    mem_str = f"{mem_gb}GB" if mem_gb else (p.memory.upper() if p.memory else "?GB")
    storage = p.storage.upper() if p.storage else "?"
    star = "⭐" if is_highlighted(p) else ""
    return (
        f"- {star} **[{label}]** [{p.title}]({p.url})\n"
        f"   - メモリ: {mem_str} / ストレージ: {storage} / 価格: {p.price}\n"
        f"   - partNumber: `{p.part_number}`"
    )


def build_issue_title(new_products: list[Product]) -> str:
    cats = sorted({CATEGORY_LABELS.get(p.category, p.category) for p in new_products})
    cat_str = " / ".join(cats)
    star = "⭐ " if any(is_highlighted(p) for p in new_products) else ""
    return f"{star}🆕 Apple整備済みに新着: {cat_str} ({len(new_products)}件)"


def build_issue_body(new_products: list[Product], now_jst: datetime) -> str:
    lines = [
        f"検出時刻: **{now_jst.strftime('%Y-%m-%d %H:%M:%S JST')}**",
        "",
        f"## 新着商品 ({len(new_products)}件)",
        "",
    ]
    for p in sorted(new_products, key=lambda x: (x.category, -x.price_raw)):
        lines.append(format_product_line(p))
        lines.append("")
    lines.append("---")
    lines.append("[Apple 整備済み Mac 一覧](https://www.apple.com/jp/shop/refurbished/mac)")
    return "\n".join(lines)


def create_github_issue(title: str, body: str) -> None:
    """gh CLI で Issue 作成 (GitHub Actions 環境想定)。"""
    import subprocess

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        print(f"[dry-run] Would create issue: {title}")
        print(body)
        return
    cmd = [
        "gh", "issue", "create",
        "--repo", repo,
        "--title", title,
        "--body", body,
        "--label", "refurb-new",
    ]
    print(f"[info] Creating issue: {title}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[error] gh issue create failed: {result.stderr}", file=sys.stderr)
        # ラベルが存在しない場合のフォールバック
        cmd_no_label = [c for c in cmd if c not in ("--label", "refurb-new")]
        result2 = subprocess.run(cmd_no_label, capture_output=True, text=True)
        if result2.returncode != 0:
            raise RuntimeError(f"gh issue create failed: {result2.stderr}")
        print(f"[info] Created (without label): {result2.stdout.strip()}")
    else:
        print(f"[info] Created: {result.stdout.strip()}")


# ---- メインループ -----------------------------------------------------

async def check_once(state: dict) -> dict:
    """1回チェックして、新着があればIssue作成し、stateを更新して返す。"""
    products = await fetch_all_categories()
    watched = filter_watched(products)
    current_pns = {p.part_number for p in watched}
    known_pns = set(state.get("known_part_numbers", []))

    new_pns = current_pns - known_pns
    new_products = [p for p in watched if p.part_number in new_pns]

    now_utc = datetime.now(timezone.utc)
    now_jst = now_utc.astimezone(JST)

    print(
        f"[{now_jst.strftime('%H:%M:%S')}] "
        f"total={len(products)} watched={len(watched)} known={len(known_pns)} new={len(new_products)}",
        flush=True,
    )

    if new_products:
        title = build_issue_title(new_products)
        body = build_issue_body(new_products, now_jst)
        create_github_issue(title, body)

    # 監視対象のあるカテゴリだけは known を最新に保つ。
    # 監視対象外カテゴリ(iMac等)のpartNumberは保存しない(state肥大化防止)。
    state["known_part_numbers"] = sorted(current_pns | known_pns)
    state["last_check_utc"] = now_utc.isoformat()
    state["last_watched_count"] = len(watched)
    return state


async def run_loop(iterations: int, interval_sec: int) -> None:
    state = load_state()
    for i in range(iterations):
        try:
            state = await check_once(state)
            save_state(state)
        except Exception as e:
            print(f"[error] iteration {i+1} failed: {e!r}", file=sys.stderr)
        if i < iterations - 1:
            await asyncio.sleep(interval_sec)


def main():
    iterations = int(os.environ.get("CHECK_ITERATIONS", "1"))
    interval_sec = int(os.environ.get("CHECK_INTERVAL_SEC", "60"))
    print(f"[info] Starting watch loop: {iterations} iterations × {interval_sec}s")
    asyncio.run(run_loop(iterations, interval_sec))


if __name__ == "__main__":
    main()
