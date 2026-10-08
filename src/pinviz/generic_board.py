"""Procedural controller-board artwork from pinout JSON.

Generates a simple PCB rectangle with labeled pads on left/right/top/bottom
edges — good enough to follow wiring without hand-drawn silkscreen art.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from .model import Point

SIDES = ("left", "right", "top", "bottom")

# Default geometry (SVG units / px)
DEFAULT_PIN_SPACING = 14.0
DEFAULT_MARGIN = 18.0
DEFAULT_PAD_R = 4.2
DEFAULT_LABEL_GAP = 8.0


def _side_pins(pins: list, side: str) -> list:
    return [p for p in pins if getattr(p, "header", None) == side]


def compute_sides_geometry(
    pins: list,
    *,
    pin_spacing: float = DEFAULT_PIN_SPACING,
    margin: float = DEFAULT_MARGIN,
    width: float | None = None,
    height: float | None = None,
) -> tuple[float, float, dict[int, Point]]:
    """Compute board size and pin positions for a multi-side header layout.

    Pins must set ``header`` to left/right/top/bottom. Order along a side is
    the order of pins in the config list (top→bottom for left/right,
    left→right for top/bottom).
    """
    by_side = {side: _side_pins(pins, side) for side in SIDES}
    unknown = [
        p.physical_pin
        for p in pins
        if getattr(p, "header", None) not in SIDES
    ]
    if unknown:
        raise ValueError(
            f"Sides layout requires every pin to set header to one of "
            f"{', '.join(SIDES)}; missing/invalid for pins: {unknown}"
        )

    left_n = max(len(by_side["left"]), 1)
    right_n = max(len(by_side["right"]), 1)
    top_n = max(len(by_side["top"]), 1)
    bottom_n = max(len(by_side["bottom"]), 1)

    content_h = max(left_n, right_n) * pin_spacing
    content_w = max(top_n, bottom_n) * pin_spacing
    # Extra horizontal room for left/right pin labels inside the PCB.
    label_band = 52.0
    auto_w = max(content_w, 120.0) + 2 * margin + 2 * label_band
    auto_h = max(content_h, 80.0) + 2 * margin + 24.0
    board_w = float(width) if width and width > 0 else auto_w
    board_h = float(height) if height and height > 0 else auto_h

    positions: dict[int, Point] = {}

    def place_vertical(side_pins: list, x: float) -> None:
        if not side_pins:
            return
        total = (len(side_pins) - 1) * pin_spacing
        start_y = (board_h - total) / 2.0
        for index, pin in enumerate(side_pins):
            positions[pin.physical_pin] = Point(x, start_y + index * pin_spacing)

    def place_horizontal(side_pins: list, y: float) -> None:
        if not side_pins:
            return
        total = (len(side_pins) - 1) * pin_spacing
        start_x = (board_w - total) / 2.0
        for index, pin in enumerate(side_pins):
            positions[pin.physical_pin] = Point(start_x + index * pin_spacing, y)

    place_vertical(by_side["left"], margin)
    place_vertical(by_side["right"], board_w - margin)
    place_horizontal(by_side["top"], margin)
    place_horizontal(by_side["bottom"], board_h - margin)

    return board_w, board_h, positions


def generate_board_svg(
    *,
    name: str,
    width: float,
    height: float,
    pins: list,
    positions: dict[int, Point],
    pcb_color: str = "#1B4F72",
    border_color: str = "#0E2F44",
) -> str:
    """Return a self-contained SVG string for a generic controller board."""
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}" height="{height:.2f}" '
        f'viewBox="0 0 {width:.2f} {height:.2f}">',
        f'<rect x="0" y="0" width="{width:.2f}" height="{height:.2f}" rx="10" ry="10" '
        f'fill="{pcb_color}" stroke="{border_color}" stroke-width="2"/>',
        # USB-ish notch hint (top center) — decorative only
        f'<rect x="{width / 2 - 18:.2f}" y="0" width="36" height="8" rx="2" fill="#CFCFCF" '
        f'stroke="#666" stroke-width="0.8"/>',
        f'<text x="{width / 2:.2f}" y="{height / 2:.2f}" text-anchor="middle" '
        f'font-family="Arial, sans-serif" font-size="13" font-weight="bold" fill="#FFFFFF">'
        f"{escape(name)}</text>",
        '<text x="'
        + f'{width / 2:.2f}" y="{height / 2 + 16:.2f}" text-anchor="middle" '
        'font-family="Arial, sans-serif" font-size="9" fill="#D6EAF8">generic pinout</text>',
    ]

    for pin in pins:
        pos = positions.get(pin.physical_pin)
        if pos is None:
            continue
        side = getattr(pin, "header", "right") or "right"
        parts.append(
            f'<circle cx="{pos.x:.2f}" cy="{pos.y:.2f}" r="{DEFAULT_PAD_R}" '
            f'fill="#F4D03F" stroke="#7D6608" stroke-width="0.8"/>'
        )
        label = escape(str(pin.name))
        if side == "left":
            tx, anchor = pos.x + DEFAULT_LABEL_GAP, "start"
        elif side == "right":
            tx, anchor = pos.x - DEFAULT_LABEL_GAP, "end"
        elif side == "top":
            tx, anchor = pos.x, "middle"
            parts.append(
                f'<text x="{tx:.2f}" y="{pos.y + DEFAULT_LABEL_GAP + 8:.2f}" '
                f'text-anchor="{anchor}" font-family="Arial, sans-serif" '
                f'font-size="8" fill="#FFFFFF">{label}</text>'
            )
            continue
        else:  # bottom
            tx, anchor = pos.x, "middle"
            parts.append(
                f'<text x="{tx:.2f}" y="{pos.y - DEFAULT_LABEL_GAP:.2f}" '
                f'text-anchor="{anchor}" font-family="Arial, sans-serif" '
                f'font-size="8" fill="#FFFFFF">{label}</text>'
            )
            continue

        parts.append(
            f'<text x="{tx:.2f}" y="{pos.y + 3:.2f}" text-anchor="{anchor}" '
            f'font-family="Arial, sans-serif" font-size="8" fill="#FFFFFF">{label}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def ensure_generated_svg(
    config_name: str,
    *,
    name: str,
    width: float,
    height: float,
    pins: list,
    positions: dict[int, Point],
    assets_dir: Path | None = None,
) -> Path:
    """Write (or refresh) ``assets/generated/{config_name}.svg`` and return its path."""
    module_dir = Path(__file__).parent
    out_dir = assets_dir or (module_dir / "assets" / "generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{config_name}.svg"
    svg = generate_board_svg(
        name=name,
        width=width,
        height=height,
        pins=pins,
        positions=positions,
    )
    out_path.write_text(svg, encoding="utf-8")
    return out_path


def layout_is_sides(layout_dict: dict) -> bool:
    """True when layout uses explicit per-side headers (or mode=sides)."""
    if layout_dict.get("mode") == "sides":
        return True
    return any(layout_dict.get(f"{side}_header") for side in SIDES)


def calculate_sides_positions(layout_dict: dict, pins: list) -> tuple[float, float, dict[int, Point]]:
    """Positions from either auto sides geometry or explicit per-side header blocks."""
    if layout_dict.get("mode") == "sides" or not any(
        layout_dict.get(f"{side}_header") for side in SIDES
    ):
        return compute_sides_geometry(
            pins,
            pin_spacing=float(layout_dict.get("pin_spacing") or DEFAULT_PIN_SPACING),
            margin=float(layout_dict.get("margin") or DEFAULT_MARGIN),
            width=layout_dict.get("width"),
            height=layout_dict.get("height"),
        )

    # Explicit left_header / right_header / top_header / bottom_header blocks:
    # { start, spacing, x|y }
    positions: dict[int, Point] = {}
    width = float(layout_dict.get("width") or 200)
    height = float(layout_dict.get("height") or 200)

    for pin in pins:
        side = getattr(pin, "header", None)
        if side not in SIDES:
            raise ValueError(f"Pin {pin.physical_pin} missing valid header side")
        header = layout_dict.get(f"{side}_header") or {}
        spacing = float(header.get("spacing") or header.get("pin_spacing") or DEFAULT_PIN_SPACING)
        # Index among pins on this side (config order)
        side_list = _side_pins(pins, side)
        index = next(i for i, p in enumerate(side_list) if p.physical_pin == pin.physical_pin)
        if side in ("left", "right"):
            x = float(header.get("x") if header.get("x") is not None else (DEFAULT_MARGIN if side == "left" else width - DEFAULT_MARGIN))
            y0 = float(header.get("start") or header.get("start_y") or DEFAULT_MARGIN)
            positions[pin.physical_pin] = Point(x, y0 + index * spacing)
        else:
            y = float(header.get("y") if header.get("y") is not None else (DEFAULT_MARGIN if side == "top" else height - DEFAULT_MARGIN))
            x0 = float(header.get("start") or header.get("start_x") or DEFAULT_MARGIN)
            positions[pin.physical_pin] = Point(x0 + index * spacing, y)

    return width, height, positions
