"""Cross-platform `jade` entry point (the console_scripts target in pyproject.toml).

After `pip install -e .` (or via the installer), this gives every OS a `jade`
command on PATH — no bash wrapper needed.

  jade                     run now, voice-only headless (best for autostart)
  jade --interactive       add the desktop window + tray
  jade --no-welcome        skip the spoken greeting
  jade --install-autostart start automatically at login (systemd/launchd/Startup)
  jade --uninstall-autostart  remove the login autostart
"""
import envconfig  # noqa: F401  — load .env before any module reads os.environ
import argparse
import sys


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="jade", description="Jade — voice-first AI companion")
    ap.add_argument("--interactive", action="store_true",
                    help="Run with the desktop window + tray (default is voice-only headless).")
    ap.add_argument("--no-welcome", action="store_true",
                    help="Skip the spoken startup greeting.")
    ap.add_argument("--install-autostart", action="store_true",
                    help="Set Jade to start automatically at login (per-OS).")
    ap.add_argument("--uninstall-autostart", action="store_true",
                    help="Remove the login autostart entry.")
    args = ap.parse_args(argv)

    if args.install_autostart or args.uninstall_autostart:
        import autostart
        print(autostart.uninstall() if args.uninstall_autostart
              else autostart.install(interactive=args.interactive))
        return

    # Hand off to the full launcher, translating flags to its argv.
    fwd = []
    if not args.interactive:
        fwd.append("--voice-only")
    if args.no_welcome:
        fwd.append("--no-welcome")
    sys.argv = ["jade", *fwd]
    import launcher
    launcher.main()


if __name__ == "__main__":
    main()
