"""The shardcheck command line. Check never writes files."""

import argparse
import json
import sys

from . import __version__
from .core import Invalid, check, record


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline CI artifact completeness, not test success or provenance.")
    parser.add_argument("--version", action="version", version=f"shardcheck {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="create a new sidecar alongside artifact files")
    rec.add_argument("--root", default=".")
    rec.add_argument("--output", required=True, help="relative path ending .shardcheck.json; must not exist")
    rec.add_argument("--shard-id", required=True)
    rec.add_argument("--attempt", required=True, type=int)
    rec.add_argument("files", nargs="+", help="relative to output's directory, use -- before filenames beginning -")
    chk = sub.add_parser("check", help="check a downloaded artifact tree read-only")
    chk.add_argument("--root", required=True)
    chk.add_argument("--expected", required=True, help="explicit expected-shard manifest JSON")
    chk.add_argument("--format", choices=("text", "json"), default="text")
    for command in (rec, chk):
        command.add_argument("--run-id", required=True)
        command.add_argument("--revision", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            record(args.root, args.output, args.run_id, args.revision, args.shard_id, args.attempt, args.files)
            print(f"recorded {args.output}")
        else:
            result = check(args.root, args.expected, args.run_id, args.revision)
            if args.format == "json":
                print(json.dumps(result, sort_keys=True, ensure_ascii=True))
            else:
                for item in result["selected"]:
                    for path in item["paths"]:
                        print(path)
        return 0
    except (Invalid, OSError, UnicodeError, ValueError) as exc:
        if args.command == "check" and args.format == "json":
            print(json.dumps({"schema_version": 1, "complete": False, "error": str(exc)}, sort_keys=True))
        else:
            print(f"shardcheck: {exc}", file=sys.stderr)
        return 1
