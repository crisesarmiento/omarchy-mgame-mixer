# Device control API (helper ↔ panel contract)

Hardware facts verified live on 2026-11-01 (USB 0763:0042):

- Gets are answered in set form (`F0 00 01 05 42 00 <N> <param> <values> <cs> F7`) on the same seq port the listener reads.
- `amidi -p <hw> -S` can send while the aseqdump listener holds the input.
- Mixer gain `0x44000000 + dest*0x100 + src*2` is writable (7-bit, default 115, 0 off). Each write is echoed on `0x4401xxxx` (effective volume) and `0x4400xxxx`.
- LED `0x01030C00` (pad 1, N=3 `[mode, active, idle]`) is writable and reads back.
- Phantom `0x00030000` reads back 0/1 (currently 1 on this unit).
- Button latches `0x010201xx` are readable but writes are ignored (echo keeps the old value). Mute vector `0x44020000` is read-only.
- `0x01040008/0C/10/14` read as the mute-button masks for game/chat/sampler/main_alt (`0x02`, `0x04`, `0x10`, `0x28`, repeated in 4 bytes).

## Names

dest (axis 0, `n/6`): `stream chat alt sampler main phones`
src (axis 1, `n%6`): `mic game chat aux sampler system`

## State file

`~/.local/state/mgame-mixer/device.json`, written atomically by the listener on every parsed frame, and by `dev-state --refresh` when no listener is running.

```json
{
  "connected": true,
  "updated": 1793291234.5,
  "phantom": 1,
  "gain":      {"stream": {"mic": 115, "game": 115, ...}, ...},
  "effective": {"stream": {"mic": 115, ...}, ...},
  "muted":     {"stream": ["sampler"], ...},
  "buttons":   {"mic_mute": false, "game_mute": null, ..., "sample_page_1": true, "sample_page_2": false, "bank_switch": false},
  "muteMap":   {"game_mute": ["game"], "chat_mute": ["chat"], "sampler_mute": ["sampler"], "main_alt_mute": ["aux", "system"]},
  "leds":      {"pad_1": {"param": "01030C00", "mode": 0, "active": 1, "idle": 52}, ...},
  "raw":       {"01040300": [..], "01010000": [..]}
}
```

A value is `null` until it has been read. `muted[dest]` is the list of src names whose bit is set in that dest's byte of the mute vector.

## Commands

Every command prints one JSON object: `{"ok": true, ...}` or `{"ok": false, "error": "..."}`, and exits 0 / 1.

| Command | Effect |
| --- | --- |
| `dev-state [--refresh]` | Print device.json. `--refresh` sends every known get, then waits up to 2 s for the replies. |
| `dev-gain DEST SRC 0..127` | Set one mixer gain. |
| `dev-route DEST SRC on\|off` | `off` stores the current gain in state.json and writes 0. `on` writes the stored gain, or 115. |
| `dev-routing-preset default\|no_chat_to_stream` | Apply a stock routing (from the .MGameRGBDualRouting files, see protocol.md). |
| `dev-phantom on\|off` | Phantom power, 48 V. |
| `dev-led CONTROL ACTIVE IDLE [MODE]` | Set one button/pad LED. CONTROL comes from `data/leds.json`. |
| `dev-led-presets` | `{"ok":true,"presets":["Red", ...]}` from `data/led_presets/*.json`. |
| `dev-led-preset NAME` | Apply every LED in that preset. |

Writes are allowlisted by param id. Nothing outside the table above is ever sent. Never send ids in the "dangerous" list of protocol.md.

## Data files (repo `data/`)

- `data/leds.json`: `{"controls": {"pad_1": {"param": "01030C00", "label": "Pad 1"}, ...}, "palette": {"0": "#000000", "1": "#FF0000", ...}}`. When an RGB value is unknown, put `null` and the panel shows the index.
- `data/led_presets/<Name>.json`: `{"name": "Red", "leds": {"pad_1": {"mode": 0, "active": 2, "idle": 52}, ...}}`. Converted from the Mac `*.MGameRGBDualLEDs` files.
- `data/routing_presets.json`: `{"default": {"stream": {"mic": 115, ...}, ...}, "no_chat_to_stream": {...}}`.
