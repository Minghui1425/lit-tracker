import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from littrack import config as cfgmod  # noqa: E402

EXAMPLE = BASE / "configs" / "example-minimal.yaml"


@pytest.fixture(scope="session")
def cfg():
    """仓库自带的示例配置：改了它而没跑测试的话，这里会先炸。"""
    return cfgmod.load(EXAMPLE)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "library.db"


def article(pmid="1", **kw):
    """一篇 efetch 之后、入库之前形态的文章。"""
    a = {"pmid": pmid, "title": "A title", "title_zh": "", "journal": "Circulation",
         "journal_abbr": "Circulation", "pub_date": "2026-01-02", "section": "",
         "subsection": "", "abstract": "", "keywords": [], "affiliation": "",
         "authors": ["Doe J"], "doi": "10.1/x", "if_value": "", "quartile": "",
         "type_label": "Journal Article"}
    a.update(kw)
    return a
