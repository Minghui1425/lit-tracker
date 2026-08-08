"""收藏库 index.html 渲染。

板块 / 子板块 / 项目的下拉选项与排序**全部从配置生成**，模板里不出现任何
学科相关的名字——换个配置就是另一个学科的收藏库。
"""
from __future__ import annotations

import datetime
import html
import json
from pathlib import Path

from . import library


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _json_for_script(value) -> str:
    """Serialize data for an inline script without allowing ``</script>`` escapes."""
    return (json.dumps(value, ensure_ascii=False)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


_CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
 "Hiragino Sans GB","Microsoft YaHei",sans-serif;margin:0;padding:22px;
 background:#f6f7f9;color:#222;line-height:1.5}
h1{font-size:21px;margin:0 0 4px}
.meta{color:#666;font-size:13px;margin-bottom:14px}
.bar{background:#fff;border:1px solid #ddd;border-radius:6px;padding:11px 14px;
 margin-bottom:14px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.grp{display:flex;align-items:center;gap:4px}
.bar label{font-size:12px;color:#555;font-weight:600;white-space:nowrap}
.bar select,.bar input[type=text]{font-size:13px;padding:4px 8px;border:1px solid #ccc;
 border-radius:4px;outline:none}
.bar input[type=text]{width:170px}
.bar select:focus,.bar input:focus{border-color:#0b57d0}
.btn{padding:4px 12px;font-size:12px;border:1px solid #ccc;background:#fff;
 border-radius:4px;cursor:pointer;white-space:nowrap}
.btn-p{border-color:#1a7f5a;color:#1a7f5a}
.btn-d{border-color:#c0392b;color:#c0392b}
.btn-o{border-color:#6c4ab6;color:#6c4ab6}
.btn-b{border-color:#0056b3;color:#0056b3}
.rl{font-weight:400!important;color:#333;display:flex;align-items:center;gap:3px}
.vr{width:1px;height:18px;background:#ddd;margin:0 2px}
.row-break{flex-basis:100%;display:flex;align-items:center;gap:10px}
#cnt{font-size:13px;color:#666;margin-bottom:8px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #ddd;
 border-radius:6px;overflow:hidden;font-size:13px}
th{background:#f0f4f8;padding:8px 10px;text-align:left;border-bottom:2px solid #ddd;
 font-size:12px;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #f0f0f0;vertical-align:top}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f8fbff}
.b{display:inline-block;font-size:11px;padding:1px 6px;border-radius:3px;
 margin-right:5px;font-weight:600;vertical-align:middle}
.b-sec{background:#eef2f7;color:#33506e}
.b-sub{background:#f4f4f6;color:#666}
.b-type{background:#e3f0fb;color:#1a5276}
.b-q1{background:#e8f5e9;color:#1b5e20}.b-q2{background:#fff8e1;color:#8d6e00}
.b-if{background:#f3e5f5;color:#6a1b9a}
.b-proj{background:#e6f5ef;color:#1a7f5a;border:1px solid #b7e0cd;border-radius:9px}
.b-cit{background:#fdece8;color:#a03a22;cursor:pointer}
.b-cc{background:#eceff1;color:#455a64}
.citers{display:none;font-size:12px;background:#fdfbfa;border-left:3px solid #f0cfc4;
 padding:6px 9px;margin-top:4px}
.citers.open{display:block}
.citers a{color:#0b57d0;text-decoration:none}
a.ti{color:#0b57d0;text-decoration:none;font-weight:600}
a.ti:hover{text-decoration:underline}
.zh{font-size:12px;color:#555;font-weight:600;margin-top:2px}
.ln{font-size:11px;color:#888;margin-top:2px}
.abs-t{color:#0b57d0;cursor:pointer;font-size:11px}
.abs{display:none;font-size:12px;color:#444;background:#fafbfc;border-left:3px solid #dde;
 padding:6px 9px;margin-top:4px}
.abs.open{display:block}
.rt{font-size:13px;cursor:pointer;background:none;border:none;padding:0 2px;opacity:.35}
.rt:hover{opacity:1}
.rt.on{opacity:1}
textarea{width:100%;font-size:12px;padding:4px 6px;border:1px solid #ddd;border-radius:4px;
 resize:vertical;min-height:30px;font-family:inherit;margin-top:4px}
.empty{color:#999;padding:16px;text-align:center}
.ovl{display:none;position:fixed;inset:0;background:rgba(0,0,0,.35);z-index:900}
#addm{display:none;position:fixed;top:20%;left:50%;transform:translateX(-50%);z-index:901;
 width:min(560px,92vw);background:#fff;border-radius:8px;padding:18px 20px;
 box-shadow:0 8px 28px rgba(0,0,0,.22)}
#addm h3{font-size:15px;margin:0 0 6px}
#addm p{font-size:12px;color:#777;margin:0 0 12px}
#addm input[type=text]{width:100%;font-size:13px;padding:9px 10px;border:1px solid #bbb;
 border-radius:4px;outline:none}
#addm input[type=text]:focus{border-color:#0b57d0}
.addr{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.addr label{display:block;font-size:11px;color:#666;margin-bottom:4px}
.addr select{width:100%;font-size:13px;padding:7px 8px;border:1px solid #bbb;border-radius:4px}
.adda{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}
.adda .btn-go{border-color:#1a7f5a;background:#1a7f5a;color:#fff}
.adda button:disabled{opacity:.55;cursor:wait}
/* 收起式多选下拉：文章类型有 62 种，摊平成一排勾选框会把筛选栏撑爆 */
.dd{position:relative}
.ddb{font-size:13px;padding:4px 22px 4px 8px;border:1px solid #ccc;border-radius:4px;
 cursor:pointer;background:#fff;min-width:64px;max-width:250px;user-select:none;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ddb i{position:absolute;right:6px;top:50%;transform:translateY(-50%);
 color:#888;font-size:10px;font-style:normal}
.ddp{display:none;position:absolute;top:100%;left:0;z-index:800;background:#fff;
 border:1px solid #ccc;border-radius:4px;padding:6px 10px;margin-top:2px;
 box-shadow:0 2px 8px rgba(0,0,0,.12);white-space:nowrap;max-height:52vh;overflow-y:auto}
.ddp label{display:flex;align-items:center;gap:6px;font-size:13px;color:#333;
 font-weight:400;padding:2px 0;cursor:pointer}
#pmod{display:none;position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:901;
 flex-direction:column;width:min(520px,92vw);max-height:75vh;background:#fff;
 border-radius:8px;padding:18px 20px;box-shadow:0 8px 28px rgba(0,0,0,.22)}
#pmod h3{font-size:15px;margin:0 0 4px}
#pm-sub{font-size:12px;color:#888;margin-bottom:12px}
#pm-list{overflow-y:auto;max-height:42vh;border:1px solid #e5e5e5;border-radius:5px;padding:2px 10px}
#pm-list label{display:flex;align-items:center;gap:8px;font-size:13px;padding:6px 2px;
 cursor:pointer;border-bottom:1px solid #f2f2f2}
#pm-list label:last-child{border-bottom:none}
#pm-list .cnt{margin-left:auto;font-size:11px;color:#999;white-space:nowrap}
#pm-list .none{font-size:12px;color:#999;padding:8px 2px}
#pm-new{margin-top:12px}
#pm-new label{display:block;font-size:12px;color:#666;margin-bottom:4px}
#pm-new input{width:100%;font-size:13px;padding:6px 8px;border:1px solid #ccc;border-radius:4px}
"""


def _pmid_list(raw) -> list:
    """引文关系存的是 JSON 数组字符串；还没跑过 citations 时是空串。"""
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except ValueError:
        return []


def render(config, db_path: Path, out_path: Path, *, port: int = 8765,
           token: str = "") -> Path:
    """生成收藏库页面。

    token 是写接口的凭据（见 cli.py 的 _token）：页面把它放进请求头，服务端逐一校验。
    没有它的话，任何网页都能在你开着 serve 时往 127.0.0.1 发跨源写请求改你的库。
    """
    arts = library.sorted_articles(config, library.all_articles(db_path))
    pmap = library.project_map(db_path)
    projects = library.list_projects(db_path)

    for a in arts:
        try:
            a["_kw"] = "; ".join(json.loads(a.get("keywords") or "[]"))
        except Exception:
            a["_kw"] = ""
        a["_proj"] = pmap.get(a["pmid"], [])

    js_arts = _json_for_script([{
        "pmid": a["pmid"], "title": a.get("title", ""), "zh": a.get("title_zh", ""),
        "journal": a.get("journal", ""), "date": a.get("pub_date", ""),
        "sec": a.get("section", ""), "sub": a.get("subsection", ""),
        "kw": a["_kw"], "aff": a.get("affiliation", ""), "abs": a.get("abstract", ""),
        "ifv": a.get("if_value", ""), "q": a.get("quartile", ""),
        "type": a.get("pub_type", ""), "rating": a.get("rating", ""),
        "notes": a.get("notes", ""), "proj": a["_proj"],
        "year": (a.get("pub_date") or "")[:4],
        "month": (a.get("pub_date") or "")[5:7],
        "citedby": _pmid_list(a.get("cited_by")), "cites": _pmid_list(a.get("cites")),
        "cc": a.get("citation_count"), "icc": a.get("influential_count"),
    } for a in arts])

    # 年 → 该年出现过的月份，用于「年份」联动「月份」下拉
    ym: dict[str, set] = {}
    for a in arts:
        d = a.get("pub_date") or ""
        if len(d) >= 7:
            ym.setdefault(d[:4], set()).add(d[5:7])
    ym_js = _json_for_script({k: sorted(v) for k, v in ym.items()})
    types = sorted({a.get("pub_type", "") for a in arts if a.get("pub_type")})
    type_boxes = "".join(
        f'<label><input type=checkbox class=tcb value="{_esc(t)}" '
        f'onchange="onType()"> {_esc(t)}</label>' for t in types)
    # IF 区间做成互不重叠的桶，勾多个取并集（勾「<5」和「≥20」＝两头都要）。
    # 换成「≥N」那种单选就表达不了这种筛法。
    if_boxes = "".join(
        f'<label><input type=checkbox class=icb value="{v}" data-l="{_esc(t)}" '
        f'onchange="onIf()"> {_esc(t)}</label>'
        for v, t in (("0-5", "< 5"), ("5-10", "5 ～ 10"),
                     ("10-20", "10 ～ 20"), ("20-", "≥ 20")))

    sub_map = {s.name: s.subsection_names for s in config.sections}
    sub_map_js = _json_for_script(sub_map)
    projects_js = _json_for_script([p["name"] for p in projects])
    token_js = _json_for_script(token)
    sec_opts = "".join(f'<option value="{_esc(s.name)}">{_esc(s.name)}</option>'
                       for s in config.sections)
    journals = sorted({a.get("journal", "") for a in arts if a.get("journal")})
    jrn_opts = "".join(f'<option value="{_esc(j)}">{_esc(j)}</option>' for j in journals)
    years = sorted({(a.get("pub_date") or "")[:4] for a in arts if a.get("pub_date")}, reverse=True)
    yr_opts = "".join(f'<option value="{y}">{y}</option>' for y in years)
    prj_opts = "".join(
        f'<option value="{_esc(p["name"])}">{_esc(p["name"])}'
        f'{"（已归档）" if p["archived"] else ""} ({p["count"]})</option>' for p in projects)

    html_doc = f"""<!doctype html><html lang=zh-CN><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>{_esc(config.project_name)} · 收藏库</title><style>{_CSS}</style></head><body>
<div id=povl class=ovl onclick="closeProj()"></div>
<div id=pmod>
  <h3 id=pm-title></h3>
  <div id=pm-sub></div>
  <div id=pm-list></div>
  <div id=pm-new>
    <label for=pm-name>新建项目（可留空）</label>
    <input type=text id=pm-name placeholder="输入新项目名称"
           onkeydown="if(event.key==='Enter')submitProj()">
  </div>
  <div class=adda>
    <button class=btn onclick="closeProj()">取消</button>
    <button class="btn btn-go" onclick="submitProj()">确定</button>
  </div>
</div>

<div id=ovl class=ovl onclick="closeAdd()"></div>
<div id=addm>
  <h3>添加文献</h3>
  <p>粘贴 PubMed 文章的完整标题，或输入 PMID（多个用空格/逗号分隔，一次最多 50 篇）。
     需要 <code>serve</code> 正在运行。</p>
  <input type=text id=add-q placeholder="文章标题 或 PMID"
         onkeydown="if(event.key==='Enter')doAdd()">
  <div class=addr>
    <div><label for=add-sec>板块</label>
      <select id=add-sec onchange="onAddSec()">
        <option value="">自动判定</option>{sec_opts}</select></div>
    <div><label for=add-sub>子板块</label>
      <select id=add-sub disabled><option value="">按关键词自动判定</option></select></div>
  </div>
  <div class=adda>
    <button class=btn onclick="closeAdd()">取消</button>
    <button class="btn btn-go" id=add-go onclick="doAdd()">添加</button>
  </div>
</div>

<h1>{_esc(config.project_name)} · 收藏库</h1>
<div class=meta>共 <strong>{len(arts)}</strong> 篇 &nbsp;|&nbsp; 生成于 {datetime.datetime.now():%Y-%m-%d %H:%M}</div>

<div class=bar>
  <div class=grp><label>板块</label>
    <select id=f-sec onchange="onSec()"><option value="">全部</option>{sec_opts}</select></div>
  <div class=grp><label>子板块</label>
    <select id=f-sub onchange="apply()"><option value="">全部</option></select></div>
  <div class=grp><label>年份</label>
    <select id=f-year onchange="onYear()"><option value="">全部</option>{yr_opts}</select></div>
  <div class=grp><label>月份</label>
    <select id=f-month onchange="apply()"><option value="">全部</option></select></div>
  <div class=grp><label>期刊</label>
    <select id=f-jrn onchange="apply()"><option value="">全部</option>{jrn_opts}</select></div>
  <div class=grp><label>分区</label>
    <select id=f-tier onchange="apply()"><option value="">全部</option>
      <option>Q1</option><option>Q2</option><option>Q3</option><option>Q4</option></select></div>
  <div class=grp><label>IF</label>
    <div class=dd>
      <div class=ddb id=if-lbl onclick="ddOpen(event,'if-panel')">全部<i>▾</i></div>
      <div class=ddp id=if-panel>{if_boxes}</div>
    </div></div>
  <div class=grp><label>文章类型</label>
    <div class=dd>
      <div class=ddb id=type-lbl onclick="ddOpen(event,'type-panel')">全部<i>▾</i></div>
      <div class=ddp id=type-panel>{type_boxes}</div>
    </div></div>
  <div class=grp><label>引用情况</label>
    <select id=f-cit onchange="apply()"><option value="">全部</option>
      <option value="1-10">被引 1～10</option>
      <option value="10-30">被引 10～30</option>
      <option value="30-50">被引 30～50</option>
      <option value="50-100">被引 50～100</option>
      <option value="100-">被引 ≥ 100</option>
      <option value="db1">有库内被引</option>
      <option value="db3">库内被引 ≥ 3 篇</option>
      <option value="db0">无库内被引</option></select></div>

  <div class=row-break>
    <div class=grp><label>评级</label>
      <label class=rl><input type=checkbox class=rcb value="○" onchange="apply()"> ○ 已读</label>
      <label class=rl><input type=checkbox class=rcb value="⭐" onchange="apply()"> ⭐ 重要</label>
      <label class=rl><input type=checkbox class=rcb value="🚩" onchange="apply()"> 🚩 经典</label>
    </div>
    <div class=grp><label>标题词</label><input type=text id=f-kw oninput="apply()" placeholder="关键词…"></div>
    <div class=grp><label>摘要词</label><input type=text id=f-abs oninput="apply()" placeholder="关键词…"></div>
    <button class=btn onclick="reset()">重置</button>
    <span class=vr></span>
    <button class="btn btn-p" onclick="openAdd()">添加文献</button>
    <button class="btn btn-d" onclick="delSel()">删除勾选</button>
    <button class="btn btn-b" onclick="exportNbib(event)"
            title="直接向 PubMed 取官方 MEDLINE 记录，卷期页作者都由 NLM 生成">导出勾选 nbib</button>
    <button class="btn btn-o" onclick="toObsidian()">→ Obsidian</button>
    <button class="btn btn-o" onclick="refreshObsidian()"
            title="不新增文献，只把已有笔记按最新板块归位、重建总录与项目索引">刷新总录</button>
  </div>

  <div class=row-break>
    <div class=grp><label>项目</label>
      <select id=f-prj onchange="apply()">
        <option value="">全部</option><option value="__none__">未归项目</option>{prj_opts}
      </select></div>
    <button class="btn btn-p" onclick="addProj()">加入项目</button>
    <button class=btn onclick="delProj()">移出项目</button>
  </div>
</div>

<div id=cnt></div>
<table><thead><tr>
  <th style="width:34px"><input type=checkbox id=cb-all onchange="toggleAll(this.checked)"></th>
  <th style="width:120px">板块</th><th style="width:150px">期刊</th>
  <th style="width:88px">日期</th><th>标题 / 关键词 / 通讯单位 / 摘要</th>
</tr></thead><tbody id=tb></tbody></table>

<script>
const ARTS = {js_arts};
const SUBMAP = {sub_map_js};
const YM = {ym_js};
const PROJECTS = {projects_js};
const PORT = {port};
const TOKEN = {token_js};
// 从 http://127.0.0.1:PORT/ 打开时用同源相对路径；直接双击 file:// 打开时回落到绝对地址
const API = (location.protocol==='http:'||location.protocol==='https:') ? '' : 'http://127.0.0.1:'+PORT;
let view = ARTS.slice();

function esc(s){{return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}}
function onSec(){{
  const sec=document.getElementById('f-sec').value, sel=document.getElementById('f-sub');
  sel.innerHTML='<option value="">全部</option>';
  const subs = sec ? (SUBMAP[sec]||[]) : [].concat(...Object.values(SUBMAP));
  [...new Set(subs)].forEach(s=>{{const o=document.createElement('option');o.value=s;o.textContent=s;sel.appendChild(o);}});
  apply();
}}
function onYear(){{
  const y=document.getElementById('f-year').value, sel=document.getElementById('f-month');
  sel.innerHTML='<option value="">全部</option>';
  (y?(YM[y]||[]):[]).forEach(m=>{{
    const o=document.createElement('option'); o.value=m; o.textContent=parseInt(m,10)+'月';
    sel.appendChild(o);
  }});
  apply();
}}
function apply(){{
  const g=i=>document.getElementById(i).value;
  const sec=g('f-sec'), sub=g('f-sub'), yr=g('f-year'), mo=g('f-month'), jr=g('f-jrn'),
        tier=g('f-tier'), prj=g('f-prj'), cit=g('f-cit'),
        kw=g('f-kw').toLowerCase(), abs=g('f-abs').toLowerCase(),
        rts=[...document.querySelectorAll('.rcb:checked')].map(c=>c.value),
        tps=[...document.querySelectorAll('.tcb:checked')].map(c=>c.value),
        ifr=[...document.querySelectorAll('.icb:checked')].map(c=>c.value);
  view = ARTS.filter(a=>{{
    let pOk = true;
    if(prj==='__none__') pOk = !a.proj || a.proj.length===0;
    else if(prj) pOk = (a.proj||[]).indexOf(prj)!==-1;
    let iOk = true;
    if(ifr.length){{
      const v = parseFloat(a.ifv);
      if(isNaN(v)) iOk = false;                       // 无 IF 数据的不计入任何区间
      else iOk = ifr.some(r=>{{                        // 多选取并集，区间左闭右开 [lo, hi)
        const p=r.split('-');
        return v>=parseFloat(p[0]) && v<(p[1]?parseFloat(p[1]):Infinity);
      }});
    }}
    // 「引用情况」一个下拉管两件事：db* 走库内引用关系，其余是全球被引数的区间
    let cOk = true;
    if(cit.slice(0,2)==='db'){{
      const n=(a.citedby||[]).length, want=parseInt(cit.slice(2),10);
      cOk = want===0 ? n===0 : n>=want;
    }} else if(cit){{
      const cc=a.cc||0, p=cit.split('-');          // 左闭右开 [lo, hi)
      const lo=parseInt(p[0],10), hi=p[1]?parseInt(p[1],10):Infinity;
      cOk = cc>=lo && cc<hi;
    }}
    return (!sec||a.sec===sec) && (!sub||a.sub===sub) && (!yr||a.year===yr) &&
           (!mo||a.month===mo) && (!jr||a.journal===jr) && (!tier||a.q===tier) && iOk && cOk &&
           (!rts.length||rts.includes(a.rating)) && (!tps.length||tps.includes(a.type)) &&
           (!kw|| (a.title+a.zh).toLowerCase().includes(kw)) &&
           (!abs|| (a.abs||'').toLowerCase().includes(abs)) && pOk;
  }});
  draw();
}}
function reset(){{
  ['f-sec','f-sub','f-year','f-month','f-jrn','f-tier','f-prj','f-cit']
    .forEach(i=>document.getElementById(i).value='');
  document.getElementById('f-kw').value='';
  document.getElementById('f-abs').value='';
  document.querySelectorAll('.rcb,.tcb,.icb').forEach(c=>c.checked=false);
  ddLabel('.icb','if-lbl'); ddLabel('.tcb','type-lbl');
  document.getElementById('f-month').innerHTML='<option value="">全部</option>';
  onSec();
}}
// ── 收起式多选下拉（IF / 文章类型）──
function ddOpen(e,id){{
  e.stopPropagation();
  const p=document.getElementById(id);
  document.querySelectorAll('.ddp').forEach(x=>{{ if(x.id!==id) x.style.display='none'; }});
  if(p.style.display==='block'){{ p.style.display='none'; return; }}
  // 先按左对齐展开，越界了再翻到右对齐——筛选栏最右边那个下拉否则会被切掉半截
  p.style.left='0'; p.style.right='auto'; p.style.display='block';
  const vw = window.innerWidth || document.documentElement.clientWidth;
  if(vw && p.getBoundingClientRect().right > vw-4){{
    p.style.left='auto'; p.style.right='0';
  }}
}}
document.addEventListener('click',e=>{{
  document.querySelectorAll('.dd').forEach(d=>{{
    if(!d.contains(e.target)) d.querySelector('.ddp').style.display='none';
  }});
}});
function ddLabel(sel,btn){{
  const c=[...document.querySelectorAll(sel+':checked')].map(x=>x.dataset.l||x.value);
  const b=document.getElementById(btn);
  b.textContent = c.length ? c.join('、') : '全部';   // textContent：类型名来自 PubMed，不拼 HTML
  const i=document.createElement('i'); i.textContent='▾'; b.appendChild(i);
}}
function onIf(){{ ddLabel('.icb','if-lbl'); apply(); }}
function onType(){{ ddLabel('.tcb','type-lbl'); apply(); }}
function draw(){{
  document.getElementById('cnt').innerHTML='显示 <strong>'+view.length+'</strong> / '+ARTS.length+' 篇';
  const tb=document.getElementById('tb');
  if(!view.length){{tb.innerHTML='<tr><td colspan=5 class=empty>无匹配文献</td></tr>';return;}}
  tb.innerHTML = view.map(a=>{{
    const u='https://pubmed.ncbi.nlm.nih.gov/'+a.pmid+'/', id='ab'+a.pmid;
    const chips=(a.proj||[]).map(p=>'<span class="b b-proj">'+esc(p)+'</span>').join('');
    const rt=['○','⭐','🚩'].map(s=>'<button class="rt'+(a.rating===s?' on':'')+
      '" onclick="setRating(\\''+a.pmid+'\\',\\''+s+'\\')">'+s+'</button>').join('');
    const nCit=(a.citedby||[]).length, cid='ct'+a.pmid;
    const citBadge = nCit
      ? '<span class="b b-cit" onclick="document.getElementById(\\''+cid+'\\').classList.toggle(\\'open\\')">'
        +'库内被引 '+nCit+'</span>' : '';
    const citList = nCit
      ? '<div class=citers id='+cid+'>被库内这些文章引用：<br>'+citerLinks(a.citedby)+'</div>' : '';
    const ccBadge = (a.cc===null||a.cc===undefined) ? ''
      : '<span class="b b-cc" title="Semantic Scholar 统计的全球被引数">被引 '+a.cc
        +(a.icc?'（高影响 '+a.icc+'）':'')+'</span>';
    return '<tr><td><input type=checkbox class=acb data-pmid="'+a.pmid+'"></td>'
      +'<td><span class="b b-sec">'+esc(a.sec)+'</span>'+(a.sub?'<div><span class="b b-sub">'+esc(a.sub)+'</span></div>':'')+'</td>'
      +'<td>'+esc(a.journal)+'<div>'
        +(a.q==='Q1'?'<span class="b b-q1">Q1</span>':'')+(a.q==='Q2'?'<span class="b b-q2">Q2</span>':'')
        +(a.ifv?'<span class="b b-if">IF '+esc(a.ifv)+'</span>':'')+'</div></td>'
      +'<td>'+esc(a.date)+'</td>'
      +'<td>'+(a.type?'<span class="b b-type">'+esc(a.type)+'</span>':'')+chips+citBadge+ccBadge
        +'<a class=ti href="'+u+'" target=_blank rel=noopener>'+esc(a.title)+'</a>'
        +citList
        +(a.zh?'<div class=zh>'+esc(a.zh)+'</div>':'')
        +(a.kw?'<div class=ln>关键词：'+esc(a.kw)+'</div>':'')
        +(a.aff?'<div class=ln>通讯单位：'+esc(a.aff)+'</div>':'')
        +(a.abs?'<div class=abs-t onclick="document.getElementById(\\''+id+'\\').classList.toggle(\\'open\\')">▶ 摘要</div><div class=abs id='+id+'>'+a.abs+'</div>':'')
        +'<div>'+rt+'</div>'
        +'<textarea placeholder="Notes…" onchange="setNote(\\''+a.pmid+'\\',this.value)">'+esc(a.notes)+'</textarea>'
      +'</td></tr>';
  }}).join('');
}}
function citerLinks(pmids){{
  // 引用方一定在库内，所以直接从 ARTS 里取标题，不必再嵌一份映射
  return (pmids||[]).map(p=>{{
    const a=ARTS.find(x=>x.pmid===p);
    const t=a?(a.title||p):p;
    return '· <a href="https://pubmed.ncbi.nlm.nih.gov/'+p+'/" target=_blank rel=noopener>'
           +esc(t)+'</a>';
  }}).join('<br>');
}}
function toggleAll(v){{document.querySelectorAll('.acb').forEach(c=>c.checked=v);}}
function checked(){{return [...document.querySelectorAll('.acb:checked')].map(c=>c.dataset.pmid);}}

function post(path, body, okMsg){{
  return fetch(API+path, {{method:'POST',
    headers:{{'Content-Type':'application/json','X-LitTrack-Token':TOKEN}},
    body:JSON.stringify(body||{{}})}})
    .then(r=>{{
      if(r.status===403) throw new Error('凭据不匹配');
      // 服务端出错时回的是纯文本原因（PMID 写错、标题匹配到多篇……），
      // 直接 r.json() 会把它变成解析错误，用户只看得到「连接失败」这种没用的话
      if(!r.ok) return r.text().then(t=>{{ throw new Error(t||('HTTP '+r.status)); }});
      return r.json();
    }})
    .then(d=>{{ if(okMsg) alert(okMsg(d)); return d; }})
    .catch(e=>{{
      const m=String(e.message||'');
      alert(m==='凭据不匹配'
        ? '凭据不匹配——本页面比服务端的凭据旧。\\n请重新生成页面：\\n  python3 cli.py library --config <你的配置>'
        : (m && e.name!=='TypeError' ? m
           : '连接失败——请先在终端运行：\\n  python3 cli.py serve --config <你的配置>'));
      return null;
    }});
}}
function openAdd(){{
  document.getElementById('ovl').style.display='block';
  document.getElementById('addm').style.display='block';
  setTimeout(()=>document.getElementById('add-q').focus(),0);
}}
function closeAdd(){{
  document.getElementById('ovl').style.display='none';
  document.getElementById('addm').style.display='none';
}}
function onAddSec(){{
  const sec=document.getElementById('add-sec').value, sel=document.getElementById('add-sub');
  sel.innerHTML='';
  if(!sec){{
    sel.disabled=true; sel.innerHTML='<option value="">按关键词自动判定</option>'; return;
  }}
  sel.disabled=false;
  sel.innerHTML='<option value="">（不指定）</option>';
  (SUBMAP[sec]||[]).forEach(s=>{{
    const o=document.createElement('option'); o.value=s; o.textContent=s; sel.appendChild(o);
  }});
}}
function doAdd(){{
  const q=document.getElementById('add-q').value.trim();
  if(!q) return alert('请输入文章标题或 PMID');
  const btn=document.getElementById('add-go');
  btn.disabled=true; btn.textContent='正在取…';
  post('/article/add',{{query:q,
                        section:document.getElementById('add-sec').value,
                        subsection:document.getElementById('add-sub').value}})
    .then(d=>{{
      btn.disabled=false; btn.textContent='添加';
      if(!d) return;                       // 出错时 post 已经弹过原因了
      const L=['✓ 新增 '+d.added+' 篇'];
      if(d.updated) L.push('更新 '+d.updated+' 篇（已在库中，笔记与评级保留）');
      if(d.missing.length) L.push('PubMed 没有：'+d.missing.join('、'));
      alert(L.join('\\n'));
      location.reload();
    }});
}}
function setRating(pmid,s){{
  const a=ARTS.find(x=>x.pmid===pmid); const val=(a.rating===s)?'':s;
  post('/rating',{{pmid:pmid,rating:val}}).then(()=>{{a.rating=val;draw();}});
}}
function setNote(pmid,t){{ const a=ARTS.find(x=>x.pmid===pmid); a.notes=t; post('/note',{{pmid:pmid,text:t}}); }}
// ── 项目：弹窗里勾选已有项目（可多选），新建走输入框 ──
// 早先用 prompt() 让人手打项目名，打错一个字就静默新建了个近似重名的项目，
// 而且看不到哪些勾选的文献已经在里面了。
let _pMode='add', _pPmids=[];
function addProj(){{ openProj('add'); }}
function delProj(){{ openProj('remove'); }}
function openProj(mode){{
  const s=checked();
  if(!s.length) return alert(mode==='add'?'请先勾选要加入项目的文献':'请先勾选要移出项目的文献');
  _pMode=mode; _pPmids=s;
  // 统计勾选的文献已属于哪些项目：加入时用来提示，移出时用来只列相关项目
  const cnt={{}};
  s.forEach(p=>{{
    const a=ARTS.find(x=>x.pmid===p);
    ((a&&a.proj)||[]).forEach(n=>{{ cnt[n]=(cnt[n]||0)+1; }});
  }});
  const names = (mode==='remove') ? Object.keys(cnt).sort() : PROJECTS.slice();
  const cur=document.getElementById('f-prj').value;
  const list=document.getElementById('pm-list');
  list.textContent='';
  if(!names.length){{
    const d=document.createElement('div'); d.className='none';
    d.textContent = mode==='remove' ? '勾选的文献不属于任何项目' : '还没有任何项目，请在下方输入新名称';
    list.appendChild(d);
  }} else names.forEach(n=>{{
    const lab=document.createElement('label');
    const cb=document.createElement('input');
    cb.type='checkbox'; cb.className='pcb'; cb.value=n; cb.checked=(n===cur);
    const t=document.createElement('span'); t.textContent=n;
    const c=document.createElement('span'); c.className='cnt';
    c.textContent = cnt[n] ? ('已含 '+cnt[n]+'/'+s.length+' 篇') : '未含勾选文献';
    lab.appendChild(cb); lab.appendChild(t); lab.appendChild(c);
    list.appendChild(lab);
  }});
  document.getElementById('pm-title').textContent =
    '把勾选的 '+s.length+' 篇'+(mode==='add'?'加入项目':'移出项目');
  document.getElementById('pm-sub').textContent = mode==='add'
    ? '勾选已有项目，或在下方输入新名称新建（可同时选多个）。'
    : '勾选要移出的项目（只解除关联，不会删除文献）。';
  document.getElementById('pm-new').style.display = mode==='add' ? '' : 'none';
  document.getElementById('pm-name').value='';
  document.getElementById('povl').style.display='block';
  document.getElementById('pmod').style.display='flex';
  if(mode==='add') document.getElementById('pm-name').focus();
}}
function closeProj(){{
  document.getElementById('povl').style.display='none';
  document.getElementById('pmod').style.display='none';
}}
function submitProj(){{
  const mode=_pMode, pmids=_pPmids.slice();
  const names=[...document.querySelectorAll('#pm-list .pcb:checked')].map(c=>c.value);
  if(mode==='add'){{
    const nn=document.getElementById('pm-name').value.trim();
    if(nn && names.indexOf(nn)===-1) names.push(nn);
  }}
  if(!names.length) return alert(mode==='add'?'请勾选已有项目，或输入新项目名称':'请勾选要移出的项目');
  const path = mode==='add' ? '/project/add' : '/project/remove';
  Promise.all(names.map(n=>post(path,{{name:n,pmids:pmids}}).then(d=>({{name:n,d:d}}))))
    .then(res=>{{
      const ok=res.filter(x=>x.d);
      if(!ok.length) return;                       // 全失败，post 已经弹过原因
      closeProj();
      applyProjChange(mode, ok.map(x=>x.name), pmids);
      alert('✓ 已完成\\n'+ok.map(x=>'「'+x.name+'」'+(mode==='add'
        ? ('加入 '+(x.d.added||0)+' 篇') : ('移出 '+(x.d.removed||0)+' 篇'))).join('\\n'));
    }});
}}
// 就地更新内存里的项目归属，省掉一次整页刷新
function applyProjChange(mode,names,pmids){{
  pmids.forEach(p=>{{
    const a=ARTS.find(x=>x.pmid===p); if(!a) return;
    a.proj = a.proj || [];
    names.forEach(n=>{{
      const i=a.proj.indexOf(n);
      if(mode==='add'){{ if(i===-1) a.proj.push(n); }}
      else if(i!==-1) a.proj.splice(i,1);
    }});
  }});
  if(mode==='add') names.forEach(n=>{{ if(PROJECTS.indexOf(n)===-1) PROJECTS.push(n); }});
  refreshProjFilter();
  apply();
}}
function refreshProjFilter(){{
  const sel=document.getElementById('f-prj'), cnt={{}};
  ARTS.forEach(a=>(a.proj||[]).forEach(n=>{{ cnt[n]=(cnt[n]||0)+1; }}));
  [...sel.options].forEach(o=>{{
    if(!o.value||o.value==='__none__') return;
    o.textContent = o.textContent.replace(/ \\(\\d+\\)$/,'')+' ('+(cnt[o.value]||0)+')';
  }});
  PROJECTS.forEach(n=>{{
    if([...sel.options].some(o=>o.value===n)) return;
    const o=document.createElement('option');
    o.value=n; o.textContent=n+' ('+(cnt[n]||0)+')';
    sel.appendChild(o);
  }});
}}
function delSel(){{
  const s=checked(); if(!s.length) return alert('请先勾选文献');
  if(!confirm('确定从收藏库删除这 '+s.length+' 篇？此操作不可撤销。')) return;
  post('/delete',{{pmids:s}},d=>'✓ 已删除 '+d.deleted+' 篇\\n刷新页面可见');
}}
function toObsidian(){{
  const s=checked(); if(!s.length) return alert('请先勾选文献');
  post('/obsidian/export',{{pmids:s}},d=>'✓ Obsidian 已更新\\n新增 '+d.written+' 篇，跳过 '+d.skipped+' 篇（已存在）');
}}
function refreshObsidian(){{
  post('/obsidian/refresh',{{}},d=>'✓ 已刷新：现有笔记 '+d.total+' 篇，归位 '+d.moved+' 篇\\n总录与项目索引已重建');
}}
function dl(name, text){{
  const b=new Blob([text],{{type:'text/plain;charset=utf-8'}}), a=document.createElement('a');
  a.href=URL.createObjectURL(b); a.download=name; a.click();
}}
// 只导 nbib，不再自己拼 RIS：库里没存卷/期/页，本地拼出来的条目导进 EndNote
// 是残的，还得手工补。PubMed 的 MEDLINE 记录由 NLM 生成，字段齐全。
function exportNbib(ev){{
  const s=checked(); if(!s.length) return alert('请先勾选文献');
  const btn=ev&&ev.target, lab=btn?btn.textContent:'';
  if(btn){{ btn.disabled=true; btn.textContent='正在从 PubMed 取…'; }}
  // 分批：一次几百个 PMID 会把 URL 顶到几千字符，NCBI 会直接拒
  const chunks=[]; for(let i=0;i<s.length;i+=200) chunks.push(s.slice(i,i+200));
  const parts=[];
  chunks.reduce((chain,c)=>chain.then(()=>
    fetch('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
          +'?db=pubmed&retmode=text&rettype=medline&id='+c.join(','))
      .then(r=>{{ if(!r.ok) throw new Error('HTTP '+r.status); return r.text(); }})
      .then(t=>parts.push(t.trim()))), Promise.resolve())
    .then(()=>dl('library.nbib', parts.join('\\n\\n')+'\\n'))
    .catch(e=>alert('取 PubMed 数据失败：'+e.message+'\\n请检查网络后重试'))
    .then(()=>{{ if(btn){{ btn.disabled=false; btn.textContent=lab; }} }});
}}
onSec();
</script></body></html>"""

    _sanity_check(html_doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


def _sanity_check(doc: str) -> None:
    """校验生成的 JS 能不能解析。

    页面里的 JS 是用 f-string 拼的，转义层数写错（JS 的 `\\n` 在源码里要写成 `\\\\n`，
    少写一层就会变成真换行、把字符串截断）会让**整段脚本语法错误**——页面照常打开，
    但筛选和按钮全部失灵，而且浏览器控制台里往往看不到报错，极难定位。开发时踩过一次。

    有 node 就用它做真正的语法检查；没有就只做花括号配平这种保守检查。
    不用「数引号」的土办法——正则字面量里的引号（如 `.replace(/"/g, …)`）会误报。
    """
    try:
        js = doc.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    except IndexError:
        return

    depth = js.count("{") - js.count("}")
    if depth != 0:
        raise RuntimeError(f"生成的页面 JS 花括号不配平（差 {depth} 个），整段脚本会失效。")

    import shutil
    node = shutil.which("node")
    if not node:
        return                      # 没装 node 就跳过，不影响正常使用
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        tmp = f.name
    try:
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        if r.returncode != 0:
            detail = (r.stderr or "").strip().split("\n")
            hint = "\n  ".join(detail[:4])
            raise RuntimeError(
                f"生成的页面 JS 语法有误，整段脚本会失效：\n  {hint}\n"
                f"  常见原因：f-string 里的转义层数写错（JS 的 \\n 源码里要写 \\\\n）。")
    finally:
        Path(tmp).unlink(missing_ok=True)
