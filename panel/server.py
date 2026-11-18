"""Local operator console: python -m panel.server. No external web dependencies."""
import base64
from collections import defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from panel_settings import read_settings, save_settings

CSRF = secrets.token_urlsafe(32)
MUTEX = threading.Lock()
CACHE = (0, None)
CHILD = None
TOKEN_PROBES = {}
PATTERN = re.compile(r'_(\d{14})_(\d{14})_(\d{14})\.parquet$')


def specs():
    # Importing main only defines downloaders; it does not run them.
    import main
    return main


def token_status():
    result = []
    for name in ('HK', '54', 'SmartPanelHK', 'SmartPanel54'):
        path = ROOT / 'tokens' / f'token{name}.txt'
        item = {'name': name, 'status': 'missing', 'expires': None}
        if path.exists() and path.stat().st_size:
            item['status'] = 'unknown'
            try:
                token = path.read_text(encoding='utf-8').strip().removeprefix('Bearer ')
                payload = token.split('.')[1]
                expiry = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))).get('exp')
                if expiry:
                    item['expires'] = datetime.fromtimestamp(expiry).isoformat(timespec='seconds')
                    item['status'] = 'expired' if expiry < time.time() else 'unverified'
            except (ValueError, IndexError, UnicodeError, TypeError):
                pass
        result.append(item)
        if name in TOKEN_PROBES and time.time() - TOKEN_PROBES[name]['checked_epoch'] < 300:
            item.update(TOKEN_PROBES[name])
    return result


def probe_tokens():
    """A server/network failure is unknown, never a successful auth check."""
    import jdatetime
    from downloaders import SCL_HK, INV_SAL_54, SPA_HK, SPA_54
    from downloaders.downloader_core import call_api, load_token, load_smart_panel_token, AuthExpiredError
    now = jdatetime.datetime.now()
    for name, module, code, smart in (
        ('HK', SCL_HK, 'HK', False), ('54', INV_SAL_54, '54', False),
        ('SmartPanelHK', SPA_HK, 'HK', True), ('SmartPanel54', SPA_54, '54', True)):
        response = None
        status = 'unknown'
        try:
            token = load_smart_panel_token(code) if smart else load_token(code)
            mode = 'bearer' if smart or code == '54' else 'cookie'
            response = call_api(module.LEADERS_URL if smart else module.URL,
                'GET' if smart else module.METHOD, None if smart else module.build_params(now,now),
                token, auth_mode=mode, json_body={} if mode=='bearer' and not smart else None,
                timeout=(5,12))
            status = 'healthy' if not response.history and 'text/html' not in response.headers.get('Content-Type','').lower() else 'unknown'
        except AuthExpiredError:
            status = 'expired'
        except Exception:
            status = 'unknown'
        finally:
            if response is not None:
                response.close()
        TOKEN_PROBES[name] = {'status':status, 'checked':datetime.now().isoformat(timespec='seconds'), 'checked_epoch':time.time()}


def sql_snapshot():
    from db.sql_loader import get_connection
    from load_raw_data_to_sql import SQL_SERVER, SQL_DATABASE
    result = {'name': SQL_DATABASE, 'connected': False, 'tables': [], 'files': [], 'storage': []}
    conn = None
    try:
        start = time.monotonic()
        conn = get_connection(SQL_SERVER, SQL_DATABASE)
        conn.timeout = 12
        cur = conn.cursor()
        cur.execute('''SELECT s.name,t.name,SUM(CASE WHEN p.index_id IN (0,1) THEN p.row_count ELSE 0 END),
            SUM(p.reserved_page_count)*8.0/1024 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
            JOIN sys.dm_db_partition_stats p ON t.object_id=p.object_id GROUP BY s.name,t.name''')
        result['tables'] = [{'schema': s, 'name': n, 'rows': r, 'mb': float(m)} for s,n,r,m in cur.fetchall()]
        cur.execute('''SELECT s.name,t.name FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
            WHERE EXISTS (SELECT 1 FROM sys.indexes i WHERE i.object_id=t.object_id AND i.index_id=0)
            AND NOT EXISTS (SELECT 1 FROM sys.indexes i WHERE i.object_id=t.object_id AND i.index_id>0)''')
        result['unindexed_tables'] = [f'{s}.{t}' for s,t in cur.fetchall()]
        cur.execute("SELECT name,size*8.0/1024,FILEPROPERTY(name,'SpaceUsed')*8.0/1024 FROM sys.database_files")
        result['storage'] = [{'name': n, 'mb': float(m), 'used_mb': float(u) if u is not None else None} for n,m,u in cur.fetchall()]
        cur.execute("SELECT OBJECT_ID('dbo.LoadedFiles')")
        if cur.fetchone()[0]:
            cur.execute('SELECT RelativePath,TableName,[RowCount],LoadedAt FROM dbo.LoadedFiles')
            result['files'] = [{'path': p.replace('\\','/'), 'table': t, 'rows': r, 'loaded': str(d)} for p,t,r,d in cur.fetchall()]
        result.update(connected=True, latency_ms=round((time.monotonic()-start)*1000))
    except Exception as exc:
        result['error'] = type(exc).__name__ + ': ' + str(exc)[:350]
    finally:
        if conn is not None:
            conn.close()
    return result


