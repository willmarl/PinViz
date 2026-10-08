"""Pictorial solderless-breadboard layout.

``layout: breadboard`` draws the real board artwork beside a vertical
breadboard with plug-in modules seated on its holes, and colored jumpers
between the actual pins. Schematic layout is unchanged.

Layout rules, chosen so that different modules' wires never cross:

- The breadboard stands upright. Rails run top to bottom: logic ground and
  3.3V on the left, motor ground and motor supply on the right.
- A 16-pin stepstick straddles the trench, one 8-pin column on row ``b``
  and one on row ``f`` (0.6 inch apart), seated as the silkscreen reads
  from above: EN top left, DIR bottom left, VM top right, GND bottom
  right. Modules stack top to bottom in YAML order, so they should be
  listed in the order their signals leave the header.
- Left-column header pins never cross the board face: they leave left,
  climb above the board, then run into the fan corridor. Right-column pins
  leave directly toward the breadboard.
- Each module's header wires travel as one ribbon, sorted by header
  height, from beside the header to row ``a`` beside the module. A wire
  whose pin sits above the pins of wires that leave the header before it
  (EN, the top pin, with STEP and DIR at the bottom) cannot reach its row
  without crossing them, so it lands below the ribbon and climbs the left
  edge of the breadboard to its row: one deliberate hop per module instead
  of a tangle.
- Rail power reaches a module as a short stub (MS1, MS2, VM, both GNDs)
  or a lane under the module (VDD), never across another module's ribbon.
- A motor sits beside its own module; coil leads are straight.
- Logic GND and motor MGND are tied at the bottom of the board whenever
  MGND is used; PinViz rejects a Rails-to-Rails connection as a cycle.
- Any device with no connection fails the render.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import drawsvg as draw

from .layout import LayoutConfig
from .model import DEFAULT_COLORS, Board, Connection, Device, Diagram, PinRole
from .render_constants import RENDER_CONSTANTS
from .render_svg import SVGRenderer
from .theme import get_color_scheme
from .wire_renderer import get_halo_color

# BIGTREETECH TMC2209 V1.3 silkscreen, seated with DIR at the top of the board.
# BIGTREETECH TMC2209 V1.2/V1.3 silkscreen viewed from above, both columns top
# to bottom: EN top left, DIR bottom left, VM top right, GND bottom right.
STEPSTICK_LEFT = ("EN", "MS1", "MS2", "PDN", "PDN_ALT", "CLK", "STEP", "DIR")
STEPSTICK_RIGHT = ("VM", "VMGND", "A2", "A1", "B1", "B2", "VDD", "IOGND")
STEPSTICK_PINS = STEPSTICK_LEFT + STEPSTICK_RIGHT
# Card text for pins whose names had to be made unique. The board silkscreen
# prints 2B/2A/1A/1B/VIO where the card (and these names) say A2/A1/B1/B2/VDD.
STEPSTICK_LABELS = {"PDN_ALT": "PDN", "VMGND": "GND", "IOGND": "GND"}

# Device types this layout can draw; each takes this role unless ``breadboard.role`` overrides it.
STEPSTICK_TYPES = {"tmc2209"}
# Compact single-column breakouts seated on the left of the trench (pot, servo, LED, …).
BREAKOUT_TYPES = {"potentiometer", "pot", "sg90", "led", "button"}
DEFAULT_ROLES = {
    "tmc2209": "module",
    "potentiometer": "module",
    "pot": "module",
    "sg90": "module",
    "led": "module",
    "button": "module",
    "nema17": "motor",
    "psu_24v": "supply",
    "electrolytic": "capacitor",
    "breadboard_rail": "rail",
}
MODULE_TYPES = STEPSTICK_TYPES | BREAKOUT_TYPES
BREAKOUT_FILL = {
    "potentiometer": "#6B7280",
    "pot": "#6B7280",
    "sg90": "#EA580C",
    "led": "#DC2626",
    "button": "#4B5563",
}
BREAKOUT_GAP = 3  # empty rows between stacked breakouts

RAIL_PINS = ("GND", "+3V3", "MGND", "+24V")
# +5V is the same physical left power strip as +3V3 (Arduino vs Pi logic voltage).
RAIL_COLUMN_ALIASES = {"+5V": "+3V3"}
# Rail colors follow the pin-role wire colors used everywhere else.
RAIL_ROLES = {
    "GND": PinRole.GROUND,
    "+3V3": PinRole.POWER_3V3,
    "+5V": PinRole.POWER_5V,
    "MGND": PinRole.GROUND,
    "+24V": PinRole.POWER_EXT,
}


def _rail_column(rail: str) -> str:
    """Map rail pin names onto Geometry column keys."""
    return RAIL_COLUMN_ALIASES.get(rail, rail)

MARGIN = LayoutConfig.canvas_padding
# Extra left/top gutter so left-column wires can run around the board
# (never across the silkscreen) without clipping the canvas.
LEFT_WIRE_GUTTER = 80.0
TOP_WIRE_GUTTER = 72.0
PI_ORIGIN = (
    LayoutConfig.board_margin_left + LEFT_WIRE_GUTTER,
    60.0 + TOP_WIRE_GUTTER,
)
PI_SCALE = 1.4
PITCH = 22.0
MODULE_ROWS = 12
MODULE_SPAN = 8
MIN_MODULE_ROW = 3
FIRST_MODULE_ROW = 4
BREADBOARD_TOP = PI_ORIGIN[1]
BOARD_TO_BREADBOARD = 250.0  # header right edge to breadboard left edge
FAN_OFFSET = 60.0  # header right edge to where header wires start fanning out
RIBBON_END_GAP = 48.0  # ribbon end to the left rail
HOP_GAP = 31.0  # left rail to the column a hopping wire climbs
MOTOR_OFFSET = 58.0  # right rail to the motor leads
MOTOR_BODY_WIDTH = 150.0  # motor leads to the far edge of the motor body
SUPPLY_TOP = 62.0  # last hole row to the supply box
SUPPLY_WIDTH = 230.0
SUPPLY_HEIGHT = 54.0
SUPPLY_LEFT_OF_MGND = 104.0
CAPACITOR_LABEL_WIDTH = 120.0  # right of the breadboard, room for the capacitor label
RIBBON_SPACING = 9.0
LEFT_ESCAPE_CLEAR = 32.0  # left of the left pin column before climbing
TOP_BYPASS_CLEAR = 40.0  # above the board top for the cross-over lane
TOP_BYPASS_LANE = 14.0  # vertical spacing between stacked around-board lanes
FONT = "Arial, sans-serif"
# Same sizes as the schematic: device names and headings 12, labels and table text 9.
NAME_FONT_SIZE = float(RENDER_CONSTANTS.LEGEND_TITLE_FONT_SIZE.removesuffix("px"))
LABEL_FONT_SIZE = 9.0
LABEL_CHAR_WIDTH = 5.2  # average advance of the 9 px label font
LABEL_PADDING = 4.0
LABEL_HEIGHT = 12.0


@dataclass
class Geometry:
    """Hole coordinates of an upright breadboard."""

    left: float
    top: float
    rows: int
    pitch: float = PITCH
    x: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        p = self.pitch
        self.x["GND"] = self.left + 18
        self.x["+3V3"] = self.x["GND"] + p
        start = self.x["+3V3"] + 1.7 * p
        for index, name in enumerate("abcde"):
            self.x[name] = start + index * p
        start = self.x["e"] + 3 * p
        for index, name in enumerate("fghij"):
            self.x[name] = start + index * p
        self.x["MGND"] = self.x["j"] + 1.7 * p
        self.x["+24V"] = self.x["MGND"] + p

    def y(self, row: float) -> float:
        return self.top + 16 + row * self.pitch

    @property
    def right(self) -> float:
        return self.x["+24V"] + 18

    @property
    def bottom(self) -> float:
        return self.y(self.rows - 1) + 16


def stepstick_seat(device: Device, pin_name: str) -> tuple[str, int]:
    """Return ``(column, row offset)`` of a stepstick pin from the module's first row."""
    if pin_name in STEPSTICK_LEFT:
        return "b", STEPSTICK_LEFT.index(pin_name)
    if pin_name in STEPSTICK_RIGHT:
        return "f", STEPSTICK_RIGHT.index(pin_name)
    raise ValueError(f"{device.name} has no stepstick pin {pin_name}")


