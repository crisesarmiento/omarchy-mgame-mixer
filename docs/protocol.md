# M-Game RGB Dual host protocol

Observed from the Mac control panel 1.1.1.15864 (`Panel` Mach-O, x86_64 slice).
The bytes `F0 00 01 05 42` are built at runtime in `DeviceValue`; they are not a string in the binary.

The layout comes from the official app. The checksum and the pad-1 messages were checked against a live `aseqdump` of port `16:0` on this unit. Do not send unsolicited sets until a param id is identified.

## SysEx layout

Manufacturer header, always:

```
F0 00 01 05 42
```

`DeviceValue::CreateMIGxSetMessage` and `CreateMIGxGetMessage` then differ.

### Set / device event (byte 5 = 0x00)

```
F0 00 01 05 42 00 <N> <param_id:4 LE> <value:4 LE> × N <checksum> F7
```

Length is `13 + 4*N`. `N` is byte 6.

`MidiMessageToParamValue` reads the same layout: byte 6 is the count of `uint32` values, the param id is the 4 bytes at offset 7, and value `i` is the 4 bytes at offset `11 + 4*i`.

### Get (byte 5 = 0x02)

```
F0 00 01 05 42 02 <sub> <param_id:4 LE> <checksum> F7
```

Length is 13. `sub` is the trailing `char` argument of `CreateMIGxGetMessage`.

`ValidateMidiMessage` has no third layout. Byte 5 `< 2` must be the set form (`13 + 4*N`, `N` = byte 6). Byte 5 `>= 2` must be 13 bytes. `MidiMessageToParamValue` then reads byte 6 as a value count and the `uint32`s at offset 11. A reply this host can turn into values is the set form. The device has not been observed answering a get.

`ValidateMidiMessage` accepts byte 5 `< 2` as the long form and byte 5 `>= 2` as the 13-byte form.

## Checksum

From `DeviceValue::ValidateMidiMessage`, and it matches the four live packets below.

- Sum every byte after `F0` and before the checksum byte, as a wrapping signed 8-bit add.
- Checksum byte is `(-sum) & 0x7F`.
- `F7` is not included in the sum. A length mismatch or a bad checksum returns `0x80000008`.

## Controls, captured on this unit

State param is `0x01020100 + id`. LED echo is `0x01020200 + id` with the same value. Pads are momentary (1 press, 0 release). The other buttons latch. Page 2 forced page 1 back to 0, so the two page buttons are exclusive.

| Control | State param | LED param | Activity bit |
| --- | --- | --- | --- |
| FX param | `0x01020100` | `0x01020200` | not isolated |
| Mic mute | `0x01020102` | `0x01020202` | `0x02` |
| Game mute | `0x01020106` | `0x01020206` | `0x08` |
| Chat mute | `0x01020108` | `0x01020208` | `0x10` |
| Sampler mute | `0x0102010A` | `0x0102020A` | `0x20` |
| Main/Alt mute | `0x0102010C` | `0x0102020C` | `0x40` |
| Sample page 1 | `0x0102010E` | `0x0102020E` | `0x100` |
| Bank | `0x01020110` | `0x01020210` | not isolated |
| Sample page 2 | `0x01020112` | `0x01020212` | `0x400` |
| Pad 1..5 | `0x01020114` + 2×(n-1) | not captured | `0x800`, `0x1000`, `0x2000`, `0x4000`, `0x10000` |

Mic mute also emits companion param `0x01020130` / LED `0x01020230`. The activity bit rides on param `0x00020000` and clears back to `0x00020000`; it is not the latch. Ignore it for routing.

Mute presses also sent param `0x44020000`, `N = 2`. Each press added a bit in the first six payload bytes and left the last two at `0x01`: mic `0x01`, game `0x02`, chat `0x04`, sampler `0x10`, main/alt `0x28`. That is why value 1 is treated as muted for this pass. Main/Alt adding `0x28` is two bits (`0x08` and `0x20`), which fits one button covering both outputs. Not sent back to the device.

Changing sample page also pushed undecoded preset blocks: param `0x5F000000` carried 1 then 2, matching the page, plus blobs on `0x41000000` (`N = 11`), `0x41040000`, `0x41070000` (`N = 6`), `0x41080000` and `0x01040300`. Those blobs are not parsed.

## Routing preset file

`Default.MGameRGBDualRouting` is a property stream, not SysEx.

- 12-byte preamble `08 00 00 00 00 00 00 00 00 00 00 00`
- then 72 records of 40 bytes, property indices 4..75
- each value is `0` or `115` (`0x73`)
- `Default - No Chat to Stream` differs only at index 8: `115` vs `0`

Index 8 is Chat-to-Stream. The other indices are not a flat list of icon names. `LRoutingChanelPanel::OnHeadphoneCueButtonValueChanged` classifies a property id into the mixer enum, then passes that enum to `GetMixerFriendlyName`. The test is unsigned `(id - base) <= 11`:

| Enum | Destination | Property ids |
| --- | --- | --- |
| 0 | Stream | 4..15 |
| 1 | Chat | 16..27 |
| 2 | Alt | 28..39 |
| 3 | Sampler | 40..51 |
| 4 | Main Out | 52..63 |
| 5 | Headphone Out | 64..75 |

That accounts for all 72 indices. Each destination owns 12 properties, not 6.

Inside a destination block the headphone-cue path writes six mirror ids, starting at the block base and stepping by 2 (`0x40`, `0x42`, `0x44`, `0x46`, `0x48`, `0x4A` for phones). So the even offsets are the six source slots. The odd offsets are the remembered value of that gain. `LMixerGainControl::SetRememberedValue` (`0x10043458e`) reads the even id at control `+0x64c`, adds 1, and sends that id through `vtable+0x3b0`. Both stock presets store `115` (`0x73`) in every odd slot, the same default `GetParamValueDefault` returns for local 1. That value is not sent to the device.

