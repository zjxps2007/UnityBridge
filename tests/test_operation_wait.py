from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from unity_bridge import CommandResponse, Instance, UnityBridgeAdapter, UnityBridgeError, UnityClient


class OperationWaitTests(unittest.TestCase):
    def run_wait(self, *, wrong_id=False, stable_sec=None, never_complete=False, receipt_state=None,
                 lost_first=False, rejected_first=None):
        instance = Instance("ready", "D:/ReceiptProject", 8090, 123, timestamp=100)
        client = UnityClient()
        adapter = UnityBridgeAdapter(client=client)
        clock, calls = {"now": 0.}, []

        def query(command, params, **kwargs):
            calls.append((command, params))
            self.assertEqual(command, "get_editor_state")
            self.assertLessEqual(kwargs["timeout_ms"], 1_000)
            if lost_first and len(calls) == 1:
                clock["now"] += kwargs["timeout_ms"] / 1000
                return CommandResponse(False, "old listener closed", {"completion": "unknown"})
            if rejected_first and len(calls) == 1:
                return CommandResponse(False, rejected_first, {"completion": "not_started", "reason": rejected_first})
            return CommandResponse(True, "state", {"requestId": params["request_id"], "instance": instance.to_dict(),
                "operation": {"id": "unrelated" if wrong_id else "receipt-1",
                              "state": receipt_state or ("pending" if never_complete or len(calls) == 1 else "completed")}})

        def advance(seconds):
            clock["now"] += seconds

        with (patch.object(adapter, "_resolve_same_project", return_value=instance),
              patch.object(client, "call", side_effect=query),
              patch("unity_bridge.client.time.monotonic", side_effect=lambda: clock["now"]),
              patch("unity_bridge.client.time.sleep", side_effect=advance)):
            result = adapter._wait_after_operation(CommandResponse(True, "requested", {"operation_id": "receipt-1"}),
                instance, "ready", timeout_sec=2, poll_interval_sec=None, stable_sec=stable_sec)
        return result, clock["now"], calls

    def test_an_old_ready_state_cannot_complete_a_pending_operation(self):
        result, elapsed, calls = self.run_wait()
        self.assertEqual(result.state, "ready")
        self.assertEqual(len(calls), 2)
        self.assertAlmostEqual(elapsed, .05)

    def test_explicit_stability_interval_remains_respected(self):
        _, elapsed, _ = self.run_wait(stable_sec=.2)
        self.assertGreaterEqual(elapsed, .25)

    def test_unrelated_receipt_cannot_confirm_execution(self):
        with self.assertRaisesRegex(UnityBridgeError, "invalid operation confirmation"):
            self.run_wait(wrong_id=True)

    def test_pending_receipt_times_out_without_resending_mutation(self):
        with self.assertRaises(UnityBridgeError):
            self.run_wait(never_complete=True)

    def test_cancelled_operation_is_not_success_even_if_editor_is_ready(self):
        with self.assertRaisesRegex(UnityBridgeError, "cancelled"):
            self.run_wait(receipt_state="cancelled")

    def test_lost_receipt_fails_instead_of_replaying_the_operation(self):
        with self.assertRaisesRegex(UnityBridgeError, "was not repeated"):
            self.run_wait(receipt_state="unknown")

    def test_lost_control_response_leaves_time_to_confirm_the_new_listener(self):
        result, elapsed, calls = self.run_wait(lost_first=True)
        self.assertEqual(result.state, "ready")
        self.assertEqual(len(calls), 2)
        self.assertAlmostEqual(elapsed, 1.05)

    def test_reload_rejections_retry_only_the_live_read(self):
        for reason in ("expired", "not_ready", "unsupported_connector", "stale_domain"):
            with self.subTest(reason=reason):
                _, elapsed, calls = self.run_wait(rejected_first=reason)
                self.assertEqual(len(calls), 2)
                self.assertAlmostEqual(elapsed, .05)

    def test_authentication_failure_is_not_hidden_by_retry(self):
        with self.assertRaisesRegex(UnityBridgeError, "unauthorized"):
            self.run_wait(rejected_first="unauthorized")

    def test_older_connector_keeps_its_conservative_wait(self):
        instance = Instance("ready", "D:/ReceiptProject", 8090, 123, timestamp=100)
        adapter = UnityBridgeAdapter(client=UnityClient())
        with patch("unity_bridge.adapter.wait_for_state", return_value=instance) as wait:
            adapter._wait_after_operation(CommandResponse(True, "requested", {}), instance, "ready",
                                          timeout_sec=5, poll_interval_sec=None, stable_sec=None)
        self.assertEqual(wait.call_args.kwargs["stable_sec"], .5)
        self.assertEqual(wait.call_args.kwargs["poll_interval_sec"], .5)
        self.assertEqual(wait.call_args.kwargs["after_timestamp"], 100)
