# Popular boards catalog

Goal: ship **verified pinout JSON** for boards people actually wire, and prefer
**real silkscreen SVG** when we have it. Procedural (`render_mode: generated`)
is a fallback for follow-along diagrams — not a substitute for checking the
official pinout.

Selection inspired by popular MCU lists (e.g.
[Slayingripper/MicroControllers](https://github.com/Slayingripper/MicroControllers))
plus Waveshare / Raspberry Pi form-factors common in maker wiring asks.

## Status legend

| Art | Meaning |
| --- | --- |
| `svg` | Hand-tuned asset under `src/pinviz/assets/` |
| `generated` | Dual-column procedural pads from JSON |
| Pinout | Checked against the cited source |

## Catalog

| Config stem | Aliases (sample) | Art | Pinout source | Notes |
| --- | --- | --- | --- | --- |
| `raspberry_pi_4` | `rpi4`, `pi4` | svg | Pi 40-pin | Stock |
| `raspberry_pi_5` | `rpi5` | svg | Pi 40-pin | Stock |
| `raspberry_pi_zero` | `pi_zero`, `pizero` | svg* | Same 40-pin as Pi 4 | \*reuses `pi_4_mod.svg` for header alignment |
| `raspberry_pi_zero_w` | `pi_zero_w`, `zero_w` | svg* | Same 40-pin | WiFi Zero |
| `raspberry_pi_zero_2_w` | `pi_zero_2_w`, `zero2w` | svg* | Same 40-pin | Zero 2 W |
| `raspberry_pi_pico` | `pico` | svg | Pico dual header | Stock |
| `raspberry_pi_pico_w` | `pico_w`, `picow` | svg* | Same as Pico | \*reuses `pico_mod.svg` |
| `rp2040_zero` | `rp2040zero`, `waveshare_rp2040_zero` | generated | [arduino-pico variant diagram](https://github.com/earlephilhower/arduino-pico/blob/master/variants/waveshare_rp2040_zero/pins_arduino.h) | Main + bottom castellated; underside GP16–25 omitted (NeoPixel=GP16 onboard) |
| `esp32_devkit_v1` | `esp32` | svg | DevKit V1 | Stock |
| `esp32_s3_devkitc1` | `esp32s3` | svg | DevKitC-1 | Stock |
| `esp32_c2_devkitm1` | `esp32_c2` | generated | Espressif C2-DevKitM-1 | |
| `esp32_c3_supermini` | `c3_supermini` | generated | Common SuperMini silkscreen | WiFi C3; 16 edge pins |
| `esp8266_nodemcu` | `nodemcu` | svg | NodeMCU | Stock |
| `wemos_d1_mini` | `d1_mini` | svg | D1 mini | Stock |
| `arduino_uno` | `uno`, `arduino` | generated | Uno R3 headers | |
| `arduino_mega_2560` | `mega` | generated | [Mega datasheet](https://docs.arduino.cc/resources/datasheets/A000067-datasheet.pdf) | D22–D53 dual-row omitted |
| `arduino_nano` | `nano` | generated | Classic Nano DIP | |
| `arduino_leonardo` | `leonardo` | generated | Leonardo / Uno-form headers | I2C on D2/D3 |
| `arduino_micro` | `micro` | generated | Micro 32U4 dual row | |
| `arduino_pro_mini` | `pro_mini` | generated | Pro Mini dual row | 5V silk labels; 3.3V boards still use VCC |
| `stm32_bluepill` | `bluepill`, `stm32f103` | generated | Blue Pill dual 20-pin | USB “up” order |

## How to add a popular board

1. **Recon** the official pinout (PDF / product page / board-support package).
2. Add `src/pinviz/board_configs/<stem>.json` with `aliases` and either stock
   layout + `svg_asset` or `layout.mode: "sides"` + `render_mode: "generated"`.
3. Prefer a real SVG when headers align; otherwise generated art is fine.
4. Smoke: `uv run pinviz render examples/<stem>_….yaml`
5. Row in this table + InvBot `PINVIZ_WIRING_CONTEXT` `board_pin` hint if useful for wiring asks.

## Verification checklist

- [ ] Header order top→bottom matches silkscreen/datasheet (or BSP ASCII art)
- [ ] Power roles: `3V3` / `5V` / `GND` / `EXT_POWER` where applicable
- [ ] `pinviz list` shows stem + aliases
- [ ] `load_board_from_config` + `check_board` succeed
- [ ] InvBot cheat sheet lists the canonical stem when users will ask for it
