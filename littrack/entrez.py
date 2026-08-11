"""PubMed E-utilities 客户端。与领域无关，可直接复用。

要点：
- 长查询自动走 POST：关键词一多，GET 的 URL 会超长触发 414。
- 异常信息统一脱敏：Entrez 报错会带完整 URL（含 api_key），不能直接进日志。
"""
from __future__ import annotations

import logging
import os
import re
import time
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger(__name__)

ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
RETMAX = 9999
_URL_LIMIT = 2000        # 超过就改用 POST

# 含 api_key / email 的字符串脱敏，避免密钥随异常进日志
_SECRET_RE = re.compile(r'((?:api_key|email)=)[^&\s]+', re.IGNORECASE)


def mask_secret(text) -> str:
    return _SECRET_RE.sub(r'\1***', str(text))


class NetworkError(RuntimeError):
    """重试耗尽后仍连不上 NCBI。单独立类型，便于入口层给出友好提示而不吞掉真 bug。"""


_SESSION = requests.Session()
_SESSION.headers.update({"Connection": "keep-alive"})


def _api_key() -> str:
    return os.environ.get("NCBI_API_KEY", "")


# NCBI 的 E-utilities 使用规范要求每个请求带 tool 与 email：出问题时他们据此联系你，
# 而不是直接封 IP。email 缺失只警告一次，不阻断——但请求量大时强烈建议配上。
TOOL = "lit-tracker"
_warned_no_email = False


def _email() -> str:
    global _warned_no_email
    e = os.environ.get("NCBI_EMAIL", "").strip()
    if not e and not _warned_no_email:
        _warned_no_email = True
        log.warning("未设置 NCBI_EMAIL。NCBI 的使用规范要求请求带联系邮箱，"
                    "以便异常时联系你而非直接限流。请在 .env 里加：NCBI_EMAIL=你的邮箱")
    return e


def _request(endpoint: str, params: dict, *, use_post: bool,
             retries: int = 8, wait: int = 8) -> str | None:
    params = dict(params)
    params.update({"api_key": _api_key(), "retmode": "xml", "tool": TOOL})
    email = _email()
    if email:
        params["email"] = email
    url = ENTREZ_BASE + endpoint
    for attempt in range(retries):
        try:
            if use_post:
                r = _SESSION.post(url, data=params, timeout=30)
            else:
                r = _SESSION.get(url, params=params, timeout=30)
            if r.status_code == 504:
                raise requests.exceptions.Timeout("504 Gateway Timeout")
            r.raise_for_status()
            return r.text
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError, requests.exceptions.SSLError) as e:
            log.warning(f"Entrez 第 {attempt+1}/{retries} 次请求失败：{mask_secret(e)}")
            if attempt < retries - 1:
                _SESSION.close()
                time.sleep(wait)
            else:
                raise NetworkError(mask_secret(e)) from None
        except requests.exceptions.RequestException as e:
            # 其余请求异常重试也不会好转，直接转成 NetworkError 交给入口层提示
            raise NetworkError(mask_secret(e)) from None
    return None


def esearch(term: str, retmax: int = RETMAX) -> list[str]:
    """按检索式取 PMID 列表。查询过长时自动改用 POST。"""
    xml = _request("esearch.fcgi", {"db": "pubmed", "term": term, "retmax": retmax},
                   use_post=len(term) > _URL_LIMIT)
    if not xml:
        return []
    root = ET.fromstring(xml)
    ids = [el.text for el in root.findall(".//Id") if el.text]
    if len(ids) >= retmax:
        log.warning(f"结果数达到上限 retmax={retmax}，可能被截断。检索式片段：{term[:120]}…")
    return ids


def pmc_ids(pmids: list[str], batch: int = 180) -> dict:
    """PMID → PMCID。没有 PMC 版本的不出现在结果里。

    id 必须**重复传参**（id=1&id=2），不能逗号拼接：逗号形式会被 NCBI 合并成一个
    linkset，links 是所有输入的并集，按位置回填就会把别人的 PMCID 安到本篇头上，
    进而下载到完全不相干的 PDF。
    """
    out: dict[str, str] = {}
    for i in range(0, len(pmids), batch):
        chunk = [str(p) for p in pmids[i:i + batch]]
        params = {"dbfrom": "pubmed", "db": "pmc", "id": chunk,
                  "api_key": _api_key(), "tool": TOOL, "retmode": "json"}
        email = _email()
        if email:
            params["email"] = email
        try:
            r = _SESSION.get(ENTREZ_BASE + "elink.fcgi", params=params, timeout=40)
            r.raise_for_status()
            for ls in r.json().get("linksets", []):
                src = (ls.get("ids") or [None])[0]
                for db in ls.get("linksetdbs", []):
                    if db.get("linkname") == "pubmed_pmc" and db.get("links"):
                        out[str(src)] = "PMC" + str(db["links"][0])
        except (requests.RequestException, ValueError) as e:
            log.warning(f"elink 查 PMCID 失败：{mask_secret(e)}")
        time.sleep(0.2)
    return out