Source names for the even offsets are the slot index `n % 6`, not a guess from the file. `LRoutingView::GetMixerGain` (`0x1004cd548`) splits that same `n`: `n / 6` picks the destination panel, `n % 6` indexes `childPanelNames`. The table is filled at `0x1004cd697` in this order: `micMixerGainControl`, `gameMixerGainControl`, `chatMixerGainControl`, `auxMixerGainControl`, `samplerMixerGainControl`, `systemMixerGainControl`. The call then `GetChild`s that name and returns it as `IMixerGain`. `CopyMixerTo` still does not name its loop; this is the other xref.

`Application.dsc` binds each of those controls to a `SourceToDest` skin (`MicToStream`, `GameToStream`, `ChatToStream`, `AuxToStream`, `SamplerToStream`, `SystemToStream`, and the same six sources on the other destinations). On-screen sibling order is not the slot order: aux is last in the skin. The index is the code table.

| Offset in the block | Source | Stream | Chat | Alt | Sampler | Main Out | Phones |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | mic | 4 | 16 | 28 | 40 | 52 | 64 |
| 2 | game | 6 | 18 | 30 | 42 | 54 | 66 |
| 4 | chat | 8 | 20 | 32 | 44 | 56 | 68 |
| 6 | aux | 10 | 22 | 34 | 46 | 58 | 70 |
| 8 | sampler | 12 | 24 | 36 | 48 | 60 | 72 |
| 10 | system | 14 | 26 | 38 | 50 | 62 | 74 |

`115` is on, `0` is off. Stock Default, under that map: Stream, Sampler, and Phones enable all six sources. Chat enables only mic. Alt enables mic and sampler. Main Out enables every source except mic. `Default - No Chat to Stream` only clears property 8.

## What the panel binary names

`LRoutingView::GetMixerGain` indexes `childPanelNames[n % 6]` and returns that child as `IMixerGain`. The strings are UI child ids, not MIDI param ids. The slot order is the index into that table, documented above.

`LRoutingChanelPanel::GetMixerFriendlyName` is a jump table on the mixer enum, not a string list in memory order. Enum 0 Stream, 1 Chat, 2 Alt, 3 Sampler, 4 Main Out, 5 Headphone Out. The routing-file blocks above use that enum.

`LMGameRootModule::GetModuleForDeviceIndepentParam` (`0x100307aa2`..`0x10030b8ea` in the x86_64 slice) is a comparison tree on the device param id. Each named row below is a path that ends in `RCPtr::operator=` to that interface. This is host dispatch, not a capture of the device accepting the id.

Button event ids `0x01020100`..`0x01020112` (FX, the five mutes, both sample pages, Bank) do not reach a module here. They stay button events. Do not reuse them as fader or route ids.

| Module | Param ids |
| --- | --- |
| `ISampleButtonSampleSettings` | `0x01020114` + {0,2,4,6,8,10,12,14,16,18}. Physical pads are the first five. |
| `IFootSwitch` | `0x0102012C`, `0x0102012E`, `0x01040018`, `0x0104001C` |
| `IMute` | `0x01040008`, `0x0104000C`, `0x01040010`, `0x01040014`. Four slots, not the five hardware mute buttons. |
| `ISwearAndMuteAllSampleSettings` | `0x01020202`, `0x01020204`, `0x01040000`, `0x01040004` |
| `IMixerGain` | `0x44000000` + `0x100`×group + {0,2,4,6,8,10}, group 0..5. 36 slots. |
| `IEffectiveVolume` | same shape at `0x44010000`, group 0..5. 36 slots. |
| `IMutedStatus` | `0x44020000`. This is the aggregate mute word captured live (`N = 2`). |
| `ICompLimiter` | `0x45000000` |
| `IEffects` | `0x41000000`, then `0x41010000` + `0x100`×0..8. Ten exact ids, not a base. Page changes pushed blobs on several of these. |
| `IFader` | `0x01000000` + `0x100`×0..6 |
| `ILEDArray` | `0x01010000` + `0x100`×0..8 |
| `IToneControl` | `0x40000004`, and `0x43000000`..`0x43000002` |
| `IMixer` | `0x40000002` |
| `IGlobalSettings` | `0x01050000`, `0x40000006` |
| `IMic` | `0x00030000` |
| `IDevice` | `0x01020002`, `0x01020004` |
| `IFootSwitches` | `0x01020000` |
| `IPreset` | any id whose top bits match `id & 0xFFE00000 == 0x50000000`. The function accepts that whole window. Which of those ids the device uses is not known. |

`IMixerGain` / `IEffectiveVolume` slot index is `(id & 0xFF) >> 1`, and the group is `(id - base) >> 8`. Six groups by six even slots.

`LMixerGain::TranslateModuleParamValueToDeviceParamValue` builds the device id from the child index stored at `LMixerGain+0x18`. `IMixer::SetFirstParamID` writes that index as `0..35` while creating 36 gain children. The arithmetic is `0x44000000 + (n / 6) * 0x100 + (n % 6) * 2`.

`LRoutingChanelPanel::CopyMixerTo` names the axes. It reads `LRoutingChanelPanel::Mixer` and, when the enum is `< 6`, stores `enum * 6` as the fader index base, then calls `SetFaderToMixerInputEnabled` with `n = base + loopIndex`. That function passes `n / 6` as `DeviceValue::Mixer` and `n % 6` as the input bit. The headphone cue handler uses the same formula with base `30` (`5 * 6`). So `n / 6` is the destination and `n % 6` is the source slot:

| `n / 6` | Destination |
| --- | --- |
| 0 | Stream |
| 1 | Chat |
| 2 | Alt |
| 3 | Sampler |
| 4 | Main Out |
| 5 | Headphone Out |

MIDI id: `0x44000000 + dest * 0x100 + sourceSlot * 2`. Do not send it. Source slot `0..5` is mic, game, chat, aux, sampler, system, from `GetMixerGain`'s `childPanelNames[n % 6]`. A routing-file property index is not this MIDI id. The same function also computes the file block base `enum * 12 + 4`, which matches the destination blocks above.

`SetFaderToMixerInputEnabled` (`0x100435840`) passes `n % 6` unchanged as `MixerInputConfigurationBit`. For slots 3, 4 and 5 it remaps only the hardware fader index (`3 → 4`, `4 → 3`, `5 → 4`, table at `0x100e7d598`) before `SetFaderInputToMixer`. That remap is not a source rename.

