"""读 EndNote / Zotero 导出的文献文件，解析出 PMID。

支持 RIS(.ris)、MEDLINE/nbib(.nbib)、BibTeX(.bib)、EndNote XML(.xml)、CSL JSON(.json)
——EndNote 与 Zotero 的默认导出选项都在里头。

**为什么解析完还要回 PubMed**：本工具的库以 PMID 为主键，元数据（IF/分区、文章类型、
关键词、通讯单位）也一律以 PubMed 记录为准。导出文件里的书目字段各家写法不一、
常年不更新（预印本年份、缩写刊名、缺 DOI），拿它直接入库会让同一篇文章因为来源不同
而长得不一样。所以这里只做一件事：**把每条记录落到一个 PMID 上**，剩下的照常走
`intake.collect`，和手动 `add` 的结果完全一致。

落 PMID 的三级路径，逐级变贵也逐级变不可靠：
  ① 文件里直接写了 PMID（PubMed 导出、Zotero 的 Extra 字段、EndNote 的 accession
     number）——不用联网，最可信；
  ② DOI → PubMed 查（一次 esearch）；
  ③ 标题 → PubMed 查（同 `intake.find_pmid_by_title`，撞名时宁可报错也不猜）。
非期刊文献（书籍、网页、会议摘要）本来就不在 PubMed 里，认不出来是正常的，
会原样列进 unresolved 让你自己看。
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import entrez, intake

log = logging.getLogger(__name__)

SUFFIXES = {".ris": "ris", ".nbib": "nbib", ".bib": "bibtex",
            ".xml": "endnote-xml", ".json": "csl-json",
            # EndNote 自家的 .enw 与 .txt 导出都是 RIS 那类「标签 - 值」结构，
            # 交给 RIS 解析器兜住，认不出的字段忽略即可
            ".enw": "ris", ".txt": "ris"}

FORMAT_NAMES = {"ris": "RIS", "nbib": "MEDLINE/nbib", "bibtex": "BibTeX",
                "endnote-xml": "EndNote XML", "csl-json": "CSL JSON"}

# 一次导入的上限。真正的瓶颈是「一条记录一次 PubMed 查询」——没写 PMID 的那些，
# 上千条能跑很久，且中途出错不好收拾。超了就报错让用户分批，不偷偷截断。
MAX_REFS = 500

_PMID_RE = re.compile(r"^\d{1,9}$")
# "PMID: 39123456"、"PMID39123456"、"pmid=39123456" 都认。7~9 位是为了不把年份、
# 页码、ISSN 当成 PMID——PubMed 的 ID 早就过千万了。
_PMID_IN_TEXT = re.compile(r"PMID[:=\s]*\s*(\d{7,9})", re.IGNORECASE)
_PUBMED_URL = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{7,9})", re.IGNORECASE)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;]+)", re.IGNORECASE)


class RefError(ValueError):
    """文件读不了或格式认不出——信息可直接展示给用户。"""


def _clean_doi(raw: str) -> str:
    m = _DOI_RE.search(raw or "")
    if not m:
        return ""
    # 尾部常粘上句号、右括号，或 nbib 的 " [doi]" 标记
    return m.group(1).rstrip(".,;)]}").strip()


def _pmid_from_text(*chunks) -> str:
    for c in chunks:
        if not c:
            continue
        m = _PMID_IN_TEXT.search(str(c)) or _PUBMED_URL.search(str(c))
        if m:
            return m.group(1)
    return ""


def _ref(pmid: str = "", doi: str = "", title: str = "") -> dict:
    return {"pmid": (pmid or "").strip(), "doi": _clean_doi(doi),
            "title": re.sub(r"\s+", " ", (title or "")).strip().rstrip(".")}


# ─── 各格式解析 ───────────────────────────────────────────────────────────────

# RIS：两位标签 + 两空格 + 短横。EndNote 的 .enw 用 "%A" 这类单字母标签，也一并认。
_RIS_TAG = re.compile(r"^([A-Z][A-Z0-9])\s{1,2}-\s?(.*)$")
_ENW_TAG = re.compile(r"^%([A-Z0-9])\s(.*)$")


def _parse_ris(text: str) -> list[dict]:
    """RIS / .enw。

    PMID 可能出现在好几处，取决于导出方：PubMed 自己导出的放 AN（accession number），
    Zotero 把 Extra 字段整段塞进 N1，EndNote 有时写进 ID。所以宁可全扫一遍。
    """
    recs, cur, last = [], {}, None

    def flush():
        if cur:
            recs.append(dict(cur))
        cur.clear()

    for line in text.splitlines():
        m = _RIS_TAG.match(line.strip("﻿")) or _ENW_TAG.match(line.strip("﻿"))
        if m:
            tag, val = m.group(1), m.group(2).strip()
            last = tag
            if tag == "ER":                     # 记录结束
                flush(); last = None
                continue
            if tag == "TY" and cur:             # 有些导出漏掉 ER，靠下一条的 TY 断开
                flush()
            cur.setdefault(tag, []).append(val)
        elif line.strip() and last:
            # 续行（缩进或裸行）接到上一个标签后面
            cur[last][-1] += " " + line.strip()
    flush()

    out = []
    for r in recs:
        def g(*tags):
            for t in tags:
                if r.get(t):
                    return r[t][0]
            return ""
        blob = " ".join(v for vs in r.values() for v in vs)
        pmid = ""
        # AN/ID/M 本身就是数字时直接当 PMID，否则再去正文里找 "PMID: xxx"
        for cand in (g("AN"), g("ID"), g("M")):
            if _PMID_RE.match(cand.strip()) and len(cand.strip()) >= 7:
                pmid = cand.strip()
                break
        out.append(_ref(pmid or _pmid_from_text(blob),
                        g("DO", "R", "DI") or blob,
                        g("TI", "T1", "T", "CT")))
    return out


_MEDLINE_TAG = re.compile(r"^([A-Z]{2,4})\s*-\s?(.*)$")


def _parse_nbib(text: str) -> list[dict]:
    """MEDLINE/nbib（PubMed 官方导出，EndNote 也能读）。续行以空格开头。"""
    recs, cur, last = [], {}, None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[:1].isspace() and last:
            cur[last][-1] += " " + line.strip()
            continue
        m = _MEDLINE_TAG.match(line.strip("﻿"))
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "PMID" and cur:               # 新记录以 PMID 开头
            recs.append(cur); cur = {}
        cur.setdefault(tag, []).append(val)
        last = tag
    if cur:
        recs.append(cur)

    out = []
    for r in recs:
        # DOI 在 AID/LID 里，一行一个标识符，只有带 [doi] 的那行是 DOI
        doi = ""
        for v in r.get("AID", []) + r.get("LID", []):
            if "[doi]" in v.lower():
                doi = v
                break
        out.append(_ref((r.get("PMID") or [""])[0], doi, (r.get("TI") or [""])[0]))
    return out


_BIB_ENTRY = re.compile(r"@\w+\s*\{", re.IGNORECASE)


def _bib_entries(text: str) -> list[str]:
    """按花括号配对切出每条 BibTeX 记录（字段值里也可能有花括号，不能按行切）。"""
    out = []
    for m in _BIB_ENTRY.finditer(text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out.append(text[m.end():i])
    return out


_BIB_FIELD = re.compile(r"(\w+)\s*=\s*(\{|\")", re.DOTALL)


def _parse_bibtex(text: str) -> list[dict]:
    """BibTeX。PMID 看 pmid 字段（Better BibTeX 会写）、note/annote 里的 "PMID: x"。"""
    out = []
    for body in _bib_entries(text):
        fields = {}
        for m in _BIB_FIELD.finditer(body):
            name, opener = m.group(1).lower(), m.group(2)
            i, depth, buf = m.end(), 1, []
            while i < len(body):
                ch = body[i]
                if opener == "{":
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                elif ch == '"' and body[i - 1] != "\\":
                    break
                buf.append(ch)
                i += 1
            fields[name] = "".join(buf).strip()
        blob = " ".join(fields.values())
        out.append(_ref(fields.get("pmid", "").strip()
                        or _pmid_from_text(fields.get("note"), fields.get("annote"),
                                           fields.get("keywords"), fields.get("url"),
                                           blob),
                        fields.get("doi") or blob,
                        # 花括号在 BibTeX 里是保护大小写用的（{HFpEF}），不是标题的一部分，
                        # 留着会让「按标题查 PubMed」这条路必然落空
                        re.sub(r"[{}]", "", fields.get("title") or "")))
    return out


def _parse_endnote_xml(text: str) -> list[dict]:
    """EndNote XML。

    字段文字常被 <style> 包一层（字体、大小），所以一律用 itertext 取全文，
    不能只读 element.text——只读 text 会拿到空串，全库都变成「认不出」。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise RefError(f"EndNote XML 解析失败：{e}") from None

    def txt(node) -> str:
        return " ".join(t.strip() for t in node.itertext() if t.strip()) if node is not None else ""

    out = []
    for rec in root.iter("record"):
        title = ""
        for path in ("titles/title", "titles/secondary-title"):
            node = rec.find(path)
            if txt(node):
                title = txt(node)
                break
        acc = txt(rec.find("accession-num"))
        pmid = acc if _PMID_RE.match(acc) and len(acc) >= 7 else ""
        blob = " ".join(txt(rec.find(p)) for p in
                        ("notes", "custom1", "custom2", "custom3", "custom4",
                         "urls", "remote-database-name", "electronic-resource-num"))
        out.append(_ref(pmid or _pmid_from_text(blob),
                        txt(rec.find("electronic-resource-num")) or blob,
                        title))
    return out


