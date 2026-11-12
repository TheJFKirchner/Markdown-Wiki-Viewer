"""Entry point: python sb.py <command>. Run `python sb.py --help` for the commands."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from secondbrain.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
