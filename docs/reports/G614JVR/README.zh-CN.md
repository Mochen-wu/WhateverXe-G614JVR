# 中文摘要 — ASUS ROG Strix G16 (G614JVR) 内屏 eDP 点亮

完整技术报告见 [`README.md`](README.md)（英文）。本页是同一份内容的摘要。

## 结果

机型 ASUS ROG Strix G16 **G614JVR**，i9-14900HX，核显 `8086:A788`，macOS 26.7.2
(25G332)，OpenCore。**官方 0.8.0 点不亮这块内屏**，应用
[`patches/`](patches/) 里的补丁后点亮，2560x1600 正常出图并带加速。

这是目前第一例 Raptor Lake-S/HX 内屏 eDP 在实机上跑通的记录。

| | 官方 0.8.0 | 打补丁后 |
| --- | --- | --- |
| `WhateverXeFirmwarePanel` | `valid=0, ddi=9` | `valid=1, ddi=0, lowSwing=1` |
| `WEXEDPPanelFix` | 不存在 | `Yes` |
| `TGLEDPTrainingFix` | 不存在 | `Yes` |
| `TGLEDPTrainingFixReady` | 不存在 | `Yes` |
| `TGLPanelColdCycle` | 不存在 | 有记录 |
| 内屏 | 黑 | 2560x1600，显存 1536 MB |

注意是“不存在”而不是 `No`：那段代码从来没被执行过，属性压根没被写出来。

## 两个独立缺陷

**一、固件面板记录被整条丢弃。**
`panelFacts()` 把 BDB40（`CHILD_DEVICES`）首字节当成面板类型索引，要求小于 16。
这块主板的该字节是 **`0xFF`（255）**，于是整条记录被丢，`ddi` 退回哨兵值 9，
`nativePPS0()` 直接为假。改成越界时回落类型 0 即可 —— 回落是安全的，因为
BDB27/BDB43/BDB44 的其余字段仍会被逐项校验，这块 VBT 的类型 0 时序
（200/100/200/50/500 ms）和背光（`pwmPresent=1`、`backlightType=2`、
`controller=0`）都合格。

**二、门禁写死了 TGL，而这台机器被判定为 ADL-S。**
`A788` 被 WEX 选成 Raptor Lake-S，`displayAdapter()` 返回 `ADLS`；但驱动面板用的
却仍是 TGL 那套 donor framebuffer。修复段的条件是
`displayAdapter(family) == TGL`，于是永远不成立，整段代码（连同所有
`TGLEDP*` 属性）从来没运行过。

这一步之所以难找，是因为它被第一个缺陷掩盖了：只修好第一处时，面板记录已经
`valid=1, ddi=0`，`nativePPS0()` 也已经为真，但 `TGLEDPTrainingFix` 仍然不存在。
这个组合只能说明门禁没放行。

**三、ADL-S 的 PWM 通路先占走了 `LightUpEDP`。**
`ADLSPanelPWMReady` 在官方版就是 `Yes`，ADL-S 分支已经把 `LightUpEDP` 挂走。
修复段需要同一个入口来做面板供电复位，而它的守卫条件
`if(ready && !orgADLSLightUpEDP && ...)` 会静默放弃。所以补丁让修复段优先：
`edpPanelFix` 成立时，ADL-S 分支只挂背光亮度/PWM 适配器，把 `LightUpEDP` 让出来。

## 补丁分组

`patches/wex-0.8.0-g614jvr-edp.patch`（415 行，可干净应用到 tag `0.8.0`）。
**只有 C 组是本机专属**：

- **A** `kern_vbt.hpp`：BDB40 首字节越界时回落类型 0 —— 通用 bug 修复，任何
  BDB40 写 `0xFF` 的主板都会踩。
- **B** `kern_vbt.hpp` + `kern_firmware.cpp`：重复 DDI 的可选策略
  （`-wex-ddi-conflict-select-first/-last`），默认仍是拒绝；新增
  `WhateverXeFirmwareConflicts` 诊断属性。这块 VBT `duplicates=0`，本机实际用不上。