def _parse_csl_json(text: str) -> list[dict]:
    """CSL JSON（Zotero 的「CSL JSON」导出）。PMID 多半在 note 里："PMID: 123"。"""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise RefError(f"JSON 解析失败：{e}") from None
    if isinstance(data, dict):
        data = data.get("items") or [data]
    if not isinstance(data, list):
        raise RefError("这个 JSON 不是 CSL JSON（应当是一个记录数组）")

    out = []
    for it in data:
        if not isinstance(it, dict):
            continue
        title = it.get("title")
        if isinstance(title, dict):                 # 少数导出把 title 写成对象
            title = title.get("main") or ""
        out.append(_ref(str(it.get("PMID") or it.get("pmid") or "").strip()
                        or _pmid_from_text(it.get("note"), it.get("URL")),
                        str(it.get("DOI") or it.get("doi") or ""),
                        str(title or "")))
    return out


_PARSERS = {"ris": _parse_ris, "nbib": _parse_nbib, "bibtex": _parse_bibtex,
            "endnote-xml": _parse_endnote_xml, "csl-json": _parse_csl_json}


def sniff(text: str, suffix: str = "") -> str:
    """认格式：先看扩展名，再看内容——扩展名骗人的情况太常见（RIS 存成 .txt）。"""
    head = text.lstrip("﻿ \t\r\n")[:4000]
    by_content = ""
    if head.startswith(("[", "{")):
        by_content = "csl-json"
    elif head.startswith("<"):
        by_content = "endnote-xml"
    elif _BIB_ENTRY.search(head):
        by_content = "bibtex"
    elif re.search(r"^PMID\s*-\s*\d", head, re.M):
        by_content = "nbib"
    elif re.search(r"^(TY\s{0,2}-|%0\s)", head, re.M):
        by_content = "ris"
    fmt = SUFFIXES.get(suffix.lower(), "")
    # 内容说了算：.xml 里装着 CSL JSON 这种事不会发生，但 .txt/.ris 里装着别的很常见
    return by_content or fmt or ""


