"""全文 PDF：存放、回收站、从文件夹认领。

不联网——OA 抓取那条路只测「批量调度」本身，下载函数换成假的。
"""
import pytest

from conftest import BASE, article  # noqa: F401  （插入 sys.path）
from littrack import library, pdfs

MINI = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


@pytest.fixture
def pdf_dir(tmp_path):
    return tmp_path / "pdf"


# ── 存放 ─────────────────────────────────────────────────────────────────────

def test_save_and_have(pdf_dir):
    pdfs.save(pdf_dir, "42482656", MINI)
    assert pdfs.have(pdf_dir) == {"42482656"}
    assert pdfs.path_for(pdf_dir, "42482656").read_bytes() == MINI


def test_have_is_empty_when_dir_missing(pdf_dir):
    assert pdfs.have(pdf_dir) == set()


def test_save_rejects_non_pdf(pdf_dir):
    """出版商的拦截页是 200 + HTML，不验 %PDF 头就会把一堆「请登录」当全文存下。"""
    with pytest.raises(pdfs.PdfError, match="%PDF"):
        pdfs.save(pdf_dir, "42482656", b"<html>Please sign in</html>")


@pytest.mark.parametrize("bad", ["", "abc", "12a", "../../etc/passwd", "1234567890"])
def test_save_rejects_bad_pmid(pdf_dir, bad):
    with pytest.raises(pdfs.PdfError, match="PMID"):
        pdfs.save(pdf_dir, bad, MINI)


def test_save_rejects_oversize(pdf_dir):
    with pytest.raises(pdfs.PdfError, match="上限"):
        pdfs.save(pdf_dir, "42482656", MINI + b"x" * 100, max_bytes=50)


def test_trash_moves_instead_of_deleting(pdf_dir):
    pdfs.save(pdf_dir, "42482656", MINI)
    assert pdfs.trash(pdf_dir, "42482656") is True
    assert pdfs.have(pdf_dir) == set()
    kept = list((pdf_dir / "_trash").glob("42482656_*.pdf"))
    assert len(kept) == 1 and kept[0].read_bytes() == MINI


def test_trash_on_missing_file_is_a_no_op(pdf_dir):
    assert pdfs.trash(pdf_dir, "42482656") is False


# ── 用系统默认应用打开 ───────────────────────────────────────────────────────

def test_open_external_hands_the_file_to_the_os(pdf_dir, monkeypatch):
    """不指定具体应用，交给系统的文件关联——各平台装了什么就用什么。"""
    pdfs.save(pdf_dir, "42482656", MINI)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(pdfs.sys, "platform", "darwin")
    monkeypatch.setattr(pdfs.subprocess, "run", fake_run)
    assert pdfs.open_external(pdf_dir, "42482656")
    assert seen["cmd"] == ["open", str(pdfs.path_for(pdf_dir, "42482656"))]

    monkeypatch.setattr(pdfs.sys, "platform", "linux")
    pdfs.open_external(pdf_dir, "42482656")
    assert seen["cmd"][0] == "xdg-open"


def test_open_external_on_windows_uses_the_file_association(pdf_dir, monkeypatch):
    pdfs.save(pdf_dir, "42482656", MINI)
    seen = {}
    monkeypatch.setattr(pdfs.sys, "platform", "win32")
    monkeypatch.setattr(pdfs.os, "startfile", lambda p: seen.setdefault("p", p),
                        raising=False)
    monkeypatch.setattr(pdfs.subprocess, "run",
                        lambda *a, **k: pytest.fail("Windows 上不该走 subprocess"))
    assert pdfs.open_external(pdf_dir, "42482656")
    assert seen["p"] == str(pdfs.path_for(pdf_dir, "42482656"))


def test_open_external_without_a_pdf_says_so(pdf_dir, monkeypatch):
    monkeypatch.setattr(pdfs.subprocess, "run",
                        lambda *a, **k: pytest.fail("没有文件就不该去调系统"))
    with pytest.raises(pdfs.PdfError, match="还没有 PDF"):
        pdfs.open_external(pdf_dir, "42482656")


def test_open_external_reports_what_the_os_complained_about(pdf_dir, monkeypatch):
    pdfs.save(pdf_dir, "42482656", MINI)
    monkeypatch.setattr(pdfs.sys, "platform", "linux")
    monkeypatch.setattr(pdfs.subprocess, "run", lambda *a, **k: type(
        "R", (), {"returncode": 3, "stderr": "no application found"})())
    with pytest.raises(pdfs.PdfError, match="no application found"):
        pdfs.open_external(pdf_dir, "42482656")


def test_deleting_an_article_trashes_its_pdf(db):
    """删了文献却留着 PDF，日后重新收藏同一篇会莫名其妙自带一份全文。"""
    library.upsert(db, [article(pmid="42482656")])
    pdf_dir = pdfs.dir_for(db)
    pdfs.save(pdf_dir, "42482656", MINI)
    assert library.delete(db, ["42482656"]) == 1
    assert pdfs.have(pdf_dir) == set()
    assert list((pdf_dir / "_trash").glob("42482656_*.pdf"))


# ── 认领 ─────────────────────────────────────────────────────────────────────

fitz = pytest.importorskip("fitz", reason="认领要靠 PyMuPDF 从正文读 DOI/标题")

