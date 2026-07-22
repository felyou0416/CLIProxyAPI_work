import json
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKENS = Path(r'E:\U_App\CLIProxyAPI_work\CLIProxyAPI\storage\runtime\access_tokens.json')
token = list(json.loads(TOKENS.read_text(encoding='utf-8')).keys())[-1]
BASE = 'http://127.0.0.1:8765'
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def req(path, method='GET', body=None, timeout=8):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
            return round(time.time() - t0, 2), resp.status, payload
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {'raw': 'http-error'}
        return round(time.time() - t0, 2), exc.code, payload
    except Exception as exc:
        return round(time.time() - t0, 2), 'ERR', str(exc)


def summarize(payload):
    if isinstance(payload, dict):
        msg = (payload.get('message') or '')[:70]
        return f"ok={payload.get('ok')} msg={msg}"
    return str(payload)[:80]


for method, path, body in [
    ('GET', '/api/status', None),
    ('POST', '/api/openclaw/start', {}),
    ('POST', '/api/start-oauth-manager', {}),
    ('POST', '/api/create-grok/start', {}),
    ('POST', '/api/77chat/start', {}),
    ('POST', '/api/tunnel/start', {}),
]:
    elapsed, code, payload = req(path, method, body, timeout=8)
    print(f'{method:4} {path:35} {elapsed:5}s {code} {summarize(payload)}')
