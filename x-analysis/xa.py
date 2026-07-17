#!/usr/bin/env python3
"""X運用 自動分析システム オーケストレーター (v2)

サブコマンド:
  format    自分のXアナリティクス生データを一覧表に整形 (Sonnet)
  fetch     Grok Live Search で界隈の伸びポストを収集 (xAI API)
  analyze   自分×界隈×ジャンル外の比較分析レポートを生成 (Opus)
  playbook  レポートから勝ちパターンを抽出し playbook を更新 (Opus)
  run       上記を順に全部実行 (fetch は codex があれば委任)
  status    データの揃い具合を表示 (APIキー不要)

標準ライブラリのみで動く (Python 3.11+)。
実データが無いフェーズは捏造せずスキップする。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from datetime import datetime, timedelta, timezone
from os import environ
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
PLAYBOOK = ROOT / "playbook" / "x_win_patterns.md"
XAI_API_URL = "https://api.x.ai/v1/chat/completions"


# ---------- 共通ヘルパ ----------

def load_config() -> dict:
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def prompt_text(name: str) -> str:
    return (ROOT / "prompts" / name).read_text(encoding="utf-8")


def real_content(path: Path) -> str:
    """コメント行(#)と空行を除いた実データを返す。無ければ空文字。"""
    if not path.exists():
        return ""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return "\n".join(lines)


def run_claude(model: str, prompt: str, timeout: int = 900) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--model", model, prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude 実行失敗 (model={model}): {proc.stderr.strip()[-500:]}")
    return proc.stdout.strip()


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------- format: 生データ → 一覧表 ----------

def cmd_format(cfg: dict) -> bool:
    raw = real_content(DATA / "own_posts_raw.txt")
    if not raw:
        print("skip format: data/own_posts_raw.txt に実データがありません "
              "(捏造防止のため自己分析は実データ必須)", file=sys.stderr)
        return False
    out = run_claude(cfg["models"]["light"], f"{prompt_text('01_format_posts.md')}\n{raw}")
    (DATA / "own_posts.md").write_text(out + "\n", encoding="utf-8")
    print("format: data/own_posts.md を更新")
    return True


# ---------- fetch: Grok Live Search ----------

def build_search_prompt(cfg: dict) -> str:
    accounts = "、".join(cfg["genre"]["role_model_accounts"]) or "（指定なし）"
    days = cfg["search"]["period_days"]
    limit = cfg["search"]["max_results"]
    return f"""あなたはXの公開ポストを検索するリサーチャーです。
次のジャンルで、直近{days}日で伸びている（インプレッションやブックマークが多い）
Xのポスト（長文記事・ツリーを優先）を{limit}件まで探してください。

- テーマ: {cfg['genre']['theme']}
- 参考になるお手本アカウント: {accounts}
- 除外: 明らかなジャンル違い、公式アカウント、広告

必ず次のJSONだけを出力してください（前後の説明文は禁止）:
{{"posts": [{{"title": "見出しまたは冒頭要約", "opening": "冒頭2〜3行の実文",
"engagement": "確認できた数値（例: 1.2万インプ）。不明なら null",
"thumbnail": "添付画像の内容。不明なら null",
"url": "https://x.com/... の実URL", "posted_at": "YYYY-MM-DD または null"}}]}}

厳守: 実在が確認できたポストだけを入れる。URLを創作しない。確認できない項目は null にする。
"""