ARTS = [
    {"pmid": "42482656", "title": "Sacubitril valsartan in heart failure with preserved ejection fraction",
     "doi": "10.1161/CIRCULATIONAHA.126.00123"},
    {"pmid": "42031428", "title": "SGLT2 inhibitors and kidney outcomes in a nationwide cohort study",
     "doi": "10.1161/CIRCULATIONAHA.126.00456"},
    {"pmid": "42999001", "title": "Device therapy in advanced heart failure: a contemporary review",
     "doi": ""},
]


def _pdf(path, text):
    d = fitz.open()
    d.new_page().insert_text((60, 80), text, fontsize=12)
    d.save(path)
    d.close()


@pytest.fixture
def incoming(tmp_path):
    d = tmp_path / "incoming"
    d.mkdir()
    _pdf(d / "2026-Circulation-下载时被重命名了.pdf",
         "https://doi.org/10.1161/CIRCULATIONAHA.126.00456")
    _pdf(d / "downloaded (3).pdf",
         "Device therapy in advanced heart failure: a contemporary review")
    _pdf(d / "PMID42482656_fulltext.pdf", "totally unrelated body text")
    _pdf(d / "unrelated.pdf", "Some unrelated paper about deep-sea geology")
    return d


def test_import_claims_by_doi_title_and_filename(incoming, pdf_dir):
    r = pdfs.import_dir(incoming, pdf_dir, pdfs.build_index(ARTS))
    got = {it["pmid"]: it["how"] for it in r["imported"]}
    assert got == {"42031428": "正文 DOI",
                   "42999001": "正文标题",
                   "42482656": "文件名里的 PMID"}
    assert len(r["unmatched"]) == 1 and "unrelated.pdf" in r["unmatched"][0]
    assert pdfs.have(pdf_dir) == {"42031428", "42999001", "42482656"}


def test_import_dry_run_writes_nothing(incoming, pdf_dir):
    r = pdfs.import_dir(incoming, pdf_dir, pdfs.build_index(ARTS), dry_run=True)
    assert len(r["imported"]) == 3
    assert pdfs.have(pdf_dir) == set()
    assert len(list(incoming.glob("*.pdf"))) == 4        # 源文件一个没动


def test_import_leaves_sources_alone_without_move(incoming, pdf_dir):
    pdfs.import_dir(incoming, pdf_dir, pdfs.build_index(ARTS))
    assert len(list(incoming.glob("*.pdf"))) == 4


def test_import_move_removes_claimed_sources_only(incoming, pdf_dir):
    pdfs.import_dir(incoming, pdf_dir, pdfs.build_index(ARTS), move=True)
    left = [f.name for f in incoming.glob("*.pdf")]
    assert left == ["unrelated.pdf"]                     # 没认出来的不能动


def test_import_skips_the_librarys_own_pdf_dir(tmp_path):
    """pdf/ 就在收藏库目录下，别把已经归位的文件再认领一遍。"""
    pdf_dir = tmp_path / "pdf"
    pdfs.save(pdf_dir, "42482656", MINI)
    r = pdfs.import_dir(tmp_path, pdf_dir, pdfs.build_index(ARTS))
    assert r["imported"] == []


def test_import_takes_only_the_first_of_duplicate_versions(tmp_path, pdf_dir):
    src = tmp_path / "dup"
    src.mkdir()
    for name in ("a-version1.pdf", "b-version2.pdf"):
        _pdf(src / name, "Device therapy in advanced heart failure: a contemporary review")
    r = pdfs.import_dir(src, pdf_dir, pdfs.build_index(ARTS))
    assert len(r["imported"]) == 1 and len(r["unmatched"]) == 1
    assert "同属 PMID 42999001" in r["unmatched"][0]


def test_import_rejects_a_missing_directory(tmp_path, pdf_dir):
    with pytest.raises(pdfs.PdfError, match="目录不存在"):
        pdfs.import_dir(tmp_path / "nope", pdf_dir, pdfs.build_index(ARTS))


def test_short_titles_are_not_used_for_claiming():
    """短标题容易撞车，不够长就不进特征表——宁可认不出，也别认错。"""
    idx = pdfs.build_index([{"pmid": "1", "title": "Heart failure", "doi": ""}])
    assert idx["titles"] == {}


# ── OA 抓取的调度 ────────────────────────────────────────────────────────────

def test_fetch_many_skips_articles_that_already_have_a_pdf(pdf_dir, monkeypatch):
    pdfs.save(pdf_dir, "42482656", MINI)
    monkeypatch.setattr(pdfs.entrez, "pmc_ids", lambda ids, **kw: {})
    monkeypatch.setattr(pdfs, "fetch_oa", lambda p, doi="", pmcid="": (MINI, "PMC(x)"))
    r = pdfs.fetch_many([{"pmid": "42482656", "doi": ""}, {"pmid": "42031428", "doi": ""}],
                        pdf_dir, sleep=0)
    assert (r["fetched"], r["skipped"], r["failed"]) == (1, 1, 0)
    assert pdfs.have(pdf_dir) == {"42482656", "42031428"}


def test_fetch_many_reports_the_ones_it_could_not_get(pdf_dir, monkeypatch):
    monkeypatch.setattr(pdfs.entrez, "pmc_ids", lambda ids, **kw: {})
    monkeypatch.setattr(pdfs, "fetch_oa", lambda p, doi="", pmcid="": (None, ""))
    r = pdfs.fetch_many([{"pmid": "42482656", "doi": ""}], pdf_dir, sleep=0)
    assert (r["fetched"], r["failed"]) == (0, 1)
    assert r["detail"] == [{"pmid": "42482656", "ok": False, "source": ""}]
