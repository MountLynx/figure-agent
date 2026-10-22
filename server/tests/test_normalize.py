"""规范化与确定性 hash 测试。"""

from figure_agent.svgkit import base_hash, normalize, parse_svg, serialize
from figure_agent.svgkit.semantics import semantic_path


def test_hash_stable_across_identical_renders(svg_a, svg_a2):
    assert base_hash(svg_a) == base_hash(svg_a2)


def test_hash_ignores_metadata_date(svg_a):
    import re

    doctored = re.sub(
        r"<dc:date>[^<]*</dc:date>",
        "<dc:date>1999-01-01T00:00:00</dc:date>",
        svg_a,
    )
    assert base_hash(svg_a) == base_hash(doctored)


def test_normalize_drops_noop_transform(svg_text):
    root = parse_svg(svg_text)
    normalize(root)
    text = serialize(root)
    assert "rotate(" not in text  # matplotlib 的 rotate(-0 ...) 应被清除


def test_normalize_sorts_attrs(svg_a):
    root = parse_svg(svg_a)
    normalize(root)
    for el in root.iter():
        keys = list(el.attrib)
        assert keys == sorted(keys)


def test_semantic_path_known_element(roots_a):
    el = roots_a.xpath('//*[@id="fa:treatment-bar-0"]')[0]
    assert semantic_path(el) == "figure_1/axes_1/fa:treatment-bar-0"


def test_semantic_path_with_anonymous_g():
    from figure_agent.svgkit import parse_svg

    svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
  <g id="fig">
    <g>
      <g><rect id="fa:bar" x="1" y="1" width="2" height="2"/></g>
      <g><rect id="fa:bar2" x="5" y="5" width="2" height="2"/></g>
    </g>
  </g>
</svg>"""
    root = parse_svg(svg)
    r1 = root.xpath('//*[@id="fa:bar"]')[0]
    r2 = root.xpath('//*[@id="fa:bar2"]')[0]
    assert semantic_path(r1) == "fig/g[1]/g[1]/fa:bar"
    assert semantic_path(r2) == "fig/g[1]/g[2]/fa:bar2"
