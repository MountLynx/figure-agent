"""身份匹配测试：id 命中、指纹回退、降级、lost、target 治愈。"""

from figure_agent.svgkit import identity
from figure_agent.svgkit import normalize, parse_svg

OPS = [
    {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"}, "attr": "fill", "value": "#dd3322"},
    {"id": "op-2", "kind": "set_style", "target": {"id": "patch_3"}, "attr": "fill", "value": "#123456"},
    {"id": "op-3", "kind": "set_text", "target": {"id": "text_1"}, "value": "new"},
]


def test_fa_id_survives_data_change(roots_a, roots_b):
    res = identity.match(roots_a, roots_b, OPS)
    assert res["op-1"].status == "matched"
    assert res["op-1"].target["id"] == "fa:treatment-bar-2"
    assert res["op-1"].degraded is False


def test_fingerprint_recovers_after_data_change(roots_a, roots_b):
    """数据变化 → 形状变了 → 指纹必然变。这里验证未带 fa: gid 的目标
    （patch_3，第一根蓝柱）在新图里仍然按 祖先链+序号 降级找回。"""
    res = identity.match(roots_a, roots_b, OPS)
    assert res["op-2"].status == "matched"
    # 治愈：target 指向新图的元素
    assert res["op-2"].target["id"]


def test_text_target_match(roots_a, roots_b):
    res = identity.match(roots_a, roots_b, OPS)
    # text_1 是 x 轴刻度标签 "-0.5"（数据没变，文本不变）
    assert res["op-3"].status == "matched"


def test_lost_when_gone():
    old = parse_svg('<svg xmlns="http://www.w3.org/2000/svg"><g id="axes_1"><g id="patch_1"><path d="M 0 0 L 1 1"/></g></g></svg>')
    new = parse_svg('<svg xmlns="http://www.w3.org/2000/svg"><g id="axes_1"></g></svg>')
    normalize(old)
    normalize(new)
    ops = [{"id": "op-x", "kind": "set_style", "target": {"id": "patch_1"}, "attr": "fill", "value": "#000"}]
    res = identity.match(old, new, ops)
    assert res["op-x"].status == "lost"


def test_locate_prefers_id_then_path_then_fingerprint(roots_a):
    el = identity.locate(roots_a, {"id": "fa:control-bar-1"})
    assert el is not None and el.get("id") == "fa:control-bar-1"

    el = identity.locate(roots_a, {"semanticPath": "figure_1/axes_1/fa:control-bar-1"})
    assert el is not None and el.get("id") == "fa:control-bar-1"

    fp = identity.fingerprint(el)
    el2 = identity.locate(roots_a, {"fingerprint": fp})
    assert el2 is not None


def test_duplicate_bar_index_shift_still_matches(roots_a, roots_b):
    """删数据导致 matplotlib 自动编号平移：无 gid 目标靠降级匹配。"""
    ops = [{"id": "op-1", "kind": "set_style", "target": {"id": "patch_6"}, "attr": "fill", "value": "#123456"}]
    res = identity.match(roots_a, roots_b, OPS + ops)
    assert res["op-1"].status == "matched"