def _is_stepstick(device: Device) -> bool:
    return (device.type_id or "") in STEPSTICK_TYPES


def _module_height(device: Device) -> int:
    """How many breadboard rows a seated module occupies."""
    if _is_stepstick(device):
        return MODULE_SPAN
    return max(len(device.pins), 2)


def module_seat(device: Device, pin_name: str) -> tuple[str, int]:
    """Return ``(column, row offset)`` of a module pin from the module's first row."""
    if _is_stepstick(device):
        return stepstick_seat(device, pin_name)
    names = [pin.name for pin in device.pins]
    if pin_name not in names:
        raise ValueError(f"{device.name} has no pin {pin_name}")
    return "b", names.index(pin_name)


def _role(device: Device) -> str:
    if device.placement and device.placement.role:
        return device.placement.role
    role = DEFAULT_ROLES.get(device.type_id or "")
    if role is None:
        raise ValueError(
            f"Breadboard layout cannot draw {device.name} ({device.type_id or 'custom device'}). "
            f"Supported types: {', '.join(sorted(DEFAULT_ROLES))}"
        )
    return role


def check_board(board: Board) -> None:
    """Fail unless the board has dual vertical pin columns and an SVG asset to embed.

    Classic Pi 4/5 (40-pin) still works. Generic generated boards (Arduino, ESP32-C2,
    …) are accepted when they expose at least two distinct pin X columns and a
    renderable ``svg_asset_path`` (hand-drawn or procedurally generated).
    """
    positioned = [pin for pin in board.pins if pin.position]
    xs = sorted({round(pin.position.x, 2) for pin in positioned})
    has_columns = len(positioned) >= 4 and len(xs) >= 2
    has_asset = bool(board.svg_asset_path) and Path(board.svg_asset_path).exists()
    if not has_columns or not has_asset:
        raise ValueError(
            f"Breadboard layout needs a dual-column board SVG for {board.name} "
            f"(pins={len(positioned)}, x-columns={len(xs)}, asset={board.svg_asset_path!r})"
        )


def _rounded(points: list[tuple[float, float]], radius: float = 7.0) -> str:
    """Polyline path with rounded corners."""
    if len(points) < 2:
        raise ValueError("A wire needs two points")
    path = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for index in range(1, len(points) - 1):
        (x0, y0), (x1, y1), (x2, y2) = points[index - 1], points[index], points[index + 1]
        in_len = max(abs(x1 - x0), abs(y1 - y0))
        out_len = max(abs(x2 - x1), abs(y2 - y1))
        r = min(radius, in_len / 2, out_len / 2)
        ax = x1 - (r if x1 > x0 else -r if x1 < x0 else 0)
        ay = y1 - (r if y1 > y0 else -r if y1 < y0 else 0)
        bx = x1 + (r if x2 > x1 else -r if x2 < x1 else 0)
        by = y1 + (r if y2 > y1 else -r if y2 < y1 else 0)
        path.append(f"L {ax:.1f} {ay:.1f} Q {x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}")
    path.append(f"L {points[-1][0]:.1f} {points[-1][1]:.1f}")
    return " ".join(path)


def check_connected(diagram: Diagram) -> None:
    """Fail when a device has no wire, so a floating part cannot be drawn."""
    used: set[str] = set()
    for connection in diagram.connections:
        if connection.device_name:
            used.add(connection.device_name)
        if connection.source_device:
            used.add(connection.source_device)
    floating = [device.name for device in diagram.devices if device.name not in used]
    if floating:
        raise ValueError(
            "Breadboard layout: no connections for "
            + ", ".join(floating)
            + ". Wire it or remove it."
        )


