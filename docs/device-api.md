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
| `dev-fx` | Read the voice-FX knob and blocks from `device.json`, labeled by `data/fx.json`. Does not send. Missing readings are null. |
| `dev-fx-presets` | `{"ok":true,"voice":["Chef",...],"mic":["Default",...]}` |
| `dev-fx-preset voice\|mic NAME` | Print one preset file. Does not send. |

Writes are allowlisted by param id. Nothing outside the table above is ever sent. Never send ids in the "dangerous" list of protocol.md.

## Data files (repo `data/`)

- `data/leds.json`: `{"controls": {"pad_1": {"param": "01030C00", "label": "Pad 1"}, ...}, "palette": {"0": "#000000", "1": "#FF0000", ...}}`. When an RGB value is unknown, put `null` and the panel shows the index.
- `data/led_presets/<Name>.json`: `{"name": "Red", "leds": {"pad_1": {"mode": 0, "active": 2, "idle": 52}, ...}}`. Converted from the Mac `*.MGameRGBDualLEDs` files.
- `data/routing_presets.json`: `{"default": {"stream": {"mic": 115, ...}, ...}, "no_chat_to_stream": {...}}`.

## Apps and profiles

Same contract: one JSON object on stdout, exit 0 if `ok` is true and 1 otherwise. `apps-watch` is the exception: it is long-running, not for the panel, and exits non-zero when `pactl` dies. It does not import the device module and does not call `amidi`.

### Rules

`~/.config/mgame-mixer/app-rules.json`, replaced atomically:

```json
{"rules": [{"match": "firefox", "field": "binary", "sink": "game"}]}
```

- `match`: 1..80 characters after strip, no control characters. Empty is rejected (it would match everything).
- `field`: `binary` (basename of `application.process.binary`), `name` (`application.name`), or `both`. Case-insensitive substring. First match wins.
- `sink`: `game` | `chat` | `sampler` | `system` only.
- While watching, a parse or validation error keeps the last good rules and logs to stderr. It never silently becomes "no rules". A missing file means no rules, logged once.
- Streams whose `node.name` starts with `mgame_` or `pw-play` are skipped before matching, so a rule `"pw"` cannot catch the sampler. A `pw-play` binary is skipped too.

### Watcher

User unit `mgame-mixer-apps.service`. `ExecStart` is the helper with `apps-watch`. `Restart=on-failure`, `RestartSec=2`. That is the only backoff: the process does not sleep-retry, and it does not restart PipeWire. `pactl subscribe` runs under `stdbuf -oL`.

It does one full pass at startup and on `apps-apply`, and reacts only to Event `new` on `sink-input`. Event `change` is ignored (it would fight a manual move and loop on our own moves). A failed move is cached by sink-input id until Event `remove`. A stream already on the target is not moved. `apps-apply` does the same full pass, one move at a time, and does not lock against the watcher.

### Profiles

`~/.config/mgame-mixer/profiles/<name>.json`. User names match `^[A-Za-z0-9][A-Za-z0-9 _-]{0,40}$`. A leading underscore is rejected on save and delete. `profile-list` hides underscore names. Load writes the reserved `_before-restore.json` and `profile-load _before-restore` can read it back.

Schema version 1. No channel pairs, no FX, no phantom.

```json
{
  "version": 1,
  "volumes": {"game": {"pct": 40, "mute": false}, "chat": {"pct": 40, "mute": false},
              "sampler": {"pct": 40, "mute": false}, "system": {"pct": 40, "mute": false},
              "mic": {"pct": 40, "mute": false}},
  "mic": {"enabled": true, "preset": "natural", "overrides": {}},
  "rules": [{"match": "firefox", "field": "binary", "sink": "game"}],
  "gains": null,
  "ledPreset": null,
  "deviceUpdated": null
}
```

`volumes.*.pct` is an int 0..150. `mute` is a bool. Restore sets that mute with `0` or `1`, not `toggle`. `mic` uses the existing presets and override ranges. `gains` is every dest×src cell as an int 0..127 (not a bool), or `null`. `ledPreset` is a string or `null`. `deviceUpdated` is a number or `null`.

Save reads pactl, `state.json`, the rules file and `device.json`. It does not `--refresh`. If any of the 36 gains is missing, `gains` is `null`. It does not invent 115. `ledPreset` comes only from `state.json`, and only if `dev-led-preset` recorded a name that `list_led_presets()` still has; otherwise `null`.

`dev-led-preset`, on success, merges `{"ledPreset": NAME}` into `state.json` under the same flock as `save_state` and `remember_gains`. That merge does not drop `routeMemory`.

Load takes a non-blocking exclusive lock (`profile-restore.lock`). If it is held, the result is exactly `{"ok": false, "error": "busy"}` and the exit code is 1. The whole file is validated before any mutation: one bad gain, rule, sink key or unknown `ledPreset` rejects everything and touches nothing. Then `_before-restore` is written from the current live state (same shape; incomplete `device.json` stores `gains: null`). Then, in order:

1. Absolute sink/source volumes and mutes. A missing `mgame_*` node or a pactl error stops here, before any device write.
2. Mic: `save_state`, the mic conf, then `apply_mic_live`. If live returns false, `ok` is false, `mic.live` is false, and device writes do not start.
3. Rules file, atomically.
4. Gains, only if not null, via `build_gain` / `checked_set`, in chunks of 16 with 30 ms (`amidi_send_batch_quiet`, `WRITE_GAP`). The result says `sent N/36`, never "applied". Null gains skip this step and say `skipped`.
5. LED preset, only if `ledPreset` is a non-null name that exists. Null skips that step.

A device send that fails mid-way stops and returns the partial steps. There is no hardware rollback. Phantom is never sent. No id outside the gain allowlist is sent for the gain step. The result includes `deviceUpdated` and `age` (seconds since that timestamp).

### Commands

| Command | Effect |
| --- | --- |
| `apps-rules` | List rules. A missing file is an empty list. An invalid file is an error, not an empty list. Includes `watch: {enabled, active, installed}` so the panel switch matches the user unit. |
| `apps-rule-set MATCH FIELD SINK` | Add or replace the rule with that match and field. |
| `apps-rule-del MATCH FIELD` | Delete that rule. |
| `apps-apply` | One full pass. Not locked against the watcher. |
| `apps-watch` | Long-running watcher. Not for QML. |
| `apps-watch-enable` / `apps-watch-disable` | Install or stop the user unit. |
| `profile-list` | Names, hiding a leading `_`. |
| `profile-save NAME` | Write a version-1 profile. |
| `profile-load NAME` | Restore, or `profile-load _before-restore`. |
| `profile-delete NAME` | Delete. Rejects a leading `_`. |
