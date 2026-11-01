# M-Game Mixer (Omarchy plugin)

A bar widget for the **M-Audio M-Game RGB Dual** on Linux. The unit exposes one 8-channel
output and one 8-channel input. This plugin splits them with PipeWire into the same
channels the Windows software offers, adds a microphone processing chain, and drives a
sampler from the hardware pads.

Plugin id: `csarmiento.mgame-mixer`. The UI is available in English and Spanish.

## What you get

**Mixer tab**
- 4 virtual outputs: Game, Chat, Sampler, System.
- 4 virtual inputs: Stream, Alt, Chat in, Sampler in.
- Volume, mute and "set as default" for each one. Right-click a slider to mute it.
- A list of apps that are playing audio, with one button per output to route each app.
- Read-only indicators for the hardware mute buttons (see below).

**Mic tab**
- `M-Game Mic (processed)` source built from the Alt input (mono downmix):
  RNNoise → high-pass → EQ (mud cut, presence, air) → compressor → optional gate.
- Presets: Off, Natural, Broadcast, Noisy room, plus sliders for noise removal strength,
  compression ratio and voice presence.
- Changes apply live (no PipeWire restart) and are saved to `51-mgame-mic.conf`.

**Sampler tab**
- Five pads. Drop sounds in `~/.local/share/mgame-mixer/samples` (wav, flac, ogg, opus, mp3),
  select a pad, then assign a file from the library. Sounds play on the Sampler output.
- Four sets of five pads: page 1 or 2, bank A or B (20 slots in total).
- "Hardware pads" switch: runs a small listener (systemd user service) so the physical pads
  trigger the samples. Pressing a pad again restarts its sound.

## Install

```bash
omarchy plugin validate ~/Projects/omarchy-mgame-mixer
omarchy plugin add ~/Projects/omarchy-mgame-mixer --enable
```

Requires `python3`, `pactl` (pipewire-pulse), `pw-play`, `pw-cli`, `pw-dump`, `aseqdump`,
and for the mic chain `lsp-plugins-ladspa` and `noise-suppression-for-voice`
(`librnnoise_ladspa`). The EQ uses PipeWire's built-in filters.

### First run

When the virtual channels do not exist yet, the panel shows a notice with a button.
It writes these files and restarts `pipewire pipewire-pulse wireplumber`:

- `~/.config/pipewire/pipewire.conf.d/50-mgame-split.conf` — 4 sinks + 4 sources
- `~/.config/pipewire/pipewire.conf.d/51-mgame-mic.conf` — mic chain

**Restarting audio cuts all sound for a few seconds, games included.** Copies of both files
with the default settings live in `pipewire/`.

## Channel pairs

The 8-channel mapping below comes from the community. Each pair is a widget setting
(`outGame`, `outChat`, `outSampler`, `outSystem`, `inStream`, `inAlt`, `inChat`,
`inSampler`) in case your unit differs. Options: `FL FR`, `FC LFE`, `RL RR`, `SL SR`.

On one RGB Dual (USB 0763:0042, Stream port) the four outputs were confirmed by ear,
and the mic showed up on Stream (ch 1-2) and Alt (ch 3-4) only. Chat in and Sampler in
were silent during that test, so those two capture pairs are still unconfirmed.

| Output | Pair | Input | Pair |
|---|---|---|---|
| Game | `FL FR` (ch 1-2) | Stream | `FL FR` (ch 1-2) |
| Chat | `FC LFE` (ch 3-4) | Alt | `FC LFE` (ch 3-4) |
| Sampler | `RL RR` (ch 5-6) | Chat in | `RL RR` (ch 5-6) |
| System | `SL SR` (ch 7-8) | Sampler in | `SL SR` (ch 7-8) |

After changing a pair, open the panel and press **Apply channels and restart audio**.

Check the outputs by ear. It announces each channel in turn:

```bash
speaker-test -c 8 -t wav -l 1
```

For the inputs, record from each virtual source (for example
`pw-record --target mgame_in_alt /tmp/alt.wav`) while speaking into the mic you want to test.
The capture channels 3-6 may be in a different order than the outputs.

## Hardware pads and buttons

The device sends proprietary SysEx messages on its ALSA sequencer port. The listener
(`mgame.py listen`) finds that port by client name (`M-Game RGB Dual Streaming Port`),
since the client number changes between boots.

- `pads.json` — the press message of each pad, matched by prefix (`??` = any byte).
- `buttons.json` — latching buttons: five mute buttons, sample page 1/2 and bank switch.
  Messages for `fx_param` and the undecoded preset dumps are ignored.

Both files ship in the repo and are copied to `~/.config/mgame-mixer/` on first run, where you
can edit them. The listener reads them as messages arrive. Every SysEx message it sees is
logged to `~/.local/state/mgame-mixer/sysex.log` (capped at 100 KB).

Hardware buttons are latching and the device never reports its state at startup, so the
listener shows each button as **unknown** until the first press after it starts. The mute
indicators are read-only: the plugin does not change PipeWire volumes from them.
Page and bank choose which of the four pad sets is active. Until you press a page or
bank button the plugin assumes page 1, bank A (bank "on" is B).

The service unit is written to `~/.config/systemd/user/mgame-mixer-pads.service` when you turn
on the switch, and removed from autostart when you turn it off.

## Files

| File | Purpose |
|---|---|
| `manifest.json`, `BarWidget.qml`, `Panel.qml` | The plugin |
| `mgame.py` | Helper: status, volume, routing, config generation, mic chain, sampler, listener |
| `pads.json`, `buttons.json` | Hardware message maps |
| `pipewire/` | Default PipeWire configs |
| `i18n/` | English and Spanish strings |

State lives in `~/.config/mgame-mixer/state.json` (mic preset, sample assignments).
The helper only runs `pactl`, `pw-play`, `pw-cli`, `pw-dump`, `aseqdump`, `pkill`
and `systemctl --user`, always as argument lists, with every value checked against a fixed list.

## License

MIT
