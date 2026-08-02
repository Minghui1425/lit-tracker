"""本地收藏库：SQLite 存储 + 项目标签。

与旧版最大的不同：**板块/子板块的排序完全由配置决定，不写进 SQL。**
旧版把子板块名硬编码在 `ORDER BY CASE WHEN '关节炎' THEN 2 ...` 里，共 37 处，
换个学科就得改代码。这里 section/subsection 在库里只是普通文本，
排序在 Python 侧用 `config.subsection_order()` 完成。
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

RATINGS = ("○", "⭐", "🚩")


def _conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def init_db(db_path: Path) -> None:
    with _conn(db_path) as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                pmid        TEXT PRIMARY KEY,
                title       TEXT,
                title_zh    TEXT,
                journal     TEXT,
                journal_abbr TEXT,
                pub_date    TEXT,
                section     TEXT,
                subsection  TEXT,
                abstract    TEXT,
                keywords    TEXT,
                affiliation TEXT,
                authors     TEXT,
                doi         TEXT,
                if_value    TEXT DEFAULT '',
                quartile    TEXT DEFAULT '',
                pub_type    TEXT DEFAULT '',
                notes       TEXT DEFAULT '',
                rating      TEXT DEFAULT '',
                added_date  TEXT
            );
            -- 项目标签：与板块/子板块正交的手动分组。一篇可属 0..N 个项目。
            -- 项目只是主库的子集视图，删除项目不删文章。
            CREATE TABLE IF NOT EXISTS projects (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                created     TEXT,
                archived    INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS article_projects (
                pmid       TEXT,
                project_id INTEGER,
                added      TEXT,
                PRIMARY KEY (pmid, project_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ap_project ON article_projects(project_id);
            CREATE INDEX IF NOT EXISTS idx_ap_pmid    ON article_projects(pmid);
        """)
        _migrate(c)


# 后加的列。CREATE TABLE IF NOT EXISTS 不会给已存在的库补列，只能显式 ALTER——
# 老用户的 library.db 是升级上来的，漏掉这步会在查询时报 no such column。
_ADDED_COLUMNS = (
    ("cites",             "TEXT DEFAULT ''"),      # 本篇引用了库内哪些 PMID（JSON 数组）
    ("cited_by",          "TEXT DEFAULT ''"),      # 库内哪些 PMID 引用了本篇（JSON 数组）
    ("citation_count",    "INTEGER"),              # 全球被引数（Semantic Scholar）
    ("influential_count", "INTEGER"),              # 其中的「高影响被引」
    ("citations_synced",  "TEXT DEFAULT ''"),      # 上次成功抓参考文献的日期，空＝没抓过
)


def _migrate(c) -> None:
    cols = {r["name"] for r in c.execute("PRAGMA table_info(articles)")}
    for name, decl in _ADDED_COLUMNS:
        if name not in cols:
            c.execute(f"ALTER TABLE articles ADD COLUMN {name} {decl}")


# ─── 文章 ─────────────────────────────────────────────────────────────────────

def upsert(db_path: Path, articles: list[dict]) -> tuple[int, int]:
    """写入文章，返回 (新增, 更新)。

    已存在的**不再原样跳过**——否则「补上关键词后重新入库以修正板块」这条 CLI 明确
    推荐的做法根本不生效：终端会打印新判定的板块，库里却纹丝不动。
    重新入库会刷新 PubMed 侧的元数据与板块判定，但：
      · notes / rating / added_date 属于用户资产，一律保留；
      · section/subsection 只在新判定非空时才覆盖，避免关键词没命中时
        把用户先前 --section 手动指定的归类抹成空。
    """
    init_db(db_path)
    today = str(datetime.date.today())
    added = updated = 0
    with _conn(db_path) as c:
        for a in articles:
            if c.execute("SELECT 1 FROM articles WHERE pmid=?", (a["pmid"],)).fetchone():
                sets = ["title=?", "title_zh=?", "journal=?", "journal_abbr=?", "pub_date=?",
                        "abstract=?", "keywords=?", "affiliation=?", "authors=?", "doi=?",
                        "if_value=?", "quartile=?", "pub_type=?"]
                vals = [a.get("title", ""), a.get("title_zh", ""),
                        a.get("journal") or a.get("journal_full", ""), a.get("journal_abbr", ""),
                        a.get("pub_date", ""), a.get("abstract", ""),
                        json.dumps(a.get("keywords") or [], ensure_ascii=False),
                        a.get("affiliation", ""), "; ".join(a.get("authors") or []),
                        a.get("doi", ""), a.get("if_value", ""), a.get("quartile", ""),
                        a.get("type_label", "")]
                if a.get("section"):
                    sets += ["section=?", "subsection=?"]
                    vals += [a["section"], a.get("subsection", "")]
                c.execute(f"UPDATE articles SET {','.join(sets)} WHERE pmid=?",
                          (*vals, a["pmid"]))
                updated += 1
                continue
            c.execute("""INSERT INTO articles
                (pmid,title,title_zh,journal,journal_abbr,pub_date,section,subsection,
                 abstract,keywords,affiliation,authors,doi,if_value,quartile,pub_type,
                 notes,rating,added_date)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'','',?)""",
                (a["pmid"], a.get("title", ""), a.get("title_zh", ""),
                 a.get("journal") or a.get("journal_full", ""), a.get("journal_abbr", ""),
                 a.get("pub_date", ""), a.get("section", ""), a.get("subsection", ""),
                 a.get("abstract", ""), json.dumps(a.get("keywords") or [], ensure_ascii=False),
                 a.get("affiliation", ""), "; ".join(a.get("authors") or []),
                 a.get("doi", ""), a.get("if_value", ""), a.get("quartile", ""),
                 a.get("type_label", ""), today))
            added += 1
    return added, updated