def snapshot():
    global CACHE
    with MUTEX:
        if time.time() - CACHE[0] < 30 and CACHE[1]:
            return CACHE[1]
        main = specs()
        settings = read_settings()
        sql = sql_snapshot()
        loaded = {f['path']: f for f in sql.pop('files')}
        tables = {t['name']: t for t in sql['tables'] if t['schema'] == 'dbo'}
        reports = []
        import jdatetime
        today = jdatetime.date.today()
        for spec in main.DOWNLOADERS:
            days = defaultdict(lambda: {'raw': 0, 'loaded': 0, 'retired': 0, 'latest': None, 'rows': 0})
            for base, kind in ((main.RAW_DATA_ROOT, 'raw'), (main.RETIRED_ROOT, 'retired')):
                folder = base / spec.report_code / spec.company_code
                if not folder.exists():
                    continue
                for path in folder.glob('*.parquet'):
                    match = PATTERN.search(path.name)
                    if not match:
                        continue
                    day = match[1][:8]
                    entry = days[day]
                    entry[kind] += 1
                    if kind == 'raw':
                        relative = path.relative_to(main.RAW_DATA_ROOT).as_posix()
                        tracking = loaded.get(relative)
                        if tracking:
                            entry['loaded'] += 1
                            entry['rows'] += tracking['rows']
                        entry['latest'] = max(entry['latest'] or '', match[3])
            window = settings.get('windows', {}).get(spec.label, main.WINDOW_DAYS.get(spec.label, 0))
            dates = sorted(days)
            first = dates[0] if dates else None
            timeline = []
            if first:
                start = jdatetime.datetime.strptime(first, '%Y%m%d').date()
                for offset in range(min((today-start).days+1, 5000)):
                    day = (start + main.timedelta(days=offset)).strftime('%Y%m%d')
                    info = dict(days.get(day, {}))
                    state = 'missing'
                    if info.get('raw'):
                        state = 'loaded' if info.get('loaded') == info['raw'] else ('pending' if sql['connected'] else 'unknown')
                        if info.get('retired') and state == 'loaded':
                            state = 'replaced'
                    timeline.append({'date': day, 'state': state, **info})
            reports.append({'name': spec.label, 'company': spec.company_code, 'window': window,
                'enabled': spec.label not in settings.get('disabled', []), 'first': first,
                'last': max((d for d in dates if days[d]['raw']), default=None),
                'table': tables.get(getattr(spec, 'table', spec.label)), 'days': timeline,
                'raw': sum(d['raw'] for d in days.values()),
                'missing': sum(d['state']=='missing' for d in timeline)})
        logpath = ROOT / 'logs' / 'robot_downloader.log'
        logs = []
        if logpath.exists():
            with logpath.open('rb') as stream:
                stream.seek(max(0, logpath.stat().st_size-24000))
                logs = stream.read().decode('utf-8', errors='replace').splitlines()[-90:]
        active = main.LOCK_PATH.exists() and main._lock_owner_alive()
        disk = shutil.disk_usage(ROOT)
        data = {'sql': sql, 'reports': reports, 'tokens': token_status(), 'logs': logs,
                'running': active, 'child_exit': CHILD.poll() if CHILD else None,
                'settings': {'delay': settings.get('delay', main.DELAY_BETWEEN_CALLS_SECONDS)},
                'disk_free_gb': round(disk.free/1024**3,1), 'updated': datetime.now().isoformat(timespec='seconds')}
        CACHE = (time.time(), data)
        return data


class Handler(BaseHTTPRequestHandler):
    def reply(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        return self.headers.get('Host') in ('127.0.0.1:8876','localhost:8876')

    def do_GET(self):
        if not self.allowed():
            return self.reply({'error':'Invalid host'},403)
        path = urlparse(self.path).path
        try:
            if path == '/api/state':
                return self.reply(snapshot())
            if path == '/api/session':
                return self.reply({'csrf': CSRF})
            files = {'/':'index.html', '/app.js':'app.js', '/style.css':'style.css'}
            if path not in files:
                return self.reply({'error':'Not found'},404)
            content = (Path(__file__).parent / files[path]).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type',{'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[path])
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)
        except Exception as exc:
            self.reply({'error':str(exc)[:350]},500)

    def do_POST(self):
        global CACHE, CHILD
        if not self.allowed() or self.headers.get('X-CSRF-Token') != CSRF or self.headers.get('Origin') not in ('http://localhost:8876','http://127.0.0.1:8876'):
            return self.reply({'error':'Invalid request origin'},403)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 20000:
                return self.reply({'error':'Invalid body size'},400)
            value = json.loads(self.rfile.read(length))
            with MUTEX:
                if self.path == '/api/settings':
                    save_settings(value, {s.label for s in specs().DOWNLOADERS})
                elif self.path == '/api/tokens/check':
                    probe_tokens()
                elif self.path == '/api/run':
                    main = specs()
                    if (CHILD and CHILD.poll() is None) or (main.LOCK_PATH.exists() and main._lock_owner_alive()):
                        return self.reply({'error':'Robot already running'},409)
                    with open(os.devnull,'w') as output:
                        CHILD = subprocess.Popen([sys.executable,str(ROOT/'main.py')],cwd=ROOT,stdout=output,stderr=output,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:
                    return self.reply({'error':'Not found'},404)
                CACHE = (0,None)
            self.reply({'ok':True})
        except (ValueError, TypeError) as exc:
            self.reply({'error':str(exc)},400)
        except Exception as exc:
            self.reply({'error':str(exc)[:350]},500)


class GatewayRedirect(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # pythonw has no stderr

    # All administration now lives behind the shared administrator login.
    def do_GET(self):
        self.send_response(302)
        self.send_header('Location', 'http://127.0.0.1:8770/database')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def do_POST(self):
        self.send_error(410, 'Use the authenticated shared dashboard on port 8770')


if __name__ == '__main__':
    print('Shared console: http://127.0.0.1:8770/database', flush=True)
    ThreadingHTTPServer(('127.0.0.1',8876), GatewayRedirect).serve_forever()