A second set of exact ids is dispatched through `IRootModule::GetModule(localIndex)` (vtable slot 1, `callq *0x8`) inside `GetModuleForDeviceIndepentParam`. The call stores a `LParameterizedModule`. The interface is not named there. `localIndex = firstParamID + offset`:

| Device id | Offset |
| --- | --- |
| `0x01030000` | `0x105` |
| `0x01030100` | `0xF4` |
| `0x01030200` | `0xF9` |
| `0x01030300` | `0xCA` |
| `0x01030400` | `0xCD` |
| `0x01030500` | `0xD0` |
| `0x01030600` | `0xD3` |
| `0x01030700` | `0xD6` |
| `0x01030800` | `0x106` |
| `0x01030900` | `0xDA` |
| `0x01030C00` | `0x88` |
| `0x01030D00` | `0x90` |
| `0x01030E00` | `0x98` |
| `0x01030F00` | `0xA0` |
| `0x01031000` | `0xA8` |
| `0x01031100` | `0xB0` |
| `0x01031200` | `0xB8` |
| `0x01031300` | `0xC0` |
| `0x01031400` | `0xDE` |
| `0x01031500` | `0xE2` |
| `0x01031600` | `0x107` |
| `0x01031700` | `0x108` |
| `0x01031800` | `0x109` |
| `0x01031900` | `0x10A` |
| `0x01031A00` | `0x10B` |
| `0x01031B00` | `0x10C` |
| `0x01031C00` | `0x10D` |
| `0x01031D00` | `0x10E` |
| `0x01031E00` | `0x10F` |
| `0x01031F00` | `0x110` |
| `0x01032000` | `0x111` |
| `0x01040100` | `0xD4` |
| `0x01040102` | `0xD8` |
| `0x01040108` | `0xDC` |
| `0x0104010A` | `0xE0` |

`0x01030A00` and `0x01030B00` are not handled.

Root `firstParamID` is 0. `LApplication::RunApplicationStartup` (`0x100458de1`) calls `LAppEngine::Initialize` with `esi = 0`. That value is forwarded to `LRootModule::Initialize` as `r9d`, and that function passes it as `edx` to `SetFirstParamID`. `deviceFirst` is already 0, so `localIndex` equals the offset.

`IDevice::GetModule` then selects:

| Offset | Selected interface |
| --- | --- |
| `0x88`, `0x90`, `0x98`, `0xA0`, `0xA8`, `0xB0`, `0xB8`, `0xC0` | `ISamples` |
| `0xCA`, `0xCD`, `0xD0`, `0xD3` | `IMuteButtons` |
| `0xD4`, `0xD6`, `0xD8`, `0xDA`, `0xDC`, `0xDE`, `0xE0`, `0xE2` | `IVoiceEffects` |
| `0xF4`, `0xF9` | `ISwearAndMuteAllButtons` |
| `0x105`, `0x106`, `0x107`..`0x111` | `ILEDs` |

`IMuteButtons::SetFirstParamID` (`0x1003a60f0`) assigns four `IMute` children, first ids `0xC8`, `0xCB`, `0xCE` and `0xD1`. Offsets `0xCA`, `0xCD`, `0xD0` and `0xD3` are local relative 2 of those children. `IMute::GetModule` (`0x1006191d4`) returns the `IMute` itself when the relative is 1 or 2. Relative 0 forwards through `vtable+0x88`. Those four offsets are the `IMute` object, not a further child.

`ISamples::SetFirstParamID` (`0x100577a68`) assigns an `ISample` whose first id is `samplesFirst + 8*index`. The eight sample offsets are relative 0 of that `ISample`. `APP_ENGINE::LSample::InitModule` (`0x1005a8726`) creates `APP_ENGINE::LButtonLEDSettings` and stores it at `LSample+0x20`. `ISample::GetModule` (`0x1005a81c0`) forwards relative 0 through `vtable+0x88` (`GetButtonLedSettings`). That child's `vtable+0x8` is `LParameterizedModule::GetModule` (`0x100249d10`), which stores `this` and ignores the id. Those eight offsets are `APP_ENGINE::LButtonLEDSettings`. Relative 7 still forwards through `vtable+0xa8`, and relatives 1..6 through `vtable+0x98`. Those are not the table offsets.

`IVoiceEffects::GetModule` (`0x100527990`) uses `relative >> 2` as the `IEffect` index. Offsets `0xD6`, `0xDA`, `0xDE` and `0xE2` are relative 2 of that `IEffect`. `IEffect::GetModule` (`0x1005269c4`) forwards relative 2 through `vtable+0x88`. `APP_ENGINE::LEffect::InitModule` (`0x1006a97f8`) creates `APP_ENGINE::LButtonLEDSettings` and stores it at `LEffect+0x20`. That child's `vtable+0x8` returns `this`. Those four offsets are the same class. Offsets `0xD4`, `0xD8`, `0xDC` and `0xE0` are relative 0 and forward through `vtable+0x98`. `InitModule` creates `APP_ENGINE::LUnassignedLEDSettings` at `LEffect+0x28`. Its vtable at file `0xf602d0` has slot `+0x8` equal to the same `LParameterizedModule::GetModule`. Those four offsets are `APP_ENGINE::LUnassignedLEDSettings`.

## Mic effect preset ids

The seven `*.MGameRGBDualMicEffects` files are the same property stream, 492 bytes, six size-prefixed records. The id is the `uint32` at offset 8 of each record. Five of those ids are the immediates `LMicSettingsPanel::Send*ParamToEngine` writes into the descriptor before the `vtable+0x3b0` send. Each of those functions first calls the matching `GetAsVariant`. The load side is `SetParamValueEffects`: it decrements `IEffects::Param` and jumps. That enum is not the file id.

