import ipaddress
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from backend.paths import (
    ACTIVE_AUTH_DIR,
    AUTH_ARCHIVE_DIR,
    AUTH_DIR,
    PROXY_STDOUT,
    REQUEST_ARCHIVE_DIR,
    REQUEST_LOG_DIR,
    STORAGE_DIR,
)
from backend.api_keys import find_key_by_masked_value, record_api_key_usage


_PROXY_LINE_RE = re.compile(
    r'^\[(?P<ts>[^\]]+)\]\s+\[(?P<request_id>[^\]]*)\].*?\s(?P<status>\d{3})\s+\|\s+'
    r'(?P<latency>[^|]+)\|\s+(?P<ip>[^|]+)\|\s+(?P<method>[A-Z]+)\s+"(?P<path>[^"]+)"'
)
_REQUEST_URL_RE = re.compile(r'^URL:\s*(.+)$', re.MULTILINE)
_REQUEST_TIMESTAMP_RE = re.compile(r'^Timestamp:\s*(.+)$', re.MULTILINE)
_RESPONSE_STATUS_RE = re.compile(r'^Status:\s*(\d{3})$', re.MULTILINE)
_ERROR_MESSAGE_RE = re.compile(r'"message"\s*:\s*"([^"]+)"')
_AUTHORIZATION_RE = re.compile(r'^Authorization:\s*Bearer\s+(.+)$', re.MULTILINE)
_SECTION_HEADER_RE = re.compile(r'^=== .+ ===$', re.MULTILINE)
_API_REQUEST_HEADER_RE = re.compile(r'^=== API REQUEST(?:\s+\d+)? ===$', re.MULTILINE)
_API_REQUEST_AUTH_PROVIDER_RE = re.compile(r'^Auth:\s*provider=([^,\s]+)', re.MULTILINE)
# Prefer full proxy chains over single-hop headers so the dashboard shows the original client.
_PROXY_HEADER_PRIORITY = (
    'x-forwarded-for',
    'cf-connecting-ip',
    'true-client-ip',
    'x-real-ip',
    'x-client-ip',
)


_PRECISE_EVENT_KEYS = (
    'timestamp',
    'request_id',
    'path',
    'method',
    'client_ip',
    'requested_model',
    'status_code',
    'latency_ms',
)

_OBSERVABILITY_CACHE_LOCK = threading.Lock()
_OBSERVABILITY_CACHE = {
    'ready': False,
    'refreshing': False,
    'refreshed_at': 0.0,
    'events': [],
    'clients': [],
    'auth_health': [],
}
_REQUEST_LOG_PARSE_CACHE_LOCK = threading.Lock()
_PRECISE_REQUEST_LOG_CACHE = {}
_ERROR_REQUEST_LOG_CACHE = {}
_REQUEST_LOG_PARSE_CACHE_VERSION = 3  # bumped when event format or extraction logic changes
_OBSERVABILITY_REFRESH_INTERVAL_SECONDS = 15.0
_OBSERVABILITY_EVENT_LIMIT = 300
_OBSERVABILITY_SUMMARY_LIMIT = 200
_REQUEST_LOG_KEEP_FILES = 50
_REQUEST_EVENT_ARCHIVE_KEEP_ENTRIES = 2000


def _normalize_client_ip(raw: str) -> str:
    value = str(raw or '').strip().strip('"[]')
    if not value:
        return ''
    if value.startswith('::ffff:'):
        value = value.rsplit(':', 1)[-1]
    if '%' in value:
        value = value.split('%', 1)[0]
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        if ':' in value:
            host = value.rsplit(':', 1)[0].strip('[]')
            try:
                parsed = ipaddress.ip_address(host)
            except ValueError:
                return ''
        else:
            return ''
    if getattr(parsed, 'ipv4_mapped', None):
        parsed = parsed.ipv4_mapped
    return str(parsed)


def _first_forwarded_ip(raw: str) -> str:
    for part in str(raw or '').split(','):
        ip = _normalize_client_ip(part)
        if ip:
            return ip
    return ''