def all_articles(db_path: Path) -> list[dict]:
    init_db(db_path)
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute("SELECT * FROM articles").fetchall()]


def delete(db_path: Path, pmids: list[str]) -> int:
    init_db(db_path)
    with _conn(db_path) as c:
        n = 0
        for p in pmids:
            n += c.execute("DELETE FROM articles WHERE pmid=?", (str(p),)).rowcount
            c.execute("DELETE FROM article_projects WHERE pmid=?", (str(p),))
        return n


def move(db_path: Path, pmid: str, section: str, subsection: str = "") -> bool:
    init_db(db_path)
    with _conn(db_path) as c:
        return c.execute("UPDATE articles SET section=?, subsection=? WHERE pmid=?",
                         (section, subsection, str(pmid))).rowcount > 0


def set_note(db_path: Path, pmid: str, text: str) -> bool:
    init_db(db_path)
    with _conn(db_path) as c:
        return c.execute("UPDATE articles SET notes=? WHERE pmid=?",
                         (text, str(pmid))).rowcount > 0


def set_rating(db_path: Path, pmid: str, rating: str) -> bool:
    if rating and rating not in RATINGS:
        raise ValueError(f"评级只能是 {' / '.join(RATINGS)} 或留空，实际是 {rating!r}")
    init_db(db_path)
    with _conn(db_path) as c:
        return c.execute("UPDATE articles SET rating=? WHERE pmid=?",
                         (rating, str(pmid))).rowcount > 0


# ─── 引文网络 ─────────────────────────────────────────────────────────────────

def citation_targets(db_path: Path, *, force: bool = False) -> list[str]:
    """待抓参考文献的 PMID。默认只补没抓过的，force 时全量重抓。"""
    init_db(db_path)
    with _conn(db_path) as c:
        rows = c.execute("SELECT pmid, citations_synced FROM articles ORDER BY pmid").fetchall()
    return [r["pmid"] for r in rows if force or not (r["citations_synced"] or "").strip()]


def set_cites(db_path: Path, pmid: str, cites: list[str]) -> None:
    """记下某篇引用了库内哪些文章，并盖上「已抓过」的日期戳。

    每篇抓完立即写库：S2 限速厉害，几百篇要跑很久，中途断掉不能让已抓的白费。
    """
    init_db(db_path)
    with _conn(db_path) as c:
        c.execute("UPDATE articles SET cites=?, citations_synced=? WHERE pmid=?",
                  (json.dumps(sorted(set(cites))), str(datetime.date.today()), str(pmid)))


def set_citation_counts(db_path: Path, counts: dict[str, tuple]) -> int:
    """批量写全球被引数。counts: {pmid: (citation_count, influential_count)}。"""
    init_db(db_path)
    with _conn(db_path) as c:
        return sum(c.execute(
            "UPDATE articles SET citation_count=?, influential_count=? WHERE pmid=?",
            (cc, ic, str(p))).rowcount for p, (cc, ic) in counts.items())


def rebuild_cited_by(db_path: Path) -> int:
    """由所有 cites（正向）汇总出 cited_by（反向）。返回有库内被引的篇数。"""
    init_db(db_path)
    with _conn(db_path) as c:
        rows = c.execute("SELECT pmid, cites FROM articles").fetchall()
        known = {r["pmid"] for r in rows}
        cited_by: dict[str, list[str]] = {p: [] for p in known}
        for r in rows:
            try:
                targets = json.loads(r["cites"] or "[]")
            except ValueError:
                continue
            for t in targets:
                if t in cited_by:
                    cited_by[t].append(r["pmid"])
        for pmid, citers in cited_by.items():
            c.execute("UPDATE articles SET cited_by=? WHERE pmid=?",
                      (json.dumps(sorted(set(citers))) if citers else "", pmid))
        return sum(1 for v in cited_by.values() if v)


