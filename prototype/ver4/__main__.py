"""Run V4 deterministic discovery from the command line."""

import argparse
import asyncio
import json

from prototype.ver4.planner import run_v4


def main() -> None:
    parser = argparse.ArgumentParser(description="Cyberstrike V4 deterministic discovery")
    parser.add_argument("target", help="single host or URL")
    parser.add_argument("--discovery-only", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_v4(args.target, run_planner=not args.discovery_only))
    print(json.dumps(result, default=lambda value: value.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
