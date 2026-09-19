"""Cheap runtime identification shared by installed and compiled entry points."""
import sys


def is_standalone():
    # Nuitka deliberately does not set sys.frozen. This module is included in
    # the standalone build; source/pip installations have neither marker.
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def executable_path():
    # Nuitka standalone preserves Python's sys.executable semantics; argv[0]
    # identifies the compiled entry point. PyInstaller uses its bootloader path.
    return sys.argv[0] if "__compiled__" in globals() else sys.executable
