"""Synthetic contract tests for the October 25 review; no hardware adapters."""
import copy
import json
from pathlib import Path
import unittest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'trace_schema_v1.json').read_text())
FIXTURE = [json.loads(line) for line in (ROOT / 'examples/command_safety_correlation.jsonl').read_text().splitlines()]
VALIDATOR = Draft202012Validator(SCHEMA)
KEY = ('run_id', 'jetson_boot_id', 'mcu_boot_id', 'command_scope', 'command_epoch', 'command_sequence')


def reconcile(events):
    """Review oracle for explicit synthetic lineage, not a production matcher."""
    by_id, sends, results = {}, {}, []
    for event in events:
        VALIDATOR.validate(event)
        if event['event_id'] in by_id:
            raise ValueError('duplicate event ID')
        by_id[event['event_id']] = event
        if not event['synthetic'] and any(v is None for v in event['versions'].values()):
            raise ValueError('real evidence lacks version/configuration provenance')
        if event['event_type'] == 'COMMAND_SEND':
            key = tuple(event[k] for k in KEY)
            if key in sends:
                raise ValueError('ambiguous duplicate command identity')
            sends[key] = event
    for receive in events:
        if receive['event_type'] != 'EVENT_RECEIVE':
            continue
        if receive['correlation_status'] != 'exact':
            raise ValueError('unresolved association cannot support a timing bound')
        key = tuple(receive[k] for k in KEY)
        command = sends.get(key)
        if command is None:
            raise ValueError('no command in the same boot/session/epoch')
        parents = [by_id[p] for p in receive['parent_event_ids'] if p in by_id]
        triggers = [p for p in parents if p['event_type'] == 'SAFETY_TRIGGER']
        if len(triggers) != 1:
            raise ValueError('missing or ambiguous MCU trigger')
        trigger = triggers[0]
        if tuple(trigger[k] for k in KEY) != key or command['event_id'] not in trigger['parent_event_ids']:
            raise ValueError('trigger lacks explicit command lineage')
        can_parents = [by_id[p] for p in trigger['parent_event_ids'] if p in by_id and by_id[p]['source'] == 'can']
        if len(can_parents) != 1 or tuple(can_parents[0][k] for k in KEY) != key:
            raise ValueError('missing or conflicting CAN lineage')
        if command['event_id'] not in can_parents[0]['parent_event_ids']:
            raise ValueError('CAN event lacks explicit command lineage')
        if command['host_clock_domain'] != receive['host_clock_domain']:
            raise ValueError('host clock domains differ')
        width = int(receive['receive_monotonic_ns']) - int(command['send_monotonic_ns'])
        if width < 0:
            raise ValueError('receive precedes send in the same host clock')
        results.append({'command_sequence': key[-1], 'host_interval_ns': width,
                        'complete_capture': all(not any(e['dropped_event_counters'].values()) for e in events)})
    return results


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.events = copy.deepcopy(FIXTURE)

    def test_schema_and_examples(self):
        Draft202012Validator.check_schema(SCHEMA)
        for event in self.events:
            VALIDATOR.validate(event)

    def test_correlates_ros_can_mcu_and_host_receive_out_of_order(self):
        self.assertEqual(reconcile(list(reversed(self.events))), [
            {'command_sequence': 42, 'host_interval_ns': 9000000, 'complete_capture': True}])

    def test_mcu_clock_is_never_subtracted_from_host_clock(self):
        self.events[2]['mcu_timestamp_us'] = 4294967295
        self.assertEqual(reconcile(self.events)[0]['host_interval_ns'], 9000000)

    def test_wrong_units_rejected(self):
        self.events[0]['requested_command']['linear_unit'] = 'mm/s'
        with self.assertRaises(ValidationError): reconcile(self.events)

    def test_missing_boot_id_rejected(self):
        self.events[2]['mcu_boot_id'] = None
        with self.assertRaises(ValidationError): reconcile(self.events)

    def test_sequence_wrap_epoch_prevents_false_match(self):
        self.events[0]['command_epoch'] = 1
        with self.assertRaisesRegex(ValueError, 'no command'): reconcile(self.events)

    def test_mcu_reboot_prevents_false_match(self):
        self.events[0]['mcu_boot_id'] = 'new-boot'
        with self.assertRaisesRegex(ValueError, 'no command'): reconcile(self.events)

    def test_duplicate_command_is_ambiguous(self):
        duplicate = copy.deepcopy(self.events[0]); duplicate['event_id'] = 'duplicate'
        with self.assertRaisesRegex(ValueError, 'ambiguous'): reconcile(self.events + [duplicate])

    def test_missing_trigger_is_not_guessed(self):
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'): reconcile(self.events[:2] + self.events[3:])

    def test_can_lineage_mismatch_rejected(self):
        self.events[1]['command_sequence'] = 41
        with self.assertRaisesRegex(ValueError, 'CAN lineage'): reconcile(self.events)

    def test_clock_domain_mismatch_rejected(self):
        self.events[3]['host_clock_domain'] = 'other-boot:CLOCK_MONOTONIC'
        with self.assertRaisesRegex(ValueError, 'clock domains'): reconcile(self.events)

    def test_drop_counters_mark_incomplete_capture(self):
        self.events[2]['dropped_event_counters']['stm32'] = 1
        self.assertFalse(reconcile(self.events)[0]['complete_capture'])

    def test_can_timestamp_support_requires_a_timestamp(self):
        self.events[1]['can_timestamps'] = []
        with self.assertRaises(ValidationError): reconcile(self.events)

    def test_real_evidence_requires_version_provenance(self):
        self.events[0]['synthetic'] = False
        with self.assertRaisesRegex(ValueError, 'provenance'): reconcile(self.events)


if __name__ == '__main__':
    unittest.main()
