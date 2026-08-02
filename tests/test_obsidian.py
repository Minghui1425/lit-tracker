"""Obsidian 导出：用户手写的 label 与 Notes 必须原样活下来。

这是最容易被「刷新元数据」顺手抹掉的东西，而且抹掉了不可恢复。
"""
from conftest import article
from littrack import library, obsidian


def _export(cfg, db, root, pmids=None):
    return obsidian.export(cfg, db, root, pmids or [])


def test_export_then_refresh_keeps_user_fields(cfg, db, tmp_path):
    root = tmp_path / "vault"
    library.upsert(db, [article(section="心衰进展", subsection="其他")])
    r = _export(cfg, db, root, ["1"])
    assert r["written"] == 1

    note = next(p for p in root.rglob("*.md") if p.name != obsidian.INDEX_NAME)
    text = note.read_text(encoding="utf-8")
    note.write_text(text.replace('label: ""', 'label: "重点读"')
                        .rstrip() + "\n我自己写的一段读后感\n", encoding="utf-8")

    # 元数据变了 → 刷新；用户手写的两处不能动
    library.upsert(db, [article(title="标题被更新了", section="心衰进展",
                                subsection="其他")])
    _export(cfg, db, root)
    after = note.read_text(encoding="utf-8")
    assert 'label: "重点读"' in after
    assert "我自己写的一段读后感" in after
    assert "标题被更新了" in after


def test_empty_label_value_does_not_eat_the_separator(cfg, db, tmp_path):
    """label 的值被清空（Obsidian 属性面板清空即此效果）时，
    正则不能跨行吃掉 `---`，否则 label 会被写成 "---"。"""
    root = tmp_path / "vault"
    library.upsert(db, [article(section="心衰进展", subsection="其他")])
    _export(cfg, db, root, ["1"])
    note = next(p for p in root.rglob("*.md") if p.name != obsidian.INDEX_NAME)
    note.write_text(note.read_text(encoding="utf-8").replace('label: ""', "label:"),
                    encoding="utf-8")
    _export(cfg, db, root)
    assert 'label: "---"' not in note.read_text(encoding="utf-8")


def test_reexport_does_not_duplicate(cfg, db, tmp_path):
    root = tmp_path / "vault"
    library.upsert(db, [article(section="心衰进展", subsection="其他")])
    _export(cfg, db, root, ["1"])
    r = _export(cfg, db, root, ["1"])
    assert r["skipped"] == 1 and r["written"] == 0
    assert len([p for p in root.rglob("*.md") if p.name != obsidian.INDEX_NAME]) == 1


def test_same_title_articles_do_not_overwrite_each_other(cfg, db, tmp_path):
    root = tmp_path / "vault"
    library.upsert(db, [
        article("1", title="Same title", section="心衰进展", subsection="其他"),
        article("2", title="Same title", section="心衰进展", subsection="其他"),
    ])
    r = _export(cfg, db, root, ["1", "2"])
    notes = [p for p in root.rglob("*.md") if p.name != obsidian.INDEX_NAME]

    assert r["written"] == 2
    assert len(notes) == 2
    assert set(obsidian._scan(root)) == {"1", "2"}


def test_section_change_moves_the_note(cfg, db, tmp_path):
    root = tmp_path / "vault"
    library.upsert(db, [article(section="心衰进展", subsection="其他")])
    _export(cfg, db, root, ["1"])
    library.upsert(db, [article(section="药物不良反应", subsection="肾脏")])
    r = _export(cfg, db, root)
    assert r["moved"] == 1
    assert any("肾脏" in str(p.parent) for p in root.rglob("*.md"))


def test_project_index_links_and_cleans_up(cfg, db, tmp_path):
    root = tmp_path / "vault"
    library.upsert(db, [article(section="心衰进展", subsection="其他")])
    _export(cfg, db, root, ["1"])
    library.add_to_project(db, "课题甲", ["1"])
    obsidian.rebuild_project_notes(cfg, db, root)
    idx = next(p for p in root.rglob("*.md") if p.stem == "课题甲")
    assert "[[" in idx.read_text(encoding="utf-8")     # 已导出的文章走 wiki 链接

    library.delete_project(db, "课题甲")
    obsidian.rebuild_project_notes(cfg, db, root)
    assert not idx.exists()                            # 项目没了，索引笔记要清掉


def test_project_names_that_sanitize_the_same_do_not_overwrite(cfg, db, tmp_path):
    root = tmp_path / "vault"
    library.upsert(db, [article(section="心衰进展", subsection="其他")])
    library.add_to_project(db, "A/B", ["1"])
    library.add_to_project(db, "A:B", ["1"])

    obsidian.rebuild_project_notes(cfg, db, root)
    indexes = sorted((root / obsidian.PROJECT_DIR).glob("*.md"))

    assert len(indexes) == 2
    assert {p.read_text(encoding="utf-8").splitlines()[0] for p in indexes} == {
        "# A/B", "# A:B"
    }
