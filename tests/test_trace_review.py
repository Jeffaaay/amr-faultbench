"""Adversarial draft review cases; none execute firmware or a fault model."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from trace_review import read_events, review

COMMAND = read_events(ROOT / 'examples/command_safety_correlation.jsonl')
ASYNC = read_events(ROOT / 'examples/asynchronous_stop_unconfirmed.jsonl')


class TraceReviewTests(unittest.TestCase):
    def setUp(self):
        self.events = copy.deepcopy(COMMAND)

    def has_issue(self, events, code, status='INVALID'):
        result = review(events)
        self.assertEqual(result['status'], status)
        self.assertIn(code, [i['code'] for i in result['issues']])
        return result

    def test_valid_command_path_reports_only_host_interval(self):
        result = review(list(reversed(self.events)))
        self.assertEqual(result['status'], 'VALID')
        self.assertEqual(result['command_host_intervals'][0]['host_interval_ns'], '9000000')
        self.assertIsNone(result['experiment_verdict'])
        self.assertFalse(result['physical_stop_verified'])

    def test_async_fault_is_preserved_without_fabricated_command(self):
        result = review(ASYNC)
        self.assertEqual(result['status'], 'VALID')
        self.assertEqual(result['command_host_intervals'], [])
        self.assertEqual(result['reported_stop_observations'][0]['reported_result'], 'unconfirmed')
        self.assertFalse(result['physical_stop_verified'])

    def test_missing_parent_marks_incomplete_instead_of_success(self):
        self.has_issue(self.events[1:], 'parent_not_captured', 'INCOMPLETE')

    def test_drops_mark_capture_incomplete(self):
        self.events[2]['dropped_event_counters']['stm32'] = 1
        self.has_issue(self.events, 'capture_reports_drops', 'INCOMPLETE')

    def test_cyclic_lineage_is_invalid(self):
        self.events[0]['parent_event_ids'] = ['example-receive']
        self.has_issue(self.events, 'causal_cycle')

    def test_duplicate_command_identity_is_invalid(self):
        duplicate = copy.deepcopy(self.events[0]); duplicate['event_id'] = 'other-send'
        self.has_issue(self.events + [duplicate], 'duplicate_command_identity')

    def test_matching_sequence_without_path_does_not_create_causality(self):
        self.events[3]['parent_event_ids'] = []
        self.has_issue(self.events, 'command_has_no_explicit_causal_path')

    def test_cross_run_and_reboot_lineages_are_rejected(self):
        for field, code in [('run_id', 'parent_from_other_run'),
                            ('mcu_boot_id', 'parent_from_other_mcu_boot')]:
            with self.subTest(field=field):
                events = copy.deepcopy(COMMAND); events[3][field] = 'other'
                self.has_issue(events, code)

    def test_can_data_and_dlc_must_agree(self):
        self.events[1]['can_frame']['dlc'] = 8
        self.has_issue(self.events, 'can_dlc_payload_mismatch')

    def test_standard_can_id_and_direction_are_checked(self):
        self.events[1]['can_frame']['arbitration_id'] = 2048
        self.has_issue(self.events, 'schema_anyOf')
        self.events = copy.deepcopy(COMMAND)
        self.events[1]['can_timestamps'][0]['direction'] = 'RX'
        self.has_issue(self.events, 'schema_const')

    def test_can_timestamp_cannot_follow_its_receipt_on_same_clock(self):
        self.events[1]['can_timestamps'][0]['timestamp_ns'] = '1009000001'
        self.has_issue(self.events, 'causal_can_time_outside_host_interval')

    def test_cross_clock_values_are_not_numerically_compared(self):
        stamp = self.events[1]['can_timestamps'][0]
        stamp.update(clock_domain='unrelated-hardware-clock', timestamp_ns='9999999999999')
        self.assertEqual(review(self.events)['status'], 'VALID')

    def test_precommand_feedback_can_be_context_without_being_a_command_effect(self):
        feedback = copy.deepcopy(COMMAND[1])
        feedback.update(event_id='earlier-feedback', event_type='CAN_RX',
                        parent_event_ids=[], correlation_status='not_applicable', command_sequence=None)
        feedback['can_timestamps'][0].update(direction='RX', timestamp_ns='999000000')
        self.events[2]['parent_event_ids'].append('earlier-feedback')
        self.assertEqual(review(self.events + [feedback])['status'], 'VALID')

    def test_host_clock_change_and_negative_interval_are_invalid(self):
        self.events[3]['host_clock_domain'] = 'different-host-clock'
        self.has_issue(self.events, 'host_clock_domain_mismatch')
        self.events = copy.deepcopy(COMMAND)
        self.events[3]['receive_monotonic_ns'] = '999999999'
        self.has_issue(self.events, 'negative_host_interval')

    def test_ms_counter_normalization_crosses_us_wrap_without_reboot(self):
        for event in self.events[2:]:
            event['mcu_counter']['raw_ticks'] = '4294968'
            event['mcu_timestamp_us'] = 704
            event['mcu_timer_epoch'] = 1
        self.assertEqual(review(self.events)['status'], 'VALID')
        self.events[2]['mcu_timer_epoch'] = 0
        self.has_issue(self.events, 'normalized_mcu_epoch_mismatch')

    def test_native_ms_counter_wrap_is_not_microsecond_wrap(self):
        for event in self.events[2:]:
            event['mcu_counter'].update(raw_ticks='0', wrap_epoch=1)
            event['mcu_timestamp_us'] = 0
            event['mcu_timer_epoch'] = 1000
        self.assertEqual(review(self.events)['status'], 'VALID')

    def test_native_small_counter_wrap_is_normalized_with_its_width(self):
        for event in self.events[2:]:
            event['mcu_counter'].update(raw_ticks='1', bits=16, wrap_epoch=1)
            event['mcu_timestamp_us'] = 65537000
            event['mcu_timer_epoch'] = 0
        self.assertEqual(review(self.events)['status'], 'VALID')

    def test_unknown_wrap_is_not_silently_epoch_zero(self):
        self.events[2]['mcu_counter']['wrap_epoch'] = None
        self.has_issue(self.events, 'unknown_native_wrap_cannot_imply_epoch')
        self.events[2]['mcu_timer_epoch'] = None
        self.has_issue(self.events, 'native_wrap_epoch_unknown', 'INCOMPLETE')

    def test_counter_resolution_and_range_are_checked(self):
        self.events[2]['mcu_resolution_us'] = 1
        self.has_issue(self.events, 'native_counter_resolution_mismatch')
        self.events = copy.deepcopy(COMMAND)
        self.events[2]['mcu_counter']['raw_ticks'] = str(1 << 32)
        self.has_issue(self.events, 'native_counter_out_of_range')

    def test_stop_request_cannot_include_a_stationary_observation(self):
        events = copy.deepcopy(ASYNC)
        events[1]['stop_evidence'] = copy.deepcopy(events[2]['stop_evidence'])
        self.has_issue(events, 'schema_type')

    def test_stop_observation_needs_its_basis(self):
        events = copy.deepcopy(ASYNC)
        events[2]['stop_evidence']['result'] = 'stationary'
        self.has_issue(events, 'schema_anyOf')
        events[2]['stop_evidence']['scope'] = 'external_motion'
        self.has_issue(events, 'schema_anyOf')

    def test_transmission_is_not_received_wheel_feedback(self):
        events = copy.deepcopy(ASYNC)
        tx = copy.deepcopy(COMMAND[1]); tx.update(event_id='tx', parent_event_ids=[], correlation_status='not_applicable', command_sequence=None)
        events[2]['stop_evidence'].update(result='stationary', source_event_ids=['tx'])
        self.has_issue(events + [tx], 'wheel_observation_requires_received_feedback')

    def test_synthetic_record_cannot_be_labeled_robot_evidence(self):
        self.events[0]['evidence_level'] = 'robot'
        self.has_issue(self.events, 'schema_const')

    def test_real_record_with_missing_provenance_is_incomplete(self):
        for event in self.events:
            event.update(synthetic=False, evidence_level='HIL')
        self.has_issue(self.events, 'version_provenance_missing', 'INCOMPLETE')

    def test_nonfinite_numbers_and_duplicate_json_keys_are_rejected(self):
        self.events[0]['requested_command']['linear'] = float('nan')
        self.has_issue(self.events, 'non_finite_number')
        for raw in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e309}']:
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'trace.jsonl'; path.write_text(raw)
                with self.assertRaises(ValueError): read_events(path)

    def test_empty_input_is_not_a_successful_run(self):
        self.has_issue([], 'empty_capture')


if __name__ == '__main__':
    unittest.main()
