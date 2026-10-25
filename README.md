# amr-faultbench

Paper 1: AMR-FaultBench. Public research workspace; initialized 2026-10-23, baseline published 2026-10-24. No experiment or hardware validation is claimed.

- [Frozen research plan](docs/RESEARCH_PLAN.md)
- [Implementation milestones](docs/MILESTONES.md)
- [Decisions and IP boundaries](docs/DECISIONS.md)
- [Audit status](docs/AUDIT_STATUS.md)
- [Experiment log](docs/EXPERIMENT_LOG.md)

## Baseline source code

Start with [code/](code/README.md): current AMR PCB application source, offline C regressions, source hashes and update instructions. Includes the PD15 telemetry implementation. This is a source/test baseline; paper experiments and hardware acceptance remain pending.

## Structure

- `core/`
- `adapters/ros2/`
- `adapters/canopen/`
- `faults/`
- `evaluators/`
- `experiments/`
- `policies/`
- `baselines/`
- `tests/`
- `schemas/`
- `examples/`

## Execution boundary

Only allowlisted experimental policies may be edited by candidate-generating agents. Evaluators, hidden scenarios, baseline fixtures and safety constraints must be isolated. No live robot credentials, motion or flashing permissions. No safety-limit weakening.

The shared harness lives only in Jeffaaay/amr-faultbench. Exact dependency pins will be recorded before use. Oct 23–24 audit; Oct 25 schema freeze; Oct 26–Nov 1 isolated implementation and separately authorized measurements.

- [Research execution report](docs/RESEARCH_REPORT.md)
- [Prioritized GitHub backlog](docs/ISSUES.md)

- [中文执行顺序与当前边界](docs/EXECUTION_ROADMAP.md)
- [功能基准登记](docs/BASELINE_REGISTER.md)

- [首个故障实验的验收说明](experiments/F01_READINESS.md)
- [六类故障与编号草案](faults/CATALOG_PROPOSAL.md)
- [恢复技能边界](policies/RECOVERY_CONTRACT.md)
- [四组方法的评估协议](evaluators/METRICS_PROTOCOL.md)

- [Trace 草案 2 与离线检查命令](docs/TRACE_DRAFT2_REVIEW.md)
