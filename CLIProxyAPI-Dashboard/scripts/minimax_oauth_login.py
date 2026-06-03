import argparse
import os
import base64
import hashlib
import json
import secrets
import time
import uuid
import webbrowser
from pathlib import Path
from urllib import error, parse, request


CLIENT_ID = '78257093-7e40-4613-99e0-527b14b39113'
SCOPE = 'group_id profile model.completion'
GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:user_code'
MODELS = [
    'MiniMax-M2.7',
    'MiniMax-M2.5',
    'MiniMax-M2.5-highspeed',
    'MiniMax-M2.5-Lightning',
]

ROOT = Path(__file__).resolve().parents[1]
_proxy_root = os.environ.get('CLIPROXYAPI_ROOT', '').strip()
PROXY_ROOT = Path(_proxy_root).expanduser() if _proxy_root else ROOT.parent / 'CLIProxyAPI'
AUTH_DIR = PROXY_ROOT / 'storage' / 'auth'

REGIONS = {
    'global': {
        'base_url': 'https://api.minimax.io',
        'anthropic_url': 'https://api.minimax.io/anthropic',
        'label': 'Global',
    },
    'cn': {
        'base_url': 'https://api.minimaxi.com',
        'anthropic_url': 'https://api.minimaxi.com/anthropic',
        'label': 'China',
    },
}


def base64url_sha256(text: str) -> str:
    digest = hashlib.sha256(text.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')


def http_post_form(url: str, form_data: dict, headers: dict | None = None):
    data = parse.urlencode(form_data).encode('utf-8')
    req_headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
    }
    if headers:
        req_headers.update(headers)
    req = request.Request(url, data=data, headers=req_headers, method='POST')
    with request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode('utf-8', errors='ignore')
        return json.loads(body) if body else {}


def request_oauth_code(region: str):
    cfg = REGIONS[region]
    verifier = secrets.token_urlsafe(48)
    challenge = base64url_sha256(verifier)
    state = secrets.token_urlsafe(24)
    payload = http_post_form(
        f"{cfg['base_url']}/oauth/code",
        {
            'response_type': 'code',
            'client_id': CLIENT_ID,
            'scope': SCOPE,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'state': state,
        },
        headers={'x-request-id': str(uuid.uuid4())},
    )
    if payload.get('state') != state:
        raise RuntimeError('MiniMax OAuth state mismatch.')
    if not payload.get('user_code') or not payload.get('verification_uri'):
        raise RuntimeError(f"MiniMax OAuth authorization failed: {json.dumps(payload, ensure_ascii=False)}")
    return payload, verifier


def poll_oauth_token(region: str, user_code: str, verifier: str):
    cfg = REGIONS[region]
    payload = http_post_form(
        f"{cfg['base_url']}/oauth/token",
        {
            'grant_type': GRANT_TYPE,
            'client_id': CLIENT_ID,
            'user_code': user_code,
            'code_verifier': verifier,
        },
    )
    status = str(payload.get('status') or '').strip().lower()
    if status == 'success':
        access = str(payload.get('access_token') or '').strip()
        refresh = str(payload.get('refresh_token') or '').strip()
        expires = int(payload.get('expired_in') or 0)
        if not access or not refresh or expires <= 0:
            raise RuntimeError('MiniMax OAuth returned incomplete token payload.')
        return {
            'access': access,
            'refresh': refresh,
            'expires_in': expires,
            'resource_url': str(payload.get('resource_url') or cfg['anthropic_url']).strip(),
            'notification_message': str(payload.get('notification_message') or '').strip(),
        }
    if status == 'error':
        raise RuntimeError(str(payload.get('base_resp', {}).get('status_msg') or 'MiniMax OAuth failed.'))
    return None


def save_auth_file(region: str, token_payload: dict):
    cfg = REGIONS[region]
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    host_token = parse.urlparse(cfg['anthropic_url']).hostname or 'api.minimax.io'
    file_name = f"minimax-portal-{host_token}-{int(time.time() * 1000)}.json"
    path = AUTH_DIR / file_name
    now = int(time.time())
    payload = {
        'metadata': {
            'remark': f'minimax-portal-oauth:{region}',
            'captured_at': now,
            'source': 'dashboard_minimax_oauth',
            'region': region,
            'expires_at': now + int(token_payload['expires_in']),
            'notification_message': token_payload.get('notification_message') or '',
        },
        'content': {
            'type': 'api_key',
            'provider': 'minimax-portal',
            'api': 'anthropic-messages',
            'base_url': token_payload.get('resource_url') or cfg['anthropic_url'],
            'model': MODELS[0],
            'api_key': token_payload['access'],
            'models': MODELS,
            'refresh_token': token_payload['refresh'],
            'expires_in': int(token_payload['expires_in']),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def main():
    parser = argparse.ArgumentParser(description='MiniMax OAuth login for CLIProxyAPI')
    parser.add_argument('--region', choices=sorted(REGIONS.keys()), default='global')
    args = parser.parse_args()

    cfg = REGIONS[args.region]
    print(f"[MiniMax] Starting OAuth login for {cfg['label']} endpoint")
    print(f"[MiniMax] Target base URL: {cfg['anthropic_url']}")

    auth_payload, verifier = request_oauth_code(args.region)
    verification_uri = str(auth_payload['verification_uri'])
    user_code = str(auth_payload['user_code'])
    interval_ms = max(int(auth_payload.get('interval') or 2000), 1000)
    expire_at = int(auth_payload.get('expired_in') or 0)

    print('[MiniMax] Open the following URL in your browser and approve access:')
    print(verification_uri)
    print(f'[MiniMax] If prompted, enter code: {user_code}')
    try:
        webbrowser.open(verification_uri)
        print('[MiniMax] Browser open requested.')
    except Exception:
        print('[MiniMax] Browser open failed, please open it manually.')

    print('[MiniMax] Waiting for authorization...')
    while True:
        if expire_at and int(time.time() * 1000) >= expire_at:
            raise RuntimeError('MiniMax OAuth timed out waiting for authorization.')
        try:
            token_payload = poll_oauth_token(args.region, user_code, verifier)
        except error.HTTPError as exc:
            body = exc.read().decode('utf-8', errors='ignore')
            raise RuntimeError(f'MiniMax OAuth request failed: {body or exc.reason}') from exc
        if token_payload:
            save_path = save_auth_file(args.region, token_payload)
            print('[MiniMax] OAuth complete.')
            print(f'[MiniMax] Saved CLIProxyAPI auth file: {save_path}')
            if token_payload.get('notification_message'):
                print(f"[MiniMax] Note: {token_payload['notification_message']}")
            print('[MiniMax] Restart CLIProxyAPI to apply this auth entry.')
            return
        time.sleep(interval_ms / 1000.0)


if __name__ == '__main__':
    main()
