#!/usr/bin/env python3
"""Decode the VBT that WhateverXe published to the registry.

WhateverXe republishes the exact firmware VBT bytes it parsed as ``TGLVBT``
on the iGPU PCI device, so this runs on a booted system with WEX loaded and
needs no Windows side dump.

Usage:  python3 decode-vbt.py [--json]
"""

import re
import subprocess
import sys


def read_vbt():
    out = subprocess.run(["ioreg", "-l", "-w0"], capture_output=True, text=True).stdout
    m = re.search(r'"TGLVBT" = <([0-9a-f]+)>', out)
    if not m:
        sys.exit("TGLVBT not found: is WhateverXe loaded?")
    return bytes.fromhex(m.group(1))


def u16(p, o=0):
    return p[o] | (p[o + 1] << 8)


def u32(p, o=0):
    return u16(p, o) | (u16(p, o + 2) << 16)


def parse(b):
    if b[:4] != b"$VBT":
        sys.exit("bad signature: %r" % b[:4])
    bdb = u32(b, 28)
    ver = u16(b, bdb + 16)
    bh = u16(b, bdb + 18)
    bs = u16(b, bdb + 20)

    blocks = {}
    at = bh
    while at < bs and bs - at >= 3:
        n = u16(b, bdb + at + 1)
        if b[bdb + at] == 53:  # variable-length block
            if bs - at < 8:
                break
            if b[bdb + at + 3] >= 3:
                n = u32(b, bdb + at + 4)
        if n > bs - at - 3:
            break
        blocks.setdefault(b[bdb + at], []).append((at, n))
        at += 3 + n
    return b, bdb, ver, bh, bs, blocks


def main():
    b = read_vbt()
    b, bdb, ver, bh, bs, blocks = parse(b)
    print("VBT signature      : %s" % b[:4].decode("ascii", "replace"))
    print("VBT size           : %d bytes" % len(b))
    print("BDB offset         : 0x%x" % bdb)
    print("BDB version        : %d" % ver)
    print("BDB header / size  : %d / %d" % (bh, bs))
    print()
    print("Blocks present     :")
    for k in sorted(blocks):
        print("  BDB%-3d offset=0x%-5x size=%d" % (k, bdb + blocks[k][0][0], blocks[k][0][1]))

    opt, edp, bl, pw = (blocks.get(x) for x in (40, 27, 43, 44))
    print()
    print("--- panel facts inputs ---")
    if opt:
        oa = bdb + opt[0][0] + 3
        first = b[oa]
        print("BDB40 (CHILD_DEVICES) byte 0 : 0x%02x (%d)  <- PPS index" % (first, first))
        print("  valid PPS index (<16)?     : %s" % ("yes" if first < 16 else "no"))
    else:
        print("BDB40 missing")
        first = 0
    pt = first if first < 16 else 0
    if edp:
        ea = bdb + edp[0][0] + 3
        print("BDB27 (LFP_PANEL_1) size     : %d" % edp[0][1])
        print("  delays for type %d (x100us): %s" % (pt, [u16(b, ea + 10 * pt + 2 * i) for i in range(5)]))
    if bl:
        ba = bdb + bl[0][0] + 3
        size = bl[0][1]
        print("BDB43 (BACKLIGHT) size       : %d" % size)
        if size >= 129 and b[ba] == 6:
            et = ba + 1 + 6 * pt
            print("  entry for type %d          : %s" % (pt, b[et:et + 6].hex()))
            print("  pwmPresent                 : %s" % bool((b[et] & 3) == 2))
            print("  activeLowPWM               : %s" % bool(b[et] & 4))
            print("  pwmHz                      : %d" % u16(b, et + 1))
            print("  backlightType / controller : %d / %d" % (b[ba + 113 + pt] & 15, b[ba + 113 + pt] >> 4))
    print("BDB44 (POWER_SEQUENCE) size  : %s" % (pw[0][1] if pw else "missing"))


if __name__ == "__main__":
    main()
