"""Apple整備済みストアのHTMLから商品リストを抽出するパーサー。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Iterable


BASE_URL = "https://www.apple.com"


@dataclass
class Product:
    part_number: str
    title: str
    price: str
    price_raw: float
    url: str
    category: str
    memory: str
    storage: str
    year: str
    raw_dimensions: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _extract_balanced(html: str, start_idx: int, open_char: str, close_char: str) -> str:
    """start_idx から open_char で始まる対応する close_char までを返す。文字列内のエスケープを考慮。"""
    depth = 0
    in_str = False
    escape = False
    i = start_idx
    while i < len(html):
        c = html[i]
        if escape:
            escape = False
        elif c == "\\":
            escape = True
        elif c == '"':
            in_str = not in_str
        elif not in_str:
            if c == open_char:
                depth += 1
            elif c == close_char:
                depth -= 1
                if depth == 0:
                    return html[start_idx : i + 1]
        i += 1
    raise ValueError(f"Unbalanced {open_char}{close_char} starting at {start_idx}")


def extract_tiles(html: str) -> list[dict]:
    """HTML中の `"tiles":[ ... ]` 配列を抽出してパース。"""
    marker = '"tiles":['
    idx = html.find(marker)
    if idx < 0:
        return []
    array_start = idx + len(marker) - 1  # '[' の位置
    array_str = _extract_balanced(html, array_start, "[", "]")
    return json.loads(array_str)


def parse_products(html: str) -> list[Product]:
    """HTMLから商品のリストを抽出して Product に変換。"""
    products: list[Product] = []
    for t in extract_tiles(html):
        dims = (t.get("filters") or {}).get("dimensions", {}) or {}
        price_obj = (t.get("price") or {}).get("currentPrice", {}) or {}
        url_path = (t.get("productDetailsUrl") or "").split("?", 1)[0]
        try:
            price_raw = float(price_obj.get("raw_amount") or 0.0)
        except (TypeError, ValueError):
            price_raw = 0.0
        products.append(
            Product(
                part_number=t.get("partNumber") or "",
                title=t.get("title") or "",
                price=price_obj.get("amount") or "",
                price_raw=price_raw,
                url=BASE_URL + url_path if url_path.startswith("/") else url_path,
                category=dims.get("refurbClearModel") or "",
                memory=(dims.get("tsMemorySize") or "").lower(),
                storage=(dims.get("dimensionCapacity") or "").lower(),
                year=dims.get("dimensionRelYear") or "",
                raw_dimensions=dims,
            )
        )
    return products


# ---- フィルタリングルール --------------------------------------------------

WATCHED_CATEGORIES = {"macstudio", "macmini", "macbookpro"}


def normalize_memory_gb(memory: str) -> int:
    """'128gb' -> 128, '' -> 0"""
    m = re.match(r"\s*(\d+)\s*gb", memory.lower())
    return int(m.group(1)) if m else 0


def is_watched(product: Product) -> bool:
    """ユーザーの監視ルールにマッチするか判定。

    - macstudio: 全て (128GB以上は強調)
    - macmini: 全て
    - macbookpro: 128GBメモリのみ
    """
    if product.category not in WATCHED_CATEGORIES:
        return False
    if product.category == "macbookpro":
        return normalize_memory_gb(product.memory) >= 128
    return True


def is_highlighted(product: Product) -> bool:
    """通知タイトルに🌟をつける優先度高アイテム判定 (Mac Studio 128GB以上)。"""
    if product.category == "macstudio" and normalize_memory_gb(product.memory) >= 128:
        return True
    if product.category == "macbookpro" and normalize_memory_gb(product.memory) >= 128:
        return True
    return False


CATEGORY_LABELS = {
    "macstudio": "Mac Studio",
    "macmini": "Mac mini",
    "macbookpro": "MacBook Pro",
    "imac": "iMac",
    "display": "Display",
}


def filter_watched(products: Iterable[Product]) -> list[Product]:
    return [p for p in products if is_watched(p)]