def cmd_fetch(cfg: dict) -> bool:
    out_path = DATA / "niche_posts.json"
    api_key = environ.get("XAI_API_KEY")
    if not api_key:
        print("skip fetch: XAI_API_KEY が未設定です", file=sys.stderr)
        return False

    from_date = (
        datetime.now(timezone.utc) - timedelta(days=cfg["search"]["period_days"])
    ).strftime("%Y-%m-%d")
    body = {
        "model": cfg["models"]["grok"],
        "messages": [{"role": "user", "content": build_search_prompt(cfg)}],
        "search_parameters": {
            "mode": "on",
            "sources": [{"type": "x"}],
            "from_date": from_date,
            "max_search_results": cfg["search"]["max_results"],
            "return_citations": True,
        },
    }
    req = urllib.request.Request(
        XAI_API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            response = json.load(resp)
    except Exception as exc:
        out_path.write_text(
            json.dumps({"posts": [], "note": f"Grok検索に失敗: {exc}"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"fetch 失敗: {exc}", file=sys.stderr)
        return False

    posts = extract_posts(response)
    payload: dict = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "theme": cfg["genre"]["theme"],
        "posts": posts,
    }
    if not posts:
        payload["note"] = "取得できず。対象ポストを手で貼ってください"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    verified = sum(1 for p in posts if p.get("verified"))
    print(f"fetch: {len(posts)} 件収集 (verified {verified} 件) → {out_path.name}")
    return bool(posts)


def extract_posts(response: dict) -> list[dict]:
    content = response["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    citations = set(response.get("citations", []) or [])
    seen: set[str] = set()
    result = []
    for post in data.get("posts", []):
        url = (post.get("url") or "").strip()
        if url in seen:
            continue
        seen.add(url)
        looks_real = url.startswith(("https://x.com/", "https://twitter.com/"))
        # citations に載っているURLは Grok が実際に参照した裏付けがある
        post["verified"] = bool(looks_real and (not citations or url in citations))
        result.append(post)
    return result


def fetch_via_codex_or_direct(cfg: dict) -> None:
    if not environ.get("XAI_API_KEY"):
        print("skip fetch: XAI_API_KEY が未設定です", file=sys.stderr)
        return
    if shutil.which("codex"):
        task = (ROOT / "codex" / "grok_search_task.md").read_text(encoding="utf-8")
        proc = subprocess.run(["codex", "exec", "--full-auto", task], cwd=ROOT, timeout=1200)
        if proc.returncode == 0:
            return
        print("codex 委任に失敗。fetch を直接実行します", file=sys.stderr)
    cmd_fetch(cfg)


# ---------- analyze: 比較分析レポート ----------

def cmd_analyze(cfg: dict) -> Path | None:
    heavy = cfg["models"]["heavy"]
    own = real_content(DATA / "own_posts.md")
    niche_path = DATA / "niche_posts.json"
    niche = ""
    if niche_path.exists():
        niche_data = json.loads(niche_path.read_text(encoding="utf-8"))
        if niche_data.get("posts"):
            niche = json.dumps(niche_data, ensure_ascii=False, indent=2)
    cross = real_content(DATA / "cross_genre_raw.txt")

    if not own and not niche:
        print("skip analyze: 分析できるデータがありません (own_posts / niche_posts とも空)",
              file=sys.stderr)
        return None

    sections = [f"# X分析レポート {today()}", ""]
    sections.append("| 入力 | 状態 |")
    sections.append("|------|------|")
    sections.append(f"| 自分の記事データ | {'✅ あり' if own else '⬜ なし (own_posts_raw.txt に貼る)'} |")
    sections.append(f"| 界隈の伸びポスト | {'✅ あり' if niche else '⬜ なし (fetch 未実行/取得0件)'} |")
    sections.append(f"| ジャンル外バズ | {'✅ あり' if cross else '⬜ なし (任意)'} |")
    sections.append("")

    if own:
        print(f"analyze: 自分の記事分析 ({cfg['models']['heavy']})")
        sections += ["## 1. 自分の記事分析（辛口）", "",
                     run_claude(heavy, f"{prompt_text('02_analyze_own.md')}\n{own}"), ""]
    if niche:
        print("analyze: 界隈の勝ちパターン分析")
        sections += ["## 2. 界隈の勝ちパターン分析", "",
                     run_claude(heavy, f"{prompt_text('03_analyze_niche.md')}\n{niche}"), ""]
    if cross:
        print("analyze: ジャンル外バズの構造分析")
        sections += ["## 3. ジャンル外バズの構造分析（応用）", "",
                     run_claude(heavy, f"{prompt_text('04_cross_genre.md')}\n{cross}"), ""]

    REPORTS.mkdir(exist_ok=True)
    report_path = REPORTS / f"{today()}.md"
    report_path.write_text("\n".join(sections), encoding="utf-8")
    print(f"analyze: {report_path} を作成")
    return report_path


# ---------- playbook: 勝ちパターン資産の更新 ----------

def latest_report() -> Path | None:
    reports = sorted(REPORTS.glob("*.md"))
    return reports[-1] if reports else None


def cmd_playbook(cfg: dict, report_path: Path | None = None) -> bool:
    report_path = report_path or latest_report()
    if report_path is None:
        print("skip playbook: レポートがありません (先に analyze を実行)", file=sys.stderr)
        return False

    out = run_claude(
        cfg["models"]["heavy"],
        f"{prompt_text('05_update_playbook.md')}\n\n"
        f"【今回の分析レポート】\n{report_path.read_text(encoding='utf-8')}\n\n"
        f"【現在のplaybook】\n{PLAYBOOK.read_text(encoding='utf-8')}",
    )
    # 出力の最初のコードブロック全文が playbook 更新版 (prompts/05 の契約)
    m = re.search(r"```(?:markdown|md)?\n(.*?)\n```", out, re.DOTALL)
    if m:
        PLAYBOOK.write_text(m.group(1) + "\n", encoding="utf-8")
        print(f"playbook: {PLAYBOOK} を更新")
    else:
        print("playbook: 更新版を解析できず。レポート末尾に生出力のみ追記します", file=sys.stderr)
    with report_path.open("a", encoding="utf-8") as f:
        f.write(f"\n## 今週のアクション（playbook更新の提案含む）\n\n{out}\n")
    return bool(m)


# ---------- status ----------

def cmd_status(cfg: dict) -> None:
    def mark(ok: bool) -> str:
        return "✅" if ok else "⬜"

    print(f"テーマ: {cfg['genre']['theme']}")
    print(f"{mark(bool(real_content(DATA / 'own_posts_raw.txt')))} data/own_posts_raw.txt (自分の実データ・必須)")
    print(f"{mark((DATA / 'own_posts.md').exists())} data/own_posts.md (format 済み)")
    niche = DATA / "niche_posts.json"
    has_niche = niche.exists() and bool(json.loads(niche.read_text(encoding='utf-8')).get("posts"))
    print(f"{mark(has_niche)} data/niche_posts.json (fetch 済み)")
    print(f"{mark(bool(real_content(DATA / 'cross_genre_raw.txt')))} data/cross_genre_raw.txt (任意)")
    print(f"{mark(latest_report() is not None)} reports/ (最新: {latest_report() or 'なし'})")
    print(f"{mark(bool(environ.get('ANTHROPIC_API_KEY')))} ANTHROPIC_API_KEY")
    print(f"{mark(bool(environ.get('XAI_API_KEY')))} XAI_API_KEY")
    print(f"{mark(shutil.which('codex') is not None)} codex CLI")


# ---------- run: 全フェーズ ----------

def cmd_run(cfg: dict) -> None:
    try:
        cmd_format(cfg)
    except Exception as exc:
        print(f"format 失敗 (続行): {exc}", file=sys.stderr)
    fetch_via_codex_or_direct(cfg)
    report = cmd_analyze(cfg)
    if report:
        cmd_playbook(cfg, report)
    print("run: 完了")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command",
                        choices=["format", "fetch", "analyze", "playbook", "run", "status"])
    args = parser.parse_args()
    cfg = load_config()
    DATA.mkdir(exist_ok=True)

    if args.command == "format":
        cmd_format(cfg)
    elif args.command == "fetch":
        cmd_fetch(cfg)
    elif args.command == "analyze":
        cmd_analyze(cfg)
    elif args.command == "playbook":
        cmd_playbook(cfg)
    elif args.command == "status":
        cmd_status(cfg)
    else:
        cmd_run(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