| File id | Bytes | `Send*` immediate | Class | `IEffects::Param` |
| --- | --- | --- | --- | --- |
| `0x122` | 72 | `SendHighPassFiltersParamToEngine` (`0x10019dab0`) | `MA::MicHighPassFilters` | 1 |
| `0x123` | 40 | `SendNoiseGateParamToEngine` (`0x10019d770`) | `MA::MicNoiseGate` | 2 |
| `0x126` | 136 | `SendEQParamToEngine` (`0x10019d37c`) | `MA::Mic5BandPEQ` | 5 |
| `0x127` | 136 | `SendDeEsserParamToEngine` (`0x10019ecb0`) | `MA::MicDeEsser` | 6 |
| `0x128` | 56 | `SendCompressorParamToEngine` (`0x10019d57c`) | `MA::MicCompressor` | 7 |

`IEffects::Param` 3 and 4 fall through to the default at `0x10019e702`. These classes are host-side. They are not proof of on-device DSP.

Record id `2` is phantom power. It is `LMic`'s only local param. `IDevice::SetFirstParamID` (`0x100018e08`) assigns `GetMic` the id `deviceFirst + 2`. Mixer first is 3, so `deviceFirst` is 0 and this id is 2. `LMic::MemberData::TranslateModuleParamValueToDeviceParamValue` (`0x1000c74c6`) maps that id to `MidiParamID` `0x30000`. Do not send it. The preset value is a type-7 scalar, default 0. It is 1 in the AT2020 and Nova presets and 0 in the others.

The UI object is `panelEffectsOverview`. `RegisterControlClasses` (`0x10045aa02`) binds `MIG2.Panel.SetupView.EffectsOverview` to `Create<LMicSettingsPanel>`. `LDeviceView::GetMic` returns that child as `IMic`. The `IMic` base sits at panel `+0x638` (`__offset_flags` `0x63802`). Its `firstParamID` is panel `+0x64c`. `OnPhantomPowerButtonValueChanged` (`0x10019b95a`) and `SetParamValueLocal` (`0x10019dbee`) use that field for the phantom button, 0 or 1. `ICompLimiter` at `0x45000000` is the on-device limiter, separate from this param.

Offsets `0xF4` and `0xF9` are `APP_ENGINE::LButtonLEDSettings`. `ISpecialButton::GetModule` (`0x100527408`) forwards relative 0 through `vtable+0x88`, and `APP_ENGINE::LSpecialButton::InitModule` (`0x100257848`) stores that class at `+0x20`. The child's `vtable+0x8` returns `this`.

`ILEDs::SetFirstParamID` (`0x10014426a`) assigns `vtable+0x88` to `ILEDLabel` with first id `ledsFirst + index`, for index `0`..`0xC`. LEDs first is `0x105`, so offsets `0x105`..`0x111` are relative 0 of those labels. `ILEDs::GetModule` (`0x100146628`) saves the original id in `r12d`, and for relative `< 0x0d` calls `vtable+0x88` with the relative, then the child's `vtable+0x8` with `r12d`. `ILEDLabel::GetModule` (`0x100526f58`) handles only `edx == first` and forwards through `vtable+0x88`. `APP_ENGINE::LLEDLabel::InitModule` (`0x10075fa2e`) creates `APP_ENGINE::LButtonLEDSettings` at `+0x20`. That child's `vtable+0x8` returns `this`. Those thirteen offsets are `APP_ENGINE::LButtonLEDSettings`.


# Reverse-engineering pass 2: connect, encodings, LEDs, voice FX, samples, danger list

Tags: **[O]** observed (log or file), **[I]** inferred from disassembly, **[U]** unknown. Addresses are the x86_64 slice (`~/.cache/mgame-re/Panel.x86`, thinned with `llvm-lipo`, disassembled with `llvm-objdump -d --demangle`).

## Frame facts that change the earlier text

- Byte 6 is **N for both set and get**. `DeviceValue::MakeMidiDescriptor(Variant&, MidiParamID, signed char)` (`0x100187c08`) builds a descriptor `{type 0xFFFFFF12, [uint32 param, int8 N]}` for every module param. `ParamDescriptorToGetMessage` (`0x10081d1a4`) reads element 0 as the param id and element 1 as that `char`, then calls `CreateMIGxGetMessage(param, N)`. So the "`sub`" byte of a Get is the number of `uint32` the host expects back. [I]
- `CreateMIGxSetMessage` (`0x10082110a`) writes byte 5 = **0** always (`xorl %r14d` at `0x10082115f`, stored at `0x100821162` and `0x1008211a2`). Hosts only ever send byte 5 = 0 (set) or 2 (get). [O]
- Byte 5 = **1** frames exist in `sysex.log` (burst at 00:49:31: ten frames on `0x41000000`/`0x41000001`, N = 10/11). The Panel never writes it. Treat as device-originated, possibly replies to a get. [O] who triggered them is unknown. [U]
- Param id and value bytes are stored with a plain 8-bit shift loop, **no masking** (`0x100820ee6`..`0x100820f21`). All captured bytes are `<= 0x7F`. The encoder does not enforce it, so a byte `>= 0x80` would corrupt the SysEx. Keep every byte of every id and value `<= 0x7F` (28-bit-ish values per word in practice). [I]
- `ValidateMidiMessage` does not look at bytes after the length/checksum, so the host will accept any byte 5 `< 2` as the long form. [I]

## Q1. Connection handshake and state read

There is **no identity request, no "dump all" and no firmware query** in the Panel. `0xF0 0x7E` is not built anywhere (the only `movb $0x7e` is an audio LUT at `0x1002fc297`). The device is driven purely by per-param Gets. [I]

Callers of the get path (`LAppEngine::RequestParamValueDevice`, `0x1002fd5fa`, → `LDeviceCommunicationBase::RequestParamValue` `0x10081d056` → `CreateMIGxGetMessage` `0x100820dcc`):

