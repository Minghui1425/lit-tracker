"""HTML 报告渲染。周报与历史检索共用同一套模板。"""
from __future__ import annotations

import datetime
import html
import json
from pathlib import Path


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _json_for_script(value) -> str:
    """内联到 <script> 里的序列化，堵住 ``</script>`` 逃逸。"""
    return (json.dumps(value, ensure_ascii=False)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029"))


# 一次加入收藏库的上限，与 intake.MAX_PMIDS 对齐（每篇都要回 PubMed 取元数据，
# 一次几百篇会把请求拖到超时）。这里只作提示，服务端仍会自己再挡一道。
ADD_MAX = 50


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
.bar{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px 14px;
 margin-bottom:14px;font-size:13px;display:flex;align-items:center;gap:10px;
 flex-wrap:wrap}
.bar button{padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;
 background:#fff;border:1px solid #ccc;color:#555}
.bar button:hover{background:#f5f5f5}
.bar button:disabled{opacity:.5;cursor:default}
#add-lib{color:#0056b3;border-color:#0056b3}
#add-lib:hover{background:#e8f0fe}
#sel-n{color:#666}
.art{position:relative}
.art-cb{margin-right:7px;vertical-align:middle;cursor:pointer}
"""

_JS = """
function toggleAbs(id){var e=document.getElementById(id);
 if(e)e.classList.toggle('open');}
function checked(){return Array.prototype.slice.call(
  document.querySelectorAll('.art-cb:checked'));}
function count(){
  var n=checked().length;
  document.getElementById('sel-n').textContent = n?('已选 '+n+' 篇'):'未选';
  document.getElementById('add-lib').disabled = !n;
}
function selAll(on){
  document.querySelectorAll('.art-cb').forEach(function(c){c.checked=on;});
  count();
}
// 服务没起来时退回老路子：把等价的命令行复制给用户，功能不至于全丢。
function fallback(pmids, err){
  var cmd = 'python3 cli.py add --config <你的配置> --pmid ' + pmids.join(' ');
  var tip = '加入失败：' + err.message +
    '\\n（收藏库服务没起来？先在项目目录执行 python3 cli.py serve --config <你的配置>）' +
    '\\n已把等价命令复制到剪贴板：\\n' + cmd;
  var ta=document.createElement('textarea');
  ta.value=cmd; ta.style.position='fixed'; ta.style.opacity='0';
  document.body.appendChild(ta); ta.select();
  try{document.execCommand('copy'); alert(tip);}
  catch(e){alert('加入失败：'+err.message+'\\n请手动复制命令：\\n'+cmd);}
  document.body.removeChild(ta);
}
function addToLibrary(){
  var cbs=checked();
  if(!cbs.length){alert('尚未勾选任何文献');return;}
  if(cbs.length>ADD_MAX){
    alert('一次最多加入 '+ADD_MAX+' 篇，这次勾了 '+cbs.length+' 篇。分几批来。');
    return;
  }
  // 板块/子板块直接取自本页：这些文章在生成报告时已经按当时的配置归好类了，
  // 服务端照用即可，不必再判一次（配置改过时，以你眼前这份报告为准）。
  var items=cbs.map(function(c){return {pmid:c.dataset.pmid,
    section:c.dataset.sec||'', subsection:c.dataset.sub||''};});
  var btn=document.getElementById('add-lib'), label=btn.textContent;
  btn.disabled=true; btn.textContent='正在加入…';
  fetch(API+'/article/add-from-report',{
    method:'POST',
    headers:{'Content-Type':'application/json','X-LitTrack-Token':TOKEN},
    body:JSON.stringify({items:items})
  }).then(function(r){
    return r.text().then(function(t){
      if(!r.ok) throw new Error(t||('HTTP '+r.status));
      return JSON.parse(t);
    });
  }).then(function(d){
    var msg='已加入收藏库 '+d.added+' 篇';
    if(d.updated) msg+='，'+d.updated+' 篇原本就在库里（已刷新元数据，笔记与评级保留）';
    if(d.missing&&d.missing.length) msg+='\\nPubMed 没有这些 PMID：'+d.missing.join(' ');
    if(d.pdf_fetched) msg+='\\n顺带抓到 '+d.pdf_fetched+' 篇 OA 全文';
    alert(msg);
  }).catch(function(e){
    fallback(items.map(function(i){return i.pmid;}), e);
  }).then(function(){
    btn.disabled=false; btn.textContent=label; count();
  });
}
"""


def render(config, grouped: dict, start: str, end: str, out_path: Path,
           subtitle: str = "", *, port: int = 8765, token: str = "") -> Path:
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

    if total:
        # 勾选 → 一键入库。收藏库服务（cli.py serve）没起来时按钮会退回复制命令，
        # 所以这排按钮在双击打开的 file:// 页面上也不算废掉。
        parts.append(
            "<div class=bar>"
            "<button onclick='selAll(true)'>全选</button>"
            "<button onclick='selAll(false)'>取消全选</button>"
            "<button id=add-lib disabled onclick='addToLibrary()'>加入收藏库</button>"
            "<span id=sel-n>未选</span>"
            "<span style='color:#999'>（需要 <code>cli.py serve</code> 开着）</span>"
            "</div>")
    else:
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
                    f"<div class=art>"
                    f"<input type=checkbox class=art-cb onchange='count()'"
                    f" data-pmid='{_esc(a['pmid'])}'"
                    f" data-sec='{_esc(sec_name)}' data-sub='{_esc(sub_name)}'>"
                    f"{badges}"
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

    # 从 http://127.0.0.1:PORT/ 打开时用同源相对路径；双击 file:// 打开时回落到绝对地址
    consts = (f"const PORT={int(port)};"
              f"const TOKEN={_json_for_script(token)};"
              f"const ADD_MAX={ADD_MAX};"
              "const API=(location.protocol==='http:'||location.protocol==='https:')"
              "?'':'http://127.0.0.1:'+PORT;")
    parts.append(f"<script>{consts}{_JS}</script></body></html>")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(parts), encoding="utf-8")
    return out_path
