"""patch 应用与收敛判定测试。"""

from figure_agent.svgkit import identity, normalize, parse_svg
from figure_agent.svgkit.patchops import apply_patch, prune_resolved, verify_patch


def _style_of(root, el_id, attr):
    from figure_agent.svgkit.style import get_style_prop

    el = root.xpath(f'//*[@id="{el_id}"]')[0]
    return get_style_prop(el, attr)


def test_apply_set_style_on_group_with_children(roots_a):
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#dd3322", "status": "active"},
    ]}
    text, per_op = apply_patch(roots_a, patch)
    assert per_op["op-1"] == "applied"
    final = parse_svg(text)
    # matplotlib 把 fill 写在子 path 的 style 里 → 应命中声明处
    path = final.xpath('//*[@id="fa:treatment-bar-2"]//*[local-name()="path"]')[0]
    assert "#dd3322" in path.get("style")


def test_apply_set_text(roots_a):
    # text_1 是 x 轴第一个刻度标签组（<g id="text_1"><text>-0.5</text></g>）
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_text", "target": {"id": "text_1"}, "value": "起点", "status": "active"},
    ]}
    text, per_op = apply_patch(roots_a, patch)
    assert per_op["op-1"] == "applied"
    final = parse_svg(text)
    t = final.xpath('//*[@id="text_1"]//*[local-name()="text"]')[0]
    assert t.text == "起点"


def test_apply_translate_prepend(roots_a):
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "transform", "target": {"id": "fa:control-bar-0"},
         "value": {"translate": [5, -2]}, "status": "active"},
    ]}
    text, per_op = apply_patch(roots_a, patch)
    assert per_op["op-1"] == "applied"
    el = parse_svg(text).xpath('//*[@id="fa:control-bar-0"]')[0]
    assert el.get("transform", "").startswith("translate(5 -2)")


def test_verify_style_convergence(svg_a, svg_b):
    old = parse_svg(svg_a); normalize(old)
    new = parse_svg(svg_b); normalize(new)  # b 里 treatment 已是 #dd3322
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#DD3322", "status": "active"},
        {"id": "op-2", "kind": "set_style", "target": {"id": "fa:control-bar-0"},
         "attr": "fill", "value": "#ff0000", "status": "active"},
    ]}
    res = verify_patch(new, patch)
    assert res["op-1"]["status"] == "resolved"
    assert res["op-2"]["status"] == "active"
    pruned = prune_resolved(patch, res)
    assert [op["id"] for op in pruned["ops"]] == ["op-2"]


def test_verify_text_convergence(roots_a):
    # text_1 是 x 轴第一个刻度标签组，内容为 "A"
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_text", "target": {"id": "text_1"}, "value": "A", "status": "active"},
        {"id": "op-2", "kind": "set_text", "target": {"id": "text_1"}, "value": "other", "status": "active"},
    ]}
    res = verify_patch(roots_a, patch)
    assert res["op-1"]["status"] == "resolved"
    assert res["op-2"]["status"] == "active"


def test_verify_translate_group(roots_a):
    from figure_agent.svgkit import geom

    el = roots_a.xpath('//*[@id="fa:control-bar-0"]')[0]
    bb = geom.estimate_bbox(el)
    pre = {"center": [round(bb.cx, 3), round(bb.cy, 3)], "size": [round(bb.w, 3), round(bb.h, 3)]}
    # 同目标的 translate op 按合成位移分组判定：3+2 = 5
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "transform", "target": {"id": "fa:control-bar-0"},
         "value": {"translate": [3, 0]}, "pre": pre, "status": "active"},
        {"id": "op-2", "kind": "transform", "target": {"id": "fa:control-bar-0"},
         "value": {"translate": [2, 0]}, "pre": pre, "status": "active"},
        {"id": "op-3", "kind": "transform", "target": {"id": "fa:treatment-bar-0"},
         "value": {"translate": [1, 0]}, "status": "active"},
    ]}
    # 新图没有动 → 不收敛
    res = verify_patch(roots_a, patch)
    assert res["op-1"]["status"] == "active"
    assert res["op-3"]["status"] == "active"  # 缺 pre → active 而非误判

    # 造一个"代码已表达合成位移"的新图
    import copy

    moved = copy.deepcopy(roots_a)
    target = moved.xpath('//*[@id="fa:control-bar-0"]')[0]
    target.set("transform", "translate(5 0)")
    res2 = verify_patch(moved, patch)
    assert res2["op-1"]["status"] == "resolved"
    assert res2["op-2"]["status"] == "resolved"


