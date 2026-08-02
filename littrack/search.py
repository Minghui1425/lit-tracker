"""检索引擎。

周报与历史检索本质是同一件事——**只有日期窗口不同**。旧版把它们写成两个脚本，
结果 47 与 41 个函数里有 33 个同名，改一处要记得改另一处。这里合并为一个引擎。
"""
from __future__ import annotations

import logging

from . import entrez, matchers
from .journals import JournalIndex

log = logging.getLogger(__name__)


def _section_query(section, date_q: str) -> str:
    """按板块的匹配器构造 PubMed 检索式。"""
    f = section.search_field
    if section.matcher == "cross_product":
        a = entrez.or_terms(matchers.expand_for_query(section.trigger_keywords), f)
        b_kws: list[str] = []
        for sub in section.subsections:
            b_kws.extend(sub.cross_keywords)
        b = entrez.or_terms(matchers.expand_for_query(b_kws), f)
        kw_q = f"(({a}) AND ({b}))"
    else:
        pool = list(section.keywords)
        for sub in section.subsections:
            pool.extend(sub.keywords)
        kw_q = f"({entrez.or_terms(matchers.expand_for_query(pool), f)})"
    return f"{kw_q} AND {date_q}"


def _journal_query(journal_names: list[str], date_q: str) -> str:
    jq = " OR ".join(f'"{j}"[ta]' for j in journal_names)
    return f"({jq}) AND {date_q}"


def run(config, start: str, end: str, *, journals: JournalIndex | None = None) -> list[dict]:
    """执行一次检索，返回已分类、已去重、已过滤的文章列表。

    去重优先级 = 配置里板块的书写顺序；一篇文章只会出现在一个板块。
    """
    date_q = entrez.date_range_query(start, end)
    journals = journals or JournalIndex.empty()
    seen: dict[str, dict] = {}

    # ── 1. 走指定期刊的板块：按期刊取全量，再本地按关键词分类 ──────────────
    journal_secs = [s for s in config.sections if s.scope == "journals"]
    if journal_secs and config.all_journals:
        full_inc = list(config.full_inclusion_journals)
        kw_filt = list(config.keyword_filtered_journals)
        for names, is_full in ((full_inc, True), (kw_filt, False)):
            if not names:
                continue
            log.info(f"检索{'全量收录' if is_full else '关键词筛选'}期刊 {len(names)} 本…")
            pmids = entrez.esearch(_journal_query(names, date_q))
            log.info(f"  → {len(pmids)} 篇候选")
            for art in entrez.efetch(pmids):
                if art["pmid"] in seen:
                    continue
                hit = matchers.classify(config, art["title"], full_inclusion=is_full)
                if not hit:
                    continue
                sec_name, sub_name = hit
                sec = config.section(sec_name)
                if sec.scope != "journals":
                    continue          # 该板块只从全库取，不在期刊路径收
                if not matchers.passes_type_filter(sec, art["pub_types"]):
                    continue
                seen[art["pmid"]] = {**art, "section": sec_name, "subsection": sub_name}

    # ── 2. 走 PubMed 全库的板块 ───────────────────────────────────────────
    for sec in config.sections:
        if sec.scope != "pubmed_all":
            continue
        log.info(f"全库检索板块「{sec.name}」…")
        pmids = entrez.esearch(_section_query(sec, date_q))
        log.info(f"  → {len(pmids)} 篇候选")
        kept = 0
        for art in entrez.efetch(pmids):
            if art["pmid"] in seen:
                continue                                   # 已被更高优先级板块收走
            if not matchers.section_matches(sec, art["title"]):
                continue
            if not matchers.passes_type_filter(sec, art["pub_types"]):
                continue
            if sec.quality_filter and not journals.passes_quality(
                    art, config.allowed_quartiles, config.min_impact_factor):
                continue
            seen[art["pmid"]] = {
                **art, "section": sec.name,
                "subsection": matchers.classify_subsection(sec, art["title"]),
            }
            kept += 1
        log.info(f"  保留 {kept} 篇")

    # 补充期刊显示名与 IF/分区
    for art in seen.values():
        art["journal"] = journals.display_name(
            art["journal_full"] or art["journal_abbr"], config.all_journals)
        art["if_value"], art["quartile"] = journals.impact(art)
        art["type_label"] = matchers.type_label(art["pub_types"])

    return list(seen.values())


def group_by_section(config, articles: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """{板块: {子板块: [文章]}}，顺序按配置；组内按发表日期降序。"""
    order = config.subsection_order()
    out: dict[str, dict[str, list[dict]]] = {}
    for sec in config.sections:
        buckets = {sub.name: [] for sub in sec.subsections}
        for a in articles:
            if a["section"] == sec.name:
                buckets.setdefault(a["subsection"], []).append(a)
        buckets = {k: sorted(v, key=lambda x: x["pub_date"], reverse=True)
                   for k, v in buckets.items() if v}
        if buckets:
            rank = order.get(sec.name, {})
            out[sec.name] = dict(sorted(buckets.items(),
                                        key=lambda kv: rank.get(kv[0], 999)))
    return out
