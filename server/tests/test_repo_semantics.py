"""repo 语义测试：与 Index 对齐的边界（改名只动 SQL、删除级联、过滤）。"""

import pytest

from figure_agent.repo import items as repo_items
from figure_agent.repo.repo import FIGURE_TYPE_NAME, Repo

# 注意：groups / runs 模块属 Task 5，此处延迟导入——
# 模块级导入会让整个文件在收集期 ImportError，连本应先过的
# 4 个 items 测试一起挂掉（与 repo_tags_create 同一模式）。


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
    from figure_agent.repo import groups as repo_groups
    from figure_agent.repo import runs as repo_runs

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
    from figure_agent.repo import groups as repo_groups

    fig = repo_items.create_item(repo, "图A", FIGURE_TYPE_NAME)
    repo_items.create_item(repo, "便签", "通用")
    g = repo_groups.create_group(repo, "G")
    t = repo_tags_create(repo)
    repo_items.bind_group(repo, fig["id"], g["id"])
    repo_items.bind_tag(repo, fig["id"], t["id"])
    assert [i["id"] for i in repo_items.list_items(repo, FIGURE_TYPE_NAME)] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, q="图A")] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, group_id=g["id"])] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, tag_id=t["id"])] == [fig["id"]]
    got = repo_items.list_items(repo, FIGURE_TYPE_NAME)[0]
    assert got["groupIds"] == [g["id"]] and got["tags"] == ["T"]


def repo_tags_create(repo):
    from figure_agent.repo import tags as repo_tags

    return repo_tags.create_tag(repo, "T")


def test_require_id_rejects_traversal():
    for bad in ("../../etc", "ABCDEF123456", "a b", ""):
        with pytest.raises(ValueError):
            repo_items.require_id(bad)