- **C** `kern_xe.cpp`：把 `ADLS` 纳入 eDP 修复门禁，发布 `WEXEDPPanelFix`。**平台修复**。
- **D** `kern_xe.cpp` + `kern_xe.hpp`：`pwmOnly` 让路，以及修复本体 ——
  `tglPanelAuxDDI()`、`tglPowerDomainRepair()`、`wrapTGLPanelLightUp()`
  （donor `hwSetPanelPower` 走 PPS off → T12 → on，随后排空并重新使能 DDI/AUX
  电源域引用，再执行原生 light-up）。

## 验证要点

`TGLPanelColdCycle` 解出来：seq 1，`PP_STATUS` 前后都是 `0x80000008`，
`PP_CONTROL=0x63`，主电源 `0x3F`，off/on 返回值均为 0，T12 = 6（600 ms）。
说明面板供电确实被断开又拉起来了。

`TGLEDPPowerDomainLast`：ddi 0，DDI/AUX 引用计数各 1 → 排空 1 → 重新使能到 1，
显示引擎已调用。首次开机时这一条是 `0/0`（无可排空），`TGLEDPTrainingFixReady`
两次都是 `Yes`，说明有无残留都能过。

`evidence/` 下有三个原始采集文件，`tools/collect-evidence.sh` 可重跑，
`tools/decode-vbt.py` 直接从 WEX 回写的 `TGLVBT` 属性解码，不需要回 Windows 抓。

## 还没解决的

- **没有亮度滑条**：`PNLF` 设备根本不存在，`AppleBacklight` 不加载。屏幕亮着是因为
  WEX 直接写 PWM。这是 ACPI 侧独立问题，常见模板有两个坑：`Device (PNLF)` 没包在
  `Scope(\_SB)` 里；`_STA` 用 `_OSI("Darwin")` 而配置里开了 `_OSI → XOSI` 重命名。
  [`ssdt-pnlf/`](ssdt-pnlf/) 是绕开这两点的写法，但**尚未完整验证**，仅供参考。
- **刷新率报 0 Hz**：`IOFBDetailedTimings` 每条里偏移 `0x84` 的
  `verticalRefreshRate` 全是 0，系统据此打上 `IOFB0Hz`，下拉框不显示。时序本身算得
  出 60.00 Hz，只是没填进去。这块屏 EDID 范围写 60–240 Hz 但只有一条 60 Hz DTD，
  要 240 Hz 得自己加时序并开 DSC，WEX 没有 DSC 实现，不在本次范围。
- **睡眠/唤醒**未系统验证。

## 两个会误导人的属性

`TGLAUX0Count`（改前 633、改后 636）和 `TGLBootstrapAUXReady`（一直 `No`）来自
启动早期的 bootstrap AUX 探测，那时面板还没上电，之后也不会更新。**它们不是内屏
eDP 的成功判据**：内屏亮着而 `TGLBootstrapAUXReady = No` 是正常结果。

## 适用范围

已确认 `A788`。代码路径相同的有 Raptor Lake-S/HX `A780`–`A78B`（同为 `ADLS`），
以及 Alder Lake-S/HX `4680`–`4693`（同为 `ADLS`，A 组值得一试）。

**未覆盖**：Alder Lake-H/P/U 与 Raptor Lake-H/P（如 `A7A0`、`A7A8`）走
`DisplayAdapter::ADLP`，C 组没有放行。加一行 `ADLP` 不难，但必须在真机上验证
`nativePPS0()` 是否满足，门禁放行不代表 VBT 合格。

## 构建与安装

```
git apply docs/reports/G614JVR/patches/wex-0.8.0-g614jvr-edp.patch
python3 tools/build.py --sdk /path/to/MacKernelSDK --lilu /path/to/Lilu.kext --release
```

替换 `WhateverXe.kext`，保持排在 Lilu 之后，`boot-args` 加
`-wex-edp-fix-training`。其他配置不变，WhateverGreen 必须保持禁用。

`artifacts/` 里是本机实际运行的那份二进制（1,830,520 字节，
sha256 `c1f3b6eb…716c3`）。自己重新编译哈希会不同，属正常。
