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
