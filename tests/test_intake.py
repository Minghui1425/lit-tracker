"""收藏库入库：PMID/标题解析、板块校验、写库。

不联网——efetch / esearch 在测试里换成假的，只测我们自己的逻辑。
"""
import pytest

from conftest import BASE  # noqa: F401  （插入 sys.path）
from littrack import entrez, intake, library, pdfs
from littrack.journals import JournalIndex


def _art(pmid, title, journal="Circulation"):
    return {"pmid": pmid, "title": title, "journal_full": journal, "journal_abbr": journal,
            "pub_date": "2026-01-02", "abstract": "", "keywords": [],
            "pub_types": ["Journal Article"], "affiliation": "", "authors": ["Doe J"],
            "issns": set(), "doi": ""}


# ── 输入解析 ─────────────────────────────────────────────────────────────────

def test_parse_pmids_splits_and_dedups():
    assert intake.parse_pmids("42482656, 123；123 456") == ["42482656", "123", "456"]
    assert intake.parse_pmids(["1", 2]) == ["1", "2"]


@pytest.mark.parametrize("bad", ["", "   ", "abc", "12a", "-3", None])
def test_parse_pmids_rejects_junk(bad):
    with pytest.raises(intake.IntakeError):
        intake.parse_pmids(bad)


def test_resolve_treats_digits_as_pmids(monkeypatch):
    monkeypatch.setattr(intake, "find_pmid_by_title",
                        lambda t: pytest.fail("纯数字不该走标题检索"))
    assert intake.resolve(" 42482656 ,123 ") == ["42482656", "123"]


def test_resolve_looks_up_a_title(monkeypatch):
    monkeypatch.setattr(entrez, "esearch", lambda term, retmax=5: ["999"])
    assert intake.resolve("Sacubitril valsartan in heart failure") == ["999"]


def test_title_lookup_disambiguates_by_exact_match(monkeypatch):
    """标题撞车时只认完全一致的那篇——猜错就是往库里加了别人的文章。"""
    monkeypatch.setattr(entrez, "esearch", lambda term, retmax=5: ["1", "2"])
    monkeypatch.setattr(entrez, "efetch", lambda ids, **kw: [
        _art("1", "Sacubitril valsartan in heart failure."),
        _art("2", "Sacubitril valsartan in heart failure: a correction to the trial"),
    ])
    assert intake.resolve("Sacubitril valsartan in heart failure") == ["1"]


def test_title_lookup_refuses_when_ambiguous(monkeypatch):
    monkeypatch.setattr(entrez, "esearch", lambda term, retmax=5: ["1", "2"])
    monkeypatch.setattr(entrez, "efetch", lambda ids, **kw: [
        _art("1", "Heart failure in 2026"), _art("2", "Heart failure in 2026")])
    with pytest.raises(intake.IntakeError, match="匹配到"):
        intake.resolve("Heart failure in 2026")


def test_title_lookup_reports_no_hit(monkeypatch):
    monkeypatch.setattr(entrez, "esearch", lambda term, retmax=5: [])
    with pytest.raises(intake.IntakeError, match="没搜到"):
        intake.resolve("A paper that does not exist anywhere")


def test_short_title_is_rejected_before_hitting_pubmed(monkeypatch):
    monkeypatch.setattr(entrez, "esearch",
                        lambda *a, **kw: pytest.fail("太短的标题不该发请求"))
    with pytest.raises(intake.IntakeError, match="太短"):
        intake.resolve("HF")


# ── 板块校验 ─────────────────────────────────────────────────────────────────

def test_check_section_rejects_unknown_names(cfg):
    sec = cfg.sections[0]
    intake.check_section(cfg, sec.name, sec.subsection_names[0])
    intake.check_section(cfg, "", "")
    with pytest.raises(intake.IntakeError, match="没有板块"):
        intake.check_section(cfg, "不存在的板块", "")
    with pytest.raises(intake.IntakeError, match="没有子板块"):
        intake.check_section(cfg, sec.name, "不存在的子板块")
    with pytest.raises(intake.IntakeError, match="没给板块"):
        intake.check_section(cfg, "", "某子板块")


# ── 写库 ─────────────────────────────────────────────────────────────────────

