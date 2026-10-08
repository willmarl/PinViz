"""Board selection strategies shared across config and MCP flows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Protocol

from . import boards
from .model import Board

# Hand-maintained aliases for built-in boards (plus JSON ``aliases`` field).
_STATIC_ALIASES: dict[str, str] = {
    # Raspberry Pi 5
    "raspberry_pi_5": "raspberry_pi_5",
    "rpi5": "raspberry_pi_5",
    # Raspberry Pi 4
    "raspberry_pi_4": "raspberry_pi_4",
    "rpi4": "raspberry_pi_4",
    "pi4": "raspberry_pi_4",
    # Raspberry Pi Pico
    "raspberry_pi_pico": "raspberry_pi_pico",
    "pico": "raspberry_pi_pico",
    # ESP32 DevKit V1
    "esp32_devkit_v1": "esp32_devkit_v1",
    "esp32": "esp32_devkit_v1",
    "esp32dev": "esp32_devkit_v1",
    "esp32_devkit": "esp32_devkit_v1",
    # ESP32-S3-DevKitC-1
    "esp32_s3_devkitc1": "esp32_s3_devkitc1",
    "esp32_s3_devkitc": "esp32_s3_devkitc1",
    "esp32_s3_devkit": "esp32_s3_devkitc1",
    "esp32s3": "esp32_s3_devkitc1",
    "esp32_s3": "esp32_s3_devkitc1",
    "esp32_s3_devkitc1_schematic": "esp32_s3_devkitc1_schematic",
    "esp32s3_schematic": "esp32_s3_devkitc1_schematic",
    "esp32_s3_schematic": "esp32_s3_devkitc1_schematic",
    # Wemos D1 Mini
    "wemos_d1_mini": "wemos_d1_mini",
    "d1mini": "wemos_d1_mini",
    "d1_mini": "wemos_d1_mini",
    "wemos": "wemos_d1_mini",
    # ESP8266 NodeMCU
    "esp8266_nodemcu": "esp8266_nodemcu",
    "esp8266": "esp8266_nodemcu",
    "nodemcu": "esp8266_nodemcu",
    # Legacy alias → Pi 5
    "raspberry_pi": "raspberry_pi_5",
    "rpi": "raspberry_pi_5",
}


def _board_configs_dir() -> Path:
    return Path(boards.__file__).parent / "board_configs"


@lru_cache(maxsize=1)
def _discover_config_aliases() -> dict[str, str]:
    """Map alias/config_name → config file stem for every board_configs/*.json."""
    mapping: dict[str, str] = {}
    for path in sorted(_board_configs_dir().glob("*.json")):
        stem = path.stem
        mapping[stem.lower()] = stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for alias in data.get("aliases") or []:
            if isinstance(alias, str) and alias.strip():
                mapping[alias.strip().lower()] = stem
    return mapping


def resolve_board_config_name(board_name: str) -> str | None:
    """Return board config stem for a name/alias, or None."""
    key = board_name.lower().strip()
    if key in _STATIC_ALIASES:
        return _STATIC_ALIASES[key]
    return _discover_config_aliases().get(key)


def list_board_entries() -> list[dict]:
    """Board catalog for ``pinviz list`` (name + aliases)."""
    entries: list[dict] = []
    discovered = _discover_config_aliases()
    # Invert: stem → aliases
    by_stem: dict[str, set[str]] = {}
    for alias, stem in {**{k: v for k, v in _STATIC_ALIASES.items()}, **discovered}.items():
        by_stem.setdefault(stem, set()).add(alias)

    for stem in sorted(by_stem):
        path = _board_configs_dir() / f"{stem}.json"
        display = stem
        if path.exists():
            try:
                display = json.loads(path.read_text(encoding="utf-8")).get("name") or stem
            except (OSError, json.JSONDecodeError):
                display = stem
        aliases = sorted(a for a in by_stem[stem] if a != stem.lower())
        entries.append({"name": stem, "display_name": display, "aliases": aliases})
    return entries


# Back-compat: callable table used by older tests / code paths.
def _loader_for(stem: str) -> Callable[[], Board]:
    return lambda: boards.load_board_from_config(stem)


BOARD_LOADERS: dict[str, Callable[[], Board]] = {
    alias: _loader_for(stem) for alias, stem in _STATIC_ALIASES.items()
}


class BoardSelectionStrategy(Protocol):
    """Strategy interface for resolving board names to board instances."""

    def select_board(self, board_name: str) -> Board:
        """Resolve a board name to a board instance."""


@dataclass(frozen=True)
class AliasBoardSelectionStrategy:
    """Resolve boards from alias table + auto-discovered board_configs.

    When ``fallback_board_name`` is set, unknown names fall back to that board.
    Otherwise an unknown board raises ``ValueError``.
    """

    fallback_board_name: str | None = None

    def select_board(self, board_name: str) -> Board:
        stem = resolve_board_config_name(board_name)
        if stem is None:
            if self.fallback_board_name is None:
                raise ValueError(f"Unknown board: {board_name}")
            stem = resolve_board_config_name(self.fallback_board_name)
            if stem is None:
                raise ValueError(f"Unknown board: {board_name}")
        return boards.load_board_from_config(stem)
