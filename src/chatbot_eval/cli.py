import argparse
import importlib
import json
from pathlib import Path
from .adapters import CallableAdapter, HttpAdapter, PortfolioAdapter
from .dataset import load_cases, verify_freeze
from .demo import respond
from .runner import run


def main(argv=None):
    parser = argparse.ArgumentParser(description="Capture chatbot behavior; phase one does not assign quality scores.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate bundled dataset and frozen hashes")
    capture = sub.add_parser("run")
    capture.add_argument("--target", choices=["demo", "http", "portfolio", "callable"], default="demo")
    capture.add_argument("--endpoint")
    capture.add_argument("--function", help="Trusted local Python function, module:name")
    capture.add_argument("--dataset", type=Path, help="Custom JSONL cases; required for non-demo targets")
    capture.add_argument("--split", choices=["development", "heldout"], default="development")
    capture.add_argument("--include-heldout", action="store_true", help="Explicitly unlock held-out collection")
    capture.add_argument("--allow-network", action="store_true")
    capture.add_argument("--max-calls", type=int, default=40)
    capture.add_argument("--output", type=Path, default=Path("reports/capture.json"))
    args = parser.parse_args(argv)
    try:
        manifest = verify_freeze()
        if args.command == "validate":
            cases = load_cases()
            print(f"Validated {len(cases)} cases; dataset {manifest['version']}")
            return 0
        if args.split == "heldout" and not args.include_heldout:
            parser.error("Held-out cases are reserved; use --include-heldout explicitly")
        if args.target != "demo" and args.dataset is None:
            parser.error("Provide --dataset for your target; the bundled corpus describes a fictional demo")
        if args.target in {"http", "portfolio"}:
            if not args.allow_network or not args.endpoint:
                parser.error("Network targets require --allow-network and --endpoint")
            adapter = (PortfolioAdapter if args.target == "portfolio" else HttpAdapter)(args.endpoint)
        elif args.target == "callable":
            if not args.function or ":" not in args.function:
                parser.error("Provide a trusted --function module:name")
            module, name = args.function.split(":", 1)
            adapter = CallableAdapter(getattr(importlib.import_module(module), name))
        else:
            adapter = CallableAdapter(respond)
        report = run(load_cases(args.dataset, args.split), adapter, target=args.target,
                     dataset_version="custom" if args.dataset else manifest["version"], max_calls=args.max_calls)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{report['summary']} - capture only, NOT a model quality score. Saved {args.output}")
        return 1 if report["summary"]["errors"] else 0
    except (ValueError, ImportError, AttributeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
