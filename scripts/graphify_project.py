"""Build the local Graphify graph, or check source freshness using content hashes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ['PYTHONUTF8'] = '1'
OUT = ROOT / 'graphify-out'
STAMP = OUT / 'project-sources.json'

def sources():
    from graphify.detect import detect
    detected = detect(ROOT)
    result = {}
    for category in ('code', 'document', 'paper', 'image', 'video'):
        for item in detected.get('files', {}).get(category, []):
            path = Path(item if isinstance(item, str) else item['path'])
            if not path.is_absolute():
                path = ROOT / path
            result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('.graphifyignore', '.gitignore'):
        path = ROOT / name
        if path.exists():
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in detected.get('unclassified', []) + detected.get('resolution_inputs', []):
        path = Path(name)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file():
            result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if mode not in ('status', 'update'):
        raise SystemExit('Usage: graphify_project.py [status|update]')
    current = sources()
    if mode == 'update':
        subprocess.run([sys.executable, '-m', 'graphify', 'extract', '.', '--code-only', '--force', '--max-workers', '2'], check=True)
        subprocess.run([sys.executable, '-m', 'graphify', 'cluster-only', '.'], check=True)
        if sources() != current:
            raise SystemExit('Sources changed during build. Run update again.')
        OUT.mkdir(exist_ok=True)
        STAMP.write_text(json.dumps({'built_at': datetime.now(timezone.utc).isoformat(), 'files': current, 'coverage': 'Local AST code graph; documents are freshness-tracked but not semantically indexed.'}, indent=2), encoding='utf-8')
        print('Graph updated; source hashes saved.')
        return
    if not STAMP.exists() or not (OUT / 'graph.json').exists():
        print('MISSING: run update')
        return
    previous = json.loads(STAMP.read_text(encoding='utf-8'))['files']
    changes = sorted(name for name in current.keys() | previous.keys() if current.get(name) != previous.get(name))
    print('STALE: update required' if changes else 'CURRENT: no update required')
    for name in changes:
        print(name)

if __name__ == '__main__':
    main()
