# Trace 草案 2：分清停止请求与停止证据

状态：1.0.0-draft.2，准备 10/25 审查，**未冻结**。这是离线数据契约检查工具，不运行控制器、虚拟驱动、故障注入或机器人，也不判定实验成功。

本轮审计发现后续实验必须区分：命令已接收、CAN 发送、停止请求、驱动反馈确认、外部测量确认、复位完成和重新使能。它们不能共用一个 success=true。

## 可立即运行

在独立 Python 环境安装 requirements-dev.txt 后，从仓库根目录运行：

```text
python tools/trace_review.py examples/command_safety_correlation.jsonl
python tools/trace_review.py examples/asynchronous_stop_unconfirmed.jsonl
python -m unittest discover -s tests -v
```

两个例子均为人工构造的合成记录，数值不是已审计固件的运行输出，也没有发生真正的 TPDO 丢包。示例 CAN 标识/字节是任意占位数据，不是部署配置。

返回 VALID（退出码 0）表示记录符合这份草案；INCOMPLETE（2）表示缺失父事件、记录丢失、版本或回绕信息不足；INVALID（1）表示结构或内部关系矛盾。**这三个结果都不表示整车实验通过。** 输出始终保留 experiment_verdict=null 和 physical_stop_verified=false。

## 草案 2 增加了什么

| 字段/检查 | 作用 |
| --- | --- |
| evidence_level | 显式区分 synthetic / model / extracted_logic / HIL / robot；这是记录者声明的来源类别，不是认证 |
| can_frame | 经典 CAN 的 bus_id、标准/扩展帧、标识、DLC、数据；检查 ID 范围、方向和字节数，不解码公司协议 |
| mcu_counter | 保留原始 ticks、位宽、tick_period_us、原生回绕次数；与规范化微秒字段核对 |
| stop_evidence | STOP_OBSERVED 必须带观测范围、stationary/moving/unconfirmed、方法和证据引用；轮反馈不能直接改名为外部物理测量 |
| 事件关系 | 检查重复 ID/命令、因果环、跨 run/MCU boot、缺失父事件；相同序号或相近时间不自动构成因果关系 |
| 时间区间 | 只比较同一时钟域。显式命令祖先到接收的主机时间区间不是单向通信、控制器执行或制动延迟 |

STOP_REQUEST、RECOVERY_REQUEST、RECOVERY_RESULT、STATE_TRANSITION 已加入候选词表。事务阶段、规则 ID、旧日志到新词表的精确映射仍需 10/25 审查，尚未进入任何固件。

SAFE_STOP 是发出停止决定，不能代替 STOP_OBSERVED。STOP_OBSERVED 的 wheel_feedback/外部测量也只是附有证据位置的观测声明；工具不执行驱动解码、仪器校准、物理测量或停止距离验算。空的外部测量引用不能支持 stationary/moving；CAN_TX 也不能冒充接收到的轮反馈。

## 毫秒到微秒的明确规则

已知原生回绕次数时，以 Python 整数计算：

```text
expanded_us = (wrap_epoch * 2**bits + raw_ticks) * tick_period_us
mcu_timestamp_us = expanded_us % 2**32
mcu_timer_epoch = expanded_us // 2**32
mcu_resolution_us = tick_period_us
```

例如 32 位毫秒计数的 raw_ticks=4,294,968、wrap_epoch=0，应成为微秒余数 704、微秒 epoch=1；MCU 并未重启。原生毫秒计数真正回绕一次时，微秒 epoch 对应 1000。单位换算不会把 1 ms 精度提升为 1 us。

原生 wrap_epoch 不知道时，mcu_timer_epoch 必须为 null，记录局部 raw_ticks 换算的微秒余数并返回 INCOMPLETE；不得假定 epoch=0 后做跨段时间排序。每个 boot 重新建立计数身份。CAN 控制器的原始硬件计时器另属时钟域，须验证频率、位宽和回绕，再产生 can_timestamps，不能直接把原始计数写成纳秒。

## 仍然不能靠此工具证明的事情

- 数据是否真的来自所声明的固件、硬件或测量装置；非合成记录缺少版本摘要会标记不完整，有摘要也不能替代验证。
- 驱动的实际状态机、阈值执行、CAN on-wire 时间、控制周期、轮子或车体是否停止。
- 复位请求是否得到现场/实验运行器授权。请求 nonce 只是关联标识，不是权限凭证。
- 控制器里的停止证据是否满足全部采样、停留时间、安全代次等规则。需要后续独立 evaluator 与源码行为对照。

draft.1 示例需显式迁移到 draft.2，不能只改版本号：补来源层级、实际帧元数据、原始计数/回绕信息和停止观测范围。无法确定的字段保持 unknown/null 并保留缺口；不得伪造测量。既有窄范围 command reconciliation 测试只证明一个合成链路；tools/trace_review.py 才是本轮的通用离线草案检查入口。
