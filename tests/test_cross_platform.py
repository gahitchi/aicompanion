"""Cross-platform import + autostart-builder smoke test.

Runs on Linux / macOS / Windows in CI to prove the OS-integration layer
(Phases 1-3) imports cleanly and produces the right per-OS artifacts on every
platform. It deliberately does NOT install the heavy ML stack
(torch / faster-whisper / chromadb / kokoro) — that's validated by actually
running the installer. The point here is to catch a Windows/macOS-only import
error or a broken autostart builder before a user hits it.

Standalone (no pytest needed):  python tests/test_cross_platform.py
"""
import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_failures = []


def check(name, fn):
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:  # noqa: BLE001
        _failures.append((name, e))
        print(f"FAIL  {name}: {type(e).__name__}: {e}")


def _imports():
    # The cross-platform layer must import with stdlib only (python-dotenv is
    # optional and guarded inside envconfig).
    for m in ("platform_io", "autostart", "jade_cli", "envconfig"):
        importlib.import_module(m)


def _installer_module():
    # installer/setup.py is a script dir (not a package) — load it by path.
    path = ROOT / "installer" / "setup.py"
    spec = importlib.util.spec_from_file_location("jade_installer_setup", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.DEFAULT_MODEL, "installer is missing DEFAULT_MODEL"


def _platform_detection():
    import platform_io as pio
    assert pio.platform_name(), "platform_name() returned empty"
    assert sum([pio.IS_LINUX, pio.IS_MAC, pio.IS_WINDOWS]) == 1, \
        "exactly one OS flag must be set"


def _autostart_builders():
    # Pure builders run on any OS and must produce each platform's artifact.
    import autostart
    cmd = ["/opt/jade/jade", "--interactive"]
    unit = autostart._systemd_unit(cmd)
    assert "ExecStart=" in unit and "jade" in unit, "systemd unit malformed"
    plist = autostart._launchd_plist(cmd)
    assert b"com.jade.companion" in plist and b"ProgramArguments" in plist, \
        "launchd plist malformed"
    shim = autostart._windows_cmd(cmd)
    assert "start" in shim and "jade" in shim, "windows shim malformed"


def _cli_help():
    import jade_cli
    try:
        jade_cli.main(["--help"])
    except SystemExit as e:  # argparse exits 0 after printing help
        assert e.code == 0, f"--help exited {e.code}"
    else:
        raise AssertionError("--help did not exit")


check("import cross-platform modules", _imports)
check("import installer/setup.py", _installer_module)
check("platform_io detection", _platform_detection)
check("autostart builders (all OSes)", _autostart_builders)
check("jade --help parses", _cli_help)

print()
if _failures:
    print(f"{len(_failures)} check(s) failed.")
    sys.exit(1)
print("All cross-platform checks passed.")
