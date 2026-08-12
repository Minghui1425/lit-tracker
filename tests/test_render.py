"""周报 / 历史报告页：勾选框、「加入收藏库」按钮、内嵌凭据。

页面里的 JS 是 f-string 拼的，转义写错会让整段脚本失效而页面照常打开——
装了 node 时这里做真正的语法检查。
"""
import json
import re
import shutil
import subprocess

import pytest

from conftest import BASE  # noqa: F401  （插入 sys.path）
from littrack import render

ART = {"pmid": "42482656", "title": 'Quotes " and <tags> and \\ in a title',
       "journal": "Circulation", "pub_date": "2026-07-01", "keywords": ["a"],
       "quartile": "Q1", "if_value": "37.8", "type_label": "Journal Article",
       "abstract": "An abstract"}


@pytest.fixture
def page(cfg, tmp_path):
    grouped = {cfg.sections[0].name: {cfg.sections[0].subsection_names[0]: [ART]}}
    out = render.render(cfg, grouped, "2026-07-01", "2026-07-07",
                        tmp_path / "weekly.html", port=8781, token="tok-abc")
    return out.read_text(encoding="utf-8")


def _js(page: str) -> str:
    return page.split("<script>", 1)[1].rsplit("</script>", 1)[0]


def test_every_article_gets_a_checkbox_carrying_its_section(cfg, page):
    assert 'class=art-cb' in page
    assert f"data-pmid='{ART['pmid']}'" in page
    assert f"data-sec='{cfg.sections[0].name}'" in page


def test_token_and_endpoint_are_embedded(page):
    assert 'const TOKEN="tok-abc"' in page
    assert "/article/add-from-report" in page
    assert "X-LitTrack-Token" in page


def test_the_add_button_is_only_shown_when_there_are_articles(cfg, tmp_path):
    empty = render.render(cfg, {}, "2026-07-01", "2026-07-07",
                          tmp_path / "empty.html").read_text(encoding="utf-8")
    assert "id=add-lib" not in empty        # CSS 里那条规则不算
    assert "未检索到" in empty


def test_script_closing_tag_in_the_token_is_escaped(cfg, tmp_path):
    bad = '</script><script>alert("x")</script>'
    doc = render.render(cfg, {}, "2026-07-01", "2026-07-07",
                        tmp_path / "x.html", token=bad).read_text(encoding="utf-8")
    assert doc.count("</script>") == 1
    assert bad not in doc


def test_special_characters_in_titles_do_not_break_the_page(page):
    assert page.count("<script>") == 1
    assert "&quot;" in page or "&#34;" in page          # 标题里的引号被转义了
    assert "<tags>" not in page


@pytest.mark.skipif(not shutil.which("node"), reason="需要 node 才能真的做语法检查")
def test_generated_js_parses(page, tmp_path):
    f = tmp_path / "page.js"
    f.write_text(_js(page), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_selection_cap_matches_the_intake_limit():
    """页面提示的上限与服务端真正的上限对不上的话，用户会白勾一遍。"""
    from littrack import intake
    assert render.ADD_MAX == intake.MAX_PMIDS


def test_articles_are_still_listed_with_their_metadata(page):
    assert "Circulation" in page and "IF 37.8" in page and "Q1" in page
    assert json.dumps("42482656")[1:-1] in page