def _extract_headers(content: str) -> dict[str, list[str]]:
    raw = str(content or '')
    marker = '=== HEADERS ===\n'
    if marker not in raw:
        return {}
    section = raw.split(marker, 1)[1]
    next_header = _SECTION_HEADER_RE.search(section)
    if next_header:
        section = section[:next_header.start()]
    headers: dict[str, list[str]] = {}
    for line in section.splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            headers.setdefault(key, []).append(value)
    return headers


def _extract_client_ip_from_headers(content: str) -> tuple[str, str]:
    headers = _extract_headers(content)
    for header in _PROXY_HEADER_PRIORITY:
        values = headers.get(header) or []
        for value in values:
            ip = _first_forwarded_ip(value) if header == 'x-forwarded-for' else _normalize_client_ip(value)
            if ip:
                return ip, header
    return '', ''




def _safe_timestamp(raw: str | None, fallback: int = 0) -> int:
    value = str(raw or '').strip()
    if not value:
        return fallback
    try:
        return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
    except Exception:
        return fallback


def _tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists() or not path.is_file():
        return []
    if limit <= 0:
        try:
            return path.read_text(encoding='utf-8', errors='ignore').splitlines()
        except Exception:
            return []

    try:
        with path.open('rb') as fh:
            fh.seek(0, 2)
            file_size = fh.tell()
            chunk_size = 8192
            buffer = b''
            newline_count = 0
            position = file_size
            target_newlines = max(1, limit + 1)

            while position > 0 and newline_count < target_newlines:
                read_size = min(chunk_size, position)
                position -= read_size
                fh.seek(position)
                chunk = fh.read(read_size)
                buffer = chunk + buffer
                newline_count = buffer.count(b'\n')

        text = buffer.decode('utf-8', errors='ignore')
        lines = text.splitlines()
        return lines[-limit:]
    except Exception:
        try:
            return path.read_text(encoding='utf-8', errors='ignore').splitlines()[-limit:]
        except Exception:
            return []


def _parse_duration_to_ms(raw: str) -> int | None:
    token = str(raw or '').strip().lower()
    if not token:
        return None
    try:
        if token.endswith('ms'):
            return int(float(token[:-2]))
        if token.endswith('s'):
            return int(float(token[:-1]) * 1000)
        if token.endswith('m'):
            return int(float(token[:-1]) * 60 * 1000)
    except Exception:
        return None
    return None


