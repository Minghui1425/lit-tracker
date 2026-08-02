"""导出到 Obsidian：每篇一个笔记 + 总录 + 项目索引。

三条不可违背的约定（都是踩过坑换来的）：

1. **绝不覆盖用户手写内容。** 笔记里 `label` 与 `Notes` 两处归用户所有，刷新时原样保留。
2. **frontmatter 正则不能用 `\\s*`。** `\\s` 包含换行——当用户把 label 的值清空只剩键时
   （Obsidian 属性面板清空值就是这个效果），`^label:\\s*"?([^"\\n]*)"?` 会跨行吃掉下一行
   的 `---` 分隔符，把 label 写成 "---"。必须用 `[ \\t]*` 限定行内空白并锚定行尾。
3. **文献笔记本身不写项目信息。** 项目只体现在 `项目/` 下的索引笔记里，
   这样删项目、改项目名都不会动到文献笔记。
"""
from __future__ import annotations

import re
from pathlib import Path

from . import library

# 见模块 docstring 第 2 条：不能用 \s*
_LABEL_RE = r'^label:[ \t]*"?([^"\n]*?)"?[ \t]*$'
_PMID_RE = r'^pmid:[ \t]*"?(\d+)"?[ \t]*$'

_INVALID = r'[\\/:*?"<>|]'
PROJECT_DIR = "项目"
INDEX_NAME = "总录.md"


def _safe(name: str, limit: int = 90) -> str:
    return re.sub(_INVALID, "_", (name or "").strip())[:limit].strip() or "untitled"


def _note_name(art: dict) -> str:
    year = (art.get("pub_date") or "")[:4] or "0000"
    jrn = _safe(art.get("journal") or "", 40)
    title = _safe(art.get("title") or "", 80)
    pmid = _safe(str(art.get("pmid") or "unknown"), 20)
    return f"{year}_{jrn}_{title}_{pmid}.md"


def _note_folder(root: Path, art: dict) -> Path:
    """按 板块/子板块 归档。两者都空则放在 vault 根下的「未归板块」。"""
    sec = _safe(art.get("section") or "", 40)
    sub = _safe(art.get("subsection") or "", 40)
    if not sec and not sub:
        return root / "未归板块"
    return root / sec / sub if sub else root / sec


def _fmt_authors(raw: str, limit: int = 6) -> str:
    names = [x.strip() for x in (raw or "").split(";") if x.strip()]
    if not names:
        return "—"
    if len(names) <= limit:
        return "、".join(names)
    return "、".join(names[:limit]) + f" 等（共 {len(names)} 位）"


def _body(art: dict, label: str = "", notes: str = "") -> str:
    pm = f"https://pubmed.ncbi.nlm.nih.gov/{art['pmid']}/"
    import json
    try:
        kws = json.loads(art.get("keywords") or "[]")
    except Exception:
        kws = []
    jrn = art.get("journal") or ""
    if art.get("if_value"):
        jrn += f"（IF={art['if_value']}）"
    return (
        f'---\npmid: "{art["pmid"]}"\nlabel: "{label}"\n---\n\n\n'
        f'## [{(art.get("title") or "").strip()}]({pm})\n'
        f'{(art.get("title_zh") or "").strip()}\n\n'
        f'**期刊**：{jrn} | **发表日期**：{art.get("pub_date") or ""} '
        f'| **板块**：{art.get("section") or "—"} / {art.get("subsection") or "—"}\n'
        f'**作者**：{_fmt_authors(art.get("authors") or "")}\n'
        f'**通讯单位**：{(art.get("affiliation") or "").strip() or "—"}\n'
        f'**Keywords**：{"；".join(kws) if kws else "—"}\n'
        f'\n**Notes**：\n{notes}\n')


def _scan(root: Path) -> dict[str, Path]:
    """扫描现有文献笔记，返回 {pmid: 路径}。项目索引与总录不算文献笔记。"""
    out: dict[str, Path] = {}
    pdir = root / PROJECT_DIR
    for p in root.rglob("*.md"):
        if p.name == INDEX_NAME or pdir in p.parents:
            continue
        m = re.search(_PMID_RE, p.read_text(encoding="utf-8"), re.M)
        if m:
            out[m.group(1)] = p
    return out


def _extract(text: str) -> tuple[str, str]:
    """取出用户手写的 label 与 Notes。"""
    lm = re.search(_LABEL_RE, text, re.M)
    label = lm.group(1).strip() if lm else ""
    nm = re.search(r"\*\*Notes\*\*[：:][^\n]*\n([\s\S]*)", text)
    return label, (nm.group(1).strip() if nm else "")


