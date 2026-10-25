# P1 baseline code — AMR PCB fault/recovery

这是第一版可读取、可在电脑上运行回归测试的真实源码基准，用于后续 MCU 恢复策略与 SIL。
当前只交付 baseline；F01 运行器、候选策略接口和四组论文实验尚未实现。

| 研究入口 | 文件（均相对 `baseline/amr_pcb/`） | 用途 |
| --- | --- | --- |
| 恢复与故障锁存 | `Core/Src/drive_safety.c`, `drive_fault_reset.c` | 定位反馈丢失、启动恢复、复位条件 |
| 反馈权威与配对 | `Core/Src/drive_core.c`, `canopen.c`, `wheel_pdo_config.c` | 新鲜度、双侧反馈和 DS402 状态 |
| 命令执行与限制 | `Core/Src/drive_control.c`, `drive_target.c`, `wheel_rpdo_tx.c` | 保留现有动作与保护边界 |
| 已有回归 | `tests/host/test_drive_boot_recovery.c`, `test_pdo_startup_recovery.c` | 起点和反例，不等同 F01 实验 |

反馈回来不等于故障锁存自动解除；request nonce 也不等于恢复授权。
正式实验需先冻结 Trace、恢复 C 接口与允许动作。

## 快速运行 / Offline quick start

Requirements: Python 3.10+ and a native C11 compiler (Linux GCC/Clang or Windows LLVM-MinGW).
The retained tests use the Python standard library and fake GPIO/CAN; no serial device is opened.
Run from the repository root:

```sh
python code/verify_baseline.py
python code/run_checks.py
```

Set `AMR_HOST_CC` to a compiler executable when it is not on PATH. On Windows,
use LLVM-MinGW rather than MSVC-targeting Clang; the existing runner also accepts
`AMR_HOST_SYSROOT` for a GNU-compatible Windows sysroot. Test outputs go under
`code/baseline/amr_pcb/output/` and are ignored by Git.

## What this snapshot contains

- `baseline/amr_pcb/Core/`: current application C/headers and STM32 startup source.
- `baseline/amr_pcb/tests/host/`: the existing fake-bus regression tests.
- `baseline/amr_pcb/tools/`: the two retained offline test entry points.
- `baseline/amr_pcb/jetson_tools/`: the exact protocol/RPDO parser dependencies used by those tests.
- `baseline/amr_pcb/docs/`: protocol, startup recovery and PD15 contracts copied with the source.
- `baseline_manifest.json`: SHA-256 and byte size for every imported file, plus a whole-snapshot digest.
- `source_selection.json`: explicit paths approved for the next import.
- `VALIDATION.json`: validation status bound to a snapshot digest.

源基准为当前 `AMR_PCB _RGB`，包含 25 ms 轮速控制、开机等待/恢复逻辑和新 PD15 上报。
本地目录没有可用的独立 Git commit，因此用逐文件哈希和快照摘要锁定，不能把它标成
Bayro Fleet 的某个 Git 提交。当前源码快照也不证明它已烧到实车。

This is an application-source and host-test baseline. The STM32 HAL/CMSIS driver
trees, linker/build project and flash helpers are not bundled, so this folder alone
is not a complete target-firmware build kit. Existing vendor headers and available
license notices are preserved; see [NOTICE](NOTICE.md).

The Bayro Fleet ROS2/navigation stack, deployment maps, credentials, logs, generated
binaries and backup copies are outside this initial selection. The copied Jetson
protocol library contains serial-session helpers, but `run_checks.py` calls only
offline parser/test paths. Production firmware, fleet code and real devices are
not changed by these checks.

## Baseline boundaries

This folder is a frozen input to future experiments. Keep agent-generated recovery
or tuning changes in separate experiment/policy files; do not alter this baseline
to improve a score. The existing shared research harness remains owned by P1;
P2/P3's `dependencies.lock.json` pins are unchanged. A baseline regression suite is
not the planned SIL fault benchmark, commissioning experiment or HIL validation.

PD15 telemetry is already implemented in this snapshot: active HIGH, 30 ms release
debounce, change reports and 100 ms snapshots. It reports input state; it does not
add an MCU emergency-stop control gate. Jetson base-driver ESTOP parsing and
physical acceptance remain follow-up work. Source configuration values, including
deceleration constants, are not measured braking performance.

## Later updates

From the repository root, compare the same explicit selection to a new source directory:

```sh
python code/refresh_baseline.py --source "/path/to/AMR_PCB _RGB"
python code/refresh_baseline.py --source "/path/to/AMR_PCB _RGB" --write
python code/run_checks.py
```

The first command only reports differences. `--write` updates the research copy
and invalidates old validation status; it does not push, build production firmware
or access hardware. Review newly needed dependencies before editing the allowlist.
Record the new test/compiler results against the new digest in `VALIDATION.json`,
update this repository's baseline register, and commit the reviewed snapshot.
Keep the same digest across all three papers when they share a baseline. Existing
experiment manifests must retain the digest of the baseline they actually used.
