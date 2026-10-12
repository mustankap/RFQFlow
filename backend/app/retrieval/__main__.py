"""python -m backend.app.retrieval --help"""
import argparse
import json
from pathlib import Path

from .config import FIXTURES, ROOT, create_service
from .demo import seed_demo
from .evaluation import evaluate, export_grounding
from .repository import SQLiteRepository


def main():
    parser = argparse.ArgumentParser(description='Developer 2: SQLite + Nicrron + Chroma retrieval')
    parser.add_argument('command', choices=['seed-demo', 'index', 'seed', 'query', 'evaluate', 'export-grounding'])
    parser.add_argument('--db', type=Path, help='Canonical SQLite file (read-only except seed-demo)')
    parser.add_argument('--chroma', type=Path, help='Rebuildable Chroma directory')
    parser.add_argument('--rfq', type=Path, default=FIXTURES/'parsed_rfq_ideal.json')
    parser.add_argument('--catalog', type=Path, default=FIXTURES/'supplier_catalog.json')
    parser.add_argument('--cases', type=Path, default=FIXTURES/'evaluation_cases.json')
    parser.add_argument('--as-of', help='YYYY-MM-DD for reproducible pricing-date warnings')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'seed-demo':
            # Demo creation has a safe fixed default; it never uses a production DB env var.
            db = args.db or ROOT/'.local/demo.sqlite'
            seed_demo(db, args.catalog)
            result = {'database': str(db), 'is_synthetic': True}
        elif args.command == 'export-grounding':
            from dotenv import load_dotenv
            import os
            load_dotenv(ROOT/'.env')
            repo = SQLiteRepository(args.db or Path(os.getenv('RFQ_SQLITE_PATH', str(ROOT/'.local/demo.sqlite'))))
            result = export_grounding(repo, ROOT/'.local/prism')
        else:
            service = create_service(args.db, args.chroma, args.as_of)
            if args.command in {'index','seed'}:
                result = service.build_index()
            elif args.command == 'evaluate':
                result = evaluate(service, args.cases)
            else:
                result = service.retrieve_for_rfq(json.loads(args.rfq.read_text())).model_dump(mode='json')
        serialized = json.dumps(result, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized+'\n')
        print(serialized)
        if args.command == 'evaluate' and result['passed'] != result['cases']:
            parser.exit(1, 'Some labeled evaluation cases failed\n')
    except Exception as exc:
        parser.exit(1, f'Retrieval failed: {exc}\n')


if __name__ == '__main__':
    main()
