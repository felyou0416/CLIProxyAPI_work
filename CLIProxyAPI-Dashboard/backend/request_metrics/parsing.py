import hashlib
import ipaddress
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.paths import (
    ACTIVE_AUTH_DIR,
    AUTH_ARCHIVE_DIR,
    AUTH_DIR,
    LEGACY_REQUEST_LOG_DIR,
    PROXY_STDOUT,
    REQUEST_ARCHIVE_DIR,
    REQUEST_LOG_DIR,
    RUNTIME_CONFIG,
)
from backend.api_keys import find_key_by_masked_value, record_api_key_usage, record_api_key_usage_batch
from backend.request_monitoring_config import load_request_monitoring_config

# 批量解析日志文件期间，用量记录先攒在这里，避免每个文件触发一次磁盘读写。
# 由 flush_pending_api_key_usage() 在批量循环结束后一次性落盘。
_PENDING_API_KEY_USAGE: list[tuple[str, int]] = []
_PENDING_API_KEY_USAGE_LOCK = threading.Lock()


def flush_pending_api_key_usage() -> None:
    """把 _PENDING_API_KEY_USAGE 里攒的用量记录一次性批量落盘并清空缓冲区。"""
    global _PENDING_API_KEY_USAGE
    with _PENDING_API_KEY_USAGE_LOCK:
        pending = _PENDING_API_KEY_USAGE
        _PENDING_API_KEY_USAGE = []
    if pending:
        record_api_key_usage_batch(pending)


_PROXY_LINE_RE = re.compile(
    r'^\[(?P<ts>[^\]]+)\]\s+\[(?P<request_id>[^\]]*)\].*?\s(?P<status>\d{3})\s+\|\s+'
    r'(?P<latency>[^|]+)\|\s+(?P<ip>[^|]+)\|\s+(?P<method>[A-Z]+)\s+"(?P<path>[^"]+)"'
)
_REQUEST_URL_RE = re.compile(r'^URL:\s*(.+)$', re.MULTILINE)
_REQUEST_TIMESTAMP_RE = re.compile(r'^Timestamp:\s*(.+)$', re.MULTILINE)
_RESPONSE_STATUS_RE = re.compile(r'^Status:\s*(\d{3})$', re.MULTILINE)
_ERROR_MESSAGE_RE = re.compile(r'"message"\s*:\s*"([^"]+)"')
_ERROR_SUMMARY_MAX_LEN = 2000  # error_summary 字段的最大保留长度，避免异常大错误撑爆归档文件
_AUTHORIZATION_RE = re.compile(r'^Authorization:\s*Bearer\s+(.+)$', re.MULTILINE)
_SECTION_HEADER_RE = re.compile(r'^=== .+ ===$', re.MULTILINE)
_API_REQUEST_HEADER_RE = re.compile(r'^=== API REQUEST(?:\s+\d+)? ===$', re.MULTILINE)
_API_RESPONSE_HEADER_RE = re.compile(r'^=== (?:API )?RESPONSE(?:\s+\d+)? ===$', re.MULTILINE)
_API_REQUEST_AUTH_PROVIDER_RE = re.compile(r'^Auth:\s*provider=([^,\s]+)', re.MULTILINE)
_UPSTREAM_URL_RE = re.compile(r'^Upstream URL:\s*(.+)$', re.MULTILINE)
_UPSTREAM_METHOD_RE = re.compile(r'^HTTP Method:\s*([A-Z]+)$', re.MULTILINE)
_AUTH_LINE_RE = re.compile(r'^Auth:\s*(.+)$', re.MULTILINE)
_TRACE_ID_RE = re.compile(r'^(?:X-Cpa-Trace-Id|Trace-Id):\s*(.+)$', re.MULTILINE | re.IGNORECASE)
_UPSTREAM_REQ_ID_RE = re.compile(r'^(?:X-Oneapi-Request-Id|X-Request-Id|Cf-Ray):\s*(.+)$', re.MULTILINE | re.IGNORECASE)
_FINISH_REASON_RE = re.compile(r'"(?:finish_reason|stop_reason)"\s*:\s*"([^"]+)"')


# ---------------------------------------------------------------------------
# Auth ID → 具体条目反查（用于在请求面板中显示具体 API Key / base_url 信息）
# ---------------------------------------------------------------------------
# Go 端生成 auth_id 的算法（synthesizer/helpers.go StableIDGenerator.Next）：
#   sha256(kind + "\x00" + part1 + "\x00" + part2 + ...)[:12]
#   kind = "openai-compatibility:{provider_name}"
#   parts = [api_key, base_url, proxy_url]  (空字符串也需要 trim 后写入)
# ---------------------------------------------------------------------------

_AUTH_ID_INDEX_LOCK = threading.Lock()
_AUTH_ID_INDEX: dict[str, dict] = {}          # auth_id → {label, base_url, api_key_masked, desc}
_AUTH_ID_INDEX_MTIME: float = 0.0             # RUNTIME_CONFIG 的 mtime，用于检测变动
_AUTH_ID_INDEX_STAT_CHECKED_AT: float = 0.0    # 上次真正做 RUNTIME_CONFIG.stat() 检查的时间
_AUTH_ID_INDEX_STAT_THROTTLE_SECONDS = 5.0     # 节流窗口：这段时间内不重复 stat()


def _stable_id_hash(kind: str, *parts: str) -> str:
    """复现 Go StableIDGenerator.Next 的 SHA-256 哈希。"""
    h = hashlib.sha256()
    h.update(kind.encode('utf-8'))
    for part in parts:
        h.update(b'\x00')
        h.update(part.strip().encode('utf-8'))
    return h.hexdigest()[:12]


def _mask_api_key(key: str) -> str:
    """返回末4位可见的脱敏 key，如 sk-****xxxx。"""
    key = key.strip()
    if len(key) <= 8:
        return key[:2] + '***' if key else ''
    return key[:3] + '***' + key[-4:]


