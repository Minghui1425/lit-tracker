"""EndNote / Zotero 导出文件的解析与「落到 PMID」。

全程离线：DOI/标题那两条路要联网，测试里换成假的——这里要保证的是**从各家导出
格式里把 PMID/DOI/标题挖出来**，以及三级路径的取舍顺序，而不是 PubMed 的返回。
"""
import pytest

from conftest import BASE  # noqa: F401  （插入 sys.path）
from littrack import refs

RIS = """TY  - JOUR
AU  - Doe, Jane
TI  - Sacubitril valsartan in heart failure with preserved
      ejection fraction
JO  - Circulation
DO  - 10.1161/CIRCULATIONAHA.126.00123
AN  - 39123456
DB  - PubMed
ER  -

TY  - JOUR
TI  - SGLT2 inhibitors and kidney outcomes
DO  - 10.1016/j.jacc.2026.01.002
N1  - PMID: 40011223
ER  -

TY  - BOOK
TI  - Some textbook nobody indexed
ER  -
"""

NBIB = """PMID- 39123456
OWN - NLM
TI  - Sacubitril valsartan in heart failure with preserved
      ejection fraction.
AID - S0735-1097(26)00002-1 [pii]
LID - 10.1161/CIRCULATIONAHA.126.00123 [doi]

PMID- 40011223
TI  - SGLT2 inhibitors.
"""

BIB = """@article{doe_2026,
  title = {Sacubitril valsartan in {HFpEF}},
  doi = {10.1161/CIRCULATIONAHA.126.00123},
  note = {PMID: 39123456},
}
@article{smith_2026,
  title = "SGLT2 inhibitors",
  doi = "10.1016/j.jacc.2026.01.002"
}
"""

ENDNOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<xml><records>
<record>
  <titles><title><style face="normal" size="100%">Sacubitril valsartan in HFpEF</style></title></titles>
  <accession-num>39123456</accession-num>
  <electronic-resource-num>10.1161/CIRCULATIONAHA.126.00123</electronic-resource-num>
