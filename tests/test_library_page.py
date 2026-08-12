"""收藏库页面：生成的 JS 必须能解析，token 必须嵌进去。

页面里的 JS 是 f-string 拼的，转义层数写错会让**整段脚本**失效——页面照常打开，
但按钮和筛选全部失灵，控制台还常常不报错。render 内部有 _sanity_check，
装了 node 时会做真正的语法检查，这里顺带把它跑起来。
"""
import json
import re

import pytest

from conftest import article
from littrack import library, library_page


@pytest.fixture
def page(cfg, db, tmp_path):
    library.upsert(db, [
        article("1", section="心衰进展", subsection="其他",
                title='带引号 " 与 <标签> 和反斜杠 \\ 的标题'),
        article("2", section="药物不良反应", subsection="肾脏", if_value="12.3",
                quartile="Q1"),
    ])
    library.add_to_project(db, "课题甲", ["1"])
    out = tmp_path / "library.html"
    library_page.render(cfg, db, out, port=8781, token="tok-abc")
    return out.read_text(encoding="utf-8")


def test_token_and_api_base_embedded(page):
    assert 'const TOKEN = "tok-abc"' in page
    assert "X-LitTrack-Token" in page


def test_articles_are_embedded_as_valid_json(page):
    m = re.search(r"^const ARTS = (\[.*?\]);$", page, re.S | re.M)
    arts = json.loads(m.group(1))
    assert {a["pmid"] for a in arts} == {"1", "2"}
    assert any(a["proj"] == ["课题甲"] for a in arts)


def test_special_characters_do_not_break_the_script(page):
    """标题里的引号/尖括号/反斜杠不能把 JS 字符串截断。"""
    assert page.count("<script>") == 1
    js = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    assert js.count("{") == js.count("}")


def test_script_closing_tag_in_data_is_escaped(cfg, db, tmp_path):
    """PubMed 或用户数据不能提前结束内嵌 script。"""
    bad = '</script><script>alert("x")</script>'
    library.upsert(db, [article(title=bad, notes=bad)])
    library.add_to_project(db, bad, ["1"])
    out = tmp_path / "library.html"
    library_page.render(cfg, db, out, token="t")
    page = out.read_text(encoding="utf-8")

    assert page.count("</script>") == 1
    assert bad not in page
    assert "\\u003c/script\\u003e" in page


def test_citation_badges_and_citer_list(cfg, db, tmp_path):
    library.upsert(db, [article("1", section="心衰进展", subsection="其他"),
                        article("2", title="引用了 1 的那篇",
                                section="心衰进展", subsection="其他")])
    library.set_cites(db, "2", ["1"])
    library.rebuild_cited_by(db)
    library.set_citation_counts(db, {"1": (120, 8)})

    out = tmp_path / "library.html"
    library_page.render(cfg, db, out, token="t")
    page = out.read_text(encoding="utf-8")

    m = re.search(r"^const ARTS = (\[.*?\]);$", page, re.S | re.M)
    arts = {a["pmid"]: a for a in json.loads(m.group(1))}
    assert arts["1"]["citedby"] == ["2"] and arts["1"]["cc"] == 120
    assert arts["2"]["cites"] == ["1"] and arts["2"]["citedby"] == []
    assert "库内被引" in page and "b-cit" in page
    # 「引用情况」下拉要同时覆盖全球被引区间和库内引用关系
    for opt in ('value="1-10"', 'value="100-"', 'value="db1"', 'value="db0"'):
        assert opt in page


def test_page_renders_before_citations_ever_ran(cfg, db, tmp_path):
    """没跑过 citations 时这些列是空串，不能让页面崩掉。"""
    library.upsert(db, [article("1", section="心衰进展", subsection="其他")])
    out = tmp_path / "library.html"
    library_page.render(cfg, db, out, token="t")
    m = re.search(r"^const ARTS = (\[.*?\]);$", out.read_text(encoding="utf-8"), re.S | re.M)
    a = json.loads(m.group(1))[0]
    assert a["citedby"] == [] and a["cites"] == [] and a["cc"] is None


def test_empty_library_still_renders(cfg, db, tmp_path):
    out = tmp_path / "library.html"
    library_page.render(cfg, db, out, port=8781, token="t")
    assert "无匹配文献" in out.read_text(encoding="utf-8")


def test_sanity_check_rejects_broken_js():
    with pytest.raises(RuntimeError):
        library_page._sanity_check("<html><script>function f(){ </script></html>")