def efetch(pmids: list[str], batch: int = 200) -> list[dict]:
    """按 PMID 批量取文献详情。"""
    out: list[dict] = []
    for i in range(0, len(pmids), batch):
        chunk = pmids[i:i + batch]
        xml = _request("efetch.fcgi",
                       {"db": "pubmed", "id": ",".join(chunk), "rettype": "xml"},
                       use_post=True)
        if xml:
            out.extend(parse_articles(xml))
        time.sleep(0.12)
    return out


# ─── XML 解析 ─────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _extract_pub_date(node) -> str:
    """优先取正式出版日期，缺失时回退到 Entrez 收录日期。"""
    for path in (".//ArticleDate", ".//PubDate"):
        el = node.find(path)
        if el is None:
            continue
        y = el.findtext("Year", "")
        m = el.findtext("Month", "") or "01"
        d = el.findtext("Day", "") or "01"
        if not y:
            medline = el.findtext("MedlineDate", "")
            mm = re.match(r"(\d{4})", medline or "")
            if mm:
                return f"{mm.group(1)}-01-01"
            continue
        months = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05",
                  "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
                  "nov": "11", "dec": "12"}
        m = months.get(m[:3].lower(), m if m.isdigit() else "01")
        return f"{y}-{int(m):02d}-{int(d) if d.isdigit() else 1:02d}"
    return ""


def _corresponding_affiliation(node) -> str:
    """通讯单位：优先带邮箱标记的单位，找不到则用末位作者的单位。"""
    affs = []
    for au in node.findall(".//Author"):
        for af in au.findall(".//AffiliationInfo/Affiliation"):
            if af.text:
                affs.append(af.text.strip())
    if not affs:
        return ""
    for a in affs:
        if "@" in a:
            return a
    return affs[-1]


def parse_articles(xml_text: str) -> list[dict]:
    articles = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.error(f"XML 解析失败：{e}")
        return articles

    for node in root.findall(".//PubmedArticle"):
        pmid_el = node.find(".//PMID")
        if pmid_el is None:
            continue

        ti = node.find(".//ArticleTitle")
        title = "".join(ti.itertext()).strip() if ti is not None else ""

        parts = []
        for ab in node.findall(".//AbstractText"):
            label = ab.get("Label", "")
            txt = _esc("".join(ab.itertext()).strip())
            parts.append(f"{_esc(label)}<br>{txt}" if label else txt)

        issns = {el.text.strip().replace("-", "") for el in node.findall(".//ISSN") if el.text}
        linking = node.findtext(".//ISSNLinking", "")
        if linking:
            issns.add(linking.strip().replace("-", ""))

        authors = []
        for au in node.findall(".//Author"):
            last, fore = au.findtext("LastName", ""), au.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {fore}".strip())

        articles.append({
            "pmid":        pmid_el.text,
            "title":       title,
            "journal_full": node.findtext(".//Journal/Title", "") or "",
            "journal_abbr": node.findtext(".//ISOAbbreviation", "") or "",
            "pub_date":    _extract_pub_date(node),
            "abstract":    "<br><br>".join(parts),
            "keywords":    [kw.text.strip() for kw in node.findall(".//Keyword") if kw.text],
            "pub_types":   [pt.text for pt in node.findall(".//PublicationType") if pt.text],
            "affiliation": _corresponding_affiliation(node),
            "authors":     authors,
            "issns":       issns,
            "doi":         next((el.text for el in node.findall(".//ArticleId")
                                 if el.get("IdType") == "doi" and el.text), ""),
        })
    return articles


# ─── 检索式构造 ───────────────────────────────────────────────────────────────

def date_range_query(start: str, end: str) -> str:
    """[dp] 日期区间，start/end 形如 2026-07-01。"""
    return f'("{start.replace("-", "/")}"[dp] : "{end.replace("-", "/")}"[dp])'


def or_terms(keywords: list[str], field: str = "ti") -> str:
    return " OR ".join(f'"{kw}"[{field}]' for kw in keywords)
