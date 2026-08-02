"""联网校验配置：期刊名是否真实存在、关键词命中量是否合理。

这一步解决的是一个**静默失败**：期刊名写得不对（少个 the、用了缩写、多个空格）
时，PubMed 不会报错，只会一篇都搜不到。用户看到空报告，却不知道问题在哪。
关键词同理——太窄则常年颗粒无收，太宽则淹没在噪音里，事前看一眼命中量就能判断。
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import entrez, matchers

log = logging.getLogger(__name__)

_RECENT = '("2024/01/01"[dp] : "3000"[dp])'


@dataclass
class Finding:
    level: str          # ok | warn | error
    target: str
    count: int
    message: str = ""
    suggestion: str = ""


def _count(term: str) -> int:
    xml = entrez._request("esearch.fcgi", {"db": "pubmed", "term": term, "retmax": 0},
                          use_post=len(term) > 2000)
    if not xml:
        return -1
    try:
        return int(ET.fromstring(xml).findtext(".//Count", "0"))
    except Exception:
        return -1


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _suggest_journal(name: str, pause: float = 0.34) -> tuple[str, bool]:
    """期刊名查不到时，猜正确的 PubMed 刊名。

    返回 (候选名, 是否高置信)。高置信＝候选名去掉标点大小写后与输入**完全一致**
    （即用户只是标点/大小写写法不同）；否则只是"相近"，措辞要保守——
    一个听起来很确定但其实不对的建议，比不给建议更容易把人带偏。
    """
    tries = [name]
    # 常见缩写还原：Res→research、Cardiovasc→cardiovascular 之类
    expanded = name
    for a, b in (("Res\\b", "research"), ("Cardiovasc", "cardiovascular"),
                 ("Immunol", "immunology"), ("Oncol", "oncology"),
                 ("Rheumatol", "rheumatology"), ("Microbiol", "microbiology"),
                 ("Metab", "metabolism"), ("Neurosci", "neuroscience"),
                 ("Biol", "biology"), ("Med\\b", "medicine")):
        expanded = re.sub(a, b, expanded, flags=re.IGNORECASE)
    if _norm(expanded) != _norm(name):
        tries.append(expanded)

    for cand in tries:
        n = _count(f'"{cand}"[ta] AND {_RECENT}')
        time.sleep(pause)
        if n > 0:
            return cand, _norm(cand) != _norm(name)

    # 退一步：用词干去 [jour] 里模糊找，只作"相近"提示
    core = re.sub(r"\b(the|of|and|journal|official)\b", " ", name.lower())
    core = " ".join(w for w in core.split() if len(w) > 2)[:60]
    if not core:
        return "", False
    xml = entrez._request("esearch.fcgi",
                          {"db": "pubmed", "term": f"{core}[jour]", "retmax": 1},
                          use_post=False)
    time.sleep(pause)
    if not xml:
        return "", False
    ids = [el.text for el in ET.fromstring(xml).findall(".//Id") if el.text]
    if not ids:
        return "", False
    arts = entrez.efetch(ids)
    return (arts[0].get("journal_full", "") if arts else ""), False


def check_journals(config, *, pause: float = 0.34) -> list[Finding]:
    out: list[Finding] = []
    groups = (("全量收录", config.full_inclusion_journals),
              ("关键词筛选", config.keyword_filtered_journals))
    for label, mapping in groups:
        for name in mapping:
            n = _count(f'"{name}"[ta] AND {_RECENT}')
            time.sleep(pause)
            if n < 0:
                out.append(Finding("warn", f"[{label}] {name}", -1, "查询失败，稍后重试"))
            elif n == 0:
                sug, confident = _suggest_journal(name, pause)
                if sug and confident:
                    tip = f"改成「{sug}」即可（已确认这个名字能搜到）"
                elif sug:
                    tip = (f"PubMed 里有一本名字相近的：「{sug}」——**仅供参考，请自行确认**；"
                           f"稳妥做法是在 PubMed 搜一篇该刊文章，复制 Journal 字段的全名")
                else:
                    tip = "请在 PubMed 搜一篇该刊文章，复制 Journal 字段的全名"
                out.append(Finding("error", f"[{label}] {name}", 0,
                                   "PubMed 查不到这本刊（名字很可能不对）", tip))
            elif n < 20:
                out.append(Finding("warn", f"[{label}] {name}", n,
                                   "2024 年以来收录很少，确认刊名是否写全"))
            else:
                out.append(Finding("ok", f"[{label}] {name}", n))
    return out


def check_keywords(config, *, pause: float = 0.34) -> list[Finding]:
    """逐个关键词报命中量。0 命中＝拼写可疑；过高＝该词太宽，会淹没结果。"""
    out: list[Finding] = []
    for sec in config.sections:
        field = sec.search_field
        pool: list[tuple[str, str]] = [(f"{sec.name}·触发词", k)
                                       for k in sec.trigger_keywords]
        pool += [(f"{sec.name}·{sub.name}", k) for sub in sec.subsections
                 for k in (sub.cross_keywords if sec.matcher == "cross_product"
                           else sub.keywords)]
        pool += [(f"{sec.name}·板块词", k) for k in sec.keywords]
        for where, kw in pool:
            forms = matchers.query_forms(kw)
            term = "(" + entrez.or_terms(forms, field) + f") AND {_RECENT}"
            n = _count(term)
            time.sleep(pause)
            if n < 0:
                out.append(Finding("warn", f"{where} / {kw}", -1, "查询失败"))
            elif n == 0:
                out.append(Finding("error", f"{where} / {kw}", 0,
                                   "2024 年以来标题里一次都没出现过",
                                   "检查拼写；或该说法在文献里不常用，换个更通行的词"))
            elif n > 60000:
                out.append(Finding("warn", f"{where} / {kw}", n,
                                   "命中量极大，这个词可能太宽",
                                   "考虑换成更具体的说法，或改用「交叉」匹配加一侧限定"))
            else:
                out.append(Finding("ok", f"{where} / {kw}", n))
    return out


def report(findings: list[Finding]) -> tuple[int, int]:
    """打印结果，返回 (错误数, 警告数)。"""
    err = [f for f in findings if f.level == "error"]
    warn = [f for f in findings if f.level == "warn"]
    ok = [f for f in findings if f.level == "ok"]

    for f in findings:
        if f.level == "ok":
            continue
        mark = "✗" if f.level == "error" else "!"
        cnt = "查询失败" if f.count < 0 else f"{f.count} 篇"
        print(f"  {mark} {f.target}   {cnt}")
        if f.message:
            print(f"      {f.message}")
        if f.suggestion:
            print(f"      → {f.suggestion}")

    print(f"\n  正常 {len(ok)} 项 · 警告 {len(warn)} 项 · 错误 {len(err)} 项")
    if ok and not err and not warn:
        print("  全部通过。")
    return len(err), len(warn)
