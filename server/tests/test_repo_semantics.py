"""repo 语义测试：与 Index 对齐的边界（改名只动 SQL、删除级联、过滤）。"""

import pytest

from figure_agent.repo import groups as repo_groups
from figure_agent.repo import items as repo_items
from figure_agent.repo import runs as repo_runs
from figure_agent.repo import tags as repo_tags
from figure_agent.repo import types as repo_types
from figure_agent.repo.repo import FIGURE_TYPE_NAME, Repo


@pytest.fixture()
def repo(tmp_path):
    r = Repo(tmp_path / "ws")
    r.open_or_init()
    return r


def test_generate_id_shape():
    for _ in range(100):
        assert repo_items.ID_RE.match(repo_items.generate_id())
    assert len({repo_items.generate_id() for _ in range(200)}) == 200


def test_rename_only_touches_db(repo):
    item = repo_items.create_item(repo, "甲")
    repo_items.update_item(repo, item["id"], name="乙")
    assert repo_items.get_item(repo, item["id"])["name"] == "乙"
    assert item["id"] in [i["id"] for i in repo_items.list_items(repo)]  # id 永不变


def test_delete_cascades(repo):
    item = repo_items.create_item(repo, "甲")
    g = repo_groups.create_group(repo, "G")
    repo_items.bind_group(repo, item["id"], g["id"])
    repo_runs.add_run(repo, item["id"], "create", True, 1, detail={"stderr": ""})
    repo_items.delete_item(repo, item["id"])
    assert repo_items.get_item(repo, item["id"]) is None
    assert repo_runs.list_runs(repo, item["id"]) == []
    with repo.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM item_groups").fetchone()[0] == 0
    with pytest.raises(ValueError):
        repo_items.delete_item(repo, item["id"])


def test_same_name_allowed(repo):
    a = repo_items.create_item(repo, "同名")
    b = repo_items.create_item(repo, "同名")
    assert a["id"] != b["id"]
    assert len(repo_items.list_items(repo, FIGURE_TYPE_NAME)) == 2


def test_list_filters(repo):
    fig = repo_items.create_item(repo, "图A", FIGURE_TYPE_NAME)
    repo_items.create_item(repo, "便签", "通用")
    g = repo_groups.create_group(repo, "G")
    t = repo_tags.create_tag(repo, "T")
    repo_items.bind_group(repo, fig["id"], g["id"])
    repo_items.bind_tag(repo, fig["id"], t["id"])
    assert [i["id"] for i in repo_items.list_items(repo, FIGURE_TYPE_NAME)] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, q="图A")] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, group_id=g["id"])] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, tag_id=t["id"])] == [fig["id"]]
    got = repo_items.list_items(repo, FIGURE_TYPE_NAME)[0]
    assert got["groupIds"] == [g["id"]] and got["tags"] == ["T"]


def test_require_id_rejects_traversal():
    for bad in ("../../etc", "ABCDEF123456", "a b", "", "aaaaaaaaaaaa\n"):  # $ 容忍尾 \n，fullmatch 不容忍
        with pytest.raises(ValueError):
            repo_items.require_id(bad)


def test_merge_properties_patch_wins(repo):
    item = repo_items.create_item(repo, "甲", properties={"模板": "旧", "来源": "src"})
    out = repo_items.merge_properties(repo, item["id"], {"模板": "新"})
    assert out["properties"] == {"模板": "新", "来源": "src"}  # patch 覆盖既有值，其余保留


def test_delete_type_preset_protected(repo):
    with pytest.raises(ValueError):
        repo_types.delete_type(repo, 1)  # Index 预设型「通用」
    with pytest.raises(ValueError):
        repo_types.delete_type(repo, 2)  # 「任务」


def test_delete_type_in_use_rejected(repo):
    t = repo_types.create_type(repo, "报告")
    repo_items.create_item(repo, "用它的条目", "报告")
    with pytest.raises(ValueError):
        repo_types.delete_type(repo, t["id"])
    # 未使用的类型仍可删（守卫只在使用中触发）
    idle = repo_types.create_type(repo, "闲置")
    repo_types.delete_type(repo, idle["id"])


def test_update_group_root_unset_and_cycles(repo):
    g1 = repo_groups.create_group(repo, "G1")
    g2 = repo_groups.create_group(repo, "G2", parent_id=g1["id"])
    # 环拒绝：自环
    with pytest.raises(ValueError):
        repo_groups.update_group(repo, g1["id"], parent_id=g1["id"])
    # 环拒绝：把 g1 移到自己的子级 g2 之下（2-环）
    with pytest.raises(ValueError):
        repo_groups.update_group(repo, g1["id"], parent_id=g2["id"])
    # 全不传 → 返回原状
    assert repo_groups.update_group(repo, g1["id"]) == g1
    # 显式 None → 移回根
    out = repo_groups.update_group(repo, g2["id"], parent_id=None)
    assert out["parentId"] is None


def test_list_runs_detail_does_not_override(repo):
    item = repo_items.create_item(repo, "甲")
    repo_runs.add_run(repo, item["id"], "create", True, 1,
                      detail={"kind": "脏数据", "ok": "假", "stderr": ""})
    runs = repo_runs.list_runs(repo, item["id"])
    assert runs[0]["kind"] == "create" and runs[0]["ok"] is True  # 权威列不被 detail 覆盖
    assert runs[0]["stderr"] == ""  # detail 其余键仍展平
