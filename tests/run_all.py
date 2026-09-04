#!/usr/bin/env python3
"""Lance toute la suite de tests.

    python3 tests/run_all.py           # tout
    python3 tests/run_all.py science   # un seul module
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODULES = ["test_science", "test_ingest", "test_api"]


def main() -> int:
    selected = sys.argv[1:]
    names = [m for m in MODULES
             if not selected or any(s in m for s in selected)]
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in names:
        suite.addTests(loader.loadTestsFromName(f"tests.{name}"))
    print(f"\n  Athlytics — {suite.countTestCases()} tests "
          f"({', '.join(names)})\n")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
