"""库内引文网络。

联网部分全部打桩：这里要验的是「抓到的东西怎么落库、断点怎么续」，
而不是 Semantic Scholar 今天在不在线。
"""
import json
import sqlite3

import pytest

from conftest import article
from littrack import citations, library


@pytest.fixture
def libdb(db):
    """三篇：2 引用 1，3 也引用 1，1 谁都不引。"""
    library.upsert(db, [article("1"), article("2"), article("3")])
    return db


@pytest.fixture
def fake_s2(monkeypatch):
    """按 {pmid: (参考文献列表, status)} 打桩，并记录调用次数。"""
    calls = []

    def install(table, counts=None):
        def _refs(pmid):
            calls.append(pmid)
            return table.get(pmid, ([], "missing"))
        monkeypatch.setattr(citations, "references", _refs)
        monkeypatch.setattr(citations, "citation_counts", lambda pmids: counts or {})
        monkeypatch.setattr(citations.time, "sleep", lambda *_: None)
        return calls

    return install


def test_builds_forward_and_reverse_links(libdb, fake_s2):
    fake_s2({
        "1": ([], "ok"),
        "2": (["1", "999"], "ok"),        # 999 不在库内，应被忽略
        "3": (["1", "2"], "ok"),
    }, counts={"1": (120, 8)})
    r = citations.refresh(libdb, on_progress=None)

    assert (r["ok"], r["missing"], r["failed"]) == (3, 0, 0)
    by_pmid = {a["pmid"]: a for a in library.all_articles(libdb)}
    assert json.loads(by_pmid["2"]["cites"]) == ["1"]
    assert json.loads(by_pmid["1"]["cited_by"]) == ["2", "3"]
    assert by_pmid["1"]["cited_by"] and not by_pmid["3"]["cited_by"]
    assert r["cited"] == 2                                  # 1 和 2 有库内被引
    assert (by_pmid["1"]["citation_count"], by_pmid["1"]["influential_count"]) == (120, 8)


def test_second_run_skips_already_fetched(libdb, fake_s2):
    table = {p: ([], "ok") for p in ("1", "2", "3")}
    calls = fake_s2(table)
    citations.refresh(libdb)
    assert len(calls) == 3

    calls.clear()
    citations.refresh(libdb)
    assert calls == []                                      # 全部跳过

    calls.clear()
    citations.refresh(libdb, force=True)
    assert len(calls) == 3                                  # --force 重抓


def test_failed_article_is_retried_next_time(libdb, fake_s2):
    calls = fake_s2({"1": ([], "ok"), "2": ([], "error"), "3": ([], "ok")})
    r = citations.refresh(libdb)
    assert r["failed"] == 1

    calls.clear()
    citations.refresh(libdb)
    assert calls == ["2"]                                   # 只重试失败的那篇


def test_s2_not_indexed_counts_as_done(libdb, fake_s2):
    calls = fake_s2({"1": ([], "missing"), "2": ([], "missing"), "3": ([], "missing")})
    r = citations.refresh(libdb)
    assert r["missing"] == 3 and r["failed"] == 0
    calls.clear()
    citations.refresh(libdb)
    assert calls == []                    # 未收录也算抓过，不必每次重问


def test_new_article_only_needs_its_own_fetch(libdb, fake_s2):
    calls = fake_s2({p: ([], "ok") for p in ("1", "2", "3", "4")})
    citations.refresh(libdb)
    calls.clear()
    library.upsert(libdb, [article("4")])
    citations.refresh(libdb)
    assert calls == ["4"]


def test_self_citation_is_ignored(libdb, fake_s2):
    fake_s2({"1": (["1"], "ok")})
    citations.refresh(libdb)
    by_pmid = {a["pmid"]: a for a in library.all_articles(libdb)}
    assert json.loads(by_pmid["1"]["cites"]) == []


def test_deleted_citer_disappears_from_cited_by(libdb, fake_s2):
    fake_s2({"1": ([], "ok"), "2": (["1"], "ok"), "3": (["1"], "ok")})
    citations.refresh(libdb)
    library.delete(libdb, ["3"])
    library.rebuild_cited_by(libdb)
    by_pmid = {a["pmid"]: a for a in library.all_articles(libdb)}
    assert json.loads(by_pmid["1"]["cited_by"]) == ["2"]


def test_old_database_gets_the_new_columns(tmp_path):
    """升级上来的库没有引文列，init_db 必须补上，而不是查询时报 no such column。"""
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE articles (pmid TEXT PRIMARY KEY, title TEXT, "
                  "notes TEXT DEFAULT '', rating TEXT DEFAULT '')")
        c.execute("INSERT INTO articles (pmid,title,notes) VALUES ('1','旧文章','我的笔记')")

    library.init_db(db)
    row = library.all_articles(db)[0]
    assert row["notes"] == "我的笔记"                        # 老数据不动
    for col in ("cites", "cited_by", "citation_count",
                "influential_count", "citations_synced"):
        assert col in row
    assert library.citation_targets(db) == ["1"]            # 老文章会被排进待抓