def parse_text(text: str, name: str = "", suffix: str = "") -> tuple[str, list[dict]]:
    """解析已经读进来的文本，返回 (格式, 记录列表)。网页那条路直接送文本进来。"""
    name = name or "这个文件"
    fmt = sniff(text, suffix)
    if not fmt:
        raise RefError(
            f"认不出 {name} 的格式。支持：RIS(.ris)、MEDLINE/nbib(.nbib)、"
            f"BibTeX(.bib)、EndNote XML(.xml)、CSL JSON(.json)。\n"
            f"  在 Zotero 里：右键条目 → 导出条目 → 格式选 RIS；\n"
            f"  在 EndNote 里：File → Export → Output style 选 RefMan (RIS) Export。")
    refs = [r for r in _PARSERS[fmt](text) if r["pmid"] or r["doi"] or r["title"]]
    if not refs:
        raise RefError(f"{name} 按 {FORMAT_NAMES[fmt]} 解析出 0 条记录，"
                       f"文件是不是空的、或者导出时选错了格式？")
    if len(refs) > MAX_REFS:
        raise RefError(f"这个文件有 {len(refs)} 条，超过一次 {MAX_REFS} 条的上限。"
                       f"没写 PMID 的记录每条都要回 PubMed 查一次，跑起来很久。"
                       f"请在 Zotero/EndNote 里分批导出。")
    return fmt, refs


def read_file(path) -> tuple[str, list[dict]]:
    """读一个导出文件，返回 (格式名, 记录列表)。"""
    p = Path(path).expanduser()
    if not p.is_file():
        raise RefError(f"文件不存在：{p}")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # EndNote 在 Windows 上导出的 RIS 常是 UTF-16 或 latin-1
        for enc in ("utf-16", "latin-1"):
            try:
                text = p.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise RefError(f"文件编码认不出来：{p}") from None
    except OSError as e:
        raise RefError(f"读不了这个文件：{e}") from None

    return parse_text(text, p.name, p.suffix)


# ─── 落到 PMID ────────────────────────────────────────────────────────────────

def resolve(refs: list[dict], *, on_each=None) -> dict:
    """把记录落成 PMID 列表。返回 {"pmids", "how", "unresolved"}。

    on_each(i, total, ref, pmid, how) 是进度回调——DOI/标题那两条路要联网，
    几百条能跑上几分钟，没有回显的话用户只能干等。
    """
    pmids: list[str] = []
    how = {"pmid": 0, "doi": 0, "title": 0}
    unresolved = []
    for i, r in enumerate(refs, 1):
        pmid, why = "", ""
        if r["pmid"]:
            pmid, why = r["pmid"], "pmid"
        elif r["doi"]:
            try:
                pmid = entrez.pmid_by_doi(r["doi"])
                why = "doi"
            except Exception as e:                      # noqa: BLE001
                log.warning(f"按 DOI 查 PMID 失败（{r['doi']}）：{entrez.mask_secret(e)}")
        if not pmid and r["title"]:
            try:
                pmid = intake.find_pmid_by_title(r["title"])
                why = "title"
            except intake.IntakeError as e:
                why = str(e)
            except Exception as e:                      # noqa: BLE001
                why = f"查询失败：{entrez.mask_secret(e)}"
        if on_each:
            on_each(i, len(refs), r, pmid, why)
        if not pmid:
            unresolved.append({**r, "why": why or "文件里既没有 PMID/DOI，也没有标题"})
            continue
        how[why] = how.get(why, 0) + 1
        if pmid not in pmids:
            pmids.append(pmid)
    return {"pmids": pmids, "how": how, "unresolved": unresolved}