| Trigger | Function / call site | Param, N | Frame |
| --- | --- | --- | --- |
| Device connected (state == 3) | `LAppEngine::OnDeviceConnectionStateChange` `0x1002fb046`, call `0x1002fb101` | `0x01020200`, N=1 | `F0 00 01 05 42 02 01 00 02 02 01 30 F7` |
| Bank selector built | `LBankSelectorPanel::Initialize`, `0x1003e23b1`; also `SetDeviceBankButtonEngagementState` | `0x01020210`, N=1 | `F0 00 01 05 42 02 01 10 02 02 01 20 F7` |
| Main window acquired | `LHomeView::ProcessRootWindowAquired`, `OnVoiceFXKnobParamAssignmentChanged` `0x10020f450`, `OnHeadphoneFunctionEngagementStateChanged` `0x10020fd4f` | `0x01040300`, N=4 | `F0 00 01 05 42 02 04 00 03 04 01 2A F7` |
| Sampler view init | `LSamplerView::Initialize` (`0x1005728ad`), `SetDeviceSampleButtonFunctionEngagementState` | id computed, N=1 (likely `0x01020114 + 2i`) | not resolved [U] |
| Per module on `UpdateFromHardwareState` | every `APP_ENGINE::L*::MemberData::GetModuleValuesFromDevice` (e.g. `LMixerGain` `0x5eefe0`) | each module's own id and N from its `TranslateModuleParamValueToDeviceParamValue` | see table below [I] |

After the first get the app calls `OpenAudioDevice` (`0x1002fc43c`). The app then relies on the device echoing events (the `0x0102xx00`, `0x00020000`, `0x44020000` traffic in the log).

`LMGameRootModule::OnHardwareReset` (`0x10030778a`) is the **host-side** "push my state to the device" path. It is not a message. It sets `0x01030A00 + 0x100*k` (k = 0..7, N=1, one per sample pad, "unassigned pad LED") through `SetParamValueDevice` (`0x1002fddca`). [I]

### N (value count) per device param, read from the Translate functions

| Device param | N | Module (`APP_ENGINE::L*`) | Notes |
| --- | --- | --- | --- |
| `0x44000000 + 0x100*dest + 2*src` | 1 | `LMixerGain` | 36 params |
| `0x44010000 + same` | 1 | `LEffectiveVolume` | 36 params |
| `0x44020000` | 2 | `LMutedStatus` | |
| `0x45000000` | 2 | `LCompLimiter` | default `[0,0]` |
| `0x43000000` | 3 | `LToneControl` | default `[0,0,0]`-like |
| `0x40000004` | 1 | `LToneControl` | default 1 |
| `0x40000002` | 1 | `LMixer` | |
| `0x01050000`, `0x40000006` | 1 | `LGlobalSettings` | |
| `0x01000000 + 0x100*k`, k=0..6 | 2 | `LFader` | |
| `0x01010000 + 0x100*k`, k=0..8 | 4 | `LLEDArray` | local id `0x112..0x11A` |
| `0x01030000 + 0x100*k` | 3 | `LButtonLEDSettings` | see Q3 |
| `0x00030000` | 1 | `LMic` | phantom |
| `0x01020114 + 2*i` | 1 | `LSampleButtonSampleSettings` | pads |
| `0x01020202`/`04`, `0x01040000`/`04` | 1 / 2 | `LSwearAndMuteAllSampleSettings` | |
| `0x01020002`, `0x01020004` | 1 | `LDevice` | meaning unknown [U] |
| `0x0102012C`, `0x0102012E` (N=1), `0x01040018`, `0x0104001C` (N=2) | 1/2 | `LFootSwitch` | |
| `0x01040008`..`0x01040014`, `0x01020206` | 2 / 1 | `LMute` | |
| `0x01020228`, `0x01020212`, `0x0102020E`, `0x0102022A`, `0x01040100`, `0x01040102`, `0x01040108`, `0x0104010A` | 1 | `LEffect` | voice-FX button LED/state |
| `0x41000000` N=11, `0x41040000`, `0x41070000` N=6, `0x41080000`, `0x41010000` N=3, `0x41030000` N=1, `0x41060000` N=2, `0x41090000` N=7 | | `LEffects` | `0x41040000`, `0x41080000`: N=1 in log. `0x41020000`, `0x41050000` N unknown [U] |
| `0x01040300` | 4 | `LVoiceFXEditor` | knob assignment |
| `0x50000000 + (a<<4) + (b<<16)` | 16 | `LPreset` | **do not send**, see Q6 |
| `0x42000000 + 2*k` | 1 | `LMIGxLevelMeter` | meters, k up to `0x16`; read-only [I] |

### Reply format

Replies are not captured for a host Get. `LDeviceCommunicationBase` routes any received frame through `MidiMessageToParamValue` (`0x10081e5af`), which only understands the set form (byte 5 `< 2`, N, id, N words). So a reply to a Get must be a set-form frame carrying that param. [I] The live log shows no get/reply pair, so this is untested. [U]

### Reading button latch, mute vector, routing, LEDs

- Latches: Get `0x01020100 + id` (and echo `0x01020200 + id`), N=1, for the ids in the controls table above. The app itself only reads `0x01020200` and `0x01020210`, so per-button Gets are unproven. [U]
- Mute vector: Get `0x44020000` N=2. Frame in Safe table. Layout in Q2.
- Routing gains: Get each `0x44000000 + 0x100*dest + 2*src` N=1 (36 frames) [I]. The device also pushes them on page change in the log.
- LED colours: Get `0x01030000 + 0x100*k` N=3 per button, `0x01010000 + 0x100*k` N=4 per array [I].

## Q2. Value encodings of host SETs

All of these pass the module value straight into the frame. `LMixerGain::TranslateModuleParamValueToDeviceParamValue` (`0x1005ee696`) copies the variant bytes unchanged. Same for `LEffectiveVolume` (`0x1001dc986`), `LMic` (`0x1000c74c6`), `LMixer`, `LGlobalSettings`, `LCompLimiter` (`0x1004dc87a`), `LToneControl` (`0x10033f518`). [I]

