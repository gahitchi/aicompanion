"""Install / uninstall login autostart for Jade, per operating system.

  Linux   — systemd user unit  (~/.config/systemd/user/jade.service)
  macOS   — LaunchAgent plist  (~/Library/LaunchAgents/com.jade.companion.plist)
  Windows — a .cmd shim in the user's Startup folder

The content builders (`_systemd_unit`, `_launchd_plist`, `_windows_cmd`) are pure
functions so they can be unit-tested on any OS. Install/uninstall are best-effort
and return a human-readable status string.
"""
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import platform_io as pio

LABEL = "com.jade.companion"


def _run_command(interactive: bool) -> list[str]:
    """The argv autostart should launch. Prefer the installed `jade` console
    script; fall back to running launcher.py with the current interpreter.

    `jade` defaults to voice-only and takes --interactive; launcher.py is the
    reverse (defaults interactive, takes --voice-only), so flags differ by path.
    """
    exe = shutil.which("jade")
    if exe:
        return [exe] + (["--interactive"] if interactive else [])
    launcher = str(Path(__file__).resolve().parent / "launcher.py")
    return [sys.executable, launcher] + ([] if interactive else ["--voice-only"])


# --------------------------------------------------------------------------- #
# Content builders (pure)
# --------------------------------------------------------------------------- #
def _systemd_unit(cmd: list[str]) -> str:
    exec_start = " ".join(shlex.quote(c) for c in cmd)
    return f"""[Unit]
Description=Jade — voice-first AI companion
After=graphical-session.target sound.target
Wants=graphical-session.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def _launchd_plist(cmd: list[str]) -> bytes:
    logs = Path.home() / "Library" / "Logs" / "jade.log"
    data = {
        "Label": LABEL,
        "ProgramArguments": cmd,
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(logs),
        "StandardErrorPath": str(logs),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }
    return plistlib.dumps(data)


def _windows_cmd(cmd: list[str]) -> str:
    # `start "" /min` launches detached and minimized; quote args with spaces.
    line = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    return f'@echo off\r\nstart "" /min {line}\r\n'


# --------------------------------------------------------------------------- #
# Install / uninstall
# --------------------------------------------------------------------------- #
def install(interactive: bool = False) -> str:
    cmd = _run_command(interactive)
    if pio.IS_LINUX:
        return _install_linux(cmd)
    if pio.IS_MAC:
        return _install_macos(cmd)
    if pio.IS_WINDOWS:
        return _install_windows(cmd)
    return f"Autostart isn't supported on {pio.platform_name()}."


def uninstall() -> str:
    if pio.IS_LINUX:
        return _uninstall_linux()
    if pio.IS_MAC:
        return _uninstall_macos()
    if pio.IS_WINDOWS:
        return _uninstall_windows()
    return f"Autostart isn't supported on {pio.platform_name()}."


def _install_linux(cmd: list[str]) -> str:
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit = unit_dir / "jade.service"
    if unit.exists():
        return (f"systemd unit already present at {unit} — left as-is to preserve "
                f"your settings. Enable with: systemctl --user enable --now jade")
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit.write_text(_systemd_unit(cmd))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", "jade"], check=False)
    return f"Installed and enabled systemd user service at {unit}."


def _uninstall_linux() -> str:
    # Disable + stop, but keep the unit file so tuned Environment= lines survive.
    subprocess.run(["systemctl", "--user", "disable", "--now", "jade"],
                   check=False, capture_output=True)
    return ("Disabled the systemd autostart. The unit file was kept; re-enable "
            "with: systemctl --user enable --now jade")


def _install_macos(cmd: list[str]) -> str:
    la = Path.home() / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    (Path.home() / "Library" / "Logs").mkdir(parents=True, exist_ok=True)
    plist = la / f"{LABEL}.plist"
    plist.write_bytes(_launchd_plist(cmd))
    subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(plist)], check=False)
    return f"Installed LaunchAgent at {plist} (loads at login)."


def _uninstall_macos() -> str:
    plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
    if plist.exists():
        plist.unlink()
        return f"Removed LaunchAgent {plist}."
    return "No LaunchAgent was installed."


def _startup_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _install_windows(cmd: list[str]) -> str:
    startup = _startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    shim = startup / "Jade.cmd"
    shim.write_text(_windows_cmd(cmd), encoding="utf-8")
    return f"Installed Startup shim at {shim} (runs at login)."


def _uninstall_windows() -> str:
    shim = _startup_dir() / "Jade.cmd"
    if shim.exists():
        shim.unlink()
        return f"Removed Startup shim {shim}."
    return "No Startup shim was installed."
