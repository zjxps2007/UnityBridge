import sys
import unittest
from unittest.mock import patch

from unity_bridge import _runtime


class RuntimeTests(unittest.TestCase):
    def test_source_uses_python_executable(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertFalse(_runtime.is_standalone())
            self.assertEqual(_runtime.executable_path(), sys.executable)

    def test_pyinstaller_uses_bootloader_executable(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', '/bundle/unity-bridge'):
            self.assertTrue(_runtime.is_standalone())
            self.assertEqual(_runtime.executable_path(), '/bundle/unity-bridge')

    def test_nuitka_uses_compiled_entry_for_host_identity_and_update_location(self):
        with patch.object(_runtime, '__compiled__', object(), create=True), patch.object(sys, 'argv', ['/bundle/unity-bridge']):
            self.assertTrue(_runtime.is_standalone())
            self.assertEqual(_runtime.executable_path(), '/bundle/unity-bridge')