| Param | Value layout | Evidence |
| --- | --- | --- |
| `IMixerGain` `0x44000000 + 0x100*dest + 2*src` | one `uint32`. `115` (`0x73`) is the default (`GetParamValueDefault` `0x1005ef310`, writes `0x73` for all 36). `0` is off. Routing preset files use only `0` and `115`. Max is not found in the binary or in `Application.dsc` (`createParams` has no ranges). Keep within `0..0x7F`. | [I]/[U] max |
| `IEffectiveVolume` `0x44010000` + same | one `uint32`, default `115` (`0x1001dd4dc`). Likely the device-reported gain after fader/route effects. | [I] |
| `IMutedStatus` `0x44020000` | N=2, i.e. 8 bytes: six bytes then two. Each of the first six bytes is a source bitmask, one byte per destination (Stream, Chat, Alt, Sampler, Main, Phones) with bit0..5 = mic, game, chat, aux, sampler, system, **1 = muted**. Last two bytes carry bit0 (mic) only. Log: `01 01 01 01 01 01 01 01` (mic muted), `03 03 03 03 03 03 01 01` (mic+game), then unmuting in order `3E x6 00 00` → `3C` → `38` → `28` → `00` (the 00:49:17..00:50:19 sequence). Device→host only in all captures. Host writes are possible (`LMutedStatus` Translate, N=2) but unverified. | [O] layout, [U] host write |
| `IFader` `0x01000000 + 0x100*k`, N=2 | packed bytes. Default per fader (`0x10031db86`): `0x01010101 / 0x01`, `0x28282828 / 0x28`, `0x04040404 / 0x04`, `0x02020202 / 0x02`. These look like per-destination input bitmasks (`SetFaderInputToMixer`), not levels. | [I] |
| `ICompLimiter` `0x45000000`, N=2 | `[0, 0]` default. Field meaning unknown. | [U] |
| `IToneControl` `0x43000000` N=3, `0x40000004` N=1 (default 1) | meaning unknown. | [U] |
| `IGlobalSettings` `0x01050000` / `0x40000006`, N=1 | meaning unknown. | [U] |
| Phantom `0x00030000`, N=1 | `0`/`1`. `LMic` has a single local param (id 2 → `0x30000`), preset value type-7 scalar default 0. | [I] |
| Mute buttons | host does **not** write the mute latch. The device owns it: press → `0x01020100+id` = 1/0, LED echo `0x01020200+id`, then `0x44020000`. `LMute` (N=2 `0x01040008`..) and `LSwearAndMuteAllSampleSettings` (`0x01020202`/`04`, `0x01040000`/`04`) configure what a mute button does. | [O]/[I] |
| Footswitch `0x0102012C/E`, `0x01040018`, `0x0104001C` (N=2) | meaning unknown. | [U] |

The `0x00020000` word is an "activity bit" register (bits listed in the controls table). It is device→host only. [O]

## Q3. LEDs / RGB

### Device params

`APP_ENGINE::LButtonLEDSettings::...::TranslateModuleParamValueToDeviceParamValue` (`0x1002479d2`) maps the local id to `0x01030000 + 0x100*k`, **N=3**. `r14d = this.id - root.id`; compare tree and two jump tables at `0x100247f18`/`0x100247f40`:

| Local id | Device param | Control |
| --- | --- | --- |
| `0x78` | `0x01030A00` | sample-set "unassigned" LED (page A) [I] |
| `0x80` | `0x01030B00` | same, page B [I] |
| `0x88`, `0x90`, `0x98`, `0xA0`, `0xA8`, `0xB0`, `0xB8`, `0xC0` | `0x01030C00` .. `0x01031300` step `0x100` | sample pad 1..8 button LED |
| `0xCA`, `0xCD`, `0xD0`, `0xD3` | `0x01030300`, `0x01030400`, `0x01030500`, `0x01030600` | mute buttons 1..4 |
| `0xD6`, `0xDA`, `0xDE`, `0xE2` | `0x01030700`, `0x01030900`, `0x01031400`, `0x01031500` | voice-FX button LEDs |
| `0xD4`, `0xD8`, `0xDC`, `0xE0` | not handled by this function (unassigned LED settings) | |
| `0xF4`, `0xF9` | `0x01030100`, `0x01030200` | special / swear-mute-all |
| `0x105` | `0x01030000` | LED label 0 |
| `0x106` | `0x01030800` | LED label 1 |
| `0x107`..`0x111` | `0x01031600` .. `0x01032000` step `0x100` | LED labels 2..12 |
| `0x11D` | none (returns `0xFFFFFFFF`, ignored) | |

Arrays: `LLEDArray` (`0x10066a833`..): `0x01010000 + ((id-0x112) << 8)` for `id-0x112 < 9`, **N=4**.

Mapping of pad `n` (1..5) to a pad LED: pad n = sample `n-1` → `0x01030C00 + 0x100*(n-1)`. [I] for the id, [U] whether physical pad n is sample n-1.

### `*.MGameRGBDualLEDs` format [O]

Little-endian `uint32` property stream (same container as Routing/VoiceFX/MicEffects/Samples): 12-byte preamble `08 00 00 00 00 00 00 00 00 00 00 00`, then records. Record = `size` (bytes, includes itself), `0`, `local id`, `inner bytes`, then the values as `[16][1][7][value]` triples, the first prefixed `[1][16]`. So value `i` is the `uint32` after the `7` type tag. All preset files have 64 records (55 of 72 bytes = 3 values, 9 of 88 bytes = 4 values), in this local-id order:

`120 127 128 135 136 143 144 151 152 159 160 167 168 175 176 183 184 191 192 199 214 215 218 219 222 223 226 227 230 231 234 235 238 239 242 243 202 205 208 211 244 249 261..282`

Ids 261..273 (`0x105..0x111`) are the 13 LED labels, 274..282 (`0x112..0x11A`) the 9 LED arrays. Ids `120 + 8*k + {0,7}` are the paired "LED + unassigned" entries of the sample slots. The pair `(…, 127)` is the unassigned twin of the button. Only the first (id `120 + 8k`) maps to a device param in Translate.

**Button LED (N=3)** `[V1, V2, V3]`:

| Word | Bytes | Meaning (inferred from 9 presets) |
| --- | --- | --- |
| V1 | `b0, b1, b2, b3` | `b2` = lighting mode: 0 normal, 1 seen in Red/Pink, 2 = rainbow. `b0` = 2 on Rainbow buttons. |
| V2 | palette index | colour when active/pressed |
| V3 | palette index | idle colour, equals `V2 + 0x32` for solid colours |