# ─── 项目标签 ─────────────────────────────────────────────────────────────────

def list_projects(db_path: Path) -> list[dict]:
    init_db(db_path)
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute(
            """SELECT p.id,p.name,p.description,p.created,p.archived,
                      (SELECT COUNT(*) FROM article_projects ap WHERE ap.project_id=p.id) AS count
                 FROM projects p ORDER BY p.name""").fetchall()]


def create_project(db_path: Path, name: str, description: str = "") -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("项目名不能为空")
    init_db(db_path)
    with _conn(db_path) as c:
        row = c.execute("SELECT id FROM projects WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        return c.execute(
            "INSERT INTO projects (name,description,created,archived) VALUES (?,?,?,0)",
            (name, description, str(datetime.date.today()))).lastrowid


def add_to_project(db_path: Path, name: str, pmids: list[str]) -> dict:
    pid = create_project(db_path, name)
    today, added, missing = str(datetime.date.today()), 0, []
    with _conn(db_path) as c:
        for p in pmids:
            p = str(p).strip()
            if not p:
                continue
            if not c.execute("SELECT 1 FROM articles WHERE pmid=?", (p,)).fetchone():
                missing.append(p)
                continue
            added += c.execute(
                "INSERT OR IGNORE INTO article_projects (pmid,project_id,added) VALUES (?,?,?)",
                (p, pid, today)).rowcount
    return {"added": added, "missing": missing}


def remove_from_project(db_path: Path, name: str, pmids: list[str]) -> int:
    init_db(db_path)
    with _conn(db_path) as c:
        row = c.execute("SELECT id FROM projects WHERE name=?", ((name or "").strip(),)).fetchone()
        if not row:
            return 0
        return sum(c.execute("DELETE FROM article_projects WHERE pmid=? AND project_id=?",
                             (str(p).strip(), row["id"])).rowcount for p in pmids)


def rename_project(db_path: Path, old: str, new: str) -> bool:
    new = (new or "").strip()
    if not new:
        raise ValueError("新项目名不能为空")
    init_db(db_path)
    with _conn(db_path) as c:
        try:
            return c.execute("UPDATE projects SET name=? WHERE name=?",
                             (new, (old or "").strip())).rowcount > 0
        except sqlite3.IntegrityError:
            # name 上有 UNIQUE 约束，改成已存在的名字会撞车
            raise ValueError(
                f"项目「{new}」已存在，不能重名。\n"
                f"  想合并两个项目，可先把成员加过去再删掉旧项目：\n"
                f"    python3 cli.py project --config <配置> --name {new} --add --pmid <PMID…>\n"
                f"    python3 cli.py project --config <配置> --name {old} --delete") from None


def delete_project(db_path: Path, name: str) -> bool:
    """删除项目及关联，但**不删文章**。"""
    init_db(db_path)
    with _conn(db_path) as c:
        row = c.execute("SELECT id FROM projects WHERE name=?", ((name or "").strip(),)).fetchone()
        if not row:
            return False
        c.execute("DELETE FROM article_projects WHERE project_id=?", (row["id"],))
        c.execute("DELETE FROM projects WHERE id=?", (row["id"],))
        return True


def set_archived(db_path: Path, name: str, archived: bool = True) -> bool:
    init_db(db_path)
    with _conn(db_path) as c:
        return c.execute("UPDATE projects SET archived=? WHERE name=?",
                         (1 if archived else 0, (name or "").strip())).rowcount > 0


def project_map(db_path: Path) -> dict[str, list[str]]:
    init_db(db_path)
    out: dict[str, list[str]] = {}
    with _conn(db_path) as c:
        for r in c.execute("""SELECT ap.pmid, p.name FROM article_projects ap
                                JOIN projects p ON p.id=ap.project_id
                               ORDER BY p.name""").fetchall():
            out.setdefault(r["pmid"], []).append(r["name"])
    return out


# ─── 排序（全部由配置驱动）────────────────────────────────────────────────────

def sort_key(config, art: dict):
    """(板块序, 子板块序, 日期倒序)。配置里没出现的板块/子板块排到最后。"""
    sec_rank = {s.name: i for i, s in enumerate(config.sections)}
    sub_rank = config.subsection_order().get(art.get("section") or "", {})
    return (sec_rank.get(art.get("section") or "", 999),
            sub_rank.get(art.get("subsection") or "", 999),
            -int((art.get("pub_date") or "0000-00-00").replace("-", "") or 0))


def sorted_articles(config, arts: list[dict]) -> list[dict]:
    return sorted(arts, key=lambda a: sort_key(config, a))
