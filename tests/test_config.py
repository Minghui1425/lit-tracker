"""配置校验：错配置必须报出「哪错了、能填什么」，而不是深处某个 KeyError。"""
import pytest

from littrack import config as cfgmod


def test_example_config_loads(cfg):
    assert cfg.section_names == ["药物不良反应", "心衰进展"]
    assert "Circulation" in cfg.full_inclusion_journals
    assert cfg.output_dir == "output"


def _minimal(**over):
    raw = {
        "project_name": "t",
        "keyword_filtered_journals": {"JAMA": "JAMA"},
        "sections": [{
            "name": "板块甲", "matcher": "simple_keyword", "scope": "journals",
            "subsections": [{"name": "其他", "keywords": ["sepsis"]}],
        }],
    }
    raw.update(over)
    return raw


def test_minimal_config_ok():
    c = cfgmod.load_dict(_minimal())
    assert c.section_names == ["板块甲"]


def test_unknown_matcher_is_reported():
    bad = _minimal()
    bad["sections"][0]["matcher"] = "交差"
    with pytest.raises(cfgmod.ConfigError) as e:
        cfgmod.load_dict(bad)
    assert "交差" in str(e.value)


def test_section_without_subsections_is_reported():
    bad = _minimal()
    bad["sections"][0]["subsections"] = []
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load_dict(bad)


def test_no_sections_is_reported():
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load_dict(_minimal(sections=[]))


def test_missing_file():
    with pytest.raises(cfgmod.ConfigError):
        cfgmod.load("configs/这个文件不存在.yaml")
