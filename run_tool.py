"""PyInstaller entry point for Cluster Debug Tool.

On Windows, when launched by double-click, the console window normally closes
immediately on exit (success or error). This wrapper keeps the window open so
the user can read the output / error before it disappears.

Pass --no-pause anywhere on the command line to skip the prompt.
"""
import sys
import traceback


def _should_pause(argv):
    """Pause before exit when running as a frozen exe on Windows,
    unless --no-pause is passed."""
    if "--no-pause" in argv:
        return False
    if not sys.platform.startswith("win"):
        return False
    # Only pause if we're a PyInstaller-frozen exe (covers double-click case)
    return getattr(sys, "frozen", False)


def _pause_before_exit():
    try:
        input("\n[ Press Enter to close this window ] ")
    except Exception:
        pass


def main_wrapped():
    pause = _should_pause(sys.argv)
    # Strip --no-pause so it doesn't reach argparse
    sys.argv = [a for a in sys.argv if a != "--no-pause"]

    exit_code = 0
    try:
        from env_validation_tool.cli import main
        exit_code = main() or 0
    except KeyboardInterrupt:
        print("\n[interrupted]")
        exit_code = 130
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
    except Exception:
        print("\n[ERROR] An unexpected error occurred:\n")
        traceback.print_exc()
        exit_code = 1

    if pause:
        _pause_before_exit()

    sys.exit(exit_code)


if __name__ == "__main__":
    main_wrapped()