def _build_api_key_to_filename_map() -> dict[tuple[str, str], str]:
    """
    扫描 storage/auth 下的账号 JSON 文件，建立 (api_key, base_url) -> 相对文件名 映射，
    用于把 config 里的 api-key-entries 精确对应回具体的 auth 文件。
    使用联合键以区分 api_key 相同但 base_url 不同的条目（如多 IP 同密钥的 zzzz 节点）。
    """
    mapping: dict[tuple[str, str], str] = {}
    if not AUTH_DIR.exists():
        return mapping
    skip_dirs = {'archive', 'backups', 'logs', 'sources', 'model_pools'}
    for root, dirs, files in os.walk(AUTH_DIR):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
        for fn in files:
            if not fn.endswith('.json'):
                continue
            fp = Path(root) / fn
            try:
                data = json.loads(fp.read_text(encoding='utf-8'))
            except Exception:
                continue
            content = data.get('content') if isinstance(data, dict) else None
            if not isinstance(content, dict):
                continue
            key = str(content.get('api_key') or '').strip()
            base = str(content.get('base_url') or '').strip()
            if not key:
                continue
            try:
                rel = fp.relative_to(AUTH_DIR)
            except Exception:
                rel = fp.name
            # 优先精确联合键，也保留仅 key 的回退键（用 base='' 标记）
            composite = (key, base)
            mapping.setdefault(composite, str(rel))
            # 回退：仅 key（base 为空串）——若已有记录则跳过，避免覆盖
            mapping.setdefault((key, ''), str(rel))
    return mapping


