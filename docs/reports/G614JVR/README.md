# Internal eDP bring-up on Raptor Lake-S/HX — ASUS ROG Strix G16 (G614JVR)

Field report for WhateverXe 0.8.0 on an ASUS ROG Strix G16 **G614JVR**
(Core i9-14900HX, iGPU `8086:A788`, macOS 26.7.2 / 25G332, OpenCore).

The internal panel **does not light up with the stock 0.8.0 release**. It does
light up with the patch in [`patches/`](patches/), and it is the first
Raptor Lake-S/HX internal-eDP configuration reported working.

Two independent defects block the panel on this platform. Fixing only the first
one still leaves the panel dark, which is what made this take a while to pin
down; the two are separated in the "Diagnosis" section.

---

## 1. Result

| | stock 0.8.0 | patched |
| --- | --- | --- |
| `WhateverXeFirmwarePanel` | `valid=0, type=0, ddi=9` | `valid=1, type=0, ddi=0, lowSwing=1` |
| `WEXEDPPanelFix` | absent | `Yes` |
| `TGLEDPTrainingFix` | absent | `Yes` |
| `TGLEDPTrainingFixReady` | absent | `Yes` |
| `TGLEDPPowerDomainReady` | absent | `Yes` |
| `TGLPanelLightUpReady` | absent | `Yes` |
| `TGLPanelPowerFunctionReady` | absent | `Yes` |
| `TGLPanelColdCycle` | absent | present, seq 1 |
| Internal display | black | 2560x1600, VRAM 1536 MB, accelerated |
| Framebuffer | `IONDRVFramebuffer`, 15 MB, no accel | `AppleIntelTGLGraphicsFramebuffer` 0/1/2 online |

`absent` is the important word in that table: on stock 0.8.0 these properties do
not exist with a false value, they do not exist at all, because the block that
publishes them is never entered.

## 2. Hardware

