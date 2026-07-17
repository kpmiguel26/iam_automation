from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "diagrams" / "source"
PNG = ROOT / "docs" / "diagrams" / "png"
SVG = ROOT / "docs" / "diagrams" / "svg"


def render_one(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["mmdc", "-i", str(source), "-o", str(output)], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Mermaid diagrams to PNG and SVG.")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    if not shutil.which("mmdc"):
        print("Mermaid CLI was not found. Install with: npm install -g @mermaid-js/mermaid-cli")
        return 1
    if args.check_only:
        print("Mermaid CLI is available.")
        return 0
    for source in sorted(SOURCE.glob("*.mmd")):
        render_one(source, PNG / f"{source.stem}.png")
        render_one(source, SVG / f"{source.stem}.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
