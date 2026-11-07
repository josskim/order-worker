"""Collect live marketplace categories without saving or submitting products."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from order_worker.category_catalog import main

if __name__ == '__main__':
    raise SystemExit(main())