def _build_auth_id_index() -> dict[str, dict]:
    """
    解析 active runtime config YAML，为每个 openai-compatibility api-key-entry
    生成与 Go 端完全一致的 auth_id，构建反查索引。
    同时支持 codex / xai 等 codex-style key（kind = "{provider}:apikey"）。
    返回 {auth_id: {label, base_url, api_key_masked, desc, auth_file}} 字典。
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        return {}

    index: dict[str, dict] = {}
    try:
        raw = RUNTIME_CONFIG.read_text(encoding='utf-8')
        cfg = yaml.safe_load(raw) or {}
    except Exception:
        return {}

    key_to_file = _build_api_key_to_filename_map()

    # ---------- openai-compatibility ----------
    # 注意：Go 的 StableIDGenerator 的碰撞计数器是全局共享的（贯穿整个 config 遍历），
    # 所以 seen_hashes 必须按 kind（provider name）跨 compat block 共享，而不是每块重置。
    compat_seen_hashes: dict[str, dict[str, int]] = {}  # kind -> {raw_hash -> count}

    from urllib.parse import urlparse  # noqa: PLC0415

    for compat in cfg.get('openai-compatibility') or []:
        if not isinstance(compat, dict) or compat.get('disabled'):
            continue
        name = str(compat.get('name') or '').strip().lower() or 'openai-compatibility'
        base = str(compat.get('base-url') or '').strip()
        kind = f'openai-compatibility:{name}'
        display_name = str(compat.get('name') or name)

        # 跨 block 共享碰撞计数器
        seen_hashes = compat_seen_hashes.setdefault(kind, {})

        try:
            host = urlparse(base).hostname or base
        except Exception:
            host = base

        entries = compat.get('api-key-entries') or []
        if entries:
            block_key_idx = 0  # 该 block 内的 key 序号，用于展示
            for j, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                block_key_idx += 1
                key = str(entry.get('api-key') or '').strip()
                proxy = str(entry.get('proxy-url') or '').strip()
                raw_hash = _stable_id_hash(kind, key, base, proxy)
                cnt = seen_hashes.get(raw_hash, 0)
                seen_hashes[raw_hash] = cnt + 1
                short = raw_hash if cnt == 0 else f'{raw_hash}-{cnt}'
                auth_id = f'{kind}:{short}'
                # 优先用 (key, base) 联合键精确匹配文件名（避免同 key 不同 IP 混淆）
                auth_file = (
                    key_to_file.get((key, base)) or
                    key_to_file.get((key, ''), '')
                ) if key else ''
                # auth_label 只放服务商+host+key尾号，不含文件名（文件名单独放 auth_file 字段）
                desc = f'{display_name} [{host}]'
                if key:
                    desc += f' ({_mask_api_key(key)})'
                index[auth_id] = {
                    'label': display_name,
                    'base_url': base,
                    'api_key_masked': _mask_api_key(key) if key else '',
                    'desc': desc,
                    'auth_file': auth_file,
                    'entry_index': j,
                }
        else:
            # no api-key-entries: hash is just base
            raw_hash = _stable_id_hash(kind, base)
            cnt = seen_hashes.get(raw_hash, 0)
            seen_hashes[raw_hash] = cnt + 1
            short = raw_hash if cnt == 0 else f'{raw_hash}-{cnt}'
            auth_id = f'{kind}:{short}'
            index[auth_id] = {
                'label': display_name,
                'base_url': base,
                'api_key_masked': '',
                'desc': f'{display_name} [{host}]',
                'auth_file': '',
                'entry_index': 0,
            }

    # ---------- codex / xai / kimi 等 codex-style keys ----------
    for section_key, provider_name in (
        ('codex', 'codex'),
        ('xai-key', 'xai'),
        ('kimi-key', 'kimi'),
    ):
        entries_raw = cfg.get(section_key)
        if not entries_raw:
            continue
        if isinstance(entries_raw, list):
            entries_list = entries_raw
        elif isinstance(entries_raw, dict):
            entries_list = [entries_raw]
        else:
            continue
        kind = f'{provider_name}:apikey'
        seen_hashes_c: dict[str, int] = {}
        for entry in entries_list:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get('api-key') or '').strip()
            base = str(entry.get('base-url') or '').strip()
            if not key:
                continue
            raw_hash = _stable_id_hash(kind, key, base)
            cnt = seen_hashes_c.get(raw_hash, 0)
            seen_hashes_c[raw_hash] = cnt + 1
            short = raw_hash if cnt == 0 else f'{raw_hash}-{cnt}'
            auth_id = f'{kind}:{short}'
            auth_file = (
                key_to_file.get((key, base)) or
                key_to_file.get((key, ''), '')
            )
            index[auth_id] = {
                'label': provider_name,
                'base_url': base,
                'api_key_masked': _mask_api_key(key),
                'desc': f'{provider_name} ({_mask_api_key(key)})',
                'auth_file': auth_file,
                'entry_index': 0,
            }

    return index


def _get_auth_id_index() -> dict[str, dict]:
    """
    返回 auth_id 反查索引（懒加载 + mtime 缓存 + stat 节流）。

    这个函数会被 _parse_request_log_file 在批量解析上百个日志文件的循环里
    逐文件调用一次（通过 resolve_auth_id_desc）。即使 YAML 解析结果有 mtime
    缓存，每次调用仍然会触发一次 RUNTIME_CONFIG.stat() 系统调用去判断缓存是否
    过期——在这个环境下单次 stat() 实测约 5-7ms，文件一多，累计开销不可忽略。
    这里加一层节流：短时间窗口内（默认 5 秒）重复调用直接复用已缓存的索引，
    完全跳过 stat()，配置变更最多延迟一个窗口才会被感知到，可接受。
    """
    global _AUTH_ID_INDEX, _AUTH_ID_INDEX_MTIME, _AUTH_ID_INDEX_STAT_CHECKED_AT
    now = time.time()
    with _AUTH_ID_INDEX_LOCK:
        if _AUTH_ID_INDEX and (now - _AUTH_ID_INDEX_STAT_CHECKED_AT) < _AUTH_ID_INDEX_STAT_THROTTLE_SECONDS:
            return _AUTH_ID_INDEX
        try:
            mtime = RUNTIME_CONFIG.stat().st_mtime if RUNTIME_CONFIG.exists() else 0.0
        except Exception:
            mtime = 0.0
        _AUTH_ID_INDEX_STAT_CHECKED_AT = now
        if mtime != _AUTH_ID_INDEX_MTIME or not _AUTH_ID_INDEX:
            _AUTH_ID_INDEX = _build_auth_id_index()
            _AUTH_ID_INDEX_MTIME = mtime
        return _AUTH_ID_INDEX


def get_auth_id_index_snapshot() -> dict[str, dict]:
    """
    公开的一次性快照获取接口，供批量场景（如 merge_request_events）调用：
    调用方应只调用一次，然后在循环里用普通字典查找，避免每条记录都触发一次
    RUNTIME_CONFIG.stat() 系统调用（在慢速/网络盘上这个开销会被放大很多）。
    """
    return _get_auth_id_index()


def resolve_auth_id_desc(auth_id: str) -> str:
    """
    根据 auth_id 返回更具体的显示描述（服务商 + 文件名/base_url + key 尾号）。
    找不到时返回空字符串。
    """
    if not auth_id:
        return ''
    idx = _get_auth_id_index()
    entry = idx.get(auth_id)
    if not entry:
        return ''
    return entry.get('desc') or ''


def resolve_auth_id_file(auth_id: str) -> str:
    """
    根据 auth_id 返回对应的 auth 文件相对路径（如 ung/6-1 - 副本 - 副本.json）。
    找不到时返回空字符串。
    """
    if not auth_id:
        return ''
    idx = _get_auth_id_index()
    entry = idx.get(auth_id)
    if not entry:
        return ''
    return entry.get('auth_file') or ''


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
    'request_time',
    'response_time',
    'upstream_latency_ms',
    'overhead_ms',
    'tps',
    'prompt_tokens',
    'completion_tokens',
    'total_tokens',
    'cached_tokens',
    'reasoning_tokens',
    'user_agent',
    'upstream_url',
    'auth_label',
    'auth_id',
    'auth_file',
    'stream',
    'trace_id',
    'upstream_request_id',
    'finish_reason',
    'prompt_preview',
    'response_preview',
    'log_file',
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
_REQUEST_LOG_PARSE_CACHE_VERSION = 4  # bumped when event format or extraction logic changes
_OBSERVABILITY_EVENT_LIMIT = 300
_OBSERVABILITY_SUMMARY_LIMIT = 200

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
            # 单次读取的块大小随目标行数放大，避免大 limit 时反复触发多轮循环。
            chunk_size = max(65536, min(file_size, 4 * 1024 * 1024))
            buffer = b''
            newline_count = 0
            position = file_size
            target_newlines = max(1, limit + 1)

            # 性能要点：不要在每轮循环里对整个（持续增长的）buffer 重新调用 count(b'\n')，
            # 那是 O(n^2)。只对新读到的 chunk 计数，累加即可，整体降为 O(n)。
            while position > 0 and newline_count < target_newlines:
                read_size = min(chunk_size, position)
                position -= read_size
                fh.seek(position)
                chunk = fh.read(read_size)
                newline_count += chunk.count(b'\n')
                buffer = chunk + buffer

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


#  "API REQUEST N" section 只需要读 Timestamp / Upstream URL / HTTP Method /
# Auth 这几行头信息（在 section 开头几百字节内），不需要整个 body。
# 之前用 header_re.search(raw, start) 去找"下一个 section 的起点"来确定当前
# section 的结束位置——如果这是文件里最后一个 section（常见情况：紧跟着的就是
# 巨大的 RESPONSE body），"找不到下一个 header"意味着正则必须扫到文件末尾
# 才能确认失败，对几 MB 的流式响应文件代价很高。这里改为只截取一个足够覆盖
# 头信息的小窗口，避免这个 O(文件大小) 的扫描。
_API_REQUEST_SECTION_WINDOW = 4096


def _iter_api_request_sections(content: str) -> list[str]:
    raw = str(content or '')
    if not raw:
        return []
    sections = []
    matches = list(_API_REQUEST_HEADER_RE.finditer(raw))
    for index, match in enumerate(matches):
        start = match.end()
        window_end = min(len(raw), start + _API_REQUEST_SECTION_WINDOW)
        next_header = _SECTION_HEADER_RE.search(raw, start, window_end)
        if next_header:
            end = next_header.start()
        elif index + 1 < len(matches) and matches[index + 1].start() <= window_end:
            end = matches[index + 1].start()
        else:
            end = window_end
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


#  Go 的 time.RFC3339Nano 会输出纳秒精度的小数秒（最多9位，如 ".2028157"，
# 7位）。Python 的 datetime.fromisoformat 在这个环境的 Python 版本上只接受
# 3位或6位小数秒，7位/9位会直接抛异常——之前被 except Exception 静默吞掉，
# 导致这类时间戳全部解析失败，request_time/latency_ms 等字段整体缺失。
# 这里在解析前把小数秒规整为 6 位（截断或补零），与 fromisoformat 兼容。
_ISO_TS_FRACTION_RE = re.compile(r'(\.\d+)')


def _normalize_iso_fraction(value: str) -> str:
    def _fix(match: re.Match) -> str:
        frac = match.group(1)[1:]  # 去掉开头的点
        frac = (frac + '000000')[:6]
        return '.' + frac
    return _ISO_TS_FRACTION_RE.sub(_fix, value, count=1)


def _parse_iso_ts(raw: str) -> tuple[float | None, str]:
    value = str(raw or '').strip()
    if not value:
        return None, ''
    try:
        dt = datetime.fromisoformat(_normalize_iso_fraction(value.replace('Z', '+00:00')))
        return dt.timestamp(), dt.strftime('%Y-%m-%d %H:%M:%S') + f'.{dt.microsecond // 1000:03d}'
    except Exception:
        return None, ''


#  调用方（_extract_log_timings）只需要每个 section 开头的 "Timestamp: ..." 一行，
# 不需要整段内容。原实现用 next_header 的位置作为结束边界；当该 section 是文件
# 最后一段（如 RESPONSE，后面是几 MB 的流式 body、没有下一个 header）时，
# _SECTION_HEADER_RE.search 必须扫到文件末尾才能确认找不到，代价很高。
# 这里同样限制在一个小窗口内查找边界。
_SECTION_TEXT_WINDOW = 2048


def _extract_section_text(content: str, header_re: re.Pattern) -> str:
    raw = str(content or '')
    match = header_re.search(raw)
    if not match:
        return ''
    start = match.end()
    window_end = min(len(raw), start + _SECTION_TEXT_WINDOW)
    next_header = _SECTION_HEADER_RE.search(raw, start, window_end)
    end = next_header.start() if next_header else window_end
    return raw[start:end].strip()


def _extract_actual_upstream(content: str) -> tuple[str, str, str, str, str, str, str, str]:
    actual_provider = ''
    actual_model = ''
    auth_label = ''
    auth_id = ''
    auth_type = ''
    upstream_url = ''
    upstream_method = ''
    for section in _iter_api_request_sections(content):
        url_match = _UPSTREAM_URL_RE.search(section)
        if url_match and not upstream_url:
            upstream_url = str(url_match.group(1) or '').strip()
        method_match = _UPSTREAM_METHOD_RE.search(section)
        if method_match and not upstream_method:
            upstream_method = str(method_match.group(1) or '').strip()

        auth_match = _AUTH_LINE_RE.search(section)
        if auth_match:
            auth_str = auth_match.group(1)
            for part in auth_str.split(','):
                part = part.strip()
                if '=' in part:
                    k, v = part.split('=', 1)
                    k = k.strip().lower()
                    v = v.strip()
                    if k == 'provider' and not actual_provider:
                        actual_provider = v.lower()
                    elif k == 'auth_id' and not auth_id:
                        auth_id = v
                    elif k == 'label' and not auth_label:
                        auth_label = v
                    elif k == 'type' and not auth_type:
                        auth_type = v

        provider_match = _API_REQUEST_AUTH_PROVIDER_RE.search(section)
        if provider_match and not actual_provider:
            actual_provider = str(provider_match.group(1) or '').strip().lower()

        model = _extract_model_from_text(_extract_api_request_body(section))
        if model and not actual_model:
            actual_model = model

    route_source = 'precise-log' if (actual_provider or actual_model) else ''
    return actual_provider, actual_model, route_source, auth_label, auth_id, auth_type, upstream_url, upstream_method


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


def _extract_usage_tokens(content: str) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    """从 content 中提取 usage token 信息（包含 prompt/completion/total/cached/reasoning）。"""
    raw = str(content or '')
    if not raw:
        return None, None, None, None, None

    prompts = []
    completions = []
    totals = []
    cached_list = []
    reasoning_list = []
    offset = 0
    while True:
        idx = raw.find('"usage"', offset)
        if idx == -1:
            break
        brace = raw.find('{', idx + 7)
        if brace == -1:
            offset = idx + 7
            continue
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

        prompt = parsed.get('prompt_tokens') if parsed.get('prompt_tokens') is not None else parsed.get('input_tokens')
        completion = parsed.get('completion_tokens') if parsed.get('completion_tokens') is not None else parsed.get('output_tokens')
        total = parsed.get('total_tokens')

        cached = None
        prompt_details = parsed.get('prompt_tokens_details')
        if isinstance(prompt_details, dict) and prompt_details.get('cached_tokens') is not None:
            cached = prompt_details.get('cached_tokens')
        elif parsed.get('cache_read_input_tokens') is not None:
            cached = parsed.get('cache_read_input_tokens')
        elif parsed.get('cached_tokens') is not None:
            cached = parsed.get('cached_tokens')

        reasoning = None
        comp_details = parsed.get('completion_tokens_details')
        if isinstance(comp_details, dict) and comp_details.get('reasoning_tokens') is not None:
            reasoning = comp_details.get('reasoning_tokens')
        elif parsed.get('thinking_tokens') is not None:
            reasoning = parsed.get('thinking_tokens')
        elif parsed.get('reasoning_tokens') is not None:
            reasoning = parsed.get('reasoning_tokens')

        try: prompt = int(prompt) if prompt is not None else None
        except Exception: prompt = None
        try: completion = int(completion) if completion is not None else None
        except Exception: completion = None
        try: total = int(total) if total is not None else None
        except Exception: total = None
        try: cached = int(cached) if cached is not None else None
        except Exception: cached = None
        try: reasoning = int(reasoning) if reasoning is not None else None
        except Exception: reasoning = None

        if prompt is not None: prompts.append(prompt)
        if completion is not None: completions.append(completion)
        if total is not None: totals.append(total)
        if cached is not None: cached_list.append(cached)
        if reasoning is not None: reasoning_list.append(reasoning)

        offset = brace + 1

    if not prompts and not completions and not totals:
        return None, None, None, None, None

    final_prompt = max(prompts) if prompts else None
    final_completion = max(completions) if completions else None
    final_total = max(totals) if totals else None
    final_cached = max(cached_list) if cached_list else None
    final_reasoning = max(reasoning_list) if reasoning_list else None
    if final_total is None and (final_prompt is not None or final_completion is not None):
        final_total = (final_prompt or 0) + (final_completion or 0)
    return final_prompt, final_completion, final_total, final_cached, final_reasoning


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
    """Return recent archived events, or all retained events when limit is zero."""
    if not REQUEST_ARCHIVE_DIR.exists():
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
        lines = (
            archive_path.read_text(encoding='utf-8', errors='ignore').splitlines()
            if limit <= 0
            else _tail_lines(archive_path, max(limit * 2, 100))
        )
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if source and str(item.get('source') or '') != source:
                continue
            items.append(item)
            if limit > 0 and len(items) >= limit:
                return items
    return items


_ARCHIVE_COUNT_CACHE_LOCK = threading.Lock()
_ARCHIVE_COUNT_CACHE: dict = {'ts': 0.0, 'count': 0}
_ARCHIVE_COUNT_CACHE_TTL_SECONDS = 10.0


def estimate_archived_event_count() -> int:
    """
    估算归档 jsonl 里的事件总数（近似值，按行数统计，不逐行解析 JSON）。

    用于给懒加载分页路径（get_routes.py 的 /api/request-events 无筛选分支）
    的 total 字段补上归档部分的数量，使其与全量路径的 total 语义尽量接近
    （全量路径的 total 是"精细日志 + proxy + error + 归档"去重后的事件数）。
    懒加载路径本身只统计了精细日志文件数，如果不补上归档数量，用户从"无筛选"
    切到"有筛选"时会看到 total 出现断崖式跳变（比如从 270 跳到 3000+），
    容易被误解为数据不一致。
    这里做了短时缓存（10秒），避免分页时反复读大文件统计行数。
    """
    now = time.time()
    with _ARCHIVE_COUNT_CACHE_LOCK:
        if (now - _ARCHIVE_COUNT_CACHE['ts']) < _ARCHIVE_COUNT_CACHE_TTL_SECONDS:
            return _ARCHIVE_COUNT_CACHE['count']
    count = 0
    try:
        if REQUEST_ARCHIVE_DIR.exists():
            for path in REQUEST_ARCHIVE_DIR.glob('request-events-*.jsonl'):
                if not path.is_file():
                    continue
                try:
                    with path.open('rb') as fh:
                        count += sum(1 for _ in fh)
                except Exception:
                    # 单个文件读取失败时跳过它，不影响其它文件已经统计到的行数。
                    continue
    except Exception:
        # glob() 本身出问题时才会走到这里；保留已经累积的 count，不清零，
        # 这样至少能返回一个"部分统计"的估算值，比强行归零更接近真实情况。
        pass
    with _ARCHIVE_COUNT_CACHE_LOCK:
        _ARCHIVE_COUNT_CACHE['count'] = count
        _ARCHIVE_COUNT_CACHE['ts'] = now
    return count


def _request_log_dirs() -> list[Path]:
    # Active runtime auth dir is the live request-log target written by the proxy.
    # Keep legacy locations so older installs and archived auth trees still resolve.
    dirs = [
        ACTIVE_AUTH_DIR / 'logs',
        REQUEST_LOG_DIR,
        AUTH_DIR / 'logs',
        AUTH_ARCHIVE_DIR / 'default' / 'metadata' / 'logs',
        LEGACY_REQUEST_LOG_DIR,
    ]
    result = []
    seen = set()
    for path in dirs:
        key = str(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result


def _trim_request_event_archives(max_entries: int | None = None) -> None:
    if max_entries is None:
        max_entries = load_request_monitoring_config()['request_event_archive_keep_entries']
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


#  流式（SSE）响应日志文件可能有几 MB，其中绝大部分是响应体本身的数据 chunk。
# trace_id / upstream_request_id / finish_reason 这些标记只会出现在请求头区
# （文件开头）或最后一个响应 chunk（文件末尾），从不出现在中间的大段流式数据里。
# 对整个 content 做 re.search() 时，正则引擎在找不到匹配、或匹配位置在文件
# 末尾时，必须线性扫过全部字节——文件一大、数量一多，这就是解析变慢的主因。
# 因此这里先只在“头部 + 尾部”各取一段窗口内搜索，命中就直接用；
# 只有在两端都没命中时，才退回对全文做一次兜底搜索（保证正确性不降级）。
_SNIPPET_HEAD_WINDOW = 8192
_SNIPPET_TAIL_WINDOW = 131072  # 128KB，足够覆盖最后一个 SSE chunk


def _head_tail_search(pattern: re.Pattern, content: str):
    """
    只在 content 的头部/尾部窗口内查找，不做全文兜底扫描。

    重要：早期版本在头尾都找不到时会退回对全文 re.search(content) 兜底，
    这恰好是最常触发、也最昂贵的路径——当一个标记本来就不存在于文件里
    （比如非流式请求里没有 "stream": true，或者日志里没有 trace_id 头），
    头尾窗口搜索必然落空，兜底扫描就会对着几 MB 的大文件走一次完整的
    O(n) 正则匹配，而结果注定还是"找不到"。批量场景下这种"确认没有"的
    全文扫描是最大的性能陷阱。
    这几个字段按日志写入逻辑只会出现在请求头区（文件开头）或最后一个
    响应 chunk（文件末尾）附近，不会出现在中间那一大段流式数据体里，
    所以头尾窗口没找到就可以直接判定为"不存在"，不再兜底。
    """
    n = len(content)
    if n <= _SNIPPET_HEAD_WINDOW + _SNIPPET_TAIL_WINDOW:
        return pattern.search(content)
    head = content[:_SNIPPET_HEAD_WINDOW]
    m = pattern.search(head)
    if m:
        return m
    tail_start = n - _SNIPPET_TAIL_WINDOW
    tail = content[tail_start:]
    return pattern.search(tail)


def _extract_snippets_and_flags(content: str) -> dict:
    stream = False
    finish_reason = ''
    prompt_preview = ''
    response_preview = ''
    trace_id = ''
    upstream_req_id = ''

    # Stream flag：一般出现在请求体（文件靠前部分），头部窗口足够。
    if _head_tail_search(re.compile(r'"stream"\s*:\s*true', re.IGNORECASE), content):
        stream = True

    # Trace ID：出现在响应头区域（文件末尾附近）。
    trace_m = _head_tail_search(_TRACE_ID_RE, content)
    if trace_m:
        trace_id = str(trace_m.group(1) or '').strip()

    # Upstream Request ID：同上，响应头区域。
    req_id_m = _head_tail_search(_UPSTREAM_REQ_ID_RE, content)
    if req_id_m:
        upstream_req_id = str(req_id_m.group(1) or '').strip()

    # Finish Reason：非流式在响应体里，流式在最后一个 chunk 里，都在尾部窗口内。
    fr_m = _head_tail_search(_FINISH_REASON_RE, content)
    if fr_m:
        finish_reason = str(fr_m.group(1) or '').strip()

    # Prompt preview
    if '=== REQUEST BODY ===' in content:
        body_part = content.split('=== REQUEST BODY ===', 1)[1].split('===', 1)[0].strip()
        try:
            parsed_body = json.loads(body_part)
            if isinstance(parsed_body, dict):
                msgs = parsed_body.get('messages') or []
                if isinstance(msgs, list) and msgs:
                    for m in reversed(msgs):
                        if isinstance(m, dict) and m.get('role') == 'user':
                            c = m.get('content')
                            if isinstance(c, str):
                                prompt_preview = c.strip()[:300]
                            elif isinstance(c, list):
                                for item in c:
                                    if isinstance(item, dict) and item.get('text'):
                                        prompt_preview = str(item.get('text')).strip()[:300]
                                        break
                            if prompt_preview:
                                break
                    if not prompt_preview and isinstance(msgs[0], dict):
                        prompt_preview = str(msgs[0].get('content') or '')[:300]
        except Exception:
            pass

    # Response preview
    if '=== RESPONSE ===' in content or '=== API RESPONSE' in content:
        res_part = (content.split('=== RESPONSE ===', 1)[1] if '=== RESPONSE ===' in content else content.split('=== API RESPONSE', 1)[1]).split('===', 1)[0].strip()
        if '\nBody:\n' in res_part:
            res_part = res_part.split('\nBody:\n', 1)[1].strip()
        try:
            b_idx = res_part.find('{')
            if b_idx != -1:
                json_str = _extract_balanced_json(res_part, b_idx)
                if json_str:
                    res_json = json.loads(json_str)
                    if isinstance(res_json, dict):
                        choices = res_json.get('choices') or []
                        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                            msg = choices[0].get('message') or choices[0].get('delta') or {}
                            if isinstance(msg, dict):
                                response_preview = str(msg.get('content') or msg.get('reasoning_content') or '')[:300]
                        elif res_json.get('content'):
                            c = res_json.get('content')
                            if isinstance(c, list) and c and isinstance(c[0], dict):
                                response_preview = str(c[0].get('text') or '')[:300]
                            elif isinstance(c, str):
                                response_preview = c[:300]
        except Exception:
            pass

    return {
        'stream': stream,
        'finish_reason': finish_reason,
        'prompt_preview': prompt_preview,
        'response_preview': response_preview,
        'trace_id': trace_id,
        'upstream_request_id': upstream_req_id,
    }


def _extract_log_timings(content: str) -> dict:
    req_sec = _extract_section_text(content, re.compile(r'^=== REQUEST INFO ===$', re.MULTILINE))
    api_req_sec = _extract_section_text(content, _API_REQUEST_HEADER_RE)
    api_res_sec = _extract_section_text(content, _API_RESPONSE_HEADER_RE)
    res_sec = _extract_section_text(content, re.compile(r'^=== RESPONSE ===$', re.MULTILINE))

    m_req = _REQUEST_TIMESTAMP_RE.search(req_sec)
    m_api_req = _REQUEST_TIMESTAMP_RE.search(api_req_sec)
    m_api_res = _REQUEST_TIMESTAMP_RE.search(api_res_sec)
    m_res = _REQUEST_TIMESTAMP_RE.search(res_sec)

    t_start, start_fmt = _parse_iso_ts(m_req.group(1) if m_req else '')
    t_api_req, api_req_fmt = _parse_iso_ts(m_api_req.group(1) if m_api_req else '')
    t_api_res, api_res_fmt = _parse_iso_ts(m_api_res.group(1) if m_api_res else '')
    t_end, end_fmt = _parse_iso_ts(m_res.group(1) if m_res else (m_api_res.group(1) if m_api_res else ''))

    latency_ms = None
    if t_start and t_end and t_end >= t_start:
        latency_ms = int(round((t_end - t_start) * 1000))
    elif t_start and t_api_res and t_api_res >= t_start:
        latency_ms = int(round((t_api_res - t_start) * 1000))

    upstream_latency_ms = None
    if t_api_req and t_api_res and t_api_res >= t_api_req:
        upstream_latency_ms = int(round((t_api_res - t_api_req) * 1000))

    overhead_ms = None
    if t_start and t_api_req and t_api_req >= t_start:
        overhead_ms = int(round((t_api_req - t_start) * 1000))

    return {
        'request_time': start_fmt,
        'upstream_request_time': api_req_fmt,
        'upstream_response_time': api_res_fmt,
        'response_time': end_fmt or api_res_fmt,
        'latency_ms': latency_ms,
        'upstream_latency_ms': upstream_latency_ms,
        'overhead_ms': overhead_ms,
        'start_timestamp': t_start,
    }


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

    actual_provider, actual_model, route_source, auth_label, auth_id, auth_type, upstream_url, upstream_method = _extract_actual_upstream(content)
    prompt_tokens, completion_tokens, total_tokens, cached_tokens, reasoning_tokens = _extract_usage_tokens(content)

    # auth_label 原本只是服务商名（如 "ung"），无法区分具体走的哪个账号/API Key。
    # 通过 auth_id 反查 active runtime config，补上 base_url 与 key 尾号，方便面板定位。
    if auth_id:
        resolved_desc = resolve_auth_id_desc(auth_id)
        if resolved_desc:
            auth_label = resolved_desc

    auth_match = _AUTHORIZATION_RE.search(content)
    api_key_masked = str(auth_match.group(1) if auth_match else '').strip()

    if record_usage and api_key_masked:
        full_key = find_key_by_masked_value(api_key_masked)
        if full_key:
            # 不在这里直接写盘：批量解析上百个历史日志文件时，每文件一次
            # 「读usage.json→改→写回」的开销会显著拖慢刷新。改为攒到模块级
            # 缓冲区，由外层批量循环（parse_precise_request_events /
            # parse_error_logs）结束后统一调用 flush_pending_api_key_usage()
            # 一次性落盘。
            with _PENDING_API_KEY_USAGE_LOCK:
                _PENDING_API_KEY_USAGE.append((full_key, total_tokens or 0))

    status_code = int(status_match.group(1)) if status_match else (500 if error_log else 200)
    error_message = ''
    if error_log:
        message_match = _ERROR_MESSAGE_RE.search(content)
        if message_match:
            error_message = str(message_match.group(1) or '').strip()
    if not error_message and status_code >= 400:
        err_match = re.search(r'Error:\s*([^\r\n]+)', content)
        if err_match:
            error_message = str(err_match.group(1)).strip()
    # 既有缺陷：_ERROR_MESSAGE_RE 是 "message"\s*:\s*"([^"]+)"，当上游错误响应体里
    # 把大段 JSON（如完整的 tool schema 回显）内嵌在 message 字段值里时，这个正则
    # 会把整段内容当作 message 抓下来，没有长度限制。实测出现过 320KB+ 的单条错误
    # 摘要，被原样写进归档 jsonl，导致单个归档文件从几 MB 膨胀到十几 MB。
    # 这里做一次防御性截断，保留足够诊断信息即可。
    if len(error_message) > _ERROR_SUMMARY_MAX_LEN:
        error_message = error_message[:_ERROR_SUMMARY_MAX_LEN] + f'... [截断，原长度 {len(error_message)} 字符]'

    client_ip, client_ip_source = _extract_client_ip_from_headers(content)
    headers = _extract_headers(content)
    user_agent = (headers.get('user-agent') or [''])[0]
    session_id = (headers.get('x-claude-code-session-id') or [''])[0]

    timings = _extract_log_timings(content)
    snippets = _extract_snippets_and_flags(content)

    latency_ms = timings.get('latency_ms')
    tps = None
    if completion_tokens and latency_ms and latency_ms > 0:
        tps = round(completion_tokens / (latency_ms / 1000.0), 1)

    timestamp = int(timings.get('start_timestamp') or _safe_timestamp(request_time_match.group(1) if request_time_match else '', int(stat.st_mtime)))

    return {
        'timestamp': timestamp,
        'request_time': timings.get('request_time') or '',
        'upstream_request_time': timings.get('upstream_request_time') or '',
        'upstream_response_time': timings.get('upstream_response_time') or '',
        'response_time': timings.get('response_time') or '',
        'client_ip': client_ip,
        'client_ip_source': client_ip_source,
        'user_agent': user_agent,
        'session_id': session_id,
        'path': _normalize_path(url_match.group(1) if url_match else path.stem),
        'requested_model': requested_model,
        'status_code': status_code,
        'success': 200 <= status_code < 400,
        'latency_ms': latency_ms,
        'upstream_latency_ms': timings.get('upstream_latency_ms'),
        'overhead_ms': timings.get('overhead_ms'),
        'tps': tps,
        'error_summary': error_message or (path.name if error_log else ''),
        'request_id': request_id,
        'inferred_provider': actual_provider,
        'actual_provider': actual_provider,
        'routed_model': actual_model,
        'actual_model': actual_model,
        'auth_label': auth_label,
        'auth_id': auth_id,
        'auth_file': resolve_auth_id_file(auth_id) if auth_id else '',
        'auth_type': auth_type,
        'upstream_url': upstream_url,
        'upstream_method': upstream_method or 'POST',
        'route_source': route_source,
        'route_confidence': 1.0 if route_source else 0.0,
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': total_tokens,
        'cached_tokens': cached_tokens,
        'reasoning_tokens': reasoning_tokens,
        'stream': snippets.get('stream', False),
        'trace_id': snippets.get('trace_id') or '',
        'upstream_request_id': snippets.get('upstream_request_id') or '',
        'finish_reason': snippets.get('finish_reason') or '',
        'prompt_preview': snippets.get('prompt_preview') or '',
        'response_preview': snippets.get('response_preview') or '',
        'log_file': path.name,
        'api_key_masked': api_key_masked,
        'notes': [path.name],
        'source': 'error-log' if error_log else 'precise-log',
        'method': 'POST',
    }


def prune_request_logs(max_files: int | None = None) -> None:
    if max_files is None:
        max_files = load_request_monitoring_config()['request_log_keep_files']
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
    line_limit = 0 if limit <= 0 else max(200, limit * 4)
    for line in _tail_lines(PROXY_STDOUT, line_limit):
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
    return items[:limit] if limit > 0 else items


def _list_precise_log_paths() -> list[Path]:
    """列出所有非 error- 前缀的精细日志文件路径（不读取内容，只做发现）。"""
    log_paths = []
    seen_paths = set()
    for log_dir in _request_log_dirs():
        if not log_dir.exists():
            continue
        for path in log_dir.glob('*.log'):
            if path.name.startswith('error-'):
                continue
            key = str(path)
            if key not in seen_paths:
                log_paths.append(path)
                seen_paths.add(key)
    return log_paths


def _parse_one_precise_log_file(path: Path) -> dict | None:
    """
    解析单个精细日志文件，命中缓存则直接返回缓存结果，不重复读盘/解析。
    供 parse_precise_request_events（全量）和 get_precise_request_events_page
    （按需分页）共用同一套解析 + 缓存逻辑，避免两条路径各写一遍、行为不一致。
    """
    if not path.is_file():
        return None
    try:
        stat = path.stat()
    except Exception:
        return None
    signature = (int(stat.st_mtime_ns), int(stat.st_size), _REQUEST_LOG_PARSE_CACHE_VERSION)
    with _REQUEST_LOG_PARSE_CACHE_LOCK:
        cached = _PRECISE_REQUEST_LOG_CACHE.get(str(path))
    if cached and cached.get('signature') == signature:
        parsed = cached.get('item')
        return dict(parsed) if parsed else None
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return None
    if '=== REQUEST BODY ===' not in content:
        with _REQUEST_LOG_PARSE_CACHE_LOCK:
            _PRECISE_REQUEST_LOG_CACHE[str(path)] = {'signature': signature, 'item': None}
        return None
    parsed = _parse_request_log_file(path, content, stat, error_log=False, record_usage=True)
    with _REQUEST_LOG_PARSE_CACHE_LOCK:
        _PRECISE_REQUEST_LOG_CACHE[str(path)] = {'signature': signature, 'item': parsed}
    # 注意：不在这里调用 flush_pending_api_key_usage()。这个函数会被批量循环
    # 逐文件调用（parse_precise_request_events / get_precise_request_events_page），
    # 如果每解析一个文件就 flush 一次，等于完全抵消了“攒够一批再统一落盘”的优化
    # 意义——调用方应该在循环结束后自己调用一次 flush_pending_api_key_usage()。
    return parsed


def _sorted_by_mtime_desc(paths: list[Path]) -> list[Path]:
    """
    按 mtime 降序排序一批路径。

    性能要点：不要用 sorted(paths, key=lambda p: p.stat().st_mtime) ——
    Python 的 sort 是 O(n log n) 次比较，但 key 函数只会对每个元素调用一次
    （Schwartzian transform），所以 stat() 总次数就是 n 次，这本身没问题；
    真正要避免的是"排序之后还要在别处对同一批文件再 stat() 一次"。
    这里统一返回排序结果，调用方后续都基于这个已经算过 stat 的顺序操作，
    不再重复调用 path.stat() 做排序。
    """
    def _mtime_or_zero(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except Exception:
            return 0.0
    return sorted(paths, key=_mtime_or_zero, reverse=True)


def parse_precise_request_events(limit: int = 500) -> list[dict]:
    """Parse precise request events, including retained archive events.

    A positive limit keeps this suitable for lightweight background summaries.
    Passing zero reads the complete retained set for the request-table snapshot.
    """
    items = []
    log_paths = _sorted_by_mtime_desc(_list_precise_log_paths())
    if limit > 0:
        log_paths = log_paths[:max(50, limit)]
    for path in log_paths:
        parsed = _parse_one_precise_log_file(path)
        if parsed:
            items.append(parsed)
    flush_pending_api_key_usage()
    items.extend(_tail_archived_request_events(limit, source='precise-log'))
    items.sort(key=lambda item: int(item.get('timestamp') or 0), reverse=True)
    return items[:limit] if limit > 0 else items


def get_precise_request_events_page(offset: int, limit: int) -> tuple[list[dict], int]:
    """
    按需分页读取精细日志事件：只 stat() 全部文件做排序定位，只解析当前这一页
    真正落在 [offset, offset+limit) 范围内的那些文件；同页内已解析过的文件走
    _PRECISE_REQUEST_LOG_CACHE 缓存，不会重复读盘。

    用于表格“无筛选条件”时的快速分页路径：翻页只读这一页对应的文件，
    不会像 parse_precise_request_events() 那样一次性把所有保留的文件都解析一遍。

    返回 (这一页的事件列表, 参与分页的文件总数)。
    注意：这里的"总数"只统计精细日志文件本身，不包含归档 jsonl 里的历史事件——
    归档部分数据量小（受 Dashboard 请求监控中的归档保留数限制），调用方如果
    需要归档数据可以在没有更多精细日志文件时再自行补充。
    """
    log_paths = _list_precise_log_paths()
    ordered = _sorted_by_mtime_desc(log_paths)
    total = len(ordered)
    page_paths = ordered[offset:offset + limit]
    items = []
    for path in page_paths:
        parsed = _parse_one_precise_log_file(path)
        if parsed:
            items.append(parsed)
    flush_pending_api_key_usage()
    items.sort(key=lambda item: int(item.get('timestamp') or 0), reverse=True)
    return items, total


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
    files = _sorted_by_mtime_desc(files)
    if limit > 0:
        files = files[:limit]
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
    flush_pending_api_key_usage()
    items.extend(_tail_archived_request_events(limit, source='error-log'))
    items.sort(key=lambda item: int(item.get('timestamp') or 0), reverse=True)
    return items[:limit] if limit > 0 else items