</record>
<record><titles><title>A conference abstract</title></titles></record>
</records></xml>
"""

CSL_JSON = """[
 {"type":"article-journal","title":"Sacubitril valsartan in HFpEF",
  "DOI":"10.1161/CIRCULATIONAHA.126.00123","note":"PMID: 39123456\\nPMCID: PMC123"},
 {"type":"article-journal","title":"SGLT2 inhibitors","DOI":"10.1016/j.jacc.2026.01.002"}
]"""

ENW = """%0 Journal Article
%T Sacubitril valsartan in HFpEF
%R 10.1161/CIRCULATIONAHA.126.00123
%M 39123456
"""


# ── 认格式 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,suffix,fmt", [
    (RIS, ".ris", "ris"), (NBIB, ".nbib", "nbib"), (BIB, ".bib", "bibtex"),
    (ENDNOTE_XML, ".xml", "endnote-xml"), (CSL_JSON, ".json", "csl-json"),
    (ENW, ".enw", "ris"),
])
def test_sniff_by_content_and_suffix(text, suffix, fmt):
    assert refs.sniff(text, suffix) == fmt


def test_content_wins_over_a_lying_suffix():
    """导出文件被存成 .txt 很常见，扩展名不能说了算。"""
    assert refs.sniff(RIS, ".txt") == "ris"
    assert refs.sniff(CSL_JSON, ".ris") == "csl-json"


def test_unknown_format_says_how_to_export(tmp_path):
    f = tmp_path / "my-library.csv"
    f.write_text("标题,作者,年份\n某文章,某人,2026\n", encoding="utf-8")
    with pytest.raises(refs.RefError, match="Zotero"):
        refs.read_file(f)


def test_a_file_that_parses_to_nothing_says_so(tmp_path):
    """扩展名对得上但内容不是那回事——多半是导出时选错了格式。"""
    f = tmp_path / "notes.ris"
    f.write_text("这是一段随手写的笔记，不是任何导出格式", encoding="utf-8")
    with pytest.raises(refs.RefError, match="0 条记录"):
        refs.read_file(f)


# ── 各格式都要挖到同样的东西 ─────────────────────────────────────────────────

@pytest.mark.parametrize("text,suffix", [
    (RIS, ".ris"), (NBIB, ".nbib"), (BIB, ".bib"),
    (ENDNOTE_XML, ".xml"), (CSL_JSON, ".json"), (ENW, ".enw"),
])
def test_first_record_yields_pmid_and_doi(text, suffix):
    _, rs = refs.parse_text(text, "x" + suffix, suffix)
    assert rs[0]["pmid"] == "39123456"
    assert rs[0]["doi"] == "10.1161/CIRCULATIONAHA.126.00123"
    assert "Sacubitril" in rs[0]["title"]


def test_ris_folds_continuation_lines_into_the_title():
    _, rs = refs.parse_text(RIS, "a.ris", ".ris")
    assert rs[0]["title"].endswith("preserved ejection fraction")


def test_zotero_puts_the_pmid_in_a_note():
    """Zotero 把 Extra 字段整段塞进 N1，PMID 只能从文字里捞。"""
    _, rs = refs.parse_text(RIS, "a.ris", ".ris")
    assert rs[1]["pmid"] == "40011223"


def test_bibtex_braces_are_not_part_of_the_title():
    """{HFpEF} 的花括号只是保护大小写，留着会让按标题查 PubMed 必然落空。"""
    _, rs = refs.parse_text(BIB, "a.bib", ".bib")
    assert rs[0]["title"] == "Sacubitril valsartan in HFpEF"


def test_nbib_takes_the_doi_from_the_aid_line_marked_doi():
    """AID 一行一个标识符，pii 不是 DOI。"""
    _, rs = refs.parse_text(NBIB, "a.nbib", ".nbib")
    assert rs[0]["doi"] == "10.1161/CIRCULATIONAHA.126.00123"


def test_endnote_xml_reads_text_wrapped_in_style_tags():
    _, rs = refs.parse_text(ENDNOTE_XML, "a.xml", ".xml")
    assert rs[0]["title"] == "Sacubitril valsartan in HFpEF"


def test_records_without_identifiers_are_kept_for_the_title_path():
    """书籍/会议摘要没有 PMID 也没有 DOI，仍要留着——标题那条路还没走。"""
    _, rs = refs.parse_text(RIS, "a.ris", ".ris")
    assert rs[-1]["title"] == "Some textbook nobody indexed"
    assert rs[-1]["pmid"] == "" and rs[-1]["doi"] == ""


def test_too_many_records_is_refused_rather_than_truncated(monkeypatch):
    monkeypatch.setattr(refs, "MAX_REFS", 2)
    with pytest.raises(refs.RefError, match="上限"):
        refs.parse_text(RIS, "a.ris", ".ris")


def test_read_file_handles_utf16_exports(tmp_path):
    """EndNote 在 Windows 上导出的 RIS 常是 UTF-16。"""
    f = tmp_path / "en.ris"
    f.write_text(RIS, encoding="utf-16")
    fmt, rs = refs.read_file(f)
    assert fmt == "ris" and rs[0]["pmid"] == "39123456"


# ── 落到 PMID 的三级路径 ─────────────────────────────────────────────────────

@pytest.fixture
def offline(monkeypatch):
    """把两条联网路径换成可预期的假实现。"""
    calls = {"doi": [], "title": []}

    def fake_doi(doi):
        calls["doi"].append(doi)
        return {"10.1/known": "20000001"}.get(doi, "")

    def fake_title(title):
        calls["title"].append(title)
        if title == "Known title of a real paper":
            return "20000002"
        raise refs.intake.IntakeError("PubMed 按这个标题没搜到文章")

    monkeypatch.setattr(refs.entrez, "pmid_by_doi", fake_doi)
    monkeypatch.setattr(refs.intake, "find_pmid_by_title", fake_title)
    return calls


def test_pmid_in_the_file_short_circuits_the_network(offline):
    r = refs.resolve([{"pmid": "39123456", "doi": "10.1/known", "title": "Known title of a real paper"}])
    assert r["pmids"] == ["39123456"] and r["how"]["pmid"] == 1
    assert offline["doi"] == [] and offline["title"] == []


def test_doi_is_tried_before_the_title(offline):
    r = refs.resolve([{"pmid": "", "doi": "10.1/known", "title": "Known title of a real paper"}])
    assert r["pmids"] == ["20000001"] and r["how"]["doi"] == 1
    assert offline["title"] == []


def test_title_is_the_last_resort(offline):
    r = refs.resolve([{"pmid": "", "doi": "10.1/unknown", "title": "Known title of a real paper"}])
    assert r["pmids"] == ["20000002"] and r["how"]["title"] == 1


def test_unresolved_records_carry_the_reason(offline):
    r = refs.resolve([{"pmid": "", "doi": "", "title": "Some textbook nobody indexed"}])
    assert r["pmids"] == []
    assert "没搜到" in r["unresolved"][0]["why"]


def test_duplicates_collapse(offline):
    """同一篇在库里出现两次会被 upsert 掉，但重复查一遍 PubMed 是白费。"""
    r = refs.resolve([{"pmid": "1", "doi": "", "title": ""},
                      {"pmid": "1", "doi": "", "title": ""}])
    assert r["pmids"] == ["1"]


def test_one_bad_lookup_does_not_sink_the_whole_batch(offline, monkeypatch):
    def boom(doi):
        raise RuntimeError("NCBI 抽风")

    monkeypatch.setattr(refs.entrez, "pmid_by_doi", boom)
    r = refs.resolve([{"pmid": "", "doi": "10.1/known", "title": "nope"},
                      {"pmid": "42", "doi": "", "title": ""}])
    assert r["pmids"] == ["42"] and len(r["unresolved"]) == 1
