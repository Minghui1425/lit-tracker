"""匹配与归类。

只开放两种匹配器：
  simple_keyword —— 标题命中任一关键词即算命中该板块
  cross_product  —— 需同时命中 trigger_keywords（A 侧）与子板块 cross_keywords（B 侧）

关键词一律按**词边界**匹配，并自动兼容常见词形变化（复数 / -y→-ies）：
纯 \\bkw\\b 精确匹配会漏掉 neuropathy→neuropathies 这类变体，且是隐蔽的系统性漏判。
因此配置里只写单数原形即可，**不要手工补变体**。
"""
from __future__ import annotations

import re

_RE_CACHE: dict[str, re.Pattern] = {}


def kw_pattern(kw: str) -> re.Pattern:
    """把关键词编译成容忍复数形式的词边界正则（结果缓存）。"""
    rx = _RE_CACHE.get(kw)
    if rx is None:
        k = kw.lower()
        esc = re.escape(k)
        if k.endswith("y"):            # neuropathy → neuropathy|neuropathies
            body = esc[:-1] + "(?:y|ies)"
        elif k.endswith("s"):          # diabetes：已是 s 结尾，不再加
            body = esc
        else:                          # rash → rash|rashes
            body = esc + "(?:e?s)?"
        rx = re.compile(r"\b" + body + r"\b", re.IGNORECASE)
        _RE_CACHE[kw] = rx
    return rx


def query_forms(kw: str) -> list[str]:
    """关键词在 PubMed 检索式中的词形。

    `"neuropathy"[ti]` 是精确短语匹配，不会命中 neuropathies，因此必须把复数一并
    送进查询——否则本地判定再准，文章在**抓取阶段**就已经漏掉了。
    """
    k = kw.lower()
    if k.endswith("y"):
        return [k, k[:-1] + "ies"]
    if k.endswith("s"):
        return [k]
    return [k, k + "s", k + "es"]


def expand_for_query(keywords: list[str]) -> list[str]:
    out: list[str] = []
    for kw in keywords:
        for f in query_forms(kw):
            if f not in out:
                out.append(f)
    return out


def hits(text: str, keywords: list[str]) -> bool:
    return any(kw_pattern(kw).search(text) for kw in keywords)


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw_pattern(kw).search(text)]


# ─── 板块判定 ─────────────────────────────────────────────────────────────────

def section_matches(section, title: str) -> bool:
    """文章是否属于该板块。"""
    if section.exclude_keywords and hits(title, section.exclude_keywords):
        return False

    if section.matcher == "cross_product":
        if not hits(title, section.trigger_keywords):
            return False
        return any(hits(title, sub.cross_keywords) for sub in section.subsections)

    # simple_keyword：板块级关键词与子板块关键词取并集
    pool = list(section.keywords)
    for sub in section.subsections:
        pool.extend(sub.keywords)
    return hits(title, pool)


def classify_subsection(section, title: str) -> str:
    """归到哪个子板块。按配置里的**书写顺序**取首个命中者，故顺序即优先级。

    都没命中时：有 fallback_subsection 就用它，否则用最后一个子板块兜底。
    """
    key = "cross_keywords" if section.matcher == "cross_product" else "keywords"
    for sub in section.subsections:
        if hits(title, getattr(sub, key)):
            return sub.name
    if section.fallback_subsection:
        return section.fallback_subsection
    return section.subsections[-1].name


def classify(config, title: str, *, full_inclusion: bool = False) -> tuple[str, str] | None:
    """返回 (板块, 子板块)；都不属于则返回 None。

    板块的**书写顺序即去重优先级**——一篇文章只归第一个命中的板块，
    避免同一篇在多个板块重复出现。
    """
    for sec in config.sections:
        if section_matches(sec, title):
            return sec.name, classify_subsection(sec, title)

    # 全量收录刊：未命中任何关键词的，落到指定板块的兜底子板块
    if full_inclusion:
        for sec in config.sections:
            if sec.fallback_subsection:
                return sec.name, sec.fallback_subsection
    return None


# ─── 文章类型过滤 ─────────────────────────────────────────────────────────────

def passes_type_filter(section, pub_types: list[str]) -> bool:
    pts = set(pub_types)
    if section.exclude_types and pts & set(section.exclude_types):
        return False
    if section.include_types and not (pts & set(section.include_types)):
        return False
    return True


_TYPE_LABEL_ORDER = ["Systematic Review", "Meta-Analysis", "Review",
                     "Randomized Controlled Trial", "Clinical Trial",
                     "Case Reports", "Journal Article"]
_TYPE_SHORT = {"Randomized Controlled Trial": "RCT", "Case Reports": "Case Report",
               "Journal Article": "Article"}


def type_label(pub_types: list[str]) -> str:
    pts = set(pub_types)
    for t in _TYPE_LABEL_ORDER:
        if t in pts:
            return _TYPE_SHORT.get(t, t)
    return ""
