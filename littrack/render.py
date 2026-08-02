"""HTML 报告渲染。周报与历史检索共用同一套模板。"""
from __future__ import annotations

import datetime
import html
import json
from pathlib import Path


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


_CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
 "Hiragino Sans GB","Microsoft YaHei",sans-serif;margin:0;padding:24px;
 background:#f6f7f9;color:#222;line-height:1.55}
h1{font-size:22px;margin:0 0 4px}
.meta{color:#666;font-size:13px;margin-bottom:18px}
.sec{background:#fff;border:1px solid #ddd;border-radius:6px;margin-bottom:14px;
 overflow:hidden}
.sec>summary{cursor:pointer;padding:11px 14px;font-weight:600;font-size:15px;
 background:#f0f4f8;border-bottom:1px solid #e2e6ea;user-select:none}
.sec>summary::marker{color:#8aa}
.sub{padding:2px 14px 10px}
.sub-h{font-size:13px;font-weight:600;color:#0056b3;margin:12px 0 6px;
 padding-bottom:3px;border-bottom:1px dashed #dde}
.art{padding:8px 0;border-bottom:1px solid #f2f2f2}
.art:last-child{border-bottom:none}
.art a{color:#0b57d0;text-decoration:none;font-weight:600;font-size:14px}
.art a:hover{text-decoration:underline}
.zh{font-size:13px;color:#555;font-weight:600;margin-top:2px}
.line{font-size:11.5px;color:#888;margin-top:2px}
.badge{display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;
 margin-right:5px;vertical-align:middle;font-weight:600}
.b-type{background:#e3f0fb;color:#1a5276}
.b-q1{background:#e8f5e9;color:#1b5e20}
.b-q2{background:#fff8e1;color:#8d6e00}
.b-if{background:#f3e5f5;color:#6a1b9a}
.b-j{color:#444;font-style:italic;font-size:12.5px}
.abs-t{color:#0b57d0;cursor:pointer;font-size:11.5px;user-select:none}
.abs{display:none;font-size:12px;color:#444;background:#fafbfc;border-left:3px solid #dde;
 padding:7px 10px;margin-top:5px;border-radius:0 3px 3px 0}
.abs.open{display:block}
.empty{color:#999;padding:14px;font-size:13px}
"""

_JS = """
function toggleAbs(id){var e=document.getElementById(id);
 if(e)e.classList.toggle('open');}
"""


def render(config, grouped: dict, start: str, end: str, out_path: Path,
           subtitle: str = "") -> Path:
    total = sum(len(v) for subs in grouped.values() for v in subs.values())
    parts = [
        f"<!doctype html><html lang=zh-CN><head><meta charset=utf-8>",
        f"<meta name=viewport content='width=device-width,initial-scale=1'>",
        f"<title>{_esc(config.project_name)} {start}~{end}</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>{_esc(config.project_name)}</h1>",
        f"<div class=meta>检索区间 {start} ~ {end} &nbsp;|&nbsp; 共 <strong>{total}</strong> 篇"
        f"{' &nbsp;|&nbsp; ' + _esc(subtitle) if subtitle else ''}"
        f" &nbsp;|&nbsp; 生成于 {datetime.datetime.now():%Y-%m-%d %H:%M}</div>",
    ]

    if not total:
        parts.append("<div class=empty>本区间未检索到符合条件的文献。</div>")

    for sec_name, subs in grouped.items():
        n = sum(len(v) for v in subs.values())
        parts.append(f"<details class=sec open><summary>{_esc(sec_name)} · {n} 篇</summary>")
        for sub_name, arts in subs.items():
            parts.append(f"<div class=sub><div class=sub-h>{_esc(sub_name)} · {len(arts)}</div>")
            for a in arts:
                aid = f"ab{a['pmid']}"
                url = f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"
                badges = ""
                if a.get("type_label"):
                    badges += f"<span class='badge b-type'>{_esc(a['type_label'])}</span>"
                if a.get("quartile") in ("Q1", "Q2"):
                    cls = "b-q1" if a["quartile"] == "Q1" else "b-q2"
                    badges += f"<span class='badge {cls}'>{a['quartile']}</span>"
                if a.get("if_value"):
                    badges += f"<span class='badge b-if'>IF {_esc(a['if_value'])}</span>"
                kw = "; ".join(a.get("keywords") or []) or "—"
                parts.append(
                    f"<div class=art>{badges}"
                    f"<a href='{url}' target=_blank rel=noopener>{_esc(a['title'])}</a>"
                    + (f"<div class=zh>{_esc(a['title_zh'])}</div>" if a.get("title_zh") else "")
                    + f"<div class=line><span class=b-j>{_esc(a.get('journal') or a.get('journal_full'))}</span>"
                      f" &nbsp;·&nbsp; {_esc(a.get('pub_date'))}</div>"
                    + f"<div class=line>关键词：{_esc(kw)}</div>"
                    + (f"<div class=line>通讯单位：{_esc(a['affiliation'])}</div>"
                       if a.get("affiliation") else "")
                    + (f"<div class=abs-t onclick=\"toggleAbs('{aid}')\">▶ 摘要</div>"
                       f"<div class=abs id={aid}>{a['abstract']}</div>"
                       if a.get("abstract") else "")
                    + "</div>")
            parts.append("</div>")
        parts.append("</details>")

    parts.append(f"<script>{_JS}</script></body></html>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(parts), encoding="utf-8")
    return out_path
