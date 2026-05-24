"""Cross-platform `jade` entry point (the console_scripts target in pyproject.toml).

After `pip install -e .` (or via the installer), this gives every OS a `jade`
command on PATH — no bash wrapper needed.

  jade                     run now, voice-only headless (best for autostart)
  jade --interactive       add the desktop window + tray
  jade --no-welcome        skip the spoken greeting
  jade --install-autostart start automatically at login (systemd/launchd/Startup)
  jade --uninstall-autostart  remove the login autostart
  jade --enroll            teach Jade your voice (unlocks personal memory for you only)
  jade --enroll-status     show whether a voiceprint is enrolled
  jade --reset-voiceprint  delete the voiceprint (turns voice gating off)
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
    ap.add_argument("--enroll", action="store_true",
                    help="Record your voice so Jade unlocks personal memory only for you.")
    ap.add_argument("--enroll-samples", type=int, default=5, metavar="N",
                    help="Number of voice clips to record when enrolling (default 5).")
    ap.add_argument("--enroll-status", action="store_true",
                    help="Show whether a voiceprint is enrolled.")
    ap.add_argument("--reset-voiceprint", action="store_true",
                    help="Delete the enrolled voiceprint (disables speaker gating).")
    args = ap.parse_args(argv)

    if args.install_autostart or args.uninstall_autostart:
        import autostart
        print(autostart.uninstall() if args.uninstall_autostart
              else autostart.install(interactive=args.interactive))
        return

    if args.enroll or args.enroll_status or args.reset_voiceprint:
        _voiceprint_command(args)
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


def _voiceprint_command(args) -> None:
    """Handle --enroll / --enroll-status / --reset-voiceprint."""
    from voice import speaker_id

    if args.reset_voiceprint:
        print("Voiceprint deleted — Jade will treat every voice as the owner again."
              if speaker_id.reset() else "No voiceprint was enrolled.")
        return

    if args.enroll_status:
        if speaker_id.is_enrolled():
            p = speaker_id.load_profile()
            print(f"Enrolled: {p['count']} sample(s), match threshold {p['threshold']:.3f}.")
            print(f"Profile: {speaker_id.PROFILE_PATH}")
        else:
            print("No voiceprint enrolled. Run `jade --enroll` to set one up.")
        return

    # --enroll
    print("Loading the speaker-recognition model (first run downloads ~20MB)...")
    if speaker_id._load_model() is None:
        print("Speaker recognition isn't available (is `speechbrain` installed?).")
        print("Jade still works fine without it — it just won't gate by voice.")
        sys.exit(1)

    samples = speaker_id.record_samples(n=max(2, args.enroll_samples))
    if len(samples) < 2:
        print("\nNot enough usable clips (need at least 2). Try again somewhere quieter.")
        sys.exit(1)

    print("Building your voiceprint...")
    stats = speaker_id.enroll(samples)
    print(f"\n✓ Enrolled from {stats['count']} clips.")
    print(f"  Self-consistency: mean {stats['self_sim_mean']:.3f}, "
          f"min {stats['self_sim_min']:.3f}")
    print(f"  Match threshold:  {stats['threshold']:.3f}")
    if stats["self_sim_min"] < 0.4:
        print("  ! Your samples varied a lot — if Jade keeps treating you as a guest,")
        print("    re-enroll in a quieter spot, or lower JADE_SPEAKER_THRESHOLD in .env.")
    print("\nJade will now load your personal memories only when she hears your voice.")
    print("Tune sensitivity any time with JADE_SPEAKER_THRESHOLD (lower = more lenient).")


if __name__ == "__main__":
    main()
