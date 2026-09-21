from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from unity_bridge.host.registry import (ProcessLock, atomic_json, endpoint_path, host_home, launch, load_launcher, read_json,
                                        register_launcher, valid_launcher)
from unity_bridge.host.transport import TransportError


class HostRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host-registry-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.worker = self.root / "compiler"
        self.worker.write_text("fixture")

    def test_registration_is_idempotent_and_runtime_versions_are_isolated(self):
        first = register_launcher(sys.executable, str(self.worker), python_module=True, version="one", root=self.root)
        repeated = register_launcher(sys.executable, str(self.worker), python_module=True, version="one", root=self.root)
        self.assertEqual(first, repeated)
        updated = register_launcher(sys.executable, str(self.worker), python_module=True, version="two", root=self.root)
        self.assertNotEqual(first["runtimeId"], updated["runtimeId"])
        self.assertNotEqual(first["token"], updated["token"])
        self.assertEqual(load_launcher(self.root, first["runtimeId"]), first)
        self.assertEqual(load_launcher(self.root), updated)
        self.assertEqual(first["argv"][1:4], ["-m", "unity_bridge", "_host"])

    def test_single_instance_process_lock_and_release(self):
        first = ProcessLock(self.root / "lock")
        second = ProcessLock(self.root / "lock")
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.close()
        self.assertTrue(second.acquire())

    def test_missing_worker_does_not_publish_launcher(self):
        with self.assertRaises(ValueError):
            register_launcher(sys.executable, str(self.root / "missing"), version="one", root=self.root)
        self.assertIsNone(load_launcher(self.root))

    def test_host_root_override_and_malformed_launcher(self):
        with patch.dict(os.environ, {"UNITY_BRIDGE_HOST_HOME": str(self.root)}):
            self.assertEqual(host_home(), self.root.resolve())
        self.assertFalse(valid_launcher({"protocol": 1, "runtimeId": "../escape"}))
        self.assertIsNone(load_launcher(self.root, "../escape"))

    def registered_endpoint(self):
        descriptor = register_launcher(sys.executable, str(self.worker), python_module=True,
                                       version="one", root=self.root)
        endpoint = {"protocol": 1, "runtimeId": descriptor["runtimeId"], "version": "one",
                    "pid": os.getpid(), "port": 54321, "token": descriptor["token"]}
        atomic_json(endpoint_path(self.root, descriptor["runtimeId"]), endpoint)
        return descriptor, endpoint

    def test_reused_live_pid_without_an_authenticated_host_does_not_suppress_launch(self):
        descriptor, _ = self.registered_endpoint()
        with patch("unity_bridge.host.transport.post", side_effect=TransportError("not a host")) as health:
            with patch("subprocess.Popen", return_value=Mock(pid=12345)) as child:
                result = launch(self.root)
        self.assertTrue(result["started"])
        self.assertEqual(result["pid"], 12345)
        self.assertEqual(child.call_args.args[0], descriptor["argv"])
        self.assertEqual(health.call_args.args[2], "/health")
        self.assertLessEqual(health.call_args.args[4], 1.)

    def test_matching_authenticated_host_is_not_launched_twice(self):
        descriptor, endpoint = self.registered_endpoint()
        health_result = {key: endpoint[key] for key in ("protocol", "runtimeId", "version", "pid")}
        with patch("unity_bridge.host.transport.post", return_value=health_result) as health:
            with patch("subprocess.Popen") as child:
                result = launch(self.root)
        self.assertFalse(result["started"])
        child.assert_not_called()
        self.assertEqual(health.call_args.args[1], descriptor["token"])

    def test_wrong_runtime_health_response_is_not_treated_as_registered_host(self):
        _, endpoint = self.registered_endpoint()
        health_result = dict(endpoint, runtimeId="f" * 32)
        with patch("unity_bridge.host.transport.post", return_value=health_result):
            with patch("subprocess.Popen", return_value=Mock(pid=12345)) as child:
                result = launch(self.root)
        self.assertTrue(result["started"])
        child.assert_called_once()

    def test_atomic_publication_recovers_from_temporary_windows_reader_lock(self):
        path = self.root / 'state.json'
        atomic_json(path, {'value': 'previous'})
        original = os.replace
        attempts = []

        def locked_once(source, target):
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError('simulated sharing violation')
            return original(source, target)

        with patch('unity_bridge.host.registry._ACCESS_RETRIES', 4):
            with patch('unity_bridge.host.registry.os.replace', side_effect=locked_once):
                with patch('unity_bridge.host.registry.time.sleep') as sleep:
                    atomic_json(path, {'value': 'next'})
        self.assertEqual(read_json(path), {'value': 'next'})
        self.assertEqual(len(attempts), 2)
        sleep.assert_called_once_with(.01)
        self.assertEqual(list(self.root.glob('.host-*.tmp')), [])

    def test_persistent_publication_denial_is_bounded_and_preserves_old_file(self):
        path = self.root / 'state.json'
        atomic_json(path, {'value': 'previous'})
        with patch('unity_bridge.host.registry._ACCESS_RETRIES', 4):
            with patch('unity_bridge.host.registry.os.replace', side_effect=PermissionError('denied')) as replace:
                with patch('unity_bridge.host.registry.time.sleep') as sleep:
                    with self.assertRaises(PermissionError):
                        atomic_json(path, {'value': 'must-not-publish'})
        self.assertEqual(replace.call_count, 5)
        self.assertEqual(sleep.call_count, 4)
        self.assertEqual(read_json(path), {'value': 'previous'})
        self.assertEqual(list(self.root.glob('.host-*.tmp')), [])

    def test_registry_read_retries_transient_denial_without_touching_metadata(self):
        path = self.root / 'state.json'
        atomic_json(path, {'timestamp': 123})
        before = path.stat().st_mtime_ns
        with patch('unity_bridge.host.registry._ACCESS_RETRIES', 4):
            with patch.object(Path, 'read_text', side_effect=[PermissionError('busy'), '{"timestamp":123}']) as read:
                with patch('unity_bridge.host.registry.time.sleep') as sleep:
                    self.assertEqual(read_json(path), {'timestamp': 123})
        self.assertEqual(read.call_count, 2)
        sleep.assert_called_once_with(.01)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_successful_registry_io_never_sleeps(self):
        with patch('unity_bridge.host.registry.time.sleep') as sleep:
            atomic_json(self.root / 'state.json', {'value': 'ready'})
            self.assertEqual(read_json(self.root / 'state.json'), {'value': 'ready'})
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
