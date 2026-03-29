"""Nia Drawing Language — SVG Renderer.

Converts a SceneGraph into SVG markup.
The renderer is a replaceable module — Nia never touches it directly.
"""
from __future__ import annotations

from html import escape as _html_escape

from backend.core.drawing.scene_graph import SceneGraph, SceneNode
from backend.core.drawing.schema import ElementType


def _esc(value: str) -> str:
    """Escape a string for safe use inside SVG/XML attribute values."""
    return _html_escape(value, quote=True)


def render_svg(scene: SceneGraph) -> str:
    """Render a SceneGraph to SVG string."""
    w = scene.canvas.width
    h = scene.canvas.height

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'style="background:#FAFAF7">',
    ]

    # Add filter definitions for softness/blur
    parts.append("<defs>")
    blur_ids: set[float] = set()
    for node in scene.nodes:
        if node.softness > 0:
            blur_ids.add(node.softness)
    for blur in sorted(blur_ids):
        fid = f"blur_{blur:.0f}"
        parts.append(
            f'  <filter id="{fid}"><feGaussianBlur stdDeviation="{blur}"/></filter>'
        )
    parts.append("</defs>")

    # Render nodes (back to front by layer, then by generated status)
    sorted_nodes = sorted(scene.nodes, key=lambda n: (n.layer, n.is_generated, n.name))
    for node in sorted_nodes:
        parts.append(_render_node(node))

    parts.append("</svg>")
    return "\n".join(parts)


def _render_node(node: SceneNode) -> str:
    """Render a single SceneNode to SVG element."""
    style = _build_style(node)
    filter_attr = f' filter="url(#blur_{node.softness:.0f})"' if node.softness > 0 else ""

    # Data attributes for tracing (escaped to prevent attribute injection)
    data = f' data-name="{_esc(node.name)}"'
    if node.because_tags:
        data += f' data-because="{_esc(",".join(node.because_tags))}"'

    if node.element_type == ElementType.DOT:
        r = max(node.width / 2, 2)
        return f'  <circle cx="{node.x:.1f}" cy="{node.y:.1f}" r="{r:.1f}" {style}{filter_attr}{data}/>'

    elif node.element_type == ElementType.CIRCLE:
        r = node.width / 2
        return f'  <circle cx="{node.x:.1f}" cy="{node.y:.1f}" r="{r:.1f}" {style}{filter_attr}{data}/>'

    elif node.element_type == ElementType.RECT:
        x = node.x - node.width / 2
        y = node.y - node.height / 2
        return (
            f'  <rect x="{x:.1f}" y="{y:.1f}" '
            f'width="{node.width:.1f}" height="{node.height:.1f}" '
            f'{style}{filter_attr}{data}/>'
        )

    elif node.element_type == ElementType.LINE:
        half_w = node.width / 2
        return (
            f'  <line x1="{node.x - half_w:.1f}" y1="{node.y:.1f}" '
            f'x2="{node.x + half_w:.1f}" y2="{node.y:.1f}" '
            f'stroke="{node.color}" stroke-width="{node.stroke_width:.1f}" '
            f'opacity="{node.opacity:.2f}"{filter_attr}{data}/>'
        )

    elif node.element_type == ElementType.AREA:
        # Area: soft ellipse (no hard boundary)
        rx = node.width / 2
        ry = node.height / 2
        return (
            f'  <ellipse cx="{node.x:.1f}" cy="{node.y:.1f}" '
            f'rx="{rx:.1f}" ry="{ry:.1f}" '
            f'{style}{filter_attr}{data}/>'
        )

    return ""


def _build_style(node: SceneNode) -> str:
    """Build SVG style attributes for a node."""
    if node.element_type == ElementType.LINE:
        return ""  # lines use stroke attributes directly

    if node.element_type == ElementType.AREA:
        # Areas have no stroke, only fill
        return f'fill="{node.color}" fill-opacity="{node.opacity:.2f}" stroke="none"'

    if node.element_type == ElementType.DOT:
        return f'fill="{node.color}" fill-opacity="{node.opacity:.2f}" stroke="none"'

    # Default: fill + thin stroke
    return (
        f'fill="{node.color}" fill-opacity="{node.opacity:.2f}" '
        f'stroke="{node.color}" stroke-opacity="{min(node.opacity + 0.1, 1.0):.2f}" '
        f'stroke-width="{node.stroke_width:.1f}"'
    )