def _extract_model_from_text(body_text: str) -> str:
    raw = str(body_text or '').strip()
    if not raw:
        return ''

    try:
        payload = json.loads(raw)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        stack = [payload]
        visited = set()
        candidate_keys = (
            'model',
            'requested_model',
            'model_id',
            'call_id',
            'upstream_id',
            'target_model',
            'routed_model',
        )
        while stack:
            current = stack.pop()
            current_id = id(current)
            if current_id in visited:
                continue
            visited.add(current_id)
            if isinstance(current, dict):
                for key in candidate_keys:
                    value = current.get(key)
                    if isinstance(value, (str, int, float)) and str(value).strip():
                        return str(value).strip()
                for value in current.values():
                    if isinstance(value, (dict, list, tuple)):
                        stack.append(value)
            elif isinstance(current, (list, tuple)):
                for value in current:
                    if isinstance(value, (dict, list, tuple)):
                        stack.append(value)

    patterns = (
        r'"model"\s*:\s*"([^"]+)"',
        r'"requested_model"\s*:\s*"([^"]+)"',
        r'"model_id"\s*:\s*"([^"]+)"',
        r'"call_id"\s*:\s*"([^"]+)"',
        r'"upstream_id"\s*:\s*"([^"]+)"',
        r'\bmodel\b\s*[:=]\s*"([^"]+)"',
        r'\brequested_model\b\s*[:=]\s*"([^"]+)"',
        r'\bmodel_id\b\s*[:=]\s*"([^"]+)"',
        r'\bcall_id\b\s*[:=]\s*"([^"]+)"',
        r'\bupstream_id\b\s*[:=]\s*"([^"]+)"',
        r'\bmodel\b\s*[:=]\s*([^\s,}\]]+)',
        r'\brequested_model\b\s*[:=]\s*([^\s,}\]]+)',
        r'\bmodel_id\b\s*[:=]\s*([^\s,}\]]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return str(match.group(1) if match else '').strip()
    return ''


def _extract_json_model(body_text: str) -> str:
    return _extract_model_from_text(body_text)


def _iter_api_request_sections(content: str) -> list[str]:
    raw = str(content or '')
    if not raw:
        return []
    sections = []
    matches = list(_API_REQUEST_HEADER_RE.finditer(raw))
    for index, match in enumerate(matches):
        start = match.end()
        next_header = _SECTION_HEADER_RE.search(raw, start)
        if next_header:
            end = next_header.start()
        elif index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(raw)
        sections.append(raw[start:end].strip())
    return sections


def _extract_api_request_body(section: str) -> str:
    raw = str(section or '')
    marker = '\nBody:\n'
    if marker in raw:
        return raw.rsplit(marker, 1)[1].strip()
    if raw.startswith('Body:\n'):
        return raw.split('Body:\n', 1)[1].strip()
    return ''


def _extract_actual_upstream(content: str) -> tuple[str, str, str]:
    actual_provider = ''
    actual_model = ''
    for section in _iter_api_request_sections(content):
        provider_match = _API_REQUEST_AUTH_PROVIDER_RE.search(section)
        provider = str(provider_match.group(1) if provider_match else '').strip().lower()
        model = _extract_model_from_text(_extract_api_request_body(section))
        if provider or model:
            actual_provider = provider or actual_provider
            actual_model = model or actual_model
    route_source = 'precise-log' if (actual_provider or actual_model) else ''
    return actual_provider, actual_model, route_source


def _normalize_path(path: str) -> str:
    value = str(path or '').strip()
    if not value:
        return ''
    if '/v1/' in value and value.count('/v1/') > 1:
        value = value[value.rfind('/v1/'):]
    return value


def _extract_balanced_json(text: str, start: int) -> str | None:
    """从 text[start] 的 '{' 开始，按花括号计数提取平衡的 JSON 字符串。

    会跳过 JSON 字符串内部的花括号，避免字符串值中的 {/} 干扰计数。
    """
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _extract_usage_tokens(content: str) -> tuple[int | None, int | None, int | None]:
    """从 content 中提取 usage token 信息。

    会遍历所有 "usage" JSON 对象并合并：对 prompt / completion 取最大值，
    以兼容流式响应中 prompt 和 completion 分散在不同 usage 对象里的情况。
    """
    raw = str(content or '')
    if not raw:
        return None, None, None

    prompts = []
    completions = []
    totals = []
    offset = 0
    while True:
        idx = raw.find('"usage"', offset)
        if idx == -1:
            break
        # 跳过 "usage" 本身，找后面的 '{'
        brace = raw.find('{', idx + 7)
        if brace == -1:
            offset = idx + 7
            continue
        # 检查中间是否只有空白和冒号（避免匹配到非 usage 值中的 '{'）
        between = raw[idx + 7:brace]
        if not re.fullmatch(r'\s*:\s*', between):
            offset = idx + 7
            continue
        json_str = _extract_balanced_json(raw, brace)
        if json_str is None:
            offset = idx + 7
            continue
        try:
            parsed = json.loads(json_str)
            if not isinstance(parsed, dict):
                offset = brace + 1
                continue
        except Exception:
            offset = brace + 1
            continue

        prompt = parsed.get('prompt_tokens')
        if prompt is None:
            prompt = parsed.get('input_tokens')
        completion = parsed.get('completion_tokens')
        if completion is None:
            completion = parsed.get('output_tokens')
        total = parsed.get('total_tokens')
        try:
            prompt = int(prompt) if prompt is not None else None
        except Exception:
            prompt = None
        try:
            completion = int(completion) if completion is not None else None
        except Exception:
            completion = None
        try:
            total = int(total) if total is not None else None
        except Exception:
            total = None
        if prompt is not None:
            prompts.append(prompt)
        if completion is not None:
            completions.append(completion)
        if total is not None:
            totals.append(total)

        offset = brace + 1

    if not prompts and not completions and not totals:
        return None, None, None

    final_prompt = max(prompts) if prompts else None
    final_completion = max(completions) if completions else None
    final_total = max(totals) if totals else None
    if final_total is None and (final_prompt is not None or final_completion is not None):
        final_total = (final_prompt or 0) + (final_completion or 0)
    return final_prompt, final_completion, final_total


def _archive_path_for_event(timestamp: int) -> Path:
    if timestamp <= 0:
        timestamp = int(datetime.now().timestamp())
    day = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
    return REQUEST_ARCHIVE_DIR / f'request-events-{day}.jsonl'


def _append_archived_request_event(event: dict) -> None:
    if not event:
        return
    archive_path = _archive_path_for_event(int(event.get('timestamp') or 0))
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload['archived_at'] = int(datetime.now().timestamp())
    with archive_path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')


def _tail_archived_request_events(limit: int, source: str | None = None) -> list[dict]:
    if limit <= 0 or not REQUEST_ARCHIVE_DIR.exists():
        return []
    items = []
    try:
        archive_files = sorted(
            [path for path in REQUEST_ARCHIVE_DIR.glob('request-events-*.jsonl') if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return []
    for archive_path in archive_files:
        for line in reversed(_tail_lines(archive_path, max(limit * 2, 100))):
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if source and str(item.get('source') or '') != source:
                continue
            items.append(item)
            if len(items) >= limit:
                return items
    return items


def _request_log_dirs() -> list[Path]:
    # Active runtime auth dir is the live request-log target written by the proxy.
    # Keep legacy locations so older installs and archived auth trees still resolve.
    dirs = [
        ACTIVE_AUTH_DIR / 'logs',
        REQUEST_LOG_DIR,
        AUTH_DIR / 'logs',
        AUTH_ARCHIVE_DIR / 'default' / 'metadata' / 'logs',
        STORAGE_DIR / 'storage' / 'runtime' / 'active-auth' / 'logs',
    ]
    result = []
    seen = set()
    for path in dirs:
        key = str(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result


def _trim_request_event_archives(max_entries: int = _REQUEST_EVENT_ARCHIVE_KEEP_ENTRIES) -> None:
    if max_entries <= 0 or not REQUEST_ARCHIVE_DIR.exists():
        return
    try:
        archive_files = sorted(
            [path for path in REQUEST_ARCHIVE_DIR.glob('request-events-*.jsonl') if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return
    remaining = max_entries
    for archive_path in archive_files:
        try:
            lines = archive_path.read_text(encoding='utf-8', errors='ignore').splitlines()
        except Exception:
            continue
        if remaining <= 0:
            try:
                archive_path.unlink()
            except Exception:
                pass
            continue
        if len(lines) > remaining:
            archive_path.write_text('\n'.join(lines[-remaining:]) + '\n', encoding='utf-8')
        remaining -= len(lines)


def _parse_request_log_file(path: Path, content: str, stat, error_log: bool = False, record_usage: bool = True) -> dict | None:
    request_time_match = _REQUEST_TIMESTAMP_RE.search(content)
    status_match = _RESPONSE_STATUS_RE.search(content)
    url_match = _REQUEST_URL_RE.search(content)

    body = ''
    if '=== REQUEST BODY ===' in content:
        if error_log:
            body = content.split('=== REQUEST BODY ===', 1)[1].split('=== API RESPONSE ===', 1)[0].strip()
        else:
            body = content.split('=== REQUEST BODY ===', 1)[1].split('=== API REQUEST ===', 1)[0].split('=== API RESPONSE ===', 1)[0].split('=== RESPONSE ===', 1)[0].strip()
    elif not error_log:
        return None

    requested_model = _extract_json_model(body)
    if not requested_model:
        requested_model = _extract_model_from_text(content)
    request_id = path.stem.rsplit('-', 1)[-1].strip()
    if not request_id or (not requested_model and not error_log):
        return None

    actual_provider, actual_model, route_source = _extract_actual_upstream(content)
    prompt_tokens, completion_tokens, total_tokens = _extract_usage_tokens(content)

    auth_match = _AUTHORIZATION_RE.search(content)
    api_key_masked = str(auth_match.group(1) if auth_match else '').strip()

    if record_usage and api_key_masked:
        full_key = find_key_by_masked_value(api_key_masked)
        if full_key:
            record_api_key_usage(full_key, tokens=total_tokens or 0)

    status_code = int(status_match.group(1)) if status_match else (500 if error_log else 200)
    error_message = ''
    if error_log:
        message_match = _ERROR_MESSAGE_RE.search(content)
        if message_match:
            error_message = str(message_match.group(1) or '').strip()

    client_ip, client_ip_source = _extract_client_ip_from_headers(content)

    return {
        'timestamp': _safe_timestamp(request_time_match.group(1) if request_time_match else '', int(stat.st_mtime)),
        'client_ip': client_ip,
        'client_ip_source': client_ip_source,
        'path': _normalize_path(url_match.group(1) if url_match else path.stem),
        'requested_model': requested_model,
        'status_code': status_code,
        'success': 200 <= status_code < 400,
        'latency_ms': None,
        'error_summary': error_message or (path.name if error_log else ''),
        'request_id': request_id,
        'inferred_provider': actual_provider,
        'actual_provider': actual_provider,
        'routed_model': actual_model,
        'actual_model': actual_model,
        'route_source': route_source,
        'route_confidence': 1.0 if route_source else 0.0,
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': total_tokens,
        'api_key_masked': api_key_masked,
        'notes': [path.name],
        'source': 'error-log' if error_log else 'precise-log',
        'method': 'POST',
    }


def prune_request_logs(max_files: int = _REQUEST_LOG_KEEP_FILES) -> None:
    if max_files <= 0:
        return
    stale_paths = []
    for log_dir in _request_log_dirs():
        if not log_dir.exists():
            continue
        try:
            files = [path for path in log_dir.glob('*.log') if path.is_file()]
        except Exception:
            continue
        if len(files) <= max_files:
            continue
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        stale_paths.extend(files[max_files:])
    for path in stale_paths:
        try:
            stat = path.stat()
            content = path.read_text(encoding='utf-8', errors='ignore')
            parsed = _parse_request_log_file(
                path,
                content,
                stat,
                error_log=path.name.startswith('error-'),
                record_usage=False,
            )
            if parsed:
                _append_archived_request_event(parsed)
            path.unlink()
        except Exception:
            continue
    _trim_request_event_archives()
    if stale_paths:
        stale_keys = {str(path) for path in stale_paths}
        with _REQUEST_LOG_PARSE_CACHE_LOCK:
            for key in stale_keys:
                _PRECISE_REQUEST_LOG_CACHE.pop(key, None)
                _ERROR_REQUEST_LOG_CACHE.pop(key, None)


def parse_proxy_requests(limit: int = 500) -> list[dict]:
    items = []
    for line in _tail_lines(PROXY_STDOUT, max(200, limit * 4)):
        match = _PROXY_LINE_RE.search(line)
        if not match:
            continue
        timestamp = _safe_timestamp(match.group('ts'))
        status_code = int(match.group('status'))
        path = _normalize_path(match.group('path'))
        items.append({
            'timestamp': timestamp,
            'client_ip': str(match.group('ip') or '').strip(),
            'path': path,
            'requested_model': '',
            'status_code': status_code,
            'success': 200 <= status_code < 400,
            'latency_ms': _parse_duration_to_ms(match.group('latency')),
            'error_summary': '',
            'request_id': str(match.group('request_id') or '').strip('- '),
            'inferred_provider': '',
            'notes': ['proxy.stdout.log'],
            'source': 'proxy',
            'method': str(match.group('method') or '').strip(),
        })
    items.sort(key=lambda item: int(item.get('timestamp') or 0), reverse=True)
    return items[:limit]


def parse_precise_request_events(limit: int = 500) -> list[dict]:
    items = []
    cache_updates = {}
    log_paths = []
    seen_paths = set()
    for log_dir in _request_log_dirs():
        if not log_dir.exists():
            continue
        for path in log_dir.glob('*.log'):
            key = str(path)
            if key not in seen_paths:
                log_paths.append(path)
                seen_paths.add(key)
    for path in sorted(log_paths, key=lambda entry: entry.stat().st_mtime, reverse=True)[:max(200, limit * 4)]:
        if not path.is_file() or path.name.startswith('error-'):
            continue
        try:
            stat = path.stat()
        except Exception:
            continue
        signature = (int(stat.st_mtime_ns), int(stat.st_size), _REQUEST_LOG_PARSE_CACHE_VERSION)
        cached = None
        with _REQUEST_LOG_PARSE_CACHE_LOCK:
            cached = _PRECISE_REQUEST_LOG_CACHE.get(str(path))
        if cached and cached.get('signature') == signature:
            parsed = cached.get('item')
            if parsed:
                items.append(dict(parsed))
            continue
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        if '=== REQUEST BODY ===' not in content:
            cache_updates[str(path)] = {'signature': signature, 'item': None}
            continue
        parsed = _parse_request_log_file(path, content, stat, error_log=False, record_usage=True)
        if not parsed:
            cache_updates[str(path)] = {'signature': signature, 'item': None}
            continue
        items.append(parsed)
        cache_updates[str(path)] = {'signature': signature, 'item': parsed}
    if cache_updates:
        with _REQUEST_LOG_PARSE_CACHE_LOCK:
            _PRECISE_REQUEST_LOG_CACHE.update(cache_updates)
    items.extend(_tail_archived_request_events(limit, source='precise-log'))
    items.sort(key=lambda item: int(item.get('timestamp') or 0), reverse=True)
    return items[:limit]


def parse_error_logs(limit: int = 500) -> list[dict]:
    items = []
    cache_updates = {}
    files = []
    seen_paths = set()
    for log_dir in _request_log_dirs():
        if not log_dir.exists():
            continue
        for path in log_dir.glob('*.log'):
            key = str(path)
            if path.is_file() and path.name.startswith('error-') and key not in seen_paths:
                files.append(path)
                seen_paths.add(key)
    files = sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
    for path in files:
        try:
            stat = path.stat()
        except Exception:
            continue
        signature = (int(stat.st_mtime_ns), int(stat.st_size), _REQUEST_LOG_PARSE_CACHE_VERSION)
        cached = None
        with _REQUEST_LOG_PARSE_CACHE_LOCK:
            cached = _ERROR_REQUEST_LOG_CACHE.get(str(path))
        if cached and cached.get('signature') == signature:
            parsed = cached.get('item')
            if parsed:
                items.append(dict(parsed))
            continue
        try:
            content = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        parsed = _parse_request_log_file(path, content, stat, error_log=True, record_usage=True)
        if not parsed:
            cache_updates[str(path)] = {'signature': signature, 'item': None}
            continue
        items.append(parsed)
        cache_updates[str(path)] = {'signature': signature, 'item': parsed}
    if cache_updates:
        with _REQUEST_LOG_PARSE_CACHE_LOCK:
            _ERROR_REQUEST_LOG_CACHE.update(cache_updates)
    items.extend(_tail_archived_request_events(limit, source='error-log'))
    items.sort(key=lambda item: int(item.get('timestamp') or 0), reverse=True)
    return items[:limit]