| Item | Value |
| --- | --- |
| Machine | ASUS ROG Strix G16 **G614JVR** (ROG Strix G16, 2023, 16") |
| CPU | Intel Core i9-14900HX (24C/32T, Raptor Lake-S/HX) |
| iGPU | `8086:A788`, subsystem `1043:3488`, UHD Graphics (32 EU) |
| dGPU | NVIDIA RTX 4060 Laptop 8 GB — driven separately, not by WEX |
| Panel | `TL160ADMP16-0`, 2560x1600, eDP on DDI A / AUX A |
| Firmware | VBT 8666 bytes, `$VBT`, BDB version 250 |
| OS | macOS 26.7.2 (25G332), OpenCore |
| WEX | 0.8.0 (tag `0.8.0`, commit `db438fd`) |
| Donor | `AppleIntelTGLGraphicsFramebuffer` 16.0.0, `AppleIntelTGLGraphics` 16.0.0 |

The discrete GPU is handled by a third-party stack that is unrelated to this
report; WEX only touches the iGPU. Both framebuffers coexist.

Relevant `boot-args`:

```
-allow3d -disablegfxfirmware -wex-edp-fix-training -wex-ddi-conflict-select-first
```

`-wex-ddi-conflict-select-first` is **inert on this board** — see section 6 — and
is kept only because it is harmless.

## 3. Symptom

With WEX enabled and the iGPU active, the external outputs driven by the
discrete GPU work, but the internal panel stays black. Forcing the iGPU to own
the desktop gives a picture only through `IONDRVFramebuffer` at 15 MB with no
acceleration, which is the classic "no working display path" fallback.

`TGLBootstrapAUXReady` stayed `No` and `TGLAUX0Count` sat around 633, i.e. the
internal AUX channel never completed a transaction. That reading sent the
investigation towards link training and PHY state for a long time and was a
dead end; see section 8.

## 4. Diagnosis

### 4.1 The firmware panel record was discarded

`WhateverXeFirmwarePanel` came back as `valid=0, type=0, ddi=9`. `ddi=9` is the
sentinel for "no internal port", so every consumer of the panel record —
including `XELP::PanelPower::nativePPS0()` — bailed out immediately.

The cause is in `XELP::VBT::panelFacts()` (`kern_vbt.hpp`). It took the first
byte of BDB40 (`CHILD_DEVICES`) as a PPS/panel type index and rejected anything
outside 0..15:

```c
if(duplicate || !options || optionsSize<1 || options[0]>=16 ||
   !edp || edpSize<212 || (ports.version>=232 && (!power || powerSize<56))) return;
...
p.type=options[0];p.ddi=internal;
```

On this VBT, BDB40 byte 0 is **`0xFF` (255)** — see
[`evidence/vbt-summary.txt`](evidence/vbt-summary.txt). That is not a panel type
index, so the whole panel record was dropped.

`0xFF` is not unique to this board; it is a plausible "no explicit panel type"
sentinel for any firmware that leaves the field unset. Falling back to panel
type 0 is safe because the rest of the record is then still validated against
BDB27/BDB43/BDB44: on this VBT type 0 carries real timings (200/100/200/50/500
ms), `pwmPresent=1`, `backlightType=2`, `controller=0`, which is exactly what
`nativePPS0()` requires.

After this change alone the panel record becomes `valid=1, ddi=0` and
`nativePPS0()` returns true when queried with the Raptor Lake-S family.

### 4.2 The admission gate never matched this platform

This is the second, independent defect. The internal eDP repair block in
`kern_xe.cpp` was admitted by:

```c
if (tglActive && !display13FramebufferRequested &&
    XELP::displayAdapter(xeProfile.family) == XELP::DisplayAdapter::TGL &&
    XELP::PanelPower::nativePPS0(firmwarePorts, xeProfile.family)) { ... }
```

`A788` is selected as **Raptor Lake-S**, and `displayAdapter()` maps that to
`DisplayAdapter::ADLS`, not `TGL`. This machine still drives the panel with the
TGL donor framebuffer, so the first half of the condition describes the driver
correctly and the second half does not. The condition could never be true here,
and the repair block — including the publication of every `TGLEDP*` property —
never ran.

Verifying this was straightforward once the two were separated: with only 4.1
applied, `nativePPS0()` was already true and the panel record was already
correct, yet `TGLEDPTrainingFix` was still absent. That can only be the gate.

The fix admits `ADLS` alongside `TGL`, and publishes the decision so it can be
checked without a debug build:

```c
const auto panelAdapter = XELP::displayAdapter(xeProfile.family);
const bool edpPanelFix = tglActive && !display13FramebufferRequested &&
  (panelAdapter == XELP::DisplayAdapter::TGL ||
   panelAdapter == XELP::DisplayAdapter::ADLS) &&
  XELP::PanelPower::nativePPS0(firmwarePorts, xeProfile.family);
IORegistryEntry::getRegistryRoot()->setProperty("WEXEDPPanelFix", edpPanelFix);
```

### 4.3 The ADL-S panel wrapper had already taken `LightUpEDP`

With `edpPanelFix` true, one more conflict had to be resolved. The ADL-S branch
of `processNativePanel()` installs

```c
KernelPatcher::RouteRequest routes[] {{light, wrapADLSLightUpEDP, orgADLSLightUpEDP},
                                      {brightness, wrapADLSPanelBacklight, orgADLSPanelBacklight}};
```

`ADLSPanelPWMReady` was `Yes` on stock 0.8.0, so the ADL-S wrapper owned
`LightUpEDP`. The eDP repair needs that same entry for its panel-supply cycle
and its guard `if(ready && !orgADLSLightUpEDP && !orgTGLPanelLightUp)` would
have silently declined to install.

The repair therefore wins: when `edpPanelFix` is set, the ADL-S branch installs
only the PWM/brightness adapters and leaves `LightUpEDP` alone.

```c
const bool pwmOnly = edpPanelFix;
if(known && patcher.routeMultiple(index,routes+(pwmOnly?1:0),pwmOnly?1:2,address,size)) { ... }
```

The PWM duty/polarity adapters and the `controller+0xE60` enable bridge are kept,
so ADL-S backlight behaviour is unchanged.

## 5. Change set

`patches/wex-0.8.0-g614jvr-edp.patch` (415 lines, applies to tag `0.8.0`) is the
full delta as deployed on this machine. It is grouped here by purpose; only
group **C** is specific to this platform.

**A. VBT panel facts — accept an out-of-range BDB40 panel type** (`kern_vbt.hpp`)
Drop the `options[0]>=16` rejection and clamp the index instead. General fix,
not board specific.

**B. Duplicate-DDI policy** (`kern_vbt.hpp`, `kern_firmware.cpp`)
`ConflictPolicy{Reject,SelectFirst,SelectLast}`, opt-in through
`-wex-ddi-conflict-select-first` / `-wex-ddi-conflict-select-last`, plus a new
`WhateverXeFirmwareConflicts` diagnostic property. The default stays `Reject`.
On this VBT `duplicates=0`, so the switches do nothing here.

**C. Admit the ADL-S adapter for the internal eDP repair** (`kern_xe.cpp`)
The `edpPanelFix` condition above, published as `WEXEDPPanelFix`. This is the
platform fix.

**D. Give `LightUpEDP` to the repair; keep ADL-S PWM only** (`kern_xe.cpp`,
`kern_xe.hpp`)
`pwmOnly` routing as described, plus the repair itself: `tglPanelAuxDDI()`,
`tglPowerDomainRepair()` and `wrapTGLPanelLightUp()` (donor
`hwSetPanelPower` PPS off -> T12 -> on, then drain and re-enable the DDI/AUX
power-well references before the native light-up). Includes
`TGLTrainingTime*` diagnostics that do not alter behaviour.

## 6. Verification

Full captures in [`evidence/`](evidence/). `tools/collect-evidence.sh`
regenerates them; `tools/decode-vbt.py` reproduces the VBT decode from the
`TGLVBT` property WEX republishes, so no Windows-side dump is needed.

**Firmware record.** `present=0x31` (DDI 0, 4, 5), `unmapped=0`, VBT source 2
(mapped firmware region), BDB version 250, checksum 220. Panel:
`valid=1, type=0, ddi=0, lowSwing=1, hobl=0`.

**Panel supply cycle.** `TGLPanelColdCycle` decoded with the field order
documented at the call site:

| field | value |
| --- | --- |
| seq | 1 |
| PP_STATUS before / after | `0x80000008` / `0x80000008` |
| PP_CONTROL | `0x63` |
| surface | 0 |
| main power / IO power | `0x3F` / 0 |
| off result, on result | 0, 0 |
| T12 | 6 (600 ms) |

So the donor PPS entry really did drive the panel rail off and back on before
the first light-up, and the pixel pipe came back with the same status.

**Power well repair.** `TGLEDPPowerDomainLast`: `ddi=0`, DDI refcount 1 -> drained
1, AUX refcount 1 -> drained 1, display engine enabled, DDI and AUX re-enabled to
1 each, main power `0x3`, IO power `0x3`. On the first boot after deployment the
same record showed `0/0` drained, i.e. the repair has also been observed with
nothing to fix, and `TGLEDPTrainingFixReady` was `Yes` in both cases.

**A later cycle.** `TGLPanelCycle` seq 2 shows the same sequence running on a
subsequent light-up with a surface already mapped (`0x0352F8B0`, main power 3),
so the hook is not a one-shot.

## 7. Not fixed by this patch

**No brightness slider.** The panel lights, but macOS exposes no brightness
control, because there is no `PNLF` device and `AppleBacklight` never loads:
`ioreg | grep -i pnlf` matched nothing across 260 ACPI devices. The display is
lit because WEX writes the PWM directly. This is a separate ACPI issue and has
nothing to do with the eDP path. The stock `SSDT-PNLF` templates fail two ways
on this configuration:

1. `Device (PNLF)` placed in the root scope instead of under `Scope(\_SB)`;
   AppleACPIPlatform only enumerates the standard scopes.
2. `_STA` guarded by `_OSI("Darwin")` while the config enables an `_OSI -> XOSI`
   rename, so the test never matches and `_STA` returns 0.

[`ssdt-pnlf/`](ssdt-pnlf/) contains a version that works around both. It has not
been re-validated end to end yet and is included for reference, not as a
recommendation.

**Refresh rate is reported as 0 Hz.** Every `IOFBDetailedTimings` entry has
`verticalRefreshRate` (offset 0x84, 16.16 fixed point) set to zero, so
`IOFramebuffer` tags the display `IOFB0Hz` and the refresh-rate picker disappears
from Displays. The timing itself is consistent — 2560x1600, 288.05 MHz,
2720x1765 = 60.00 Hz — the value is simply not filled in. The panel
(`TL160ADMP16-0`) advertises 60-240 Hz in its EDID range limits but carries a
single 60 Hz DTD, so even a populated field would offer 60 Hz only. Reaching
240 Hz needs a second timing plus DSC, which WEX does not implement. Out of scope
here.

**Sleep/wake.** Not covered by this report. The hook runs on every internal
light-up rather than cold boot only, and cycle seq 2 above came from a later
light-up, but systematic sleep testing was not performed on this machine.

## 8. Two properties that are misleading on this platform

`TGLAUX0Count` (633 before, 636 after) and `TGLBootstrapAUXReady` (`No` in both
cases) are populated by the early bootstrap AUX probe, which runs before the
panel is powered. They do not change when the panel subsequently lights up, so
neither is a usable success signal for internal eDP on this platform. A working
panel with `TGLBootstrapAUXReady = No` is a normal outcome, not a contradiction.

## 9. Applicability

Confirmed on `A788` (ASUS G614JVR). The code path is shared by:

- Raptor Lake-S/HX `A780`-`A78B` — same `RaptorLakeS -> ADLS` mapping, expected
  to behave identically.
- Alder Lake-S/HX `4680`-`4693` — also `ADLS`. Group A is worth trying there;
  whether the panel facts and the repair apply depends on the individual VBT
  satisfying `nativePPS0()`.

**Not covered:** Alder Lake-H/P/U and Raptor Lake-H/P (e.g. `A7A0`, `A7A8`) map
to `DisplayAdapter::ADLP`, which group C does not admit. Adding `ADLP` to the
condition is a one-line change but must be validated on real hardware; the gate
being open says nothing about whether the VBT on those machines satisfies
`nativePPS0()`.

Success on another board means, at minimum, `WEXEDPPanelFix = Yes`,
`TGLEDPTrainingFixReady = Yes`, a `TGLPanelColdCycle` record, and a lit panel.

## 10. Build and install

```
# in the repository root, with MacKernelSDK/ and Lilu.kext/ present or passed
git apply docs/reports/G614JVR/patches/wex-0.8.0-g614jvr-edp.patch
python3 tools/build.py --sdk /path/to/MacKernelSDK --lilu /path/to/Lilu.kext --release
```

Install the resulting `WhateverXe.kext` in place of the release build, keep it
after Lilu in the OpenCore kext order, and add `-wex-edp-fix-training` to
`boot-args`. Nothing else about the configuration described in the README
changes; WhateverGreen must stay disabled.

A prebuilt binary of exactly this tree is in
[`artifacts/WhateverXe-0.8.0-g614jvr-release.zip`](artifacts/)
(1,830,520 bytes, `Contents/MacOS/WhateverXe` sha256
`c1f3b6ebff2d5d4a82c9d16d6f402452ac67effa0cf2ad42fa07dbfa3e8716c3`,
zip sha256 `8c9ac7f9f3f783a7b6b781afd253f162bd5a036d9cb7d4a9943251abd7f0d544`).
It is BSD-3-Clause code built from this repository; if you rebuild from the patch
the hash will differ.

## 11. Contents

```
docs/reports/G614JVR/
├── README.md                                  this report
├── README.zh-CN.md                            Chinese summary
├── patches/wex-0.8.0-g614jvr-edp.patch        full delta against tag 0.8.0
├── artifacts/                                 prebuilt release kext (zip)
├── ssdt-pnlf/                                 PNLF reference SSDT (.dsl and .aml)
├── tools/collect-evidence.sh                  re-collect every value quoted here
├── tools/decode-vbt.py                        decode the republished VBT
└── evidence/
    ├── environment.txt                        OS, CPU, boot-args, loaded stack
    ├── registry-properties.txt                patched state
    ├── before-and-after.txt                   stock vs patched, field by field
    └── vbt-summary.txt                        block table and panel facts inputs
```
