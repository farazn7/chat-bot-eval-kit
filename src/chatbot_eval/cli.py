import argparse
import importlib
import json
from pathlib import Path
from .adapters import CallableAdapter, HttpAdapter, PortfolioAdapter
from .dataset import load_cases, verify_freeze
from .demo import respond
from .runner import run
from .evaluation import evaluate, compare
from .judging import judge, review_template, calibrate
from .experiment import load_experiment, plan_experiment, run_experiment


def main(argv=None):
    parser = argparse.ArgumentParser(description="Capture chatbot behavior and measure evidence coverage.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate bundled dataset and frozen hashes")
    experiment = sub.add_parser('experiment', help='Plan a frozen multi-turn run; execution is explicit')
    experiment.add_argument('directory', type=Path)
    experiment.add_argument('--variants', nargs='+', default=['minimal', 'restrictive'])
    experiment.add_argument('--split', choices=['development', 'heldout'], default='development')
    experiment.add_argument('--include-heldout', action='store_true')
    experiment.add_argument('--max-calls', type=int, default=200)
    experiment.add_argument('--execute', action='store_true', help='Permit calls through the trusted provider factory')
    experiment.add_argument('--function', help='Trusted module:factory returning a stateless provider callable')
    experiment.add_argument('--provider-id')
    experiment.add_argument('--output', type=Path)
    scoring = sub.add_parser('evaluate', help='Measure saved responses offline; not answer correctness')
    scoring.add_argument('capture', type=Path)
    scoring.add_argument('--documents', type=Path, required=True)
    scoring.add_argument('--output', type=Path, default=Path('reports/evaluation.json'))
    comparison = sub.add_parser('compare', help='Compare evidence metrics on identical cases')
    comparison.add_argument('before', type=Path)
    comparison.add_argument('after', type=Path)
    comparison.add_argument('--output', type=Path, default=Path('reports/comparison.json'))
    for name in ('judge', 'review-template'):
        command = sub.add_parser(name)
        command.add_argument('capture', type=Path)
        command.add_argument('--documents', type=Path, required=True)
        command.add_argument('--output', type=Path, default=Path(f'reports/{name}.json'))
        if name == 'judge':
            command.add_argument('--function', required=True, help='Trusted local callable module:name; may call a provider')
            command.add_argument('--judge-id', required=True, help='Model and configuration version')
            command.add_argument('--max-calls', type=int, default=40)
            command.add_argument('--allow-judge-calls', action='store_true')
    calibration = sub.add_parser('calibrate')
    calibration.add_argument('judgments', type=Path)
    calibration.add_argument('reference', type=Path)
    calibration.add_argument('--output', type=Path, default=Path('reports/calibration.json'))
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
        if args.command == 'experiment':
            design = load_experiment(args.directory)
            options = dict(variants=args.variants, split=args.split, include_heldout=args.include_heldout,
                           max_calls=args.max_calls)
            plan = plan_experiment(design, **options)
            print(json.dumps(plan, indent=2))
            if not args.execute:
                print('Plan only: no provider imported, no calls made, no output written.')
                return 0
            if not args.function or ':' not in args.function or not args.provider_id or not args.output:
                parser.error('Execution requires --function module:factory, --provider-id and a new --output path')
            if args.output.exists():
                parser.error('Output already exists; choose a new run file')
            temporary = args.output.with_name(args.output.name + '.tmp')
            if temporary.exists():
                parser.error('Temporary output already exists; inspect the interrupted run first')
            module, name = args.function.split(':', 1)
            factory = getattr(importlib.import_module(module), name)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as handle:
                handle.write('{"status": "initializing"}\n')
            last_count = -1
            def checkpoint(report):
                nonlocal last_count
                temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
                temporary.replace(args.output)
                count = report['calls_attempted']
                if count != last_count and (count % 5 == 0 or report['status'] != 'running'):
                    print(f"{count}/{plan['planned_calls']} calls; {report['status']}; {report['counts']}", flush=True)
                    last_count = count
            report = run_experiment(design, factory, provider_id=args.provider_id, checkpoint=checkpoint, **options)
            print(f"Saved {args.output}; semantic quality and attack success require review.")
            return int(report['status'] != 'complete')
        if args.command in {'evaluate', 'compare', 'judge', 'review-template', 'calibrate'}:
            if args.command == 'compare':
                paths = [args.before, args.after]
            elif args.command == 'calibrate':
                paths = [args.judgments, args.reference]
            else:
                paths = [args.capture, args.documents]
            if args.output.resolve() in [p.resolve() for p in paths]:
                raise ValueError('Output must not overwrite an input')
            inputs = [json.loads(p.read_text(encoding='utf-8-sig')) for p in paths]
            if args.command == 'judge':
                if not args.allow_judge_calls or ':' not in args.function:
                    parser.error('Judge calls require --allow-judge-calls and a trusted module:function')
                module, name = args.function.split(':', 1)
                function = getattr(importlib.import_module(module), name)
                report = judge(*inputs, function, judge_id=args.judge_id, max_calls=args.max_calls)
            else:
                function = {'evaluate': evaluate, 'compare': compare,
                            'review-template': review_template, 'calibrate': calibrate}[args.command]
                report = function(*inputs)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(f"Saved {args.output} ({report['kind']}); inspect coverage and limitations before drawing conclusions")
            if args.command == 'judge':
                return int(any(r['status'] != 'judged' for r in report['records']))
            return 0
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
