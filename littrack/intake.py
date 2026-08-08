"""把 PMID 或文章标题收进收藏库。

命令行的 `add` 和收藏库页面上的「添加文献」走的是同一条路：先把用户给的东西
解析成 PMID，再抓元数据、归板块、写库。两边共用这里，页面上加进去的文献才会
和命令行加的完全一样（同样的 IF/分区、同样的类型标签、同样的板块判定）。
"""
from __future__ import annotations

import re
from pathlib import Path

from . import entrez, library, matchers

# 一次最多收多少篇。限制的是网页那条路：输入框里粘一大段数字很容易手滑，
# 而每个 PMID 都要走 PubMed，几百个一次会把请求拖到超时。
MAX_PMIDS = 50

_PMID_RE = re.compile(r"^\d{1,9}$")
# 纯数字（可用空格/逗号/分号分隔，中英文标点都认）视为一串 PMID，否则当标题检索
_PMID_LIST_RE = re.compile(r"^[\d\s,，;；]+$")


class IntakeError(ValueError):
    """用户输入的问题（PMID 写错、标题查不到等），信息可直接展示给用户。"""


def parse_pmids(raw) -> list[str]:
    """把字符串或列表整理成去重后的 PMID 列表。"""
    if isinstance(raw, str):
        items = re.split(r"[\s,，;；]+", raw.strip())
    elif isinstance(raw, (list, tuple)):
        items = [str(x).strip() for x in raw]
    else:
        raise IntakeError("请输入文章标题或 PMID")
    out: list[str] = []
    for it in items:
        if not it:
            continue
        if not _PMID_RE.match(it):
            raise IntakeError(f"不是合法的 PMID：{it}")
        if it not in out:
            out.append(it)
    if not out:
        raise IntakeError("请输入文章标题或 PMID")
    return out


def _norm_title(s: str) -> str:
    return re.sub(r"[^\w]+", "", s.casefold())


def find_pmid_by_title(title: str) -> str:
    """把粘贴进来的完整标题解析成唯一的 PMID。

    宁可报错也不猜：标题在 PubMed 里撞车（会议摘要、勘误、同名综述）并不罕见，
    猜错就是往库里加了一篇别人的文章，而且很难发现。
    """
    title = re.sub(r"\s+", " ", title).strip().rstrip(".")
    if len(title) < 8:
        raise IntakeError("文章标题太短，请粘贴完整标题，或直接输入 PMID")

    ids: list[str] = []
    for term in (f'"{title}"[Title]', f"{title}[Title]"):
        ids = entrez.esearch(term, retmax=5)
        if ids:
            break
    if not ids:
        raise IntakeError("PubMed 按这个标题没搜到文章，请核对标题，或改用 PMID")
    if len(ids) == 1:
        return ids[0]

    # 命中多篇：只认标题完全一致（忽略大小写与标点）的那一篇
    want = _norm_title(title)
    exact = [a["pmid"] for a in entrez.efetch(ids)
             if _norm_title((a.get("title") or "").rstrip(".")) == want]
    if len(exact) == 1:
        return exact[0]
    raise IntakeError(f"这个标题在 PubMed 匹配到 {len(ids)} 篇，无法确定是哪一篇。"
                      f"请改用 PMID，以免加错")


def resolve(query) -> list[str]:
    """用户在网页输入框里给的东西 → PMID 列表。纯数字按 PMID 处理，否则按标题检索。"""
    if isinstance(query, str) and not _PMID_LIST_RE.match(query.strip() or " "):
        return [find_pmid_by_title(query)]
    return parse_pmids(query)


def check_section(config, section: str, subsection: str) -> None:
    """校验手动指定的板块/子板块确实在配置里，不合法就报错。

    页面上的下拉框本来就只列合法值，但接口不能只信页面——命令行的 --section
    也走这里，写错板块名时早点报错，好过悄悄存成一个筛选里根本选不到的值。
    """
    if not section:
        if subsection:
            raise IntakeError("只给了子板块没给板块，请一并指定板块")
        return
    names = [s.name for s in config.sections]
    if section not in names:
        raise IntakeError(f"配置里没有板块「{section}」。当前板块：{'、'.join(names)}")
    if subsection:
        subs = next(s.subsection_names for s in config.sections if s.name == section)
        if subsection not in subs:
            raise IntakeError(f"「{section}」下没有子板块「{subsection}」。"
                              f"可用值：{'、'.join(subs) or '（该板块没有子板块）'}")


def collect(config, db_path: Path, pmids: list[str], *, journals,
            section: str = "", subsection: str = "", translate=None) -> dict:
    """抓元数据 → 归板块 → 写库。

    返回 {"articles", "added", "updated", "existing", "missing"}：
      existing 是本次之前就在库里的（会按当前配置重新归类，笔记与评级保留），
      missing  是 PubMed 没返回的（PMID 写错或已被撤下）。
    """
    if len(pmids) > MAX_PMIDS:
        raise IntakeError(f"一次最多添加 {MAX_PMIDS} 篇，这次给了 {len(pmids)} 篇")
    check_section(config, section, subsection)

    existing = {a["pmid"] for a in library.all_articles(db_path)} & set(pmids)
    arts = entrez.efetch(pmids)
    if not arts:
        raise IntakeError("PubMed 没返回任何文献，请检查 PMID 是否正确")
    missing = [p for p in pmids if p not in {a["pmid"] for a in arts}]

    for a in arts:
        hit = matchers.classify(config, a["title"])
        a["section"], a["subsection"] = hit if hit else (section, subsection)
        if section:
            a["section"] = section
            a["subsection"] = subsection
        a["journal"] = journals.display_name(a["journal_full"] or a["journal_abbr"],
                                             config.all_journals)
        a["if_value"], a["quartile"] = journals.impact(a)
        a["type_label"] = matchers.type_label(a["pub_types"])
    if translate:
        translate(config, arts)

    added, updated = library.upsert(db_path, arts)
    return {"articles": arts, "added": added, "updated": updated,
            "existing": sorted(existing), "missing": missing}