class BreadboardRenderer:
    """Render a diagram as a pictorial breadboard."""

    def render(self, diagram: Diagram, output_path: str | Path) -> None:
        check_connected(diagram)
        check_board(diagram.board)
        self.diagram = diagram
        scheme = get_color_scheme(diagram.theme)
        self.bg, self.fg = scheme.canvas_background, scheme.text_primary
        self.fg_secondary = scheme.text_secondary
        self.devices = {device.name: device for device in diagram.devices}
        self.modules = [device for device in diagram.devices if _role(device) == "module"]
        for module in self.modules:
            if _is_stepstick(module):
                continue
            if module.type_id in BREAKOUT_TYPES or module.pins:
                continue
            raise ValueError(
                f"Breadboard layout can only seat stepsticks ({', '.join(sorted(STEPSTICK_TYPES))}) "
                f"or breakouts with pins ({', '.join(sorted(BREAKOUT_TYPES))}) as a module, "
                f"not {module.name}"
            )
        self.module_row: dict[str, int] = {}
        cursor = FIRST_MODULE_ROW
        for module in self.modules:
            row = module.placement.row if module.placement and module.placement.row is not None else None
            if row is None:
                row = cursor
            self.module_row[module.name] = row
            gap = MODULE_ROWS if _is_stepstick(module) else _module_height(module) + BREAKOUT_GAP
            cursor = max(cursor, row + gap)
        self._check_module_rows()
        last = max(
            (self.module_row[m.name] + _module_height(m) for m in self.modules),
            default=FIRST_MODULE_ROW,
        )
        rows = last + 4
        board = diagram.board
        positioned = [pin for pin in board.pins if pin.position]
        # Median vertical spacing between consecutive pins in the same column.
        by_x: dict[float, list[float]] = {}
        for pin in positioned:
            by_x.setdefault(round(pin.position.x, 2), []).append(pin.position.y)
        pitches: list[float] = []
        for ys in by_x.values():
            ys_sorted = sorted(ys)
            for a, b in zip(ys_sorted, ys_sorted[1:], strict=False):
                gap = b - a
                if gap > 1e-3:
                    pitches.append(gap)
        pitch = sorted(pitches)[len(pitches) // 2] if pitches else 12.0
        self.pin_pitch = pitch * PI_SCALE
        header_right = (
            PI_ORIGIN[0] + max(pin.position.x for pin in positioned) * PI_SCALE
        )
        header_left = (
            PI_ORIGIN[0] + min(pin.position.x for pin in positioned) * PI_SCALE
        )
        self.header_right = header_right
        self.header_left = header_left
        self.board_top = PI_ORIGIN[1]
        self.board_bottom = PI_ORIGIN[1] + board.height * PI_SCALE
        self.geo = Geometry(left=header_right + BOARD_TO_BREADBOARD, top=BREADBOARD_TOP, rows=rows)
        self.x_fan = header_right + FAN_OFFSET
        self.x_ribbon_end = self.geo.x["GND"] - RIBBON_END_GAP
        self.x_hop = self.geo.x["GND"] - HOP_GAP
        self.motor_x = self.geo.x["+24V"] + MOTOR_OFFSET
        # Stable top-bypass lanes for left-column header wires (top → bottom → outer).
        left_ys = sorted(
            {
                round(self._header_xy(conn.board_pin)[1], 1)
                for conn in diagram.connections
                if conn.board_pin
                and self._header_xy(conn.board_pin)[0]
                < header_right - self.pin_pitch / 4
            }
        )
        self._left_bypass_lane = {y: index for index, y in enumerate(left_ys)}

        roles = {_role(device) for device in diagram.devices}
        content_right = self.geo.right
        content_bottom = max(self.geo.bottom, PI_ORIGIN[1] + board.height * PI_SCALE)
        if "motor" in roles:
            content_right = max(content_right, self.motor_x + MOTOR_BODY_WIDTH)
        if "capacitor" in roles:
            content_right = max(content_right, self.geo.right + CAPACITOR_LABEL_WIDTH)
        if "supply" in roles:
            supply_right = self.geo.x["MGND"] - SUPPLY_LEFT_OF_MGND + SUPPLY_WIDTH
            supply_bottom = self.geo.y(self.geo.rows - 1) + SUPPLY_TOP + SUPPLY_HEIGHT
            content_right = max(content_right, supply_right)
            content_bottom = max(content_bottom, supply_bottom)
        width = content_right + MARGIN
        height = content_bottom + MARGIN

        self.svg = SVGRenderer()
        specs = [device for device in diagram.devices if device.description]
        specs_table = None
        if diagram.show_legend and specs:
            table_x = LayoutConfig.board_margin_left
            table_y = content_bottom + LayoutConfig.specs_table_top_margin
            table_width = content_right - table_x
            specs_table = (specs, table_x, table_y, table_width)
            height = table_y + self.svg.specs_table_height(specs, table_width) + MARGIN

        canvas = draw.Drawing(width, height, origin=(0, 0))
        canvas.append(draw.Rectangle(0, 0, width, height, fill=self.bg))
        self.canvas = canvas

        self._draw_title(width)
        self._draw_pi()
        self._draw_breadboard()
        for module in self.modules:
            self._draw_module(module)
        self._draw_wires()
        self._draw_pin_labels(scheme)
        self._draw_pin_numbers(scheme)
        if specs_table:
            self.svg.draw_specs_table(canvas, *specs_table, scheme)
        canvas.save_svg(str(Path(output_path)))

    def _check_module_rows(self) -> None:
        ordered = sorted(self.modules, key=lambda module: self.module_row[module.name])
        for module in ordered:
            if self.module_row[module.name] < MIN_MODULE_ROW:
                raise ValueError(f"{module.name}: breadboard row must be at least {MIN_MODULE_ROW}")
        for upper, lower in zip(ordered, ordered[1:], strict=False):
            min_gap = _module_height(upper) + (1 if not _is_stepstick(upper) else 0)
            # Stepsticks keep the historical ≥8 row separation.
            if _is_stepstick(upper) or _is_stepstick(lower):
                min_gap = max(min_gap, MODULE_SPAN)
            if self.module_row[lower.name] - self.module_row[upper.name] < min_gap:
                raise ValueError(
                    f"{upper.name} and {lower.name} overlap on the breadboard; "
                    f"their rows must be at least {min_gap} apart"
                )

    # Parts -----------------------------------------------------------------

    def _draw_title(self, width: float) -> None:
        if self.diagram.title and self.diagram.show_title:
            self.canvas.append(
                draw.Text(
                    self.diagram.title,
                    RENDER_CONSTANTS.TITLE_FONT_SIZE,
                    width / 2,
                    RENDER_CONSTANTS.TITLE_Y_OFFSET,
                    text_anchor="middle",
                    font_family=FONT,
                    font_weight="bold",
                    fill=self.fg,
                )
            )

    def _draw_pi(self) -> None:
        asset = self.diagram.board.svg_asset_path  # existence checked by check_board
        root = ET.parse(asset).getroot()
        group = draw.Group(transform=f"translate({PI_ORIGIN[0]}, {PI_ORIGIN[1]}) scale({PI_SCALE})")
        SVGRenderer().inline_svg_elements(group, root, self.canvas, show_board_name=False)
        self.canvas.append(group)

    def _draw_pin_numbers(self, scheme) -> None:
        group = draw.Group(transform=f"translate({PI_ORIGIN[0]}, {PI_ORIGIN[1]}) scale({PI_SCALE})")
        self.svg.draw_gpio_pin_numbers(group, self.diagram.board, 0, 0, scheme)
        self.canvas.append(group)

    def _pin_text(self, connection: Connection) -> str:
        target = self.devices[connection.device_name or ""]
        pin = connection.device_pin_name or ""
        if _role(target) == "rail":
            return pin
        return f"{STEPSTICK_LABELS.get(pin, pin)} {target.name.split()[-1]}"

    def _draw_pin_labels(self, scheme) -> None:
        """Tag each wired header pin with its net, in the schematic's pin-label style.

        The label sits against its own pin: left of the left column, right of the
        right column, so wires leave from under the tag.
        """
        radius = RENDER_CONSTANTS.PIN_RADIUS * PI_SCALE
        for connection in self.diagram.connections:
            if not connection.board_pin:
                continue
            text = self._pin_text(connection)
            px, py = self._header_xy(connection.board_pin)
            width = len(text) * LABEL_CHAR_WIDTH + 2 * LABEL_PADDING
            on_right = px >= self.header_right - self.pin_pitch / 4
            x = px + radius + 2 if on_right else px - radius - 2 - width
            self.canvas.append(
                draw.Rectangle(
                    x,
                    py - LABEL_HEIGHT / 2,
                    width,
                    LABEL_HEIGHT,
                    rx=2,
                    ry=2,
                    fill=scheme.pin_label_background,
                    opacity=0.8,
                )
            )
            self.canvas.append(
                draw.Text(
                    text,
                    LABEL_FONT_SIZE,
                    x + LABEL_PADDING,
                    py + LABEL_FONT_SIZE * 0.35,
                    font_family=FONT,
                    fill=scheme.pin_label_text,
                )
            )

    def _header_xy(self, pin_number: int) -> tuple[float, float]:
        pin = next((item for item in self.diagram.board.pins if item.number == pin_number), None)
        if pin is None or pin.position is None:
            raise ValueError(f"Board pin {pin_number} has no position")
        return PI_ORIGIN[0] + pin.position.x * PI_SCALE, PI_ORIGIN[1] + pin.position.y * PI_SCALE

    def _draw_breadboard(self) -> None:
        geo, c = self.geo, self.canvas
        c.append(
            draw.Rectangle(
                geo.left,
                geo.top,
                geo.right - geo.left,
                geo.bottom - geo.top,
                rx=10,
                fill="#F6F3EC",
                stroke="#D9D3C5",
                stroke_width=1.5,
            )
        )
        trench = (geo.x["e"] + geo.x["f"]) / 2
        c.append(
            draw.Rectangle(
                trench - 8, geo.top + 10, 16, geo.bottom - geo.top - 20, rx=4, fill="#E7E1D6"
            )
        )
        left_power = self._left_power_rail()
        for rail in RAIL_PINS:
            x = geo.x[rail]
            role_key = left_power if rail == "+3V3" else rail
            c.append(
                draw.Line(
                    x,
                    geo.y(0) - 10,
                    x,
                    geo.y(geo.rows - 1) + 10,
                    stroke=DEFAULT_COLORS[RAIL_ROLES[role_key]],
                    stroke_width=3,
                    stroke_opacity=0.45,
                )
            )
        for row in range(geo.rows):
            for name in RAIL_PINS + tuple("abcdefghij"):
                c.append(
                    draw.Circle(
                        geo.x[name],
                        geo.y(row),
                        3.0,
                        fill="#C8C2B6",
                        stroke="#8E887C",
                        stroke_width=0.6,
                    )
                )
        for rail in ("MGND", "+24V"):
            x, y = geo.x[rail] + 4, geo.y(0) - 20
            c.append(
                draw.Text(
                    rail,
                    LABEL_FONT_SIZE,
                    x,
                    y,
                    font_family=FONT,
                    fill=self.fg,
                    transform=f"rotate(-90 {x} {y})",
                )
            )
        for label, column in (("GND", "GND"), (left_power, "+3V3")):
            x, y = geo.x[column] + 4, geo.y(geo.rows - 1) + 32
            c.append(
                draw.Text(
                    label,
                    LABEL_FONT_SIZE,
                    x,
                    y,
                    text_anchor="end",
                    font_family=FONT,
                    fill=self.fg,
                    transform=f"rotate(-90 {x} {y})",
                )
            )

    def _draw_module(self, module: Device) -> None:
        if _is_stepstick(module):
            self._draw_stepstick(module)
        else:
            self._draw_breakout(module)

    def _draw_stepstick(self, module: Device) -> None:
        geo, c, p = self.geo, self.canvas, self.geo.pitch
        top = self.module_row[module.name]
        x0, x1 = geo.x["b"] - 0.5 * p, geo.x["f"] + 0.5 * p
        y0, y1 = geo.y(top) - 0.45 * p, geo.y(top + 7) + 0.45 * p
        c.append(
            draw.Rectangle(
                x0, y0, x1 - x0, y1 - y0, rx=4, fill="#2B241C", stroke="#1A140F", stroke_width=1
            )
        )
        for index in range(8):
            y = geo.y(top + index)
            c.append(
                draw.Circle(geo.x["b"], y, 3.6, fill="#E6C36A", stroke="#8A6A22", stroke_width=0.6)
            )
            c.append(
                draw.Circle(geo.x["f"], y, 3.6, fill="#E6C36A", stroke="#8A6A22", stroke_width=0.6)
            )
            left = STEPSTICK_LEFT[index]
            c.append(
                draw.Text(
                    STEPSTICK_LABELS.get(left, left),
                    LABEL_FONT_SIZE,
                    geo.x["b"] + 8,
                    y + 4,
                    font_family=FONT,
                    fill="#F4EFE4",
                )
            )
            right = STEPSTICK_RIGHT[index]
            c.append(
                draw.Text(
                    STEPSTICK_LABELS.get(right, right),
                    LABEL_FONT_SIZE,
                    geo.x["f"] - 8,
                    y + 4,
                    text_anchor="end",
                    font_family=FONT,
                    fill="#F4EFE4",
                )
            )
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        c.append(
            draw.Text(
                module.name,
                NAME_FONT_SIZE,
                cx,
                cy - 2,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#FFFFFF",
            )
        )
        c.append(
            draw.Text(
                (module.type_id or "").upper(),
                LABEL_FONT_SIZE,
                cx,
                cy + 12,
                text_anchor="middle",
                font_family=FONT,
                fill="#CFC6B6",
            )
        )

    def _draw_breakout(self, module: Device) -> None:
        """Single-column breakout (pot / servo / LED / button) on the left of the trench."""
        geo, c, p = self.geo, self.canvas, self.geo.pitch
        top = self.module_row[module.name]
        height = _module_height(module)
        x0, x1 = geo.x["b"] - 0.5 * p, geo.x["e"] + 0.5 * p
        y0, y1 = geo.y(top) - 0.45 * p, geo.y(top + height - 1) + 0.45 * p
        fill = BREAKOUT_FILL.get(module.type_id or "", "#374151")
        c.append(
            draw.Rectangle(
                x0, y0, x1 - x0, y1 - y0, rx=4, fill=fill, stroke="#1A140F", stroke_width=1
            )
        )
        for index, pin in enumerate(module.pins):
            y = geo.y(top + index)
            c.append(
                draw.Circle(geo.x["b"], y, 3.6, fill="#E6C36A", stroke="#8A6A22", stroke_width=0.6)
            )
            c.append(
                draw.Text(
                    pin.name,
                    LABEL_FONT_SIZE,
                    geo.x["b"] + 8,
                    y + 4,
                    font_family=FONT,
                    fill="#F4EFE4",
                )
            )
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        c.append(
            draw.Text(
                module.name,
                NAME_FONT_SIZE,
                cx,
                cy - 2,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#FFFFFF",
            )
        )
        type_label = (module.type_id or "breakout").upper()
        c.append(
            draw.Text(
                type_label,
                LABEL_FONT_SIZE,
                cx,
                cy + 12,
                text_anchor="middle",
                font_family=FONT,
                fill="#F3F4F6",
            )
        )

    def _draw_motor(self, motor: Device, leads: list[tuple[str, float]]) -> None:
        c = self.canvas
        top = min(y for _pin, y in leads) - 26
        bottom = max(y for _pin, y in leads) + 26
        box_x = self.motor_x + 32
        size = bottom - top
        c.append(
            draw.Rectangle(
                box_x, top, size, size, rx=5, fill="#4A4E54", stroke="#2A2D31", stroke_width=1.5
            )
        )
        c.append(
            draw.Circle(
                box_x + size / 2,
                top + size / 2 - 6,
                20,
                fill="#C5A46E",
                stroke="#6E5A38",
                stroke_width=2,
            )
        )
        c.append(draw.Circle(box_x + size / 2, top + size / 2 - 6, 6, fill="#2A2D31"))
        c.append(
            draw.Text(
                motor.name,
                NAME_FONT_SIZE,
                box_x + size / 2,
                bottom - 10,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#FFFFFF",
            )
        )
        for pin, y in leads:
            c.append(
                draw.Circle(self.motor_x, y, 4, fill="#F4F1EA", stroke="#333333", stroke_width=1)
            )
            c.append(
                draw.Text(
                    pin,
                    LABEL_FONT_SIZE,
                    self.motor_x + 8,
                    y + 4,
                    font_family=FONT,
                    fill=self.fg,
                )
            )

    def _draw_supply(self, supply: Device, rails: dict[str, str]) -> tuple[float, float, float]:
        geo, c = self.geo, self.canvas
        top = geo.y(geo.rows - 1) + SUPPLY_TOP
        left = geo.x["MGND"] - SUPPLY_LEFT_OF_MGND
        c.append(
            draw.Rectangle(
                left,
                top,
                SUPPLY_WIDTH,
                SUPPLY_HEIGHT,
                rx=4,
                fill="#F4F6F8",
                stroke="#5C6770",
                stroke_width=1.5,
            )
        )
        c.append(
            draw.Text(
                supply.name,
                NAME_FONT_SIZE,
                left + SUPPLY_WIDTH / 2,
                top + 22,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#1A1A1A",
            )
        )
        for pin, x in (("-V", geo.x["MGND"] - 44), ("+V", geo.x["+24V"] + 44)):
            rail = rails.get(pin)
            if rail is None:
                value = ""
            elif RAIL_ROLES[rail] == PinRole.GROUND:
                value = "GND"
            else:
                value = rail.lstrip("+")
            c.append(
                draw.Text(
                    f"{pin} {value}".strip(),
                    LABEL_FONT_SIZE,
                    x,
                    top + 42,
                    text_anchor="middle",
                    font_family=FONT,
                    fill="#1A1A1A",
                )
            )
        return top, geo.x["MGND"] - 44, geo.x["+24V"] + 44

    def _draw_capacitor(self, capacitor: Device, minus_rail: str, plus_rail: str, row: int) -> None:
        geo, c = self.geo, self.canvas
        xm, xp, y = geo.x[minus_rail], geo.x[plus_rail], geo.y(row)
        cx = (xm + xp) / 2
        body_top, body_bottom = y - 58, y - 14
        for leg_x, hole_x in ((cx - 6, xm), (cx + 6, xp)):
            c.append(draw.Line(leg_x, body_bottom, hole_x, y, stroke="#8E8E8E", stroke_width=2))
            c.append(draw.Circle(hole_x, y, 3.2, fill="#8E8E8E"))
        c.append(
            draw.Rectangle(
                cx - 15,
                body_top,
                30,
                body_bottom - body_top,
                rx=7,
                fill="#3E6A9A",
                stroke="#1F3A57",
                stroke_width=1,
            )
        )
        stripe_left = cx - 15 if xm < xp else cx + 3
        c.append(
            draw.Rectangle(
                stripe_left, body_top + 1, 12, body_bottom - body_top - 2, fill="#E8EEF4"
            )
        )
        minus_x = stripe_left + 6
        plus_x = cx + 9 if xm < xp else cx - 9
        c.append(
            draw.Text(
                "-",
                13,
                minus_x,
                body_top + 26,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#1F3A57",
            )
        )
        c.append(
            draw.Text(
                "+",
                12,
                plus_x,
                body_top + 26,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#FFFFFF",
            )
        )
        trench = (geo.x["e"] + geo.x["f"]) / 2
        on_left = max(xm, xp) < trench
        label_x = geo.left - 8 if on_left else geo.right + 8
        anchor = "end" if on_left else "start"
        c.append(
            draw.Text(
                capacitor.name,
                NAME_FONT_SIZE,
                label_x,
                body_top + 18,
                text_anchor=anchor,
                font_family=FONT,
                font_weight="bold",
                fill=self.fg,
            )
        )
        for offset, note in ((32, f"stripe (-) on {minus_rail}"), (45, f"+ on {plus_rail}")):
            c.append(
                draw.Text(
                    note,
                    LABEL_FONT_SIZE,
                    label_x,
                    body_top + offset,
                    text_anchor=anchor,
                    font_family=FONT,
                    fill=self.fg_secondary,
                )
            )

    # Wires -----------------------------------------------------------------

    def _wire(self, path: str, color: str) -> None:
        # Same halo and core widths, opacities and halo colour rule as the schematic wires.
        for stroke, width, opacity in (
            (
                get_halo_color(color),
                RENDER_CONSTANTS.WIRE_MAIN_STROKE_WIDTH,
                RENDER_CONSTANTS.WIRE_MAIN_OPACITY,
            ),
            (
                color,
                RENDER_CONSTANTS.WIRE_CORE_STROKE_WIDTH,
                RENDER_CONSTANTS.WIRE_CORE_OPACITY,
            ),
        ):
            self.canvas.append(
                draw.Path(
                    path,
                    stroke=stroke,
                    stroke_width=width,
                    opacity=opacity,
                    fill="none",
                    stroke_linecap="round",
                    stroke_linejoin="round",
                )
            )

    def _dot(self, x: float, y: float, color: str) -> None:
        self.canvas.append(
            draw.Circle(x, y, RENDER_CONSTANTS.PIN_MARKER_OUTER_RADIUS, fill=get_halo_color(color))
        )
        self.canvas.append(draw.Circle(x, y, RENDER_CONSTANTS.PIN_MARKER_INNER_RADIUS, fill=color))

    def _module_pin_xy(self, module: Device, pin: str) -> tuple[float, float, int]:
        column, offset = module_seat(module, pin)
        row = self.module_row[module.name] + offset
        return self.geo.x[column], self.geo.y(row), row

    def _classify(
        self, connection: Connection
    ) -> tuple[str, Device | None, str, Device | None, str]:
        if connection.board_pin:
            target = self.devices[connection.device_name or ""]
            return (
                "board",
                None,
                str(connection.board_pin),
                target,
                connection.device_pin_name or "",
            )
        source = self.devices[connection.source_device or ""]
        target = self.devices[connection.device_name or ""]
        return (
            "device",
            source,
            connection.source_pin or "",
            target,
            connection.device_pin_name or "",
        )

    def _draw_wires(self) -> None:
        geo, p = self.geo, self.geo.pitch
        bundles: dict[str, list[tuple[Connection, float, float, float, str]]] = {}
        feeds: list[tuple[Connection, float, float, str]] = []
        motor_leads: dict[str, list[tuple[str, float, float, str]]] = {}
        supply_feeds: list[tuple[Device, str, str, str]] = []
        capacitor_legs: dict[str, dict[str, str]] = {}
        ties: list[tuple[str, str, str]] = []
        stubs: list[tuple[Device, str, str, str]] = []

        for connection in self.diagram.connections:
            kind, source, source_pin, target, target_pin = self._classify(connection)
            color = self._wire_color(connection)
            if kind == "board":
                px, py = self._header_xy(int(source_pin))
                if _role(target) == "module":
                    _x, _y, row = self._module_pin_xy(target, target_pin)
                    land = (
                        geo.y(self.module_row[target.name] + 7) + 2.5 * p
                        if target_pin == "IOGND" and _is_stepstick(target)
                        else geo.y(row)
                    )
                    bundles.setdefault(target.name, []).append((connection, px, py, land, color))
                elif _role(target) == "rail":
                    feeds.append((connection, px, py, color))
                else:
                    raise ValueError(
                        f"Breadboard layout cannot wire board pin {source_pin} to {target.name}"
                    )
                continue
            pair = {_role(source): (source, source_pin), _role(target): (target, target_pin)}
            if "module" in pair and "rail" in pair:
                stubs.append((pair["module"][0], pair["module"][1], pair["rail"][1], color))
            elif "module" in pair and "motor" in pair:
                module, module_pin = pair["module"]
                motor, motor_pin = pair["motor"]
                _x, y, _row = self._module_pin_xy(module, module_pin)
                motor_leads.setdefault(motor.name, []).append((motor_pin, y, geo.x["j"], color))
            elif "supply" in pair and "rail" in pair:
                supply_feeds.append((pair["supply"][0], pair["supply"][1], pair["rail"][1], color))
            elif "capacitor" in pair and "rail" in pair:
                capacitor_legs.setdefault(pair["capacitor"][0].name, {})[pair["capacitor"][1]] = (
                    pair["rail"][1]
                )
            elif _role(source) == "rail" and _role(target) == "rail":
                if {source_pin, target_pin} != {"GND", "MGND"}:
                    raise ValueError(
                        f"Rail tie must join GND and MGND, not {sorted({source_pin, target_pin})}"
                    )
                ties.append((source_pin, target_pin, color))
            else:
                raise ValueError(
                    "Breadboard layout cannot wire "
                    f"{source.name}.{source_pin} to {target.name}.{target_pin}"
                )

        self._draw_feeds(feeds)
        for module in self.modules:
            if module.name in bundles:
                self._draw_bundle(module, bundles[module.name])
        for module, module_pin, rail, color in stubs:
            self._draw_stub(module, module_pin, rail, color)
        for name, leads in motor_leads.items():
            self._draw_motor(self.devices[name], [(pin, y) for pin, y, _x, _c in leads])
            for _pin, y, x, color in leads:
                self._wire(_rounded([(x, y), (self.motor_x, y)]), color)
                self._dot(x, y, color)
        supply_top = None
        if supply_feeds:
            supply_top, minus_x, plus_x = self._draw_supply(
                supply_feeds[0][0], {pin: rail for _s, pin, rail, _c in supply_feeds}
            )
            bottom = geo.y(geo.rows - 1)
            for _supply, pin, rail, color in supply_feeds:
                start_x = minus_x if pin.startswith("-") else plus_x
                rail_x = geo.x[_rail_column(rail)]
                self._wire(
                    _rounded(
                        [
                            (start_x, supply_top),
                            (start_x, bottom + 42),
                            (rail_x, bottom + 42),
                            (rail_x, bottom),
                        ]
                    ),
                    color,
                )
                self._dot(rail_x, bottom, color)
        uses_motor_ground = any(rail == "MGND" for *_rest, rail, _color in stubs) or any(
            rail == "MGND" for *_rest, rail, _color in supply_feeds
        )
        if ties or uses_motor_ground:
            self._draw_tie("#1A1A1A")
        for name, legs in capacitor_legs.items():
            minus_rail = legs.get("-")
            plus_rail = legs.get("+")
            if not minus_rail or not plus_rail:
                raise ValueError(f"{name} needs both legs on rails")
            if minus_rail == plus_rail:
                raise ValueError(f"{name} has both legs on {minus_rail}")
            self._draw_capacitor(self.devices[name], minus_rail, plus_rail, geo.rows - 3)

    def _left_power_rail(self) -> str:
        """Silk for the left power strip: +5V when used, otherwise +3V3."""
        for connection in self.diagram.connections:
            for pin in (connection.device_pin_name, connection.source_pin):
                if pin == "+5V":
                    return "+5V"
        return "+3V3"

    def _draw_feeds(self, feeds: list[tuple[Connection, float, float, str]]) -> None:
        """Header pins that land on the left rails, from above, nested so they do not cross."""
        geo = self.geo
        feeds = sorted(feeds, key=lambda item: item[2])
        count = len(feeds)
        for index, (connection, px, py, color) in enumerate(feeds):
            rail = connection.device_pin_name or ""
            if rail not in ("GND", "+3V3", "+5V"):
                raise ValueError(
                    f"Header pins land on the left rails (GND, +3V3, +5V), not {rail}"
                )
            rail_x = geo.x[_rail_column(rail)]
            apex = geo.y(0) - 20 - 18 * (count - 1 - index)
            lead, sx, sy = self._fan_start(px, py, apex)
            if sy < self.board_top:
                # Already above the board via top bypass — stay high until the rail.
                path = (
                    f"{lead} L {rail_x - 16:.1f} {sy:.1f} "
                    f"Q {rail_x:.1f} {sy:.1f} {rail_x:.1f} {min(sy + 12, geo.y(0)):.1f} "
                    f"L {rail_x:.1f} {geo.y(0):.1f}"
                )
            else:
                path = (
                    f"{lead} C {sx + 30:.1f} {sy:.1f}, "
                    f"{rail_x - 90:.1f} {apex:.1f}, {rail_x - 12:.1f} {apex:.1f} "
                    f"Q {rail_x:.1f} {apex:.1f} {rail_x:.1f} {apex + 12:.1f} "
                    f"L {rail_x:.1f} {geo.y(0):.1f}"
                )
            self._wire(path, color)
            self._dot(rail_x, geo.y(0), color)

    def _fan_start(
        self, px: float, py: float, toward_y: float, over: bool = False
    ) -> tuple[str, float, float]:
        """Leave a header pin. Returns the path so far and the point the curve starts from.

        Left-column pins take the long way around the *top* of the board (left → up
        → across above the silkscreen → into the fan corridor). Crossing the board
        face is forbidden — it hides pin labels. Right-column pins leave directly.
        ``over`` is kept for call-site compatibility but unused for left pins.
        """
        del toward_y, over  # destination handled by the caller after this stub
        if px < self.header_right - self.pin_pitch / 4:
            lane = self._left_bypass_lane.get(round(py, 1), 0)
            escape_x = self.header_left - LEFT_ESCAPE_CLEAR - lane * RIBBON_SPACING
            bypass_y = self.board_top - TOP_BYPASS_CLEAR - lane * TOP_BYPASS_LANE
            clear_x = self.header_right + self.pin_pitch / 2
            path = (
                f"M {px:.1f} {py:.1f} "
                f"L {escape_x:.1f} {py:.1f} "
                f"L {escape_x:.1f} {bypass_y:.1f} "
                f"L {clear_x:.1f} {bypass_y:.1f}"
            )
            return path, clear_x, bypass_y
        return f"M {px:.1f} {py:.1f}", px, py

    def _draw_bundle(
        self, module: Device, wires: list[tuple[Connection, float, float, float, str]]
    ) -> None:
        """One ribbon from the header to the module, in header order.

        The ribbon stays flat (no wire crosses another) as long as the pins
        land in the same top-to-bottom order they leave the header. A wire
        whose pin is above an earlier wire's pin (EN, the top pin, after
        STEP and DIR) is a hopper: it lands below everything that came
        before it and climbs the left edge of the board to its row, so the
        only crossing is that one visible hop.
        """
        geo, p = self.geo, self.geo.pitch
        wires = sorted(wires, key=lambda item: (round(item[2]), item[1]))
        center = sum(item[2] for item in wires) / len(wires)
        k = 0.45 * (self.x_ribbon_end - self.x_fan)
        routed: list[tuple[Connection, float, float, float, str, float | None]] = []
        floor = None
        hops = 0
        for connection, px, py, land, color in wires:
            hop_x = None
            if floor is not None and land < floor - 1:
                hops += 1
                hop_x = self.x_hop - (hops - 1) * RIBBON_SPACING
                land = floor + 0.9 * p
            floor = land if floor is None else max(floor, land)
            routed.append((connection, px, py, land, color, hop_x))
        for index, (connection, px, py, land, color, hop_x) in enumerate(routed):
            lane = center + (index - (len(routed) - 1) / 2) * RIBBON_SPACING
            shares_row = any(abs(other[2] - py) < 1 and other[1] > px for other in wires)
            lead, sx, sy = self._fan_start(px, py, lane, over=shares_row)
            if sy < self.board_top:
                # Top-bypass: run past the board at bypass height, then drop in the
                # fan corridor only — never cubic back down through the silkscreen.
                head = (
                    f"{lead} L {self.x_fan:.1f} {sy:.1f} "
                    f"C {self.x_fan + k:.1f} {sy:.1f}, "
                    f"{self.x_ribbon_end - k:.1f} {land:.1f}, "
                    f"{self.x_ribbon_end:.1f} {land:.1f}"
                )
            else:
                head = (
                    f"{lead} C {sx + 18:.1f} {sy:.1f}, "
                    f"{self.x_fan - 30:.1f} {lane:.1f}, {self.x_fan:.1f} {lane:.1f} "
                    f"C {self.x_fan + k:.1f} {lane:.1f}, "
                    f"{self.x_ribbon_end - k:.1f} {land:.1f}, "
                    f"{self.x_ribbon_end:.1f} {land:.1f}"
                )
            pin = connection.device_pin_name or ""
            if pin == "IOGND" and _is_stepstick(module):
                # Bottom-right pin: run under the module and up into its row.
                end_x, end_y, _row = self._module_pin_xy(module, pin)
                end_x = geo.x["i"]
                tail = _rounded([(self.x_ribbon_end, land), (end_x, land), (end_x, end_y)])
            else:
                end_x, end_y, _row = self._module_pin_xy(module, pin)
                end_x = geo.x["a"]
                if hop_x is None:
                    tail = _rounded([(self.x_ribbon_end, land), (end_x, end_y)])
                else:
                    tail = _rounded(
                        [(self.x_ribbon_end, land), (hop_x, land), (hop_x, end_y), (end_x, end_y)]
                    )
            self._wire(head + " " + tail.replace("M", "L", 1), color)
            self._dot(end_x, end_y, color)

    def _draw_stub(self, module: Device, pin: str, rail: str, color: str) -> None:
        geo, p = self.geo, self.geo.pitch
        top = self.module_row[module.name]
        _x, y, _row = self._module_pin_xy(module, pin)
        if not _is_stepstick(module):
            power = pin.upper() in ("VCC", "+", "5V", "3V3", "+3V3", "VIN", "VDD")
            ground = pin.upper() in ("GND", "-", "GROUND")
            if power:
                if rail not in ("+3V3", "+5V"):
                    raise ValueError(
                        f"{module.name}.{pin} should tie to the +3V3 or +5V rail"
                    )
                points = [(geo.x[_rail_column(rail)], y), (geo.x["a"], y)]
                end = points[-1]
            elif ground:
                if rail != "GND":
                    raise ValueError(f"{module.name}.{pin} should tie to the GND rail")
                points = [(geo.x["GND"], y), (geo.x["a"], y)]
                end = points[-1]
            else:
                raise ValueError(f"Breadboard layout has no rail stub for {module.name}.{pin}")
        elif pin in ("MS1", "MS2"):
            if rail != "+3V3":
                raise ValueError(f"{module.name}.{pin} should tie to the +3V3 rail")
            points = [(geo.x["+3V3"], y), (geo.x["a"], y)]
            end = points[-1]
        elif pin == "VDD":
            if rail != "+3V3":
                raise ValueError(f"{module.name}.VDD should tie to the +3V3 rail")
            # VDD is the second pin from the bottom on the right. The lane runs
            # under the module from the 3V3 rail and climbs between holes g
            # and h, clear of the GND stub leaving column j on the bottom row.
            lane_y = geo.y(top + 7) + 1.5 * p
            lane_x = geo.x["g"] + 0.5 * p
            points = [(geo.x["+3V3"], lane_y), (lane_x, lane_y), (lane_x, y), (geo.x["g"], y)]
            end = points[-1]
        elif pin in ("VM", "VMGND", "IOGND"):
            if pin != "VM" and rail != "MGND":
                raise ValueError(
                    f"{module.name}.{pin} should tie to the right-hand ground rail (MGND)"
                )
            if pin == "VM" and rail != "+24V":
                raise ValueError(f"{module.name}.VM should tie to the +24V rail")
            points = [(geo.x["j"], y), (geo.x[_rail_column(rail)], y)]
            end = points[0]
        else:
            raise ValueError(f"Breadboard layout has no rail stub for {module.name}.{pin}")
        self._wire(_rounded(points), color)
        self._dot(points[0][0], points[0][1], color)
        self._dot(end[0], end[1], color)
        self._dot(points[-1][0], points[-1][1], color)

    def _draw_tie(self, color: str) -> None:
        geo, p = self.geo, self.geo.pitch
        bottom = geo.y(geo.rows - 1)
        riser = geo.x["MGND"] - 0.55 * p
        points = [
            (geo.x["GND"], bottom),
            (geo.x["GND"], bottom + 22),
            (riser, bottom + 22),
            (riser, geo.y(geo.rows - 2)),
            (geo.x["MGND"], geo.y(geo.rows - 2)),
        ]
        self._wire(_rounded(points), color)
        self._dot(*points[0], color)
        self._dot(*points[-1], color)

    # Colors ----------------------------------------------------------------

    def _wire_color(self, connection: Connection) -> str:
        if connection.color:
            return connection.color
        if connection.board_pin:
            pin = self.diagram.board.get_pin_by_number(connection.board_pin)
        else:
            source = self.devices[connection.source_device or ""]
            pin = source.get_pin_by_name(connection.source_pin or "")
        return DEFAULT_COLORS.get(pin.role, "#808080") if pin else "#808080"


def module_row_offset(device: Device, pin_name: str) -> int:
    """Row of a module pin, counted from the module's first row."""
    return module_seat(device, pin_name)[1]