def export(config, db_path: Path, root: Path, pmids: list[str] | None = None) -> dict:
    """导出/刷新笔记。

    pmids 为空列表或 None：不新增，只刷新已有笔记（元数据、归位）并重建总录与项目索引。
    全程保留每篇的 label 与 Notes。
    """
    root.mkdir(parents=True, exist_ok=True)
    arts = {a["pmid"]: a for a in library.all_articles(db_path)}
    existing = _scan(root)
    written = skipped = moved = 0

    # ① 新增
    for pmid in (pmids or []):
        pmid = str(pmid)
        if pmid in existing:
            skipped += 1
            continue
        a = arts.get(pmid)
        if not a:
            continue
        folder = _note_folder(root, a)
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / _note_name(a)
        p.write_text(_body(a), encoding="utf-8")
        existing[pmid] = p
        written += 1

    # ② 刷新已有：更新元数据 + 按最新板块归位，但保留 label / Notes
    for pmid, p in list(existing.items()):
        a = arts.get(pmid)
        if not a:
            continue
        label, notes = _extract(p.read_text(encoding="utf-8"))
        target_dir = _note_folder(root, a)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / p.name
        if target != p and not target.exists():
            p.rename(target)
            p = target
            existing[pmid] = p
            moved += 1
        p.write_text(_body(a, label, notes), encoding="utf-8")

    # 清理空文件夹（板块调整后可能留下空目录）
    for d in sorted(root.rglob("*"), key=lambda x: -len(x.parts)):
        if d.is_dir() and d.name != PROJECT_DIR and not any(d.iterdir()):
            d.rmdir()

    rebuild_index(config, db_path, root)
    rebuild_project_notes(config, db_path, root)
    return {"written": written, "skipped": skipped, "moved": moved,
            "total": len(existing)}


def rebuild_index(config, db_path: Path, root: Path) -> Path:
    """重建总录。label 从各笔记里现读，因此在 Obsidian 里手改后刷新即可同步。"""
    arts = {a["pmid"]: a for a in library.all_articles(db_path)}
    rows = []
    for pmid, p in _scan(root).items():
        a = arts.get(pmid)
        if not a:
            continue
        label, _ = _extract(p.read_text(encoding="utf-8"))
        rows.append((a, p.stem, label))
    rows.sort(key=lambda r: library.sort_key(config, r[0]))

    lines = [f"# {config.project_name} 文献总录\n\n",
             f"共 {len(rows)} 篇\n\n",
             "| No. | 板块 / 子板块 | 发表时间 | 期刊 | 标题 | 标注 |\n",
             "| --- | --- | --- | --- | --- | --- |\n"]
    for i, (a, stem, label) in enumerate(rows, 1):
        jrn = a.get("journal") or ""
        if a.get("if_value"):
            jrn += f"（IF={a['if_value']}）"
        secsub = " / ".join(x for x in (a.get("section"), a.get("subsection")) if x) or "—"
        lines.append(f"| {i} | {secsub} | {a.get('pub_date') or ''} | {jrn} "
                     f"| [[{stem}\\|{a.get('title') or ''}]] | {label} |\n")
    out = root / INDEX_NAME
    out.write_text("".join(lines), encoding="utf-8")
    return out


def rebuild_project_notes(config, db_path: Path, root: Path) -> int:
    """每个项目一个索引笔记，放在 `项目/` 下，按发表时间倒序。

    文献笔记本身不写项目信息——删项目、改项目名都不会动到它们。
    """
    projects = library.list_projects(db_path)
    pdir = root / PROJECT_DIR
    if not projects:
        # 注意：不能因为「没有项目」就直接返回——最后一个项目被删除时，
        # 它的索引笔记仍在 项目/ 下，必须清掉，否则会留下指向已删项目的残留文件。
        if pdir.exists():
            for p in pdir.glob("*.md"):
                p.unlink()
            if not any(pdir.iterdir()):
                pdir.rmdir()
        return 0

    arts = {a["pmid"]: a for a in library.all_articles(db_path)}
    fname = {pmid: p.stem for pmid, p in _scan(root).items()}
    pmap: dict[str, list[str]] = {}
    for pmid, names in library.project_map(db_path).items():
        for n in names:
            pmap.setdefault(n, []).append(pmid)

    pdir.mkdir(parents=True, exist_ok=True)
    kept = set()
    for proj in projects:
        members = [arts[p] for p in pmap.get(proj["name"], []) if p in arts]
        members.sort(key=lambda a: a.get("pub_date") or "", reverse=True)
        safe = _safe(proj["name"], 60)
        if safe + ".md" in kept:
            safe = f"{safe}_{proj['id']}"
        kept.add(safe + ".md")
        head = f"# {proj['name']}\n\n"
        if proj["description"]:
            head += f"{proj['description']}\n\n"
        head += f"共 {len(members)} 篇" + ("　·　**已归档**" if proj["archived"] else "") + "\n\n"
        lines = [head,
                 "| No. | 板块 / 子板块 | 发表时间 | 期刊 | 标题 |\n",
                 "| --- | --- | --- | --- | --- |\n"]
        for i, a in enumerate(members, 1):
            jrn = a.get("journal") or ""
            if a.get("if_value"):
                jrn += f"（IF={a['if_value']}）"
            secsub = " / ".join(x for x in (a.get("section"), a.get("subsection")) if x) or "—"
            stem = fname.get(a["pmid"])
            # 尚未导出到 Obsidian 的文章退化为 PubMed 链接，不产生死链
            cell = (f"[[{stem}\\|{a.get('title') or ''}]]" if stem else
                    f"[{a.get('title') or ''}](https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/)")
            lines.append(f"| {i} | {secsub} | {a.get('pub_date') or ''} | {jrn} | {cell} |\n")
        (pdir / f"{safe}.md").write_text("".join(lines), encoding="utf-8")

    # 清理已删除/改名项目残留的索引笔记
    for p in pdir.glob("*.md"):
        if p.name not in kept:
            p.unlink()
    return len(projects)
