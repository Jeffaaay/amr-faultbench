# Trace Schema v1 proposal

Status: DRAFT, prepared October 23. Freeze remains October 25. Root `trace_schema_v1.json` is the authoritative proposal; examples are wholly synthetic. No production wire format is changed.

## Identity and causal matching

Match on `(run_id, jetson_boot_id, mcu_boot_id, command_scope, command_epoch, command_sequence)`. Sequence is uint32; increment epoch before reuse after wrap. A sender restart creates a new scope. An MCU reset creates a new boot ID; do not infer boot identity from a wrapped timer. Persist boot/session boundaries in the run manifest. IDs must be propagated or captured with independently verified causal lineage. Host-side numbering alone does not establish MCU causality. Preserve raw source event IDs and parent IDs; do not duplicate a command when exporting it.

Every event carries clock domains, dropped-event counters, requested and accepted commands with units, relevant state and exact version slots. Null explicitly means unknown, never zero. Real experiment acceptance requires verified firmware/software/harness commits and a safety-configuration digest; synthetic draft examples intentionally use null. Firmware without Git metadata needs a separately reviewed source/artifact digest manifest before experiment acceptance.

Asynchronous faults with no responsible command use null command_sequence and unresolved/not_applicable correlation with an explanation. Never guess by nearest timestamp. Scope changes, reboots, duplicate command IDs, lost events and out-of-order delivery must remain observable.

## Event vocabulary

COMMAND_SEND, CAN_TX, CAN_RX, COMMAND_ACCEPT, SAFETY_TRIGGER, EVENT_RECEIVE, BOOT, TRACE_DROP, STOP_OBSERVED. A SAFE_STOP decision means a stop was requested or commanded; it does not mean the vehicle is physically stationary. STOP_OBSERVED needs an independently defined measurement and evidence. Rule IDs and the exact source-to-vocabulary mapping remain review items for October 25.

## Timestamp uncertainty model

Jetson send_monotonic_ns and receive_monotonic_ns are decimal strings to avoid JSON/JavaScript integer precision loss. Capture immediately around defined send/receive boundaries using the same monotonic clock and boot domain. They are not ROS simulated time or wall clock. CAN timestamps state direction, capture point, resolution, uncertainty and clock domain; unavailable hardware timestamps remain explicitly unsupported or unknown. A driver enqueue timestamp is not an on-wire timestamp.

MCU mcu_timestamp_us is uint32 with an explicit timer epoch, boot ID, domain and resolution. If source time is milliseconds, conversion to microseconds retains resolution_us=1000 and must preserve the original counter/wrap metadata in the adapter manifest. Unit conversion does not create microsecond accuracy. Existing production timestamps must not be silently reinterpreted as the new counter.

Independent MCU and Jetson timestamps cannot be subtracted. A causally associated trigger that occurs after command send and before event receive is bounded by the host interval. The synthetic example has host send=1,000,000,000 ns, receive=1,009,000,000 ns, MCU trigger=85,000 us in a separate clock. Its host interval is 9 ms; the trigger occurrence is only bounded inside that interval. This does not isolate one-way transport, control latency, motor response or braking time. Include timestamp resolution, capture jitter and all unbounded terms; report unknown uncertainty instead of fabricated confidence.

A separately validated offset model must specify offset interval, drift, validation horizon, capture points, reboot/wrap handling and calibration evidence. The validated_offset field is a data slot, not proof of validation. Review must reject unsupported absolute latency claims.

## MCU logging requirements for Oct 26–Nov 1

Use bounded non-blocking enqueue with static storage and bounded ISR work. No formatting, waits or host I/O in control-critical sections. Preserve safety action even if logging fails. Report normal/critical drops and queue high-water marks; test overflow, disconnection, reboot and wrap. Budget WCET and memory on the approved HIL branch. No firmware edits are part of this proposal.

## Draft verification

Install requirements-dev.txt in an isolated Python environment and run `python -m unittest discover -s tests -v`. These tests exercise schema/matching contracts with synthetic fixtures only. They do not execute ROS 2, CAN buses, firmware, controllers or a fault scenario. October 25 review must settle transport mapping and test completeness before freezing.
