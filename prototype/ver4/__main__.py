"""Run V4 deterministic discovery from the command line."""

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from prototype.ver4.planner import run_v4


def main() -> None:
    parser = argparse.ArgumentParser(description="Cyberstrike V4 deterministic discovery")
    parser.add_argument("target", help="single host or URL")
    parser.add_argument("--ports", nargs="+", help="optional Nmap ports/ranges to scan in addition to the base scan")
    parser.add_argument("--discovery-only", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_v4(args.target, ports=args.ports, run_planner=not args.discovery_only))

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"discovery_{uuid.uuid4()}.json"
    output_path.write_text(
        json.dumps(result, default=lambda value: value.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
