"""Training-safe, read-only memory status. Does not repair or expose contents."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.memory_health import snapshot

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=ROOT/'cache/memstore/memstore.db')
    p.add_argument('--kw-db',type=Path)
    p.add_argument('--vec-db',type=Path)
    args=p.parse_args()
    report=snapshot(args.db,kw_db_path=args.kw_db,vec_db_path=args.vec_db)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 2
if __name__=='__main__': raise SystemExit(main())
