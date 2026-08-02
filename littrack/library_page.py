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
        f'<label style="font-weight:400"><input type=checkbox class=tcb '
        f'value="{_esc(t)}" onchange="apply()"> {_esc(t)}</label>' for t in types)

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
    <select id=f-if onchange="apply()"><option value="">全部</option>
      <option value="2">≥ 2</option><option value="5">≥ 5</option>
      <option value="10">≥ 10</option><option value="20">≥ 20</option>
      <option value="-5">&lt; 5</option></select></div>
  <div class=grp><label>库内被引</label>
    <select id=f-cit onchange="apply()"><option value="">全部</option>
      <option value="1">≥ 1 篇</option><option value="3">≥ 3 篇</option>
      <option value="0">无</option></select></div>

  <div class=row-break>
    <div class=grp><label>文章类型</label>{type_boxes}</div>
  </div>

  <div class=row-break>
    <div class=grp><label>评级</label>
      <label style="font-weight:400"><input type=checkbox class=rcb value="○" onchange="apply()"> ○</label>
      <label style="font-weight:400"><input type=checkbox class=rcb value="⭐" onchange="apply()"> ⭐</label>
      <label style="font-weight:400"><input type=checkbox class=rcb value="🚩" onchange="apply()"> 🚩</label>
    </div>
    <div class=grp><label>标题词</label><input type=text id=f-kw oninput="apply()" placeholder="关键词…"></div>
    <div class=grp><label>摘要词</label><input type=text id=f-abs oninput="apply()" placeholder="关键词…"></div>
    <button class=btn onclick="reset()">重置</button>
  </div>

  <div class=row-break>
    <div class=grp><label>项目</label>
      <select id=f-prj onchange="apply()">
        <option value="">全部</option><option value="__none__">未归项目</option>{prj_opts}
      </select></div>
    <button class="btn btn-p" onclick="addProj()">加入项目</button>
    <button class=btn onclick="delProj()">移出项目</button>
    <button class=btn onclick="exportRIS()">导出勾选 RIS</button>
    <button class=btn onclick="exportNbib()">导出勾选 nbib</button>
    <button class="btn btn-o" onclick="toObsidian()">→ Obsidian</button>
    <button class="btn btn-o" onclick="refreshObsidian()"
            title="不新增文献，只把已有笔记按最新板块归位、重建总录与项目索引">刷新总录</button>
    <button class="btn btn-d" onclick="delSel()">删除勾选</button>
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
        tier=g('f-tier'), ifv=g('f-if'), prj=g('f-prj'), cit=g('f-cit'),
        kw=g('f-kw').toLowerCase(), abs=g('f-abs').toLowerCase(),
        rts=[...document.querySelectorAll('.rcb:checked')].map(c=>c.value),
        tps=[...document.querySelectorAll('.tcb:checked')].map(c=>c.value);
  view = ARTS.filter(a=>{{
    let pOk = true;
    if(prj==='__none__') pOk = !a.proj || a.proj.length===0;
    else if(prj) pOk = (a.proj||[]).indexOf(prj)!==-1;
    let iOk = true;
    if(ifv){{
      const v = parseFloat(a.ifv);
      if(isNaN(v)) iOk = false;                       // 无 IF 数据的不计入任何区间
      else iOk = (ifv[0]==='-') ? v < parseFloat(ifv.slice(1)) : v >= parseFloat(ifv);
    }}
    let cOk = true;
    if(cit!==''){{
      const n=(a.citedby||[]).length;
      cOk = (cit==='0') ? n===0 : n>=parseInt(cit,10);
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
  ['f-sec','f-sub','f-year','f-month','f-jrn','f-tier','f-if','f-prj','f-cit']
    .forEach(i=>document.getElementById(i).value='');
  document.getElementById('f-kw').value='';
  document.getElementById('f-abs').value='';
  document.querySelectorAll('.rcb,.tcb').forEach(c=>c.checked=false);
  document.getElementById('f-month').innerHTML='<option value="">全部</option>';
  onSec();
}}
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
      return r.json();
    }})
    .then(d=>{{ if(okMsg) alert(okMsg(d)); return d; }})
    .catch(e=>alert(String(e.message)==='凭据不匹配'
      ? '凭据不匹配——本页面比服务端的凭据旧。\\n请重新生成页面：\\n  python3 cli.py library --config <你的配置>'
      : '连接失败——请先在终端运行：\\n  python3 cli.py serve --config <你的配置>'));
}}
function setRating(pmid,s){{
  const a=ARTS.find(x=>x.pmid===pmid); const val=(a.rating===s)?'':s;
  post('/rating',{{pmid:pmid,rating:val}}).then(()=>{{a.rating=val;draw();}});
}}
function setNote(pmid,t){{ const a=ARTS.find(x=>x.pmid===pmid); a.notes=t; post('/note',{{pmid:pmid,text:t}}); }}
function addProj(){{
  const s=checked(); if(!s.length) return alert('请先勾选文献');
  const cur=document.getElementById('f-prj').value;
  const hint=PROJECTS.length?('已有项目：'+PROJECTS.join('、')+'\\n\\n'):'';
  const n=prompt(hint+'把勾选的 '+s.length+' 篇加入哪个项目？\\n（输入新名称即新建）',
                 (cur&&cur!=='__none__')?cur:'');
  if(n===null||!n.trim()) return;
  post('/project/add',{{name:n.trim(),pmids:s}},d=>'✓ 已加入「'+n.trim()+'」'+d.added+' 篇\\n刷新页面可见');
}}
function delProj(){{
  const s=checked(); if(!s.length) return alert('请先勾选文献');
  const cur=document.getElementById('f-prj').value;
  const n=prompt('把勾选的 '+s.length+' 篇移出哪个项目？\\n（只解除关联，不删文献）',
                 (cur&&cur!=='__none__')?cur:'');
  if(n===null||!n.trim()) return;
  post('/project/remove',{{name:n.trim(),pmids:s}},d=>'✓ 已移出 '+d.removed+' 篇\\n刷新页面可见');
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
function exportRIS(){{
  const s=checked(); if(!s.length) return alert('请先勾选文献');
  const out=s.map(p=>{{const a=ARTS.find(x=>x.pmid===p);
    return ['TY  - JOUR','TI  - '+a.title,'JO  - '+a.journal,
            'PY  - '+(a.date||'').slice(0,4),'AB  - '+(a.abs||'').replace(/<[^>]+>/g,''),
            'UR  - https://pubmed.ncbi.nlm.nih.gov/'+a.pmid+'/','ER  - ',''].join('\\n');}});
  dl('library.ris', out.join('\\n'));
}}
function exportNbib(){{
  const s=checked(); if(!s.length) return alert('请先勾选文献');
  const url='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=text&rettype=medline&id='+s.join(',');
  fetch(url).then(r=>r.text()).then(t=>dl('library.nbib',t))
    .catch(()=>alert('取 PubMed 数据失败，请检查网络'));
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