Palette indices (V2): Red `2`, Orange `4`, Green `8`, Blue `0x12`, Purple `0x14`, Pink `0x17`, default also uses `0x0F`, `0x1B`, `0x2B`. V3 is `V2 + 0x32`: Red `0x34`, Orange `0x36`, Green `0x3A`, Blue `0x44`, Purple `0x46`, Pink `0x49`. Max seen `0x7C`. Brightness: [U] (no separate byte found; the 0x32 offset may be the dim bank).

Compare: `Default` vs `Red` differs in V1 `b2` (0→1) and V2/V3 only on records where Default is not red; `Blue`/`Green`/`Orange` change V2/V3 on every button record; `Rainbow` sets V1 `0x00020002` (buttons) / `0x00020000` (unassigned twins) and V3 `0x34`; `Pulse and VU-Default` adds `0x1B`/`0x2B` colours and `b2=1` on records 202/205/261.

**LED array (N=4)** `[mode, c0..c3, c4..c7, c8, c9, 0, 0]` as `uint32`s: first word is a mode word, then 10 palette bytes (one per LED of the 10-LED bar) packed into the next 2.5 words. Default: `00000000`, `40 5A 5A 5B`, `5B 5C 5C 5D`, `43 44 00 00`. Mode word seen: Default `0`, Red `2`, Blue `2`, Rainbow `0x00140003`, Pulse and VU `0x00140001`, Green `0`. UI strings `PULSE`, `RAINBOW`, `PULSE_FADER`, `RAINBOW_FADER`, `GetVUModeInputSelection`, `GetFaderModeInputSelection` (`0x1001bc88c`, `0x1001bc866`) suggest `b0` selects static/VU/fader/rainbow. Exact bit meaning [U].

### Applying a preset [I]

For each record whose local id maps in the table above: `F0 00 01 05 42 00 <N> <param LE> <values LE> cs F7`, N=3 for buttons, 4 for arrays. `LButtonLEDSettings::SendModuleValuesToDevice` (`0x1002486e6`) and `LLEDArray` do the same through the module tree. The app does not expose a separate brightness command.

## Q4. Voice effects

- `IEffects` (`LEffects`, `0x41000000` family) is **device state**. The device pushes it on page change (log), and the app writes it back: `LVoiceFXEditor::SendVoiceFXToDevice` (`0x10074057d`) sets `0x01040300` N=4. The Panel has no DSP code for the effect itself (`MA::LAudioWavePlayer` only plays samples). VoiceFXLibrary.xml / `*ProcessorPresets.xml` describe the editor UI. [I]
- Each `0x4100xxxx` block is an array of words: param `0x41000000` N=11 carries words for ids `0x41000000..0x4100000A`; `0x41040000` N=1; `0x41070000` N=6 (ids `0x41070000..05`); `0x41080000` N=1; `0x01040300` N=4 (ids `0x01040300..03`). Page-change frames in the log match these exactly (11, 1, 6, 1, 4 words). `0x41010000` N=3, `0x41030000` N=1, `0x41060000` N=2, `0x41090000` N=7 are written only when that effect type is selected. [O]
- Word layout (from the VoiceEffects file, matched to the log): `0x41000000` words, e.g. Chef effect 1: `0x00100007, 0x007F4040, 0x10340027, 0x00200000, 0x0034003F, ×4 pairs`. The log shows `07 00 10 00 | 40 40 7F 00 | 55 00 34 10 | 00 00 20 00 | 3F 00 34 00 ...` — same shape, byte `[0]` of word 2 differs per effect (`0x27` vs `0x55`). Bytes inside words are separate 7-bit parameters, not one integer. Per-byte meaning [U].
- `0x01040300` knob assignment, 4 words: `[target param id, ?, lo?, hi?]`. File (Chef 1): id `0x41000002`, then `0x01040301=0x7F`, `0x01040302=0x1D`, `0x01040303=0x31`. Log: `0x41000002, 0x7F, 0x46, 0x55`. [O] shape, [U] semantics.
- `0x5F000000` carries the page (1, 2). Do not treat as free-form. [O]

### `*.MGameRGBDualVoiceEffects` format [O]

Same property container. 248 records of 70 words, ids `307..554`. Each record holds 16 `uint32` values. 31 records × 16 = 496 words, which is one effect, so the file is 8 effects (inferred from 248 / 31; the eight-effect split is not confirmed against the UI). Concatenate the 31 records of an effect: it is a list of `(param id, value)` pairs followed by a name block:

1. `0x41000000..0x4100000A` (11 pairs), `0x41040000`, `0x41070000..05`, `0x41080000`, `0x01040300..0x01040303` (4 pairs).
2. Zero padding, then the ASCII tag `NAME` + base64 name (`T2dyZQ==` = "Ogre").

To apply an effect: group the pairs by block and send `0x41000000` N=11 (words in order), `0x41040000` N=1, `0x41070000` N=6, `0x41080000` N=1, `0x01040300` N=4. [I]

## Q5. Samples

- `*.MGameRGBDualSamples` holds only **metadata** per pad: name (e.g. "Explosion"), path to `FactorySamples.wav` (a Windows path from the authoring machine), start/end frame (`0x418AC`, `0x26E4EB`), a float gain (`1.0`), an icon file name. Types: 15 string, 7 `uint32`, 8 float. [O]
- Playback is host-side: `LAppEngine::PlaybackSample` (`0x1002fe2c0`) → `LAudioWavePlayer` → CoreAudio device. There is no symbol, id or message for audio upload, sample memory or flash in the Panel (grepped `upload|download|transfer|memory|flash` on `nm`; none relevant). Pads send only momentary `0x01020114 + 2*i` = 1/0. [O]
- Conclusion: the hardware pads do not store audio. A Linux host must play the WAV itself when it sees the pad event. [I]

## Q6. Dangerous / do not send

