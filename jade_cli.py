"""Cross-platform `jade` entry point (the console_scripts target in pyproject.toml).

After `pip install -e .` (or via the installer), this gives every OS a `jade`
command on PATH — no bash wrapper needed.

  jade                     run now, voice-only headless (best for autostart)
  jade --interactive       add the desktop window + tray
  jade --no-welcome        skip the spoken greeting
  jade --install-autostart start automatically at login (systemd/launchd/Startup)
  jade --uninstall-autostart  remove the login autostart
  jade --enroll            teach Jade your voice (the owner — unlocks personal memory)
  jade --enroll --name Sam enroll a household member she'll greet by name
  jade --enroll-status     list enrolled voiceprints
  jade --reset-voiceprint  delete all voiceprints (turns voice gating off)
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
                    help="Record a voiceprint. Owner by default; add --name for a household member.")
    ap.add_argument("--name", metavar="NAME",
                    help="Name for this voiceprint (a non-owner household member).")
    ap.add_argument("--owner", action="store_true",
                    help="Enroll/replace the owner (the one whose personal memory unlocks).")
    ap.add_argument("--enroll-samples", type=int, default=5, metavar="N",
                    help="Number of voice clips to record when enrolling (default 5).")
    ap.add_argument("--enroll-status", action="store_true",
                    help="List enrolled voiceprints.")
    ap.add_argument("--reset-voiceprint", action="store_true",
                    help="Delete all enrolled voiceprints (disables speaker gating).")
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
        print("All voiceprints deleted — Jade will treat every voice as the owner again."
              if speaker_id.reset() else "No voiceprints were enrolled.")
        return

    if args.enroll_status:
        profiles = speaker_id.list_profiles()
        if not profiles:
            print("No voiceprints enrolled. Run `jade --enroll` to set one up.")
            return
        print(f"Enrolled voiceprints ({len(profiles)}):")
        for p in profiles:
            tag = " (owner)" if p["owner"] else ""
            print(f"  - {p['name']}{tag}: {p['count']} clip(s), threshold {p['threshold']:.3f}")
        return

    # --enroll
    name = (args.name or "owner").strip()
    is_owner = args.owner or not args.name  # no name given → enrolling the owner
    role = "the owner" if is_owner else f"household member '{name}'"

    print(f"Enrolling {role}.")
    print("Loading the speaker-recognition model (first run downloads ~20MB)...")
    if speaker_id._load_model() is None:
        print("Speaker recognition isn't available (is `speechbrain` installed?).")
        print("Jade still works fine without it — it just won't gate by voice.")
        sys.exit(1)

    samples = speaker_id.record_samples(n=max(2, args.enroll_samples))
    if len(samples) < 2:
        print("\nNot enough usable clips (need at least 2). Try again somewhere quieter.")
        sys.exit(1)

    print(f"Building the voiceprint for {name}...")
    stats = speaker_id.enroll(samples, name=name, is_owner=is_owner)
    print(f"\n✓ Enrolled {stats['name']}{' (owner)' if stats['owner'] else ''} "
          f"from {stats['count']} clips.")
    print(f"  Self-consistency: mean {stats['self_sim_mean']:.3f}, "
          f"min {stats['self_sim_min']:.3f}")
    print(f"  Match threshold:  {stats['threshold']:.3f}")
    if stats["self_sim_min"] < 0.4:
        print("  ! Samples varied a lot — if recognition is flaky, re-enroll in a")
        print("    quieter spot, or lower JADE_SPEAKER_THRESHOLD in .env.")
    if stats["owner"]:
        print("\nJade will load personal memories only when she hears the owner's voice.")
    else:
        print(f"\nJade will greet {name} by name; the owner's private memory stays private.")


if __name__ == "__main__":
    main()
