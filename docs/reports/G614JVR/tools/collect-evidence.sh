#!/bin/bash
# Collect the WhateverXe state used in this report.
# Run after booting the patched build. Read-only: changes nothing.

echo "=========================================="
echo " WhateverXe internal-eDP evidence"
echo " $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=========================================="
echo

echo "[1] Loaded WEX and the deployed binary hash"
kmutil showloaded --list-only 2>/dev/null | grep -i whateverxe
for p in /System/Library/Extensions/WhateverXe.kext \
         /Library/Extensions/WhateverXe.kext \
         /Volumes/EFI/EFI/OC/Kexts/WhateverXe.kext; do
  [ -f "$p/Contents/MacOS/WhateverXe" ] || continue
  echo -n "    $p: "
  shasum -a 256 "$p/Contents/MacOS/WhateverXe" | awk '{print $1}'
done
echo

echo "[2] Admission switch (patched builds only; absent on stock 0.8.0)"
ioreg -l -w0 2>/dev/null | grep -o '"WEXEDPPanelFix" = [^ ]*' || echo "    <absent>"
echo

echo "[3] eDP repair stages"
for k in TGLEDPTrainingFix TGLEDPTrainingFixReady TGLEDPPowerDomainReady \
         TGLPanelLightUpReady TGLPanelPowerFunctionReady; do
  v=$(ioreg -l -w0 2>/dev/null | grep -o "\"$k\" = [^ ]*")
  printf "    %-30s %s\n" "$k" "${v:-<absent>}"
done
echo

echo "[4] Firmware panel facts (valid=1 ddi=0 required for the repair)"
ioreg -l -w0 2>/dev/null | grep -o '"WhateverXeFirmwarePanel" = <[^>]*>' || echo "    <absent>"
ioreg -l -w0 2>/dev/null | grep -o '"WhateverXeFirmwarePorts" = <[^>]*>' || echo "    <absent>"
echo

echo "[5] Panel power cycle record (hwSetPanelPower off -> T12 -> on)"
ioreg -l -w0 2>/dev/null | grep -o '"TGLPanelColdCycle" = <[^>]*>' | head -1
ioreg -l -w0 2>/dev/null | grep -o '"TGLPanelCycle" = <[^>]*>' | tail -1
echo

echo "[6] DDI/PG power-well repair record"
ioreg -l -w0 2>/dev/null | grep -o '"TGLEDPPowerDomainLast" = <[^>]*>' | tail -1
echo

echo "[7] AUX counters (informational only, see report)"
for k in TGLAUX0Count TGLBootstrapAUXReady TGLFramebufferStartResult; do
  v=$(ioreg -l -w0 2>/dev/null | grep -o "\"$k\" = [^ ]*")
  printf "    %-30s %s\n" "$k" "${v:-<absent>}"
done
echo

echo "[8] Internal display"
system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Chipset Model|Resolution|VRAM|Display Type" | sed 's/^/    /'
echo

echo "[9] VBT decode"
python3 "$(dirname "$0")/decode-vbt.py" 2>/dev/null || echo "    decode-vbt.py failed"
