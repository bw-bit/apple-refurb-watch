#!/usr/bin/env bash
# X分析パイプライン: 整形(Sonnet) → Grok検索(Codex) → 分析(Opus) → playbook更新(Opus)
# 必要: claude CLI (ANTHROPIC_API_KEY)。任意: codex CLI (OPENAI_API_KEY) + XAI_API_KEY
set -euo pipefail
cd "$(dirname "$0")/.."

DATE=$(date -u +%F)
REPORT="reports/${DATE}_analysis.md"
mkdir -p reports data

MODEL_HEAVY=$(grep -oP 'heavy:\s*"\K[^"]+' config.yml || echo "claude-opus-4-8")
MODEL_LIGHT=$(grep -oP 'light:\s*"\K[^"]+' config.yml || echo "claude-sonnet-5")

run_claude() { # $1=model $2=prompt
  claude -p --model "$1" "$2"
}

has_real_data() { # コメント行(#)と空行を除いて中身があるか
  grep -v '^#' "$1" 2>/dev/null | grep -q '[^[:space:]]'
}

echo "=== Phase 0: 自分のポストデータ整形 (${MODEL_LIGHT}) ==="
if has_real_data data/own_posts_raw.txt; then
  run_claude "$MODEL_LIGHT" "$(cat prompts/01_format_posts.md)
$(cat data/own_posts_raw.txt)" > data/own_posts.md
  echo "→ data/own_posts.md を更新"
else
  echo "!! data/own_posts_raw.txt が空です。Xアナリティクスのデータを貼ってください。" >&2
  echo "!! 実データ無しの分析は捏造の元なので、自分の記事分析はスキップします。" >&2
fi

echo "=== Phase 1: Grok検索 (Codex に委任) ==="
if command -v codex >/dev/null 2>&1 && [ -n "${XAI_API_KEY:-}" ]; then
  codex exec --full-auto "$(cat codex/grok_search_task.md)" || echo "codex 実行に失敗。既存の niche_posts.json を使います" >&2
elif [ -n "${XAI_API_KEY:-}" ]; then
  echo "codex が無いため grok_search.py を直接実行します" >&2
  python3 scripts/grok_search.py || true
else
  echo "XAI_API_KEY 未設定のため Grok検索をスキップ" >&2
fi

echo "=== Phase 2: 重い分析 (${MODEL_HEAVY}) ==="
{
  echo "# X分析レポート ${DATE}"
  echo
  if [ -s data/own_posts.md ]; then
    echo "## 1. 自分の記事分析"
    run_claude "$MODEL_HEAVY" "$(cat prompts/02_analyze_own.md)
$(cat data/own_posts.md)"
    echo
  fi
  if [ -s data/niche_posts.json ]; then
    echo "## 2. 界隈の勝ちパターン分析"
    run_claude "$MODEL_HEAVY" "$(cat prompts/03_analyze_niche.md)
$(cat data/niche_posts.json)"
    echo
  fi
  if has_real_data data/cross_genre_raw.txt; then
    echo "## 3. ジャンル外バズの構造分析（応用）"
    run_claude "$MODEL_HEAVY" "$(cat prompts/04_cross_genre.md)
$(cat data/cross_genre_raw.txt)"
    echo
  fi
} > "$REPORT"
echo "→ ${REPORT} を作成"

echo "=== Phase 3: playbook 更新 (${MODEL_HEAVY}) ==="
PLAYBOOK_OUT=$(run_claude "$MODEL_HEAVY" "$(cat prompts/05_update_playbook.md)

【今回の分析レポート】
$(cat "$REPORT")

【現在のplaybook】
$(cat playbook/x_win_patterns.md)")
# 出力の最初のコードブロックが playbook 更新後全文 (prompts/05 の契約)
UPDATED=$(printf '%s\n' "$PLAYBOOK_OUT" | awk '/^```/{n++; next} n==1{print}')
if [ -n "$UPDATED" ]; then
  printf '%s\n' "$UPDATED" > playbook/x_win_patterns.md
  echo "→ playbook/x_win_patterns.md を更新"
else
  echo "!! playbook 更新出力を解析できず。レポート末尾に生出力を残します" >&2
fi
{
  echo
  echo "## 4. 今週のアクション（playbook更新の提案含む）"
  printf '%s\n' "$PLAYBOOK_OUT"
} >> "$REPORT"

echo "=== 完了: ${REPORT} ==="