- **Firmware**: not in the Panel. `LAppEngine::CheckIfFirmwareUpdateIsNeeded` (`0x100300432`) and `LaunchFirmwareUpdater` (`0x100300c80`) run `../Applications/FirmwareUpdater.app/Contents/MacOS/FirmwareUpdater` through `MA::Launcher::LaunchAndWaitForCompletion`. That separate binary is not in the DMG extract and may speak bootloader SysEx. Do not emulate it. [I]
- `0x5F000000..0x5F00000F` (global/system): `0x5F000000` = page; `0x5F000002` is written with `0` in `LDeviceView::ProcessRootWindowClosing` (`0x1000129c2`); `0x5F00000A` is written with `!autosave` in `SetAutoSaveEnabled` (`0x100011041`). Persistence / flash behaviour is unknown, so never send any `0x5F0000xx`. [I]
- `0x50000000..0x501FFFFF` (`LPreset`, N=16, `id = 0x50000000 + (a<<4) + (b<<16)`, translate `0x1005c3678`): preset blob store/recall. Likely writes device flash. Never send. [I]
- `0x01020002`, `0x01020004` (`LDevice`): purpose unknown, treat as dangerous. [U]
- Anything N=16 or an unknown id. All `0x01040300`..`0x01040303` and `0x4100xxxx` writes change the live voice-FX state and may persist ("`NID_VOICEFX_STORED_TO_DEVICE`" string exists). Do not send until persistence is understood. [U]
- `LPersistentParamCache`, `AutoSave_`, `ParamStore.xml` are **host-side** files. No relation to the device. [I]

## Safe host commands

Checksum = `(-(sum of bytes after F0)) & 0x7F`, verified against a logged frame (`F0 00 01 05 42 00 01 00 00 02 00 02 00 02 00 31 F7`).

| Purpose | Frame | Confidence |
| --- | --- | --- |
| Get connect probe (what the app sends first) | `F0 00 01 05 42 02 01 00 02 02 01 30 F7` | high that the app sends it, medium that the device replies |
| Get bank state | `F0 00 01 05 42 02 01 10 02 02 01 20 F7` | medium |
| Get mute vector | `F0 00 01 05 42 02 02 00 00 02 44 6E F7` | medium |
| Get mic mute latch | `F0 00 01 05 42 02 01 02 01 02 01 2F F7` | low (the app never reads it) |
| Get gain mic→Stream | `F0 00 01 05 42 02 01 00 00 00 44 71 F7` | medium |
| Get phantom | `F0 00 01 05 42 02 01 00 00 03 00 32 F7` | medium |
| Get voice-FX knob block | `F0 00 01 05 42 02 04 00 03 04 01 2A F7` | medium |
| Get pad 1 LED | `F0 00 01 05 42 02 03 00 0C 03 01 23 F7` | low |
| Get LED array 0 | `F0 00 01 05 42 02 04 00 00 01 01 30 F7` | low |
| Set gain mic→Stream = 115 (default) | `F0 00 01 05 42 00 01 00 00 00 44 73 00 00 00 00 F7` | high for the frame, medium that the device applies it |
| Set phantom ON | `F0 00 01 05 42 00 01 00 00 03 00 01 00 00 00 33 F7` | medium (condenser mics only) |
| Set phantom OFF | `F0 00 01 05 42 00 01 00 00 03 00 00 00 00 00 34 F7` | medium |
| Set pad 1 LED = Red (`V1=0x00010000, V2=2, V3=0x34`) | `F0 00 01 05 42 00 03 00 0C 03 01 00 00 01 00 02 00 00 00 34 00 00 00 6E F7` | low (id and N from Translate, colour semantics inferred) |

Not tested on hardware. Do not send the gain, phantom or LED frames without first reading the same param with a Get and keeping the reply as the restore value.

## Open risks

1. Get replies are unverified: no Get was ever captured on this unit, so the reply format (byte 5 = 0 or 1) and whether the firmware answers all ids is unknown.
2. LED value semantics (V1 mode byte, brightness, palette) are inferred from preset files only; a wrong write could leave pads in an odd state until reset.
3. Persistence is unknown for `0x5F0000xx`, `0x50xxxxxx`, `0x4100xxxx`, `0x01040300`; plus the external `FirmwareUpdater` may use messages that look like normal sets.

## Pass 3: LED data files, palette, gain, voice-FX knob

Generated data lives in `data/` (`data/tools/convert_leds.py` rebuilds it from the Mac files).

- **Palette [O]**: `MA::LAppEngine::InitColorArrays` (`0x1002fb5c2`) builds a 128-entry ARGB table; the LED colour byte in every button/array word is the index (`GetColorFromMidiValue` `0x1002ff65c`). 0 and 1 are black, 2..25 dim (0x55-scaled) hues, 26..51 mixed, 52..75 full-saturation hues, 76 grey, 77..100 pastel-bright, 101..125 pastel, 126 light grey, 127 white. This explains `V3 = V2 + 0x32`: V2 is the dim twin of V3's full-brightness colour (2 = `#550000`, 52 = `#FF0000`). Stored in `data/leds.json` `palette`.
- **Sample LEDs [I]**: 10 sample labels exist (Bank 1/2 x Sample 1..5), and 10 sample LED records (`0x78 + 8k`, k=0..9) map to `0x01030A00 + 0x100*k`. So `0x01030A00/0B00` are samples 1-2, not "unassigned" LEDs as written above, and the helper's `pad_1` (`0x01030C00`) is sample 3 under that reading. Which physical pad lights for which param is unverified; `data/leds.json` `aliases` keeps the `pad_N` names.
- **Presets**: 23 LED presets, each with 64 records; only the 42 records with a device param (10 samples, 4 mutes, 4 voice-FX, mic-mute, censor, 13 labels, 9 arrays) are converted. Records `0x7F`-twins and `0xE6..0xF3` have no device param in Translate. Preset words are replayed verbatim.
- **Gain -> dB [U]**: not found. `LMixerGain` only translates `0x44000000 + dest*0x100 + src*2` with no curve, and no display conversion was located in the Panel in a time-boxed search. Keep the 0..127 raw scale.
- **`0x01040300` N=4 [U]**: observed `[0x01050000, 0x7F, 4, 0x10]`; no new decoding. Word 0 is probably a target param id like the file's `0x41000002`, but `0x0105xxxx` is a new family; words 1..3 unknown.
