"""库内引文网络：收藏库里的文章之间，谁引用了谁。

回答的是「我收藏的这批文献里，哪几篇是被反复引用的基石」——**不是**全局引文图谱。
做法：取每篇的参考文献列表，与库内 PMID 求交集，得到正向的 `cites`；
再由所有正向关系汇总出反向的 `cited_by`。另外批量刷一次全球被引数。

数据源是 Semantic Scholar 的 Academic Graph API：PubMed 自己不提供参考文献列表，
而 S2 支持直接用 `PMID:xxx` 寻址，省掉一层 DOI 转换。

限速是这里最主要的工程约束：不带 key 走的是所有匿名用户共享的池子，429 很频繁，
几百篇要跑很久。所以：
  · 每篇抓完立即写库，中断不丢已抓的部分；
  · 再跑时自动跳过抓过的（`citations_synced` 非空），只补新增的；
  · 429 分级退避，无 key 时等得更久；
  · 抓失败的不盖日期戳，下次续跑自然重试。
申请 key（免费）：https://www.semanticscholar.org/product/api
"""
from __future__ import annotations

import logging
import os
import time

import requests

from . import library

log = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1/paper"
_BATCH = 500          # /paper/batch 单次上限
_TIMEOUT = 30


def _key() -> str:
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip()


def has_key() -> bool:
    return bool(_key())


def _headers() -> dict:
    k = _key()
    return {"x-api-key": k} if k else {}


def _waits() -> list[int]:
    # 无 key 时是共享池，退避必须更狠，否则只是继续撞墙
    return [10, 20, 30] if has_key() else [60, 120, 120]


def _pace() -> float:
    return 0.3 if has_key() else 1.1


def references(pmid: str) -> tuple[list[str], str]:
    """取该文的参考文献 PMID 列表。返回 (pmids, status)，status ∈ ok/missing/error。"""
    url = f"{S2_BASE}/PMID:{pmid}/references"
    waits = _waits()
    for attempt in range(len(waits) + 1):
        try:
            r = requests.get(url, params={"fields": "externalIds", "limit": 500},
                             headers=_headers(), timeout=_TIMEOUT)
        except requests.exceptions.RequestException as e:
            log.debug(f"PMID {pmid} 请求异常：{e}")
            if attempt < len(waits):
                time.sleep(5)
                continue
            return [], "error"
        if r.status_code == 200:
            out = []
            for ref in r.json().get("data") or []:
                ext = (ref.get("citedPaper") or {}).get("externalIds") or {}
                if ext.get("PubMed"):
                    out.append(str(ext["PubMed"]))
            return out, "ok"
        if r.status_code == 404:
            return [], "missing"          # S2 没收录这篇，不是错误
        if r.status_code == 429 and attempt < len(waits):
            w = waits[attempt]
            log.info(f"S2 限速，等待 {w}s…")
            time.sleep(w)
            continue
        log.debug(f"PMID {pmid} 返回 HTTP {r.status_code}")
        return [], "error"
    return [], "error"


def citation_counts(pmids: list[str]) -> dict[str, tuple]:
    """批量取全球被引数。返回 {pmid: (citation_count, influential_count)}。

    这两个数随时间增长，所以每次都全量刷；好在 batch 端点 500 个一批，请求数很少。
    """
    out: dict[str, tuple] = {}
    for i in range(0, len(pmids), _BATCH):
        chunk = pmids[i:i + _BATCH]
        waits = _waits()
        for attempt in range(len(waits) + 1):
            try:
                r = requests.post(
                    f"{S2_BASE}/batch",
                    params={"fields": "citationCount,influentialCitationCount"},
                    json={"ids": [f"PMID:{p}" for p in chunk]},
                    headers=_headers(), timeout=_TIMEOUT)
            except requests.exceptions.RequestException as e:
                log.warning(f"批量取被引数失败：{e}")
                break
            if r.status_code == 200:
                for pmid, obj in zip(chunk, r.json()):
                    if obj:               # S2 未收录时该位是 null，保持原值不动
                        out[pmid] = (obj.get("citationCount"),
                                     obj.get("influentialCitationCount"))
                break
            if r.status_code == 429 and attempt < len(waits):
                time.sleep(waits[attempt])
                continue
            log.warning(f"批量取被引数返回 HTTP {r.status_code}")
            break
        time.sleep(1.0)
    return out


def refresh(db_path, *, force: bool = False, on_progress=None) -> dict:
    """抓参考文献 → 建库内引用关系 → 刷全球被引数。

    on_progress(done, total, pmid, status, n_linked) 每篇调用一次，供 CLI 打进度。
    """
    targets = library.citation_targets(db_path, force=force)
    total_articles = len(library.all_articles(db_path))
    known = {a["pmid"] for a in library.all_articles(db_path)}

    ok = missing = failed = 0
    for i, pmid in enumerate(targets, 1):
        refs, status = references(pmid)
        linked: list[str] = []
        if status == "error":
            failed += 1                   # 不写 citations_synced，下次续跑重试
        else:
            linked = [p for p in refs if p in known and p != pmid]
            library.set_cites(db_path, pmid, linked)
            ok += status == "ok"
            missing += status == "missing"
        if on_progress:
            on_progress(i, len(targets), pmid, status, len(linked))
        time.sleep(_pace())

    cited = library.rebuild_cited_by(db_path)
    counts = citation_counts(sorted(known))
    library.set_citation_counts(db_path, counts)

    return {"total": total_articles, "targets": len(targets), "ok": ok,
            "missing": missing, "failed": failed, "cited": cited,
            "counts": len(counts)}