def _js_const(doc: str, name: str):
    m = re.search(rf"^const {name} = (.+?);(?:\s*//.*)?$", doc, re.M)
    assert m, f"页面里没有 {name}"
    return json.loads(m.group(1))


def test_filter_dropdowns_only_offer_values_present_in_the_library(cfg, db, tmp_path):
    """列出 0 篇的子板块等于给人挖坑：选中后一片空白，还得回头怀疑是不是筛错了。"""
    library.upsert(db, [
        article("1", section="心衰进展", subsection="射血分数保留", journal="Circulation"),
        article("2", section="药物不良反应", subsection="肾脏", journal="JAMA"),
    ])
    doc = (library_page.render(cfg, db, tmp_path / "l.html")).read_text(encoding="utf-8")

    fsubs = _js_const(doc, "FSUBS")
    assert fsubs["心衰进展"] == ["射血分数保留"]        # 「器械与介入」「其他」都还没有文章
    assert fsubs["药物不良反应"] == ["肾脏"]
    assert _js_const(doc, "ALLSUBS") == ["肾脏", "射血分数保留"]   # 顺序按配置，不按字母

    # 「添加文献」弹窗用的仍是配置全量：新收的可能就是某个空子板块的第一篇
    submap = _js_const(doc, "SUBMAP")
    assert submap["心衰进展"] == ["射血分数保留", "器械与介入", "其他"]


def test_journal_dropdown_is_narrowed_per_section(cfg, db, tmp_path):
    library.upsert(db, [
        article("1", section="心衰进展", subsection="其他", journal="Circulation"),
        article("2", section="心衰进展", subsection="其他", journal="Eur Heart J"),
        article("3", section="药物不良反应", subsection="肾脏", journal="JAMA"),
    ])
    doc = (library_page.render(cfg, db, tmp_path / "l.html")).read_text(encoding="utf-8")

    assert _js_const(doc, "SECJRNS") == {"心衰进展": ["Circulation", "Eur Heart J"],
                                         "药物不良反应": ["JAMA"]}
    assert _js_const(doc, "ALLJRNS") == ["Circulation", "Eur Heart J", "JAMA"]


def test_pdf_flag_reflects_the_filesystem(cfg, db, tmp_path):
    """有没有 PDF 以目录为准，不在库表里另存字段——两处记录必然会漂移。"""
    from littrack import pdfs
    library.upsert(db, [article("1", section="心衰进展", subsection="其他"),
                        article("2", section="心衰进展", subsection="其他")])
    pdfs.save(pdfs.dir_for(db), "2", b"%PDF-1.4\n%%EOF\n")
    doc = (library_page.render(cfg, db, tmp_path / "l.html")).read_text(encoding="utf-8")

    flags = {a["pmid"]: a["pdf"] for a in _js_const(doc, "ARTS")}
    assert flags == {"1": 0, "2": 1}


# ── 入库时间筛选 ─────────────────────────────────────────────────────────────

def test_added_date_and_last_added_are_embedded(cfg, db, tmp_path):
    """「最近一次入库」按 max(added_date) 算——一批文献的入库日期常摊在几天里。"""
    import sqlite3
    library.upsert(db, [article("1"), article("2")])
    with sqlite3.connect(db) as c:
        c.execute("UPDATE articles SET added_date='2026-06-13' WHERE pmid='2'")
        c.execute("UPDATE articles SET added_date='2026-08-12' WHERE pmid='1'")
    out = tmp_path / "library.html"
    library_page.render(cfg, db, out, token="t")
    page = out.read_text(encoding="utf-8")

    assert 'const LAST_ADDED = "2026-08-12"' in page
    arts = json.loads(re.search(r"^const ARTS = (\[.*?\]);$", page, re.S | re.M).group(1))
    assert {a["pmid"]: a["added"] for a in arts} == {"1": "2026-08-12", "2": "2026-06-13"}


def test_the_added_filter_is_wired_up_and_gets_reset(page):
    assert "id=f-added" in page and "近 7 天" in page and "最近一次入库" in page
    reset = page.split("function reset(", 1)[1].split("}", 1)[0]
    assert "f-added" in reset            # 游离的筛选项是最难发现的「怎么少了几篇」


def test_an_empty_library_still_renders(cfg, db, tmp_path):
    """一篇都没有时 max() 没得可取，不能因此炸掉整页。"""
    out = tmp_path / "library.html"
    library_page.render(cfg, db, out, token="t")
    assert 'const LAST_ADDED = ""' in out.read_text(encoding="utf-8")
