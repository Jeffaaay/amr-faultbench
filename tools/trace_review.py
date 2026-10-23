"""Offline draft-contract review. Does not execute a controller or score an experiment."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
import math
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'trace_schema_v1.json').read_text(encoding='utf-8'))
VALIDATOR = Draft202012Validator(SCHEMA)
KEY = ('run_id', 'jetson_boot_id', 'mcu_boot_id', 'command_scope',
       'command_epoch', 'command_sequence')
MODULUS = 1 << 32


def read_events(path):
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def finite_only(value):
        raise ValueError('non-finite JSON number')

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('non-finite JSON number')
        return result

    with Path(path).open(encoding='utf-8') as stream:
        return [json.loads(line, object_pairs_hook=unique_keys,
                           parse_constant=finite_only, parse_float=finite_float)
                for line in stream if line.strip()]


def review(events):
    """Return conformance and evidence gaps, never a robot-success verdict."""
    issues, intervals, stops = [], [], []

    def issue(code, event_id=None, incomplete=False, path=None):
        issues.append({'code': code, 'event_id': event_id,
                       'severity': 'incomplete' if incomplete else 'invalid',
                       'path': path})

    def finish():
        invalid = any(i['severity'] == 'invalid' for i in issues)
        return {'status': 'INVALID' if invalid else ('INCOMPLETE' if issues else 'VALID'),
                'contract_only': True, 'experiment_verdict': None,
                'physical_stop_verified': False,
                'event_count': len(events), 'issues': issues,
                'command_host_intervals': [] if invalid else intervals,
                'reported_stop_observations': stops}

    if not events:
        issue('empty_capture')
        return finish()
    for index, event in enumerate(events):
        values = [event]
        while values:
            value = values.pop()
            if isinstance(value, dict):
                values.extend(value.values())
            elif isinstance(value, list):
                values.extend(value)
            elif isinstance(value, float) and not math.isfinite(value):
                issue('non_finite_number', str(index))
        for error in VALIDATOR.iter_errors(event):
            # Do not echo input values (a local trace may contain private data).
            issue('schema_' + error.validator, str(index),
                  path='/'.join(map(str, error.absolute_path)))
    if issues:
        return finish()

    by_id, sends = {}, defaultdict(list)
    for event in events:
        identity = event['event_id']
        if identity in by_id:
            issue('duplicate_event_id', identity)
        by_id[identity] = event
        if event['event_type'] == 'COMMAND_SEND':
            sends[tuple(event[k] for k in KEY)].append(event)
        if not event['synthetic'] and any(v is None for v in event['versions'].values()):
            issue('version_provenance_missing', identity, incomplete=True)
        if any(event['dropped_event_counters'].values()):
            issue('capture_reports_drops', identity, incomplete=True)
        if event['source'] == 'stm32' and event['mcu_timestamp_us'] is None:
            issue('mcu_time_missing', identity, incomplete=True)
        if event['can_frame'] is not None:
            frame = event['can_frame']
            if len(frame['data_hex']) != frame['dlc'] * 2:
                issue('can_dlc_payload_mismatch', identity)
        if event['can_timestamp_support'] != 'available' and event['can_timestamps']:
            issue('can_timestamp_support_conflict', identity)
        if event['mcu_counter'] is not None:
            counter = event['mcu_counter']
            raw, period = int(counter['raw_ticks']), counter['tick_period_us']
            if raw >= 1 << counter['bits']:
                issue('native_counter_out_of_range', identity)
            if event['mcu_resolution_us'] != period:
                issue('native_counter_resolution_mismatch', identity)
            if counter['wrap_epoch'] is None:
                if event['mcu_timestamp_us'] != (raw * period) % MODULUS:
                    issue('normalized_mcu_timestamp_mismatch', identity)
                if event['mcu_timer_epoch'] is not None:
                    issue('unknown_native_wrap_cannot_imply_epoch', identity)
                issue('native_wrap_epoch_unknown', identity, incomplete=True)
            else:
                expanded = (counter['wrap_epoch'] * (1 << counter['bits']) + raw) * period
                if event['mcu_timestamp_us'] != expanded % MODULUS:
                    issue('normalized_mcu_timestamp_mismatch', identity)
                if event['mcu_timer_epoch'] != expanded // MODULUS:
                    issue('normalized_mcu_epoch_mismatch', identity)
        if event['event_type'] == 'STOP_OBSERVED':
            observation = event['stop_evidence']
            stops.append({'event_id': identity, 'scope': observation['scope'],
                          'reported_result': observation['result'],
                          'evidence_level': event['evidence_level'],
                          'measurement_verified': False})
    for group in sends.values():
        if len(group) > 1:
            issue('duplicate_command_identity', group[0]['event_id'])

    children, indegree = defaultdict(list), dict.fromkeys(by_id, 0)
    for event in events:
        identity = event['event_id']
        for parent_id in event['parent_event_ids']:
            parent = by_id.get(parent_id)
            if parent is None:
                issue('parent_not_captured', identity, incomplete=True)
                continue
            if parent['run_id'] != event['run_id']:
                issue('parent_from_other_run', identity)
            if parent['synthetic'] != event['synthetic']:
                issue('mixed_synthetic_lineage', identity)
            if (event['event_type'] != 'BOOT' and parent['mcu_boot_id'] is not None
                    and event['mcu_boot_id'] is not None
                    and parent['mcu_boot_id'] != event['mcu_boot_id']):
                issue('parent_from_other_mcu_boot', identity)
            if parent['correlation_status'] == event['correlation_status'] == 'exact':
                if tuple(parent[k] for k in KEY) != tuple(event[k] for k in KEY):
                    issue('command_lineage_identity_mismatch', identity)
            children[parent_id].append(identity)
            indegree[identity] += 1
        if event['stop_evidence']:
            for source_id in event['stop_evidence']['source_event_ids']:
                source = by_id.get(source_id)
                if source is None:
                    issue('stop_evidence_not_captured', identity, incomplete=True)
                elif source['run_id'] != event['run_id']:
                    issue('stop_evidence_from_other_run', identity)
                elif source_id == identity:
                    issue('stop_evidence_self_reference', identity)
                elif (source['mcu_boot_id'] is not None and event['mcu_boot_id'] is not None
                      and source['mcu_boot_id'] != event['mcu_boot_id']):
                    issue('stop_evidence_from_other_mcu_boot', identity)
                elif event['stop_evidence']['scope'] == 'wheel_feedback' and source['event_type'] != 'CAN_RX':
                    issue('wheel_observation_requires_received_feedback', identity)
    queue, visited = deque(k for k, v in indegree.items() if v == 0), 0
    while queue:
        identity = queue.popleft()
        visited += 1
        for child in children[identity]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(by_id):
        issue('causal_cycle')
    if any(i['severity'] == 'invalid' for i in issues):
        return finish()

    def ancestor_ids(event):
        ancestors, queue = set(), deque(event['parent_event_ids'])
        while queue:
            ancestor = queue.popleft()
            if ancestor in ancestors:
                continue
            ancestors.add(ancestor)
            if ancestor in by_id:
                queue.extend(by_id[ancestor]['parent_event_ids'])
        return ancestors

    for receive in events:
        if receive['event_type'] != 'EVENT_RECEIVE' or receive['correlation_status'] != 'exact':
            continue
        key = tuple(receive[k] for k in KEY)
        group = sends.get(key, [])
        if len(group) != 1:
            issue('exact_command_not_captured', receive['event_id'], incomplete=True)
            continue
        command = group[0]
        ancestors = ancestor_ids(receive)
        if command['event_id'] not in ancestors:
            issue('command_has_no_explicit_causal_path', receive['event_id'])
            continue
        if command['host_clock_domain'] != receive['host_clock_domain']:
            issue('host_clock_domain_mismatch', receive['event_id'])
            continue
        start, end = int(command['send_monotonic_ns']), int(receive['receive_monotonic_ns'])
        if end < start:
            issue('negative_host_interval', receive['event_id'])
            continue
        invalid_can_time = False
        for ancestor_id in ancestors:
            ancestor = by_id.get(ancestor_id)
            if not ancestor:
                continue
            after_command = command['event_id'] in ancestor_ids(ancestor)
            for stamp in ancestor['can_timestamps']:
                if stamp['clock_domain'] == command['host_clock_domain']:
                    timestamp = int(stamp['timestamp_ns'])
                    if timestamp > end or (after_command and timestamp < start):
                        issue('causal_can_time_outside_host_interval', receive['event_id'])
                        invalid_can_time = True
        if not invalid_can_time:
            intervals.append({'command_event_id': command['event_id'],
                              'receive_event_id': receive['event_id'],
                              'host_interval_ns': str(end - start),
                              'meaning': 'host send-to-receive interval only; not isolated MCU or braking latency'})
    return finish()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    args = parser.parse_args(argv)
    try:
        result = review(read_events(args.trace))
    except (ValueError, OSError) as error:
        result = {'status': 'INVALID', 'contract_only': True,
                  'experiment_verdict': None, 'error': type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {'VALID': 0, 'INVALID': 1, 'INCOMPLETE': 2}[result['status']]


if __name__ == '__main__':
    sys.exit(main())
