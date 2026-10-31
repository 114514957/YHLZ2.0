"""Owner-local memory inspection. No model, schema changes, raw memories or auto-repair."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3
from backend.memory_resource_policy import load_memory_resource_policy, semantic_model_allowed


def snapshot(db_path: Path, *, kw_db_path: Path | None = None,
             vec_db_path: Path | None = None) -> dict:
    db_path=Path(db_path)
    policy=load_memory_resource_policy()
    out={'ok':True,'read_only':True,'resource':{'mode':policy.mode,'reason':policy.reason,
         'semantic_enabled':semantic_model_allowed()},'l1':[], 'warnings':[]}
    def warn(label):
        out['warnings'].append(label)
        out['ok']=False
    for path in sorted(db_path.parent.glob(db_path.name+'.l1*.json')):
        item={'file':path.name,'bytes':path.stat().st_size}
        try:
            if item['bytes'] > 32*1024*1024:
                raise ValueError('snapshot too large for bounded inspection')
            data=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data,dict): raise ValueError('invalid L1 root')
            for key in ('turns','pending'):
                rows=data.get(key,[])
                if not isinstance(rows,list) or any(not isinstance(t,dict) or
                    t.get('role') not in ('user','assistant') or not isinstance(t.get('text'),str) for t in rows):
                    raise ValueError('invalid L1 queue')
                item[key+'_count']=len(rows)
            scope=data.get('scope','')
            if not isinstance(scope,str): raise ValueError('invalid scope')
            digest=hashlib.sha256(scope.encode('utf-8')).hexdigest()[:16]
            expected=db_path.name+'.l1'+('.'+digest if scope else '')+'.json'
            if path.name != expected: raise ValueError('foreign scope snapshot')
            item['scope_fingerprint']=digest
            item['summary_chars']=len(str(data.get('summary','')))
            item['valid']=True
            if item['pending_count']: out['warnings'].append('l1_backlog:'+path.name)
        except (OSError,ValueError,TypeError) as exc:
            item.update(valid=False,error_type=type(exc).__name__)
            warn('l1_unreadable:'+path.name)
        out['l1'].append(item)
    try:
        con=sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05)
        try:
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'l2_items' not in tables: raise ValueError('missing authority table')
            out['l2_states']=dict(con.execute('SELECT status,COUNT(*) FROM l2_items GROUP BY status'))
            for table,key,pending in [('carrier_events','carriers','pending'),('persona_changes','persona','prepared')]:
                if table in tables:
                    states=dict(con.execute('SELECT state,COUNT(*) FROM '+table+' GROUP BY state'))
                    out[key]={'initialized':True,'states':states,'pending_reconciliation':states.get(pending,0)}
                    if states.get(pending,0): warn(key+'_reconciliation_required')
                else:
                    out[key]={'initialized':False,'states':{},'pending_reconciliation':0}
        finally: con.close()
    except (OSError,sqlite3.Error,ValueError) as exc:
        out['database_error']=type(exc).__name__
        warn('database_unavailable')
    if 'database_error' not in out:
        from backend.memory_index_audit import audit
        try:
            report=audit(db_path,kw_db_path=kw_db_path,vec_db_path=vec_db_path)
            out['indexes']={'ok':report['ok'],'authoritative':report['authoritative']}
            for key in ('fts','keyword','vector'):
                if key in report:
                    out['indexes'][key]={k:len(report[key][k]) for k in ('missing','stale','duplicates')}
            if not report['ok']: warn('index_projection_drift')
        except (OSError,sqlite3.Error,ValueError) as exc:
            out['index_error']=type(exc).__name__
            warn('index_audit_unavailable')
    out['automatic_replay']=False
    return out
