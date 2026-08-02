"""关键词变体与归类优先级。

单复数这块是「本地判定」和「PubMed 检索式」两边都要覆盖的：只补一边的话，
文章会在抓取阶段就漏掉，本地判定再准也没用。
"""
from littrack import matchers


def test_plural_matches_singular_keyword():
    assert matchers.hits("Skin rashes after therapy", ["rash"])
    assert matchers.hits("Diabetic nephropathies in elderly", ["nephropathy"])
    assert matchers.hits("A rash appeared", ["rash"])


def test_word_boundary_not_substring():
    # crashes 里含 rash，但不该命中
    assert not matchers.hits("Car crashes and injury", ["rash"])


def test_s_ending_keyword_not_double_pluralized():
    assert matchers.query_forms("diabetes") == ["diabetes"]


def test_query_forms_cover_plurals():
    assert set(matchers.query_forms("nephropathy")) == {"nephropathy", "nephropathies"}
    assert set(matchers.query_forms("rash")) == {"rash", "rashs", "rashes"}


def test_expand_for_query_dedupes():
    out = matchers.expand_for_query(["rash", "rash", "nephropathy"])
    assert out == ["rash", "rashs", "rashes", "nephropathy", "nephropathies"]


def test_section_order_is_dedup_priority(cfg):
    """一篇同时像两个板块的文章，只归**配置里靠前**的那个。"""
    title = ("SGLT2 inhibitor associated acute kidney injury in HFpEF: "
             "preserved ejection fraction cohort")
    sec, sub = matchers.classify(cfg, title)
    assert sec == "药物不良反应"          # 配置里排在「心衰进展」之前
    assert sub == "肾脏"                   # 子板块同样取首个命中者


def test_subsection_order_is_first_hit(cfg):
    title = "SGLT2 inhibitor and ketoacidosis: a safety analysis"
    sec, sub = matchers.classify(cfg, title)
    assert (sec, sub) == ("药物不良反应", "代谢")   # 「代谢」在「其他」之前


def test_no_match_returns_none(cfg):
    assert matchers.classify(cfg, "Something entirely unrelated to the config") is None


def test_cross_product_needs_both_sides(cfg):
    """cross_product 板块：只命中一侧不算数。"""
    only_trigger = "SGLT2 inhibitor in outpatients"          # 无 B 侧词
    only_cross = "Acute kidney injury after surgery"          # 无 A 侧词
    for t in (only_trigger, only_cross):
        hit = matchers.classify(cfg, t)
        assert hit is None or hit[0] != "药物不良反应"


def test_type_filter(cfg):
    sec = cfg.sections[0]
    assert matchers.passes_type_filter(sec, ["Journal Article"])
    assert not matchers.passes_type_filter(sec, ["Editorial"])
