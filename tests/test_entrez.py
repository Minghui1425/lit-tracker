"""E-utilities 客户端里那些「静默失败」的地方：elink 的重试与容错、DOI→PMID。

不联网：requests 换成假的。
"""
import json

import pytest
import requests

from conftest import BASE  # noqa: F401  （插入 sys.path）
from littrack import entrez


class _Resp:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return json.loads(self.text)


def _linkset(pmid, pmcid):
    return {"linksets": [{"ids": [pmid], "linksetdbs": [
        {"linkname": "pubmed_pmc", "links": [pmcid]}]}]}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(entrez.time, "sleep", lambda *a: None)


def test_pmc_ids_batches_small_enough_to_survive(monkeypatch):
    """180 个 id 一批时 NCBI 会掐断响应，而失败是静默的——批要小。"""
    seen = []

    def fake_get(url, params=None, timeout=None):
        seen.append(len(params["id"]))
        return _Resp(json.dumps(_linkset(params["id"][0], "123")))

    monkeypatch.setattr(entrez._SESSION, "get", fake_get)
    entrez.pmc_ids([str(i) for i in range(120)])
    assert max(seen) <= 50


def test_pmc_ids_retries_a_flaky_backend(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.ConnectionError("Read failed: EOF")
        return _Resp(json.dumps(_linkset("42482656", "7654321")))

    monkeypatch.setattr(entrez._SESSION, "get", fake_get)
    assert entrez.pmc_ids(["42482656"]) == {"42482656": "PMC7654321"}


def test_pmc_ids_gives_up_quietly_after_the_retries(monkeypatch):
    """查不到 PMCID 不该让抓取整个崩掉——只是少一条来源。"""
    monkeypatch.setattr(entrez._SESSION, "get",
                        lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("x")))
    assert entrez.pmc_ids(["42482656"]) == {}


def test_pmc_ids_survives_ncbis_raw_newlines_in_json(monkeypatch):
    """NCBI 报错时把 C++ 异常原文（含真换行）塞进 JSON 字符串，标准解析会直接炸。"""
    body = '{"ERROR": "Error: CFastMutex::Lock\nfailed", "linksets": []}'
    monkeypatch.setattr(entrez._SESSION, "get", lambda *a, **k: _Resp(body))
    assert entrez.pmc_ids(["42482656"]) == {}          # 报错识别成失败，不是崩溃


def test_pmid_by_doi_uses_the_article_identifier_field(monkeypatch):
    terms = []

    def fake_esearch(term, retmax=0):
        terms.append(term)
        return ["33301246"]

    monkeypatch.setattr(entrez, "esearch", fake_esearch)
    assert entrez.pmid_by_doi("10.1056/NEJMoa2034577.") == "33301246"
    assert terms == ['"10.1056/NEJMoa2034577"[AID]']


def test_pmid_by_doi_refuses_to_guess_when_a_doi_hits_several(monkeypatch):
    monkeypatch.setattr(entrez, "esearch", lambda *a, **k: ["1", "2"])
    assert entrez.pmid_by_doi("10.1/x") == ""


def test_pmid_by_doi_on_empty_input_does_not_search(monkeypatch):
    monkeypatch.setattr(entrez, "esearch",
                        lambda *a, **k: pytest.fail("没有 DOI 就不该发请求"))
    assert entrez.pmid_by_doi("") == ""
