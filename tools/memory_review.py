"""Local-only S3 review. No model/QQ/network approvals. Stable IDs required."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.memory_review import MemoryReviewQueue
from backend.target_memory import DEFAULT_DB, TargetMemoryService


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', type=Path, default=DEFAULT_DB)
    actions = p.add_subparsers(dest='action', required=True)
    ls = actions.add_parser('list')
    ls.add_argument('--status', choices=['pending', 'approved', 'rejected', 'all'], default='pending')
    ls.add_argument('--limit', type=int, default=50)
    show = actions.add_parser('show')
    show.add_argument('id')
    for action in ('approve', 'reject', 'invalidate'):
        cmd = actions.add_parser(action)
        cmd.add_argument('id')
        cmd.add_argument('--reason', required=True)
        cmd.add_argument('--confirm', action='store_true', help='Explicit local owner decision')
    fix = actions.add_parser('propose-correction')
    fix.add_argument('old_id')
    fix.add_argument('--text', required=True)
    fix.add_argument('--evidence', required=True)
    args = p.parse_args(argv)
    if args.action in ('approve', 'reject', 'invalidate') and not args.confirm:
        p.error('no change: use --confirm after reviewing the stable ID and source')
    # A typo must not silently create a new production memory database.
    if not args.db.is_file():
        p.error('selected L2 database does not exist')
    queue = MemoryReviewQueue(args.db)
    if args.action == 'list':
        result = queue.list(args.status, args.limit)
    elif args.action == 'show':
        result = queue.inspect(args.id)
    elif args.action == 'propose-correction':
        result = queue.submit(summary=args.text, channel='owner_local', speaker='owner',
                              kind='fact', observed_at=time.time(), evidence_ref=args.evidence,
                              user_text=args.text, replaces_id=args.old_id)
    elif args.action == 'invalidate':
        result = {'changed': queue.invalidate(args.id, reason=args.reason)}
    else:
        service = TargetMemoryService(db_path=args.db) if args.action == 'approve' else None
        result = queue.decide(args.id, approve=args.action == 'approve', reason=args.reason, service=service)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except (ValueError, KeyError) as exc:
        print(f'Review refused: {exc}', file=sys.stderr)
        raise SystemExit(2)