def test_collect_writes_and_reports(cfg, db, monkeypatch):
    monkeypatch.setattr(entrez, "efetch",
                        lambda ids, **kw: [_art("1", "A heart failure trial")])
    r = intake.collect(cfg, db, ["1", "2"], journals=JournalIndex.empty())
    assert r["added"] == 1 and r["updated"] == 0
    assert r["existing"] == [] and r["missing"] == ["2"]     # 2 是 PubMed 没有的
    assert [a["pmid"] for a in library.all_articles(db)] == ["1"]

    r2 = intake.collect(cfg, db, ["1"], journals=JournalIndex.empty())
    assert r2["added"] == 0 and r2["updated"] == 1 and r2["existing"] == ["1"]


def test_manual_section_overrides_auto_classification(cfg, db, monkeypatch):
    sec = cfg.sections[0]
    monkeypatch.setattr(entrez, "efetch",
                        lambda ids, **kw: [_art("1", "Something unclassifiable zzz")])
    intake.collect(cfg, db, ["1"], journals=JournalIndex.empty(),
                   section=sec.name, subsection=sec.subsection_names[0])
    got = library.all_articles(db)[0]
    assert (got["section"], got["subsection"]) == (sec.name, sec.subsection_names[0])


def test_collect_refuses_more_than_the_cap(cfg, db):
    with pytest.raises(intake.IntakeError, match="最多"):
        intake.collect(cfg, db, [str(i) for i in range(intake.MAX_PMIDS + 1)],
                       journals=JournalIndex.empty())


def test_collect_does_not_touch_pdfs_unless_asked(cfg, db, monkeypatch):
    monkeypatch.setattr(entrez, "efetch", lambda ids, **kw: [_art("1", "A heart failure trial")])
    monkeypatch.setattr(pdfs, "fetch_many",
                        lambda *a, **kw: pytest.fail("没要求抓全文就不该去抓"))
    r = intake.collect(cfg, db, ["1"], journals=JournalIndex.empty())
    assert r["pdf_fetched"] == 0


def test_collect_can_fetch_oa_for_newly_added(cfg, db, monkeypatch):
    monkeypatch.setattr(entrez, "efetch", lambda ids, **kw: [_art("1", "A heart failure trial")])
    monkeypatch.setattr(pdfs, "fetch_many", lambda arts, d, **kw: {"fetched": len(arts)})
    r = intake.collect(cfg, db, ["1"], journals=JournalIndex.empty(), fetch_pdf=True)
    assert r["added"] == 1 and r["pdf_fetched"] == 1


def test_collect_only_tries_oa_for_the_new_ones(cfg, db, monkeypatch):
    """已在库的要么早有 PDF，要么之前就试过没拿到，重试一遍多半还是白等。"""
    monkeypatch.setattr(entrez, "efetch",
                        lambda ids, **kw: [_art(p, f"Trial {p}") for p in ids])
    intake.collect(cfg, db, ["1"], journals=JournalIndex.empty())        # 先收 1

    seen = []
    monkeypatch.setattr(pdfs, "fetch_many",
                        lambda arts, d, **kw: (seen.extend(a["pmid"] for a in arts),
                                               {"fetched": 0})[1])
    intake.collect(cfg, db, ["1", "2"], journals=JournalIndex.empty(), fetch_pdf=True)
    assert seen == ["2"]


def test_a_failed_pdf_fetch_never_breaks_the_add(cfg, db, monkeypatch):
    """全文是附加品：抓不到、甚至抓崩了，都不该让「文献已经收进来了」变成一次失败。"""
    monkeypatch.setattr(entrez, "efetch", lambda ids, **kw: [_art("1", "A heart failure trial")])

    def boom(*a, **kw):
        raise RuntimeError("Europe PMC 连不上")

    monkeypatch.setattr(pdfs, "fetch_many", boom)
    r = intake.collect(cfg, db, ["1"], journals=JournalIndex.empty(), fetch_pdf=True)
    assert r["added"] == 1 and r["pdf_fetched"] == 0
    assert [a["pmid"] for a in library.all_articles(db)] == ["1"]


def test_collect_reports_when_pubmed_returns_nothing(cfg, db, monkeypatch):
    monkeypatch.setattr(entrez, "efetch", lambda ids, **kw: [])
    with pytest.raises(intake.IntakeError, match="没返回"):
        intake.collect(cfg, db, ["1"], journals=JournalIndex.empty())
