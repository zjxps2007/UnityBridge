"""Routing must never replay a potentially executed Unity mutation."""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from unity_bridge.client import CommandResponse, Instance, UnityClient, UnityConnectionError
from unity_bridge._cli.arguments import build_parser, parse_direct_tool_args


class HostClientRoutingTests(unittest.TestCase):
    def setUp(self):
        self.instance = Instance("ready", "D:/Game", 8090, 321,
                                 bridge_protocol=1, domain_id="domain", reference_generation=7)

    def test_host_unknown_is_not_replayed_directly(self):
        unknown = CommandResponse(True, "Completion unknown", {"completion": "unknown"})
        with patch("unity_bridge.host.try_host_command", return_value=unknown), \
                patch("unity_bridge.client.send_command") as direct:
            result = UnityClient().call("editor", {"action": "play"}, instance=self.instance)
        self.assertIs(result, unknown)
        direct.assert_not_called()

    def test_host_connection_failure_is_not_replayed(self):
        with patch("unity_bridge.host.try_host_command", side_effect=UnityConnectionError("lost")), \
                patch("unity_bridge.client.send_command") as direct:
            with self.assertRaises(UnityConnectionError):
                UnityClient().call("exec", {"code": "ChangeScene();"}, instance=self.instance)
        direct.assert_not_called()

    def test_auto_can_fall_back_before_submission(self):
        response = CommandResponse(True, "OK")
        with patch("unity_bridge.host.try_host_command", return_value=None) as host, \
                patch("unity_bridge.client.send_command", return_value=response) as direct:
            result = UnityClient(timeout_ms=1234).call("console", {}, instance=self.instance)
        self.assertIs(result, response)
        self.assertEqual(host.call_args.args[3], 1234)
        direct.assert_called_once_with(self.instance, "console", {}, timeout_ms=1234)

    def test_forced_host_does_not_silently_use_legacy(self):
        with patch("unity_bridge.host.try_host_command", return_value=None), \
                patch("unity_bridge.client.send_command") as direct:
            with self.assertRaises(UnityConnectionError):
                UnityClient(backend="host").call("console", instance=self.instance)
        direct.assert_not_called()

    def test_legacy_connector_keeps_direct_transport(self):
        old = replace(self.instance, bridge_protocol=0)
        with patch("unity_bridge.host.try_host_command") as host, \
                patch("unity_bridge.client.send_command", return_value=CommandResponse(True, "OK")) as direct:
            UnityClient().call("console", instance=old)
        host.assert_not_called()
        direct.assert_called_once()

    def test_compiler_override_preserves_direct_route(self):
        with patch("unity_bridge.host.try_host_command") as host, \
                patch("unity_bridge.client.send_command", return_value=CommandResponse(True, "OK")) as direct:
            UnityClient(backend="host").call("exec", {"code": "return 1;", "csc": "custom.exe"},
                                             instance=self.instance)
        host.assert_not_called()
        direct.assert_called_once()

    def test_host_status_cannot_refresh_unity_or_claim_ready(self):
        reloading = replace(self.instance, state="reloading", timestamp=123)
        client = UnityClient()
        with patch.object(client, "discover_instance", return_value=reloading), \
                patch("unity_bridge.host.host_status", return_value={"state": "running", "pid": 999}):
            result = client.status()
        self.assertEqual((result.state, result.timestamp, result.pid, result.port),
                         ("reloading", 123, 321, 8090))
        self.assertEqual(result.to_dict()["host"]["state"], "running")
        self.assertEqual(Instance.from_dict(result.to_dict()).domain_id, "domain")

    def test_backend_option_supports_builtin_and_direct_tools(self):
        self.assertEqual(build_parser().parse_args(["console", "--backend", "legacy"]).backend, "legacy")
        direct = parse_direct_tool_args(["--backend", "host", "project_tool", "--value", "4"])
        self.assertEqual(direct.backend, "host")
        self.assertEqual(direct.params, {"value": 4})


if __name__ == "__main__":
    unittest.main()