def test_apply_missing_target_lost(roots_a):
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:nope"},
         "attr": "fill", "value": "#000", "status": "active"},
    ]}
    _, per_op = apply_patch(roots_a, patch)
    assert per_op["op-1"] == "lost"


def test_apply_set_visible_and_reorder(roots_a):
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_visible", "target": {"id": "fa:control-bar-0"},
         "value": False, "status": "active"},
        {"id": "op-2", "kind": "reorder", "target": {"id": "fa:treatment-bar-0"},
         "value": {"to": "front"}, "status": "active"},
    ]}
    text, per_op = apply_patch(roots_a, patch)
    assert per_op["op-1"] == "applied"
    assert per_op["op-2"] == "applied"
    final = parse_svg(text)
    assert _style_of(final, "fa:control-bar-0", "display") == "none"
    # treatment-bar-0 应移到父容器元素子节点的末位
    el = final.xpath('//*[@id="fa:treatment-bar-0"]')[0]
    siblings = [c for c in el.getparent() if isinstance(c.tag, str)]
    assert siblings[-1] is el

    # value=True（显示）应移除 display 声明
    root2 = parse_svg(text)  # 已带 display: none
    hide = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_visible", "target": {"id": "fa:control-bar-0"},
         "value": False, "status": "active"},
    ]}
    show = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_visible", "target": {"id": "fa:control-bar-0"},
         "value": True, "status": "active"},
    ]}
    apply_patch(root2, hide)
    assert _style_of(root2, "fa:control-bar-0", "display") == "none"
    _, per_show = apply_patch(root2, show)
    assert per_show["op-1"] == "applied"
    assert _style_of(root2, "fa:control-bar-0", "display") is None


def test_verify_set_visible(roots_a):
    import copy

    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_visible", "target": {"id": "fa:control-bar-0"},
         "value": False, "status": "active"},
    ]}
    # 目标还在且未隐藏 → active
    res = verify_patch(roots_a, patch)
    assert res["op-1"]["status"] == "active"
    assert "未隐藏" in res["op-1"]["detail"]

    # 目标从新 base 消失（代码 set_visible(False) 不渲染）→ resolved
    gone = copy.deepcopy(roots_a)
    el = gone.xpath('//*[@id="fa:control-bar-0"]')[0]
    el.getparent().remove(el)
    res2 = verify_patch(gone, patch)
    assert res2["op-1"]["status"] == "resolved"

    # 用样式方式隐藏也能收敛
    styled = copy.deepcopy(roots_a)
    el2 = styled.xpath('//*[@id="fa:control-bar-0"]')[0]
    el2.set("style", "display: none")
    res3 = verify_patch(styled, patch)
    assert res3["op-1"]["status"] == "resolved"


def test_verify_reorder(roots_a):
    import copy

    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "reorder", "target": {"id": "fa:treatment-bar-0"},
         "value": {"to": "front"}, "status": "active"},
    ]}
    # 没动 → active（带位置详情）
    res = verify_patch(roots_a, patch)
    assert res["op-1"]["status"] == "active"
    assert "兄弟位" in res["op-1"]["detail"]

    # 代码把 zorder 提到最高 → 文档顺序末位 → resolved
    moved = copy.deepcopy(roots_a)
    el = moved.xpath('//*[@id="fa:treatment-bar-0"]')[0]
    parent = el.getparent()
    parent.remove(el)
    parent.append(el)
    res2 = verify_patch(moved, patch)
    assert res2["op-1"]["status"] == "resolved"
