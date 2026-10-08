"""Tests for procedural / multi-side controller boards."""

from pathlib import Path

import pytest

from pinviz import boards
from pinviz.board_selection import AliasBoardSelectionStrategy, resolve_board_config_name
from pinviz.breadboard import check_board
from pinviz.generic_board import compute_sides_geometry, generate_board_svg


class _Pin:
    def __init__(self, physical_pin: int, name: str, header: str, role: str = "GPIO"):
        self.physical_pin = physical_pin
        self.name = name
        self.header = header
        self.role = role


def test_compute_sides_geometry_left_right():
    pins = [
        _Pin(1, "A0", "left"),
        _Pin(2, "A1", "left"),
        _Pin(3, "D13", "right"),
        _Pin(4, "D12", "right"),
    ]
    width, height, positions = compute_sides_geometry(pins, width=200, height=200)
    assert width == 200
    assert height == 200
    assert positions[1].x < positions[3].x
    assert positions[1].y < positions[2].y


def test_generate_board_svg_contains_name_and_pads():
    pins = [_Pin(1, "D13", "right"), _Pin(2, "GND", "left")]
    _, _, positions = compute_sides_geometry(pins, width=180, height=120)
    svg = generate_board_svg(
        name="Test Board",
        width=180,
        height=120,
        pins=pins,
        positions=positions,
    )
    assert "Test Board" in svg
    assert svg.count("<circle") == 2
    assert "D13" in svg


def test_load_arduino_uno():
    board = boards.load_board_from_config("arduino_uno")
    assert board.name == "Arduino Uno R3"
    assert len(board.pins) == 27
    assert Path(board.svg_asset_path).exists()
    assert "generated" in board.svg_asset_path
    check_board(board)


def test_load_esp32_c2():
    board = boards.load_board_from_config("esp32_c2_devkitm1")
    assert "ESP32-C2" in board.name
    assert len(board.pins) == 20
    check_board(board)


def test_load_arduino_mega():
    board = boards.load_board_from_config("arduino_mega_2560")
    assert "Mega" in board.name
    assert len(board.pins) == 48
    by_num = {p.number: p.name for p in board.pins}
    assert by_num[4] == "3V3"
    assert by_num[29] == "D13"
    assert by_num[42] == "D0"
    check_board(board)


def test_load_arduino_nano():
    board = boards.load_board_from_config("arduino_nano")
    assert "Nano" in board.name
    assert len(board.pins) == 30
    by_num = {p.number: p.name for p in board.pins}
    assert by_num[30] == "D13"
    assert by_num[19] == "5V"
    check_board(board)


@pytest.mark.parametrize(
    "alias,stem",
    [
        ("arduino", "arduino_uno"),
        ("uno", "arduino_uno"),
        ("mega", "arduino_mega_2560"),
        ("arduino_mega", "arduino_mega_2560"),
        ("nano", "arduino_nano"),
        ("esp32_c2", "esp32_c2_devkitm1"),
        ("esp32c2", "esp32_c2_devkitm1"),
    ],
)
def test_aliases_resolve(alias, stem):
    assert resolve_board_config_name(alias) == stem
    board = AliasBoardSelectionStrategy().select_board(alias)
    assert board.name


def test_get_available_boards_includes_new():
    names = {b["name"] for b in boards.get_available_boards()}
    for stem in (
        "arduino_uno",
        "arduino_mega_2560",
        "arduino_nano",
        "arduino_leonardo",
        "arduino_micro",
        "arduino_pro_mini",
        "esp32_c2_devkitm1",
        "esp32_c3_supermini",
        "rp2040_zero",
        "raspberry_pi_zero_2_w",
        "raspberry_pi_pico_w",
        "stm32_bluepill",
    ):
        assert stem in names


@pytest.mark.parametrize(
    "stem",
    [
        "rp2040_zero",
        "arduino_leonardo",
        "stm32_bluepill",
        "esp32_c3_supermini",
        "raspberry_pi_zero_2_w",
    ],
)
def test_popular_boards_load(stem):
    board = boards.load_board_from_config(stem)
    assert board.pins
    check_board(board)


def test_diagram_schema_accepts_discovered_boards():
    from pinviz.schemas import DiagramConfigSchema, get_valid_board_names

    names = get_valid_board_names()
    assert "arduino_uno" in names
    assert "mega" in names
    assert "nano" in names
    assert "leonardo" in names
    assert "rp2040_zero" in names
    assert "zero2w" in names
    assert "esp32_c2" in names  # alias from JSON
    cfg = DiagramConfigSchema(title="t", board="arduino_mega_2560", devices=[], connections=[])
    assert cfg.board == "arduino_mega_2560"
    cfg2 = DiagramConfigSchema(title="t", board="nano", devices=[], connections=[])
    assert cfg2.board == "nano"
