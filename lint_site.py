#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_required_surfaces.py")],
        cwd=ROOT,
        check=True,
    )
    print("site lint passed: exact-50 surfaces and augment-only integrity")


if __name__ == "__main__":
    main()
