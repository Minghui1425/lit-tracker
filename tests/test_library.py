"""收藏库：重复入库的语义，以及项目标签的边界情况。"""
import pytest

from conftest import article
from littrack import library


def test_insert_then_update_keeps_user_data(db):
    assert library.upsert(db, [article(section="", subsection="")]) == (1, 0)
    library.set_note(db, "1", "我的笔记")
    library.set_rating(db, "1", "⭐")

    # 二次入库：这次命中了板块，元数据也刷新了
    assert library.upsert(db, [article(title="新标题", section="心衰进展",
                                       subsection="其他", if_value="12.3")]) == (0, 1)
    r = library.all_articles(db)[0]
    assert (r["title"], r["section"], r["subsection"], r["if_value"]) == \
           ("新标题", "心衰进展", "其他", "12.3")
    assert (r["notes"], r["rating"]) == ("我的笔记", "⭐")


def test_update_never_clears_existing_section(db):
    """没命中关键词的那次重跑，不能把已有归类抹成空。"""
    library.upsert(db, [article(section="心衰进展", subsection="其他")])
    library.upsert(db, [article(title="改了标题", section="", subsection="")])
    r = library.all_articles(db)[0]
    assert (r["section"], r["subsection"]) == ("心衰进展", "其他")
    assert r["title"] == "改了标题"


def test_added_date_is_not_bumped_by_reimport(db):
    library.upsert(db, [article()])
    first = library.all_articles(db)[0]["added_date"]
    library.upsert(db, [article(title="又改了")])
    assert library.all_articles(db)[0]["added_date"] == first


def test_rating_validated(db):
    library.upsert(db, [article()])
    with pytest.raises(ValueError):
        library.set_rating(db, "1", "五星")


def test_delete_removes_project_links(db):
    library.upsert(db, [article()])
    library.add_to_project(db, "课题甲", ["1"])
    assert library.delete(db, ["1"]) == 1
    assert library.project_map(db) == {}


def test_add_to_project_reports_missing(db):
    library.upsert(db, [article()])
    r = library.add_to_project(db, "课题甲", ["1", "999"])
    assert r["added"] == 1 and r["missing"] == ["999"]
    # 重复加入不重复计数
    assert library.add_to_project(db, "课题甲", ["1"])["added"] == 0


def test_rename_to_existing_name_raises_valueerror(db):
    """SQLite 的 UNIQUE 冲突要转成用户能看懂的话，而不是 IntegrityError。"""
    library.create_project(db, "课题甲")
    library.create_project(db, "课题乙")
    with pytest.raises(ValueError) as e:
        library.rename_project(db, "课题乙", "课题甲")
    assert "课题甲" in str(e.value)
    assert {p["name"] for p in library.list_projects(db)} == {"课题甲", "课题乙"}


def test_rename_missing_project_returns_false(db):
    assert library.rename_project(db, "不存在", "新名") is False


def test_delete_project_keeps_articles(db):
    library.upsert(db, [article()])
    library.add_to_project(db, "课题甲", ["1"])
    assert library.delete_project(db, "课题甲") is True
    assert len(library.all_articles(db)) == 1


def test_sort_follows_config_order(cfg, db):
    library.upsert(db, [
        article("1", section="心衰进展", subsection="其他", pub_date="2026-01-01"),
        article("2", section="药物不良反应", subsection="代谢", pub_date="2020-01-01"),
        article("3", section="药物不良反应", subsection="肾脏", pub_date="2019-01-01"),
    ])
    order = [a["pmid"] for a in library.sorted_articles(cfg, library.all_articles(db))]
    assert order == ["3", "2", "1"]      # 板块序 > 子板块序 > 日期，日期不越级


# ── 文章类型标签的人工覆盖 ───────────────────────────────────────────────────

def test_pinned_type_survives_a_re_ingest(db):
    """钉过的标签必须挡住重新入库——否则用户改一次、PubMed 盖回来一次。"""
    library.upsert(db, [article("1", type_label="Article"),
                        article("2", type_label="Article")])
    library.set_type_override(db, "1", "Research Highlight")

    library.upsert(db, [article("1", type_label="Article"),
                        article("2", type_label="Review")])
    got = {a["pmid"]: a["pub_type"] for a in library.all_articles(db)}
    assert got == {"1": "Research Highlight", "2": "Review"}   # 没钉的照常跟着 PubMed 走


def test_clear_override_lets_pubmed_win_again(db):
    library.upsert(db, [article("1", type_label="Article")])
    library.set_type_override(db, "1", "Guideline")
    assert library.clear_type_override(db, "1") is True
    assert library.clear_type_override(db, "1") is False      # 第二次没得撤

    library.upsert(db, [article("1", type_label="Review")])
    assert library.all_articles(db)[0]["pub_type"] == "Review"


def test_listing_overrides_reports_what_was_pinned(db):
    library.upsert(db, [article("1", title="某篇综述")])
    library.set_type_override(db, "1", "Editorial")
    rows = library.list_type_overrides(db)
    assert len(rows) == 1
    assert rows[0]["pmid"] == "1" and rows[0]["pub_type"] == "Editorial"
    assert rows[0]["title"] == "某篇综述" and rows[0]["set_at"]


def test_cannot_pin_an_article_that_is_not_in_the_library(db):
    with pytest.raises(ValueError, match="没有 PMID"):
        library.set_type_override(db, "999", "Review")


def test_empty_label_is_refused(db):
    library.upsert(db, [article("1")])
    with pytest.raises(ValueError, match="不能为空"):
        library.set_type_override(db, "1", "   ")


def test_deleting_an_article_drops_its_override(db):
    """否则日后重新收藏同一篇，会莫名其妙自带一个早就忘了的标签。"""
    library.upsert(db, [article("1", type_label="Article")])
    library.set_type_override(db, "1", "Research Highlight")
    library.delete(db, ["1"])
    assert library.list_type_overrides(db) == []

    library.upsert(db, [article("1", type_label="Article")])
    assert library.all_articles(db)[0]["pub_type"] == "Article"
