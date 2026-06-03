import json
import os
import re
import shutil
import time
import hashlib
import base64
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from backend.paths import AUTH_SOURCE_DIRS, MANUAL_AUTH_SAVE_DIR, SOURCE_AUTH_DIR, ACTIVE_AUTH_DIR, BASE_CONFIG, RUNTIME_CONFIG, MODEL_MAPPING_OVERRIDES_FILE, AGGREGATE_MODEL_ALIASES_FILE, PROVIDER_MODEL_TEST_STATE_FILE, MODEL_PROXY_SETTINGS_FILE, QUOTA_CACHE_FILE, APP_DIR, AUTH_DIR, POOL_AUTH_DIR, BACKUPS_DIR
from backend.state import load_state, normalize_route_strategy, get_proxy_bind_host, get_proxy_api_key


PROVIDER_MODEL_ALIASES = {
    # Use each provider's native model IDs.
    'codex': [
        ('gpt-5.4', 'codex5.5'),
        ('gpt-5.4', 'codex-5.5'),
        ('gpt-5.4', 'gpt-5.4'),
        ('gpt-5.4-mini', 'gpt-5.4-mini'),
        ('gpt-5.4-mini', 'codex5.4mini'),
        ('gpt-5.4-mini', 'codex5.4-mini'),
        ('gpt-5.4-mini', 'codex-5.4-mini'),
        ('gpt-5.3-codex', 'gpt-5.3-codex'),
        ('gpt-5.2', 'gpt-5.2'),
        ('gpt-5.2-codex', 'gpt-5.2-codex'),
        ('gpt-5.1-codex-max', 'gpt-5.1-codex-max'),
        ('gpt-5.1-codex-mini', 'gpt-5.1-codex-mini'),
    ],
    'qwen': [
        ('qwen3-coder-plus', 'qwen3-coder-plus'),
        ('qwen3-coder-flash', 'qwen3-coder-flash'),
        ('coder-model', 'coder-model'),
        ('vision-model', 'vision-model'),
    ],
    'kimi': [
        ('kimi-k2', 'kimi-k2'),
        ('kimi-k2-thinking', 'kimi-k2-thinking'),
        ('kimi-k2.5', 'kimi-k2.5'),
    ],
    'gemini-cli': [
        ('gemini-2.5-pro', 'gemini-2.5-pro'),
    ],
    'vertex': [
        ('gemini-2.5-pro', 'gemini-2.5-pro'),
    ],
    'aistudio': [
        ('gemini-2.5-pro', 'gemini-2.5-pro'),
    ],
    'googleai': [
        ('gemini-2.5-flash', 'gemini-2.5-flash'),
        ('gemini-2.5-flash-lite', 'gemini-2.5-flash-lite'),
        ('gemini-2.5-flash-lite-preview-09-2025', 'gemini-2.5-flash-lite-preview-09-2025'),
        ('gemini-2.5-pro', 'gemini-2.5-pro'),
        ('gemini-2.5-flash-preview-tts', 'gemini-2.5-flash-preview-tts'),
        ('gemini-embedding-2-preview', 'gemini-embedding-2-preview'),
        ('gemini-embedding-001', 'gemini-embedding-001'),
        ('gemini-robotics-er-1.5-preview', 'gemini-robotics-er-1.5-preview'),
    ],
    'google': [
        ('gemini-2.5-flash', 'gemini-2.5-flash'),
        ('gemini-2.5-flash-lite', 'gemini-2.5-flash-lite'),
        ('gemini-2.5-flash-lite-preview-09-2025', 'gemini-2.5-flash-lite-preview-09-2025'),
        ('gemini-2.5-pro', 'gemini-2.5-pro'),
        ('gemini-2.5-flash-preview-tts', 'gemini-2.5-flash-preview-tts'),
        ('gemini-embedding-2-preview', 'gemini-embedding-2-preview'),
        ('gemini-embedding-001', 'gemini-embedding-001'),
        ('gemini-robotics-er-1.5-preview', 'gemini-robotics-er-1.5-preview'),
    ],
    'aihubmix': [
        ('coding-glm-4.6-free', 'coding-glm-4.6-free'),
        ('coding-glm-4.7-free', 'coding-glm-4.7-free'),
        ('coding-glm-5-free', 'coding-glm-5-free'),
        ('coding-glm-5-turbo-free', 'coding-glm-5-turbo-free'),
        ('coding-minimax-m2-free', 'coding-minimax-m2-free'),
        ('coding-minimax-m2.1-free', 'coding-minimax-m2.1-free'),
        ('coding-minimax-m2.5-free', 'coding-minimax-m2.5-free'),
        ('coding-minimax-m2.7-free', 'coding-minimax-m2.7-free'),
        ('gemini-2.0-flash-free', 'gemini-2.0-flash-free'),
        ('gemini-3-flash-preview-free', 'gemini-3-flash-preview-free'),
        ('gemini-3.1-flash-image-preview-free', 'gemini-3.1-flash-image-preview-free'),
        ('glm-4.7-flash-free', 'glm-4.7-flash-free'),
        ('gpt-4.1-free', 'gpt-4.1-free'),
        ('gpt-4.1-mini-free', 'gpt-4.1-mini-free'),
        ('gpt-4.1-nano-free', 'gpt-4.1-nano-free'),
        ('gpt-4o-free', 'gpt-4o-free'),
        ('kimi-for-coding-free', 'kimi-for-coding-free'),
        ('mimo-v2-flash-free', 'mimo-v2-flash-free'),
        ('minimax-m2.5-free', 'minimax-m2.5-free'),
        ('step-3.5-flash-free', 'step-3.5-flash-free'),
    ],
    'antigravity': [
        ('google-antigravity/claude-opus-4-6-thinking', 'google-antigravity/claude-opus-4-6-thinking'),
        ('google-antigravity/claude-sonnet-4-6', 'google-antigravity/claude-sonnet-4-6'),
        ('google-antigravity/gemini-2-5-flash', 'google-antigravity/gemini-2-5-flash'),
        ('google-antigravity/gemini-2-5-flash-lite', 'google-antigravity/gemini-2-5-flash-lite'),
        ('google-antigravity/gemini-3-flash', 'google-antigravity/gemini-3-flash'),
        ('google-antigravity/gemini-3-pro-high', 'google-antigravity/gemini-3-pro-high'),
        ('google-antigravity/gemini-3-pro-low', 'google-antigravity/gemini-3-pro-low'),
        ('google-antigravity/gemini-3-1-flash-image', 'google-antigravity/gemini-3-1-flash-image'),
        ('google-antigravity/gemini-3-1-pro-high', 'google-antigravity/gemini-3-1-pro-high'),
        ('google-antigravity/gemini-3-1-pro-low', 'google-antigravity/gemini-3-1-pro-low'),
        ('google-antigravity/gpt-oss-120b-medium', 'google-antigravity/gpt-oss-120b-medium'),
    ],
    'claude': [
        ('claude-sonnet-4-5-20250929', 'claude-sonnet-4-5-20250929'),
    ],
    'iflow': [
        ('glm-4.7', 'glm-4.7'),
    ],
    'glm': [
        ('glm-4.7-flash', 'glm-4.7-flash'),
        ('glm-4.6v-flash', 'glm-4.6v-flash'),
        ('glm-4.1v-thinking-flash', 'glm-4.1v-thinking-flash'),
        ('glm-4-flash-250414', 'glm-4-flash-250414'),
        ('glm-4v-flash', 'glm-4v-flash'),
        ('cogview-3-flash', 'cogview-3-flash'),
        ('cogvideox-flash', 'cogvideox-flash'),
    ],
    'openrouter': [
        ('openrouter/arcee-ai/trinity-large-preview:free', 'openrouter/arcee-ai/trinity-large-preview:free'),
        ('openrouter/arcee-ai/trinity-mini:free', 'openrouter/arcee-ai/trinity-mini:free'),
        ('openrouter/auto', 'openrouter/auto'),
        ('openrouter/free', 'openrouter/free'),
        ('openrouter/google/gemma-3-27b-it:free', 'openrouter/google/gemma-3-27b-it:free'),
        ('openrouter/google/gemma-3-12b-it:free', 'openrouter/google/gemma-3-12b-it:free'),
        ('openrouter/google/gemma-3-4b-it:free', 'openrouter/google/gemma-3-4b-it:free'),
        ('openrouter/healer-alpha', 'openrouter/healer-alpha'),
        ('openrouter/hunter-alpha', 'openrouter/hunter-alpha'),
        ('openrouter/liquid/lfm-2.5-1.2b-instruct:free', 'openrouter/liquid/lfm-2.5-1.2b-instruct:free'),
        ('openrouter/liquid/lfm-2.5-1.2b-thinking:free', 'openrouter/liquid/lfm-2.5-1.2b-thinking:free'),
        ('openrouter/meta-llama/llama-3.3-70b-instruct:free', 'openrouter/meta-llama/llama-3.3-70b-instruct:free'),
        ('openrouter/minimax/minimax-m2.5:free', 'openrouter/minimax/minimax-m2.5:free'),
        ('openrouter/mistralai/mistral-small-3.1-24b-instruct:free', 'openrouter/mistralai/mistral-small-3.1-24b-instruct:free'),
        ('openrouter/nvidia/llama-nemotron-embed-vl-1b-v2:free', 'openrouter/nvidia/llama-nemotron-embed-vl-1b-v2:free'),
        ('openrouter/nvidia/nemotron-3-super-120b-a12b:free', 'openrouter/nvidia/nemotron-3-super-120b-a12b:free'),
        ('openrouter/nvidia/nemotron-3-nano-30b-a3b:free', 'openrouter/nvidia/nemotron-3-nano-30b-a3b:free'),
        ('openrouter/nvidia/nemotron-nano-12b-v2-vl:free', 'openrouter/nvidia/nemotron-nano-12b-v2-vl:free'),
        ('openrouter/nvidia/nemotron-nano-9b-v2:free', 'openrouter/nvidia/nemotron-nano-9b-v2:free'),
        ('openrouter/openai/gpt-oss-120b:free', 'openrouter/openai/gpt-oss-120b:free'),
        ('openrouter/openai/gpt-oss-20b:free', 'openrouter/openai/gpt-oss-20b:free'),
        ('openrouter/qwen/qwen3-coder:free', 'openrouter/qwen/qwen3-coder:free'),
        ('openrouter/qwen/qwen3-next-80b-a3b-instruct:free', 'openrouter/qwen/qwen3-next-80b-a3b-instruct:free'),
        ('openrouter/sourceful/riverflow-v2-pro:free', 'openrouter/sourceful/riverflow-v2-pro:free'),
        ('openrouter/sourceful/riverflow-v2-fast:free', 'openrouter/sourceful/riverflow-v2-fast:free'),
        ('openrouter/stepfun/step-3.5-flash:free', 'openrouter/stepfun/step-3.5-flash:free'),
        ('openrouter/z-ai/glm-4.5-air:free', 'openrouter/z-ai/glm-4.5-air:free'),
    ],
}


PROVIDER_AGGREGATE_ALIASES = {
    'zenmux': [
        ('zenmux/auto', 'zenmux-auto'),
        ('z-ai/glm-image', 'zenmux-image'),
        ('minimax/minimax-m2.5', 'zenmux-agent'),
        ('minimax/minimax-m2.1', 'zenmux-agent-lite'),
        ('kuaishou/kat-coder-pro-v1-free', 'zenmux-coder'),
        ('z-ai/glm-4.6v-flash-free', 'zenmux-vision'),
        ('stepfun/step-3.5-flash-free', 'zenmux-fast'),
    ],
}


KNOWN_PROVIDERS = (
    'longcat', 'zhipu', 'glm', 'aihubmix',
    'codex', 'qwen', 'kimi', 'gemini-cli', 'vertex', 'aistudio', 'google', 'googleai', 'antigravity', 'claude', 'iflow', 'login',
    'minimax-portal', 'qwen-portal', 'openrouter', 'aliyun', 'volcengine', 'hunyuan', 'scnet', 'deepseek'
)


MANUAL_PROVIDER_HOST_HINTS = {
    'longcat': ('longcat',),
    'glm': ('bigmodel.cn', 'zhipu'),
    'zhipu': ('bigmodel.cn', 'zhipu'),
    'aihubmix': ('aihubmix',),
    'qwen': ('dashscope', 'qwen'),
    'aliyun': ('dashscope.aliyuncs.com',),
    'volcengine': ('volces.com', 'volcengine'),
    'hunyuan': ('hunyuan.cloud.tencent.com', 'hunyuan'),
    'scnet': ('api.scnet.cn', 'scnet'),
    'claude': ('anthropic', 'claude'),
    'codex': ('openai', 'chatgpt'),
    'google': ('generativelanguage.googleapis.com', 'googleapis.com', 'google'),
    'googleai': ('generativelanguage.googleapis.com', 'googleapis.com', 'google'),
    'openrouter': ('openrouter.ai', 'openrouter'),
    'deepseek': ('deepseek.com', 'deepseek'),
    'zenmux': ('zenmux.ai', 'zenmux'),
}


MANUAL_PROVIDER_MODEL_HINTS = {
    'longcat': ('longcat',),
    'glm': ('glm-', 'cogview-'),
    'zhipu': ('glm-',),
    'qwen': ('qwen',),
    'aliyun': ('qwen', 'deepseek', 'qvq', 'codeqwen'),
    'volcengine': ('doubao', 'deepseek', 'kimi-k2', 'glm-4-7'),
    'hunyuan': ('hunyuan',),
    'scnet': ('qwen3-235b-a22b', 'minimax-m2.5'),
    'kimi': ('kimi',),
    'claude': ('claude',),
    'codex': ('gpt-',),
    'google': ('gemini-',),
    'googleai': ('gemini-',),
    'deepseek': ('deepseek',),
    'zenmux': ('zenmux',),
}


PROVIDER_BASE_URLS = {
    'aihubmix': 'https://aihubmix.com/v1',
    'codex': 'https://api.openai.com/v1',
    'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'aliyun': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'qwen-portal': 'https://portal.qwen.ai/v1',
    'kimi': 'https://api.moonshot.cn/v1',
    'glm': 'https://open.bigmodel.cn/api/paas/v4',
    'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
    'volcengine': 'https://ark.cn-beijing.volces.com/api/v3',
    'hunyuan': 'https://api.hunyuan.cloud.tencent.com',
    'scnet': 'https://api.scnet.cn/api/llm',
    'claude': 'https://api.anthropic.com/v1',
    'minimax-portal': 'https://api.minimax.io/anthropic',
    'google': 'https://generativelanguage.googleapis.com/v1beta',
    'googleai': 'https://generativelanguage.googleapis.com/v1beta',
    'openrouter': 'https://openrouter.ai/api/v1',
    'poixe': 'https://api.poixe.com/v1',
    'deepseek': 'https://api.deepseek.com',
    'zenmux': 'https://zenmux.ai/api/v1',
}

OPENCLAW_CONFIG_PATH = Path.home() / '.openclaw' / 'openclaw.json'


def build_auth_ref(source_id: str, file_name: str):
    normalized_name = str(file_name or '').replace('\\', '/').lstrip('/')
    return f'{source_id}::{normalized_name}'


def _auth_ref_path_candidates(file_name: str):
    raw_value = str(file_name or '').replace('\\', '/').lstrip('/')
    if not raw_value:
        return []
    candidates = []

    def add(value: str):
        token = str(value or '').replace('\\', '/').lstrip('/')
        if token and token not in candidates:
            candidates.append(token)

    add(raw_value)
    transforms = (
        ("accounts/codex'/", 'oauth/codex/'),
        ('accounts/antigravity/', 'oauth/antigravity/'),
        ('accounts/', 'oauth/'),
        ('providers/', 'api/'),
        ('oauth/codex/', "accounts/codex'/"),
        ('oauth/antigravity/', 'accounts/antigravity/'),
        ('oauth/', 'accounts/'),
        ('api/', 'providers/'),
    )
    for source_token, target_token in transforms:
        if source_token in raw_value:
            add(raw_value.replace(source_token, target_token, 1))
    return candidates


def _candidate_relative_names_for_source(source_id: str, candidate_name: str):
    raw_value = str(candidate_name or '').replace('\\', '/').lstrip('/')
    values = []

    def add(value: str):
        token = str(value or '').replace('\\', '/').lstrip('/')
        if token and token not in values:
            values.append(token)

    add(raw_value)
    add(Path(raw_value).name)

    provider_prefixes = (
        f'providers/{source_id}/',
        f'api/{source_id}/',
        f'oauth/{source_id}/',
        f'accounts/{source_id}/',
    )
    for prefix in provider_prefixes:
        if raw_value.startswith(prefix):
            add(raw_value[len(prefix):])

    legacy_aliases = {
        'codex': ("accounts/codex'/", 'accounts/codex/'),
        'antigravity': ('accounts/antigravity/',),
    }
    for prefix in legacy_aliases.get(source_id, ()):
        if raw_value.startswith(prefix):
            add(raw_value[len(prefix):])

    for generic_prefix in ('oauth/', 'api/', 'providers/', 'accounts/'):
        if raw_value.startswith(generic_prefix):
            remainder = raw_value[len(generic_prefix):]
            add(remainder)
            if '/' in remainder:
                add(remainder.split('/', 1)[1])

    return values


def _relative_auth_name(source_dir: Path, path: Path):
    try:
        return path.relative_to(source_dir).as_posix()
    except Exception:
        return path.name


def _iter_auth_json_files(source_dir: Path):
    if not source_dir.exists() or not source_dir.is_dir():
        return
    for path in sorted(source_dir.rglob('*.json')):
        try:
            relative_parts = path.relative_to(source_dir).parts
        except Exception:
            relative_parts = path.parts
        if any(part in ('_archive', 'archive', 'sources', 'backups') for part in relative_parts):
            continue
        if path.is_file():
            yield path


def _iter_pool_auth_json_files():
    yield from _iter_auth_json_files(POOL_AUTH_DIR)


def _manual_auth_save_dir(provider: str | None = None):
    provider_token = _safe_name(str(provider or '').strip().lower(), 'misc')
    return MANUAL_AUTH_SAVE_DIR / provider_token


def _normalize_score_text(*values):
    return ' '.join(
        str(value or '').strip().lower()
        for value in values
        if str(value or '').strip()
    )


def _model_capability_raw_score(provider: str, upstream_id: str, call_id: str):
    _ = str(provider or '').strip().lower()
    text = _normalize_score_text(upstream_id, call_id)
    score = 48

    family_rules = [
        ('gpt-5.5', 99),
        ('gpt-5.4', 97),
        ('gpt-5.3-codex', 95),
        ('gpt-5.2-codex', 92),
        ('gpt-5.2', 90),
        ('gpt-5.1-codex-max', 93),
        ('gpt-5.1-codex-mini', 80),
        ('gpt-5.1-codex', 88),
        ('gpt-5.1', 86),
        ('gpt-5.4-mini', 82),
        ('gpt-5-codex-mini', 78),
        ('gpt-5-codex', 90),
        ('gpt-5', 88),
        ('claude-opus-4-6-thinking', 94),
        ('claude-opus', 92),
        ('claude-sonnet-4-6', 89),
        ('claude-sonnet-4-5-thinking', 88),
        ('claude-sonnet-4-5', 86),
        ('gemini-3.1-pro-high', 87),
        ('gemini-3.1-pro', 84),
        ('gemini-3-pro-high', 82),
        ('gemini-3-pro-low', 75),
        ('gemini-3.1-flash-image', 72),
        ('gemini-3-flash', 74),
        ('gemini-2.5-pro', 80),
        ('gemini-2.5-flash-thinking', 72),
        ('gemini-2.5-flash-lite', 58),
        ('gemini-2.5-flash', 65),
        ('coding-glm-5-turbo', 84),
        ('coding-glm-5', 81),
        ('glm-5-turbo', 82),
        ('glm-5', 79),
        ('glm-4.7-flash', 73),
        ('glm-4.7', 78),
        ('glm-4.6v-flash', 70),
        ('glm-4.6v', 72),
        ('qwen3-coder', 83),
        ('qwen3-next-80b-a3b-instruct', 80),
        ('qwen3-next', 78),
        ('llama-3.3-70b-instruct', 76),
        ('mistral-small-3.1-24b-instruct', 72),
        ('minimax-m2.7', 86),
        ('minimax-m2.5', 82),
        ('minimax-m2.1', 70),
        ('step-3.5-flash', 73),
        ('gpt-4o', 80),
        ('gpt-4.1-mini', 68),
        ('gpt-4.1-nano', 42),
        ('gpt-4.1', 78),
        ('gpt-oss-120b', 71),
        ('kimi-k2.5', 76),
        ('kimi-k2-thinking', 72),
        ('kimi-k2', 68),
        ('hunyuan-image3', 62),
        ('veo-3.1', 66),
        ('glm-image', 64),
        ('riverflow-v2-pro', 60),
        ('riverflow-v2-fast', 54),
        ('mimo-v2-flash', 50),
        ('kat-coder-pro-v1', 66),
        ('free', 52),
        ('auto', 50),
    ]
    for token, value in family_rules:
        if token in text:
            score = value
            break

    adjustment_rules = [
        ('codex-max', 3),
        ('thinking', 3),
        ('reasoning', 3),
        ('image', 2),
        ('vision', 2),
        ('coder', 4),
        ('coding', 3),
        ('agent', 2),
        ('tool', 1),
        ('mini', -6),
        ('nano', -16),
        ('flash-lite', -8),
        ('lite', -4),
        ('1.2b', -24),
        ('4b', -18),
        ('12b', -10),
        ('free', -2),
    ]
    for token, value in adjustment_rules:
        if token in text:
            score += value

    return max(0, min(100, score))


def _attach_provider_model_scores(items: list[dict]):
    for item in items:
        provider = str(item.get('lookup_provider') or item.get('provider') or '').strip().lower()
        for row in item.get('rows') or []:
            raw = _model_capability_raw_score(
                provider,
                row.get('lookup_upstream_id') or row.get('upstream_id') or '',
                row.get('call_id') or '',
            )
            row['capability_score_raw'] = raw
            row['capability_score'] = max(0, min(100, int(raw)))
    return items


def parse_auth_ref(auth_ref: str):
    if not auth_ref:
        return None, None
    if '::' not in auth_ref:
        return 'default', str(auth_ref).replace('\\', '/').lstrip('/')
    source_id, file_name = auth_ref.split('::', 1)
    normalized_name = str(file_name or '').replace('\\', '/').lstrip('/')
    return (source_id or 'default'), normalized_name


def _load_provider_model_test_results():
    try:
        if not PROVIDER_MODEL_TEST_STATE_FILE.exists():
            return {}
        payload = json.loads(PROVIDER_MODEL_TEST_STATE_FILE.read_text(encoding='utf-8'))
        results = payload.get('results') if isinstance(payload, dict) else {}
        return results if isinstance(results, dict) else {}
    except Exception:
        return {}


def _current_route_strategy():
    try:
        state = load_state()
        return normalize_route_strategy(state.get('route_strategy'))
    except Exception:
        return normalize_route_strategy({})


def _model_failure_cooldown_seconds(result: dict, strategy: dict):
    retry_after = int(result.get('retry_after_seconds') or 0)
    if retry_after > 0:
        return retry_after
    failure_kind = str(result.get('failure_kind') or '').strip().lower()
    if failure_kind == 'forbidden':
        return int(strategy.get('cooldown_forbidden_seconds') or 0)
    if failure_kind == 'quota':
        return int(strategy.get('cooldown_quota_seconds') or 0)
    if failure_kind == 'auth':
        return int(strategy.get('cooldown_auth_seconds') or 0)
    if failure_kind == 'timeout':
        return int(strategy.get('cooldown_timeout_seconds') or 0)
    if failure_kind == 'server':
        return int(strategy.get('cooldown_server_seconds') or 0)
    if failure_kind == 'client':
        return int(strategy.get('cooldown_client_seconds') or 0)
    return int(strategy.get('cooldown_default_seconds') or 0)


def _model_test_rank(call_id: str, results: dict, now_ts: int, strategy: dict | None = None):
    strategy = strategy or _current_route_strategy()
    if not bool(strategy.get('enabled')):
        return (1, 0, 0)
    result = results.get(str(call_id or '').strip())
    if not isinstance(result, dict):
        # Unknown -> keep middle priority.
        return (1, 0, 0)

    tested_at = int(result.get('tested_at') or 0)
    available = bool(result.get('available'))
    if available:
        # Verified healthy first.
        return (0, -tested_at, 0)

    retry_after = _model_failure_cooldown_seconds(result, strategy)
    if retry_after <= 0:
        return (2, -tested_at, 0)
    next_retry_at = tested_at + retry_after if tested_at > 0 else now_ts + retry_after
    in_cooldown = now_ts < next_retry_at

    if in_cooldown:
        # Keep cooled failures at the end until cooldown expires.
        return (3, next_retry_at, tested_at)
    # Failed but cooldown expired -> can retry, but after healthy/unknown.
    return (2, -tested_at, 0)


def _prioritize_provider_alias_pairs(provider: str, pairs: list[tuple[str, str]], overrides: dict | None = None):
    if not pairs:
        return pairs
    results = _load_provider_model_test_results()
    if not results:
        return pairs
    strategy = _current_route_strategy()
    if not bool(strategy.get('enabled')):
        return pairs
    now_ts = int(time.time())
    decorated = []
    for index, (model_name, alias) in enumerate(pairs):
        mapping = resolve_provider_mapping(provider, model_name, alias, overrides=overrides)
        call_id = str(mapping.get('call_id') or alias or model_name).strip()
        decorated.append((_model_test_rank(call_id, results, now_ts, strategy), index, (model_name, alias)))
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in decorated]


def _prioritize_model_rows_by_alias(rows: list[dict]):
    if not rows:
        return rows
    results = _load_provider_model_test_results()
    if not results:
        return rows
    strategy = _current_route_strategy()
    if not bool(strategy.get('enabled')):
        return rows
    now_ts = int(time.time())
    decorated = []
    for index, row in enumerate(rows):
        alias = str(row.get('alias') or '').strip()
        call_id = alias or str(row.get('name') or '').strip()
        decorated.append((_model_test_rank(call_id, results, now_ts, strategy), index, row))
    decorated.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in decorated]


def _aggregate_alias_id_set():
    alias_ids = {'auto', 'image', 'agent', 'coder', 'reasoning', 'chat'}
    saved = _load_aggregate_model_aliases()
    for alias_id in saved.keys():
        token = str(alias_id or '').strip().lower()
        if token:
            alias_ids.add(token)
    return alias_ids


def _read_auth_payload(path: Path):
    for encoding in ('utf-8-sig', 'utf-8', 'utf-16', 'gbk'):
        try:
            return json.loads(path.read_text(encoding=encoding, errors='ignore'))
        except Exception:
            continue
    return None


def _decode_jwt_claims(token: str):
    value = str(token or '').strip()
    if not value or value.count('.') < 2:
        return {}
    try:
        _header, payload_part, _sig = value.split('.', 2)
        padding = '=' * (-len(payload_part) % 4)
        decoded = base64.urlsafe_b64decode((payload_part + padding).encode('utf-8'))
        claims = json.loads(decoded.decode('utf-8', errors='ignore'))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def _extract_token_claims(payload):
    if not isinstance(payload, dict):
        return {}
    tokens = payload.get('tokens') if isinstance(payload.get('tokens'), dict) else {}
    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    candidates = []
    for key in ('id_token', 'access_token'):
        if isinstance(tokens.get(key), str):
            candidates.append(tokens.get(key))
    for key in ('id_token', 'access_token'):
        if isinstance(payload.get(key), str):
            candidates.append(payload.get(key))
    for key in ('id_token', 'access', 'access_token'):
        if isinstance(content.get(key), str):
            candidates.append(content.get(key))

    merged = {}
    for token in candidates:
        claims = _decode_jwt_claims(token)
        if isinstance(claims, dict):
            merged.update({k: v for k, v in claims.items() if k not in merged})
            auth_claims = claims.get('https://api.openai.com/auth')
            if isinstance(auth_claims, dict):
                merged.setdefault('openai_auth', auth_claims)
            profile_claims = claims.get('https://api.openai.com/profile')
            if isinstance(profile_claims, dict):
                merged.setdefault('openai_profile', profile_claims)
    return merged


def _detect_auth_payload_kind(payload):
    if not isinstance(payload, dict):
        return 'unknown'

    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    content_type = str(content.get('type') or '').strip().lower()
    content_provider = str(content.get('provider') or '').strip().lower()
    payload_type = str(payload.get('type') or '').strip().lower()
    payload_provider = str(payload.get('provider') or '').strip().lower()
    if str(content.get('type') or '').strip().lower() == 'api_key':
        return 'manual_api_key'
    if content_type == 'oauth':
        if content_provider in ('openai-codex', 'codex'):
            return 'codex_oauth_content'
        if content_provider in ('google-antigravity', 'antigravity'):
            return 'antigravity_oauth_content'
        return 'oauth_content'
    if payload_type == 'oauth':
        if payload_provider in ('openai-codex', 'codex'):
            return 'codex_oauth_flat'
        if payload_provider in ('google-antigravity', 'antigravity') or payload.get('projectId') or payload.get('project_id'):
            return 'antigravity_oauth_flat'
        return 'oauth_flat'

    auth_mode = str(payload.get('auth_mode') or '').strip().lower()
    has_tokens_block = isinstance(payload.get('tokens'), dict)
    has_access_token = isinstance(payload.get('access_token'), str) and bool(str(payload.get('access_token')).strip())
    has_refresh_token = isinstance(payload.get('refresh_token'), str) and bool(str(payload.get('refresh_token')).strip())
    has_account_identity = any(
        isinstance(payload.get(key), str) and bool(str(payload.get(key)).strip())
        for key in ('account_id', 'accountId', 'id_token', 'email')
    )

    if auth_mode == 'chatgpt' or has_tokens_block:
        return 'codex_chatgpt'
    if payload_type in ('codex', 'openai-codex'):
        return 'codex_flat'
    if payload_type == 'antigravity' or payload.get('project_id'):
        return 'antigravity_google'
    if payload_provider in ('codex', 'openai-codex') and has_access_token and has_account_identity:
        return 'codex_flat'
    if has_access_token and has_refresh_token and has_account_identity:
        return 'oauth_flat'
    return 'unknown'


def _extract_payload_fields(payload):
    if not isinstance(payload, dict):
        return None, None

    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    token_claims = _extract_token_claims(payload)
    token_auth = token_claims.get('openai_auth') if isinstance(token_claims.get('openai_auth'), dict) else {}
    token_profile = token_claims.get('openai_profile') if isinstance(token_claims.get('openai_profile'), dict) else {}

    # oauth-manager schema
    email = (
        content.get('email')
        or metadata.get('email')
        or payload.get('email')
        or payload.get('user_email')
        or token_profile.get('email')
        or token_claims.get('email')
    )
    account_id = (
        content.get('account_id')
        or content.get('accountId')
        or metadata.get('account_id')
        or metadata.get('accountId')
        or token_auth.get('chatgpt_account_id')
        or token_auth.get('chatgpt_account_user_id')
    )

    # cliproxy oauth schema
    if not account_id:
        tokens = payload.get('tokens') if isinstance(payload.get('tokens'), dict) else {}
        account_id = (
            content.get('accountId')
            or content.get('account_id')
            or
            tokens.get('account_id')
            or payload.get('accountId')
            or payload.get('account_id')
        )

    return email, account_id


def _extract_payload_models(payload):
    if not isinstance(payload, dict):
        return []

    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    values = []

    models = content.get('models')
    if isinstance(models, list):
        values.extend(models)

    for value in (content.get('model'), payload.get('model')):
        if value:
            values.append(value)

    result = []
    for value in values:
        model_id = str(value or '').strip()
        if model_id and model_id not in result:
            result.append(model_id)
    return result


def _extract_payload_headers(payload):
    if not isinstance(payload, dict):
        return {}
    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    headers = content.get('headers')
    if isinstance(headers, dict):
        return {str(k): str(v) for k, v in headers.items() if str(k).strip()}
    return {}


def _write_manual_auth_payload(path: Path, payload: dict):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _auth_filename_token(value, fallback='unknown'):
    text = str(value or '').strip().lower()
    if not text:
        text = fallback
    text = text.replace('\\', '-').replace('/', '-').replace(':', '-')
    text = re.sub(r'[^a-z0-9@._+-]+', '-', text)
    text = re.sub(r'-{2,}', '-', text).strip('-._ ')
    return (text or fallback)[:96]


def _normalized_provider_name(provider: str):
    value = str(provider or '').strip().lower()
    if value == 'openai-codex':
        return 'codex'
    if value == 'google-antigravity':
        return 'antigravity'
    return value or 'codex'


def _detect_codex_plan(payload, file_name: str = ''):
    if not isinstance(payload, dict):
        payload = {}
    attributes = payload.get('attributes') if isinstance(payload.get('attributes'), dict) else {}
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    tokens = payload.get('tokens') if isinstance(payload.get('tokens'), dict) else {}
    token_claims = _extract_token_claims(payload)
    token_auth = token_claims.get('openai_auth') if isinstance(token_claims.get('openai_auth'), dict) else {}
    values = [
        attributes.get('plan_type'),
        attributes.get('plan'),
        metadata.get('plan_type'),
        metadata.get('plan'),
        content.get('plan_type'),
        content.get('plan'),
        tokens.get('plan_type'),
        token_auth.get('plan_type'),
        token_auth.get('account_plan'),
        payload.get('plan_type'),
        payload.get('plan'),
        file_name,
    ]
    text = ' '.join(str(value or '').strip().lower() for value in values if str(value or '').strip())
    if re.search(r'(^|[^a-z])team([^a-z]|$)', text) or 'plus' in text or 'pro' in text:
        return 'team'
    if re.search(r'(^|[^a-z])free([^a-z]|$)', text):
        return 'free'
    return 'unknown'


def _normalized_auth_file_name(provider: str, payload, original_name: str = ''):
    provider_value = _normalized_provider_name(provider)
    email, account_id = _extract_payload_fields(payload)
    identity = email or account_id or Path(str(original_name or '')).stem or 'unknown-account'
    identity_token = _auth_filename_token(identity, 'unknown-account')
    if provider_value == 'codex':
        plan = _detect_codex_plan(payload, original_name)
        base = f'{identity_token}--codex-{plan}.json'
    else:
        base = f'{identity_token}--{_auth_filename_token(provider_value, "provider")}.json'
    return base


def _unique_child_path(directory: Path, file_name: str, source_path: Path | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / file_name
    if not candidate.exists():
        return candidate
    try:
        if source_path and candidate.resolve() == source_path.resolve():
            return candidate
    except Exception:
        pass
    stem = candidate.stem
    suffix = candidate.suffix or '.json'
    seed = str(source_path or file_name).encode('utf-8', errors='ignore')
    digest = hashlib.sha256(seed).hexdigest()[:6]
    candidate = directory / f'{stem}--{digest}{suffix}'
    counter = 2
    while candidate.exists():
        try:
            if source_path and candidate.resolve() == source_path.resolve():
                return candidate
        except Exception:
            pass
        candidate = directory / f'{stem}--{digest}-{counter}{suffix}'
        counter += 1
    return candidate


def _with_standard_auth_metadata(payload, provider: str, original_name: str = '', source: str = ''):
    if not isinstance(payload, dict):
        return payload
    provider_value = _normalized_provider_name(provider)
    normalized = dict(payload)
    is_manual_api = _detect_auth_payload_kind(normalized) == 'manual_api_key'
    if not is_manual_api:
        normalized['provider'] = provider_value
        normalized['type'] = provider_value
    if 'disabled' not in normalized:
        normalized['disabled'] = False

    email, account_id = _extract_payload_fields(normalized)
    if email and not normalized.get('email'):
        normalized['email'] = str(email)
    if account_id and not normalized.get('account_id'):
        normalized['account_id'] = str(account_id)

    attributes = dict(normalized.get('attributes') if isinstance(normalized.get('attributes'), dict) else {})
    if provider_value == 'codex':
        attributes['plan_type'] = _detect_codex_plan(normalized, original_name)
    if email:
        attributes.setdefault('account_email', str(email))
    if account_id:
        attributes.setdefault('account_id', str(account_id))
    if source:
        attributes.setdefault('source', source)
    normalized['attributes'] = attributes

    metadata = dict(normalized.get('metadata') if isinstance(normalized.get('metadata'), dict) else {})
    metadata.setdefault('file_schema', 'cliproxyapi-auth-v1')
    metadata.setdefault('provider', provider_value)
    if original_name:
        metadata.setdefault('original_file_name', str(original_name))
    metadata['normalized_at'] = datetime.now(timezone.utc).isoformat()
    normalized['metadata'] = metadata
    if provider_value == 'codex' and not is_manual_api:
        return _to_oauth_manager_codex_payload(normalized, original_name, source)
    return normalized


def _to_oauth_manager_codex_payload(payload, original_name: str = '', source: str = ''):
    if not isinstance(payload, dict):
        return payload
    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    access_token = content.get('access') or content.get('access_token') or payload.get('access_token')
    refresh_token = content.get('refresh') or content.get('refresh_token') or payload.get('refresh_token')
    if not access_token:
        return payload

    email, account_id = _extract_payload_fields(payload)
    plan = _detect_codex_plan(payload, original_name)
    now_iso = datetime.now(timezone.utc).isoformat()
    last_refresh = (
        _coerce_iso_timestamp(payload.get('last_refresh'))
        or _coerce_iso_timestamp(metadata.get('tokenRefreshedAt'))
        or _coerce_iso_timestamp(metadata.get('updatedAt'))
        or now_iso
    )
    created_at = (
        _coerce_iso_timestamp(metadata.get('createdAt'))
        or _coerce_iso_timestamp(metadata.get('created_at'))
        or _coerce_iso_timestamp(payload.get('createdAt'))
        or now_iso
    )
    id_token = content.get('id_token') or payload.get('id_token')
    remark_parts = []
    if email:
        remark_parts.append(str(email))
    if plan and plan != 'unknown':
        remark_parts.append(str(plan))
    remark = metadata.get('remark') or ' / '.join(remark_parts) or Path(str(original_name or '')).stem

    out_metadata = {
        'email': str(email or ''),
        'remark': str(remark or ''),
        'source': str(source or metadata.get('source') or 'cliproxyapi'),
        'createdAt': created_at,
        'updatedAt': now_iso,
        'tokenRefreshedAt': last_refresh,
        'plan': plan,
    }
    if original_name:
        out_metadata['originalFileName'] = str(original_name)

    out_content = {
        'type': 'oauth',
        'provider': 'openai-codex',
        'access': str(access_token),
        'refresh': str(refresh_token or ''),
        'accountId': str(account_id or ''),
        'id_token': str(id_token or ''),
        'plan': plan,
    }
    disabled = bool(payload.get('disabled'))
    result = {
        'metadata': out_metadata,
        'content': out_content,
    }
    if disabled:
        result['disabled'] = True
    return result


def _coerce_epoch_millis(value):
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if number <= 0:
        return None
    if number < 10_000_000_000:
        number *= 1000
    return int(number)


def _coerce_iso_timestamp(value):
    text = str(value or '').strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _iso_from_epoch_millis(value):
    millis = _coerce_epoch_millis(value)
    if not millis:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _normalize_runtime_oauth_payload(payload, provider: str, auth_kind: str):
    if not isinstance(payload, dict):
        return None

    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    tokens = payload.get('tokens') if isinstance(payload.get('tokens'), dict) else {}
    token_claims = _extract_token_claims(payload)
    token_auth = token_claims.get('openai_auth') if isinstance(token_claims.get('openai_auth'), dict) else {}
    token_profile = token_claims.get('openai_profile') if isinstance(token_claims.get('openai_profile'), dict) else {}

    normalized_provider = str(provider or '').strip().lower()
    if normalized_provider == 'google-antigravity':
        normalized_provider = 'antigravity'
    if normalized_provider == 'openai-codex':
        normalized_provider = 'codex'

    if normalized_provider == 'codex' or auth_kind.startswith('codex_'):
        access_token = (
            content.get('access')
            or content.get('access_token')
            or tokens.get('access_token')
            or payload.get('access_token')
        )
        refresh_token = (
            content.get('refresh')
            or content.get('refresh_token')
            or tokens.get('refresh_token')
            or payload.get('refresh_token')
        )
        account_id = (
            content.get('accountId')
            or content.get('account_id')
            or tokens.get('account_id')
            or payload.get('account_id')
            or payload.get('accountId')
            or metadata.get('accountId')
            or metadata.get('account_id')
            or token_auth.get('chatgpt_account_id')
        )
        id_token = (
            content.get('id_token')
            or tokens.get('id_token')
            or payload.get('id_token')
        )
        email = (
            content.get('email')
            or metadata.get('email')
            or payload.get('email')
            or token_profile.get('email')
            or token_claims.get('email')
        )
        expired = (
            _coerce_iso_timestamp(payload.get('expired'))
            or _coerce_iso_timestamp(payload.get('expires_at'))
            or _coerce_iso_timestamp(metadata.get('expired'))
            or _coerce_iso_timestamp(content.get('expired'))
            or _iso_from_epoch_millis(payload.get('expires'))
            or _iso_from_epoch_millis(content.get('expires'))
            or _iso_from_epoch_millis(token_claims.get('exp'))
        )
        last_refresh = (
            _coerce_iso_timestamp(payload.get('last_refresh'))
            or _coerce_iso_timestamp(payload.get('lastRefresh'))
            or _coerce_iso_timestamp(metadata.get('tokenRefreshedAt'))
            or _coerce_iso_timestamp(metadata.get('updatedAt'))
            or _coerce_iso_timestamp(content.get('updatedAt'))
        )
        if not access_token:
            return None
        normalized = {
            'type': 'codex',
            'provider': 'codex',
            'access_token': str(access_token),
            'refresh_token': str(refresh_token or ''),
            'account_id': str(account_id or ''),
            'email': str(email or ''),
            'disabled': bool(payload.get('disabled')),
            'attributes': {
                'plan_type': _detect_codex_plan(payload, str(email or '')),
                'account_email': str(email or ''),
                'account_id': str(account_id or ''),
            },
            'metadata': {
                'file_schema': 'cliproxyapi-auth-v1',
                'provider': 'codex',
                'normalized_at': datetime.now(timezone.utc).isoformat(),
            },
        }
        if id_token:
            normalized['id_token'] = str(id_token)
        if expired:
            normalized['expired'] = expired
        if last_refresh:
            normalized['last_refresh'] = last_refresh
        return normalized

    if normalized_provider == 'antigravity' or auth_kind.startswith('antigravity_'):
        access_token = (
            content.get('access')
            or content.get('access_token')
            or payload.get('access_token')
            or payload.get('access')
        )
        refresh_token = (
            content.get('refresh')
            or content.get('refresh_token')
            or payload.get('refresh_token')
            or payload.get('refresh')
        )
        email = (
            content.get('email')
            or metadata.get('email')
            or payload.get('email')
        )
        project_id = (
            content.get('projectId')
            or content.get('project_id')
            or payload.get('project_id')
            or payload.get('projectId')
        )
        timestamp = (
            _coerce_epoch_millis(payload.get('timestamp'))
            or _coerce_epoch_millis(payload.get('expires'))
            or _coerce_epoch_millis(content.get('expires'))
        )
        expired = (
            _coerce_iso_timestamp(payload.get('expired'))
            or _coerce_iso_timestamp(payload.get('expires_at'))
            or _coerce_iso_timestamp(content.get('expired'))
            or _iso_from_epoch_millis(payload.get('expires'))
            or _iso_from_epoch_millis(content.get('expires'))
            or _iso_from_epoch_millis(timestamp)
        )
        if not access_token or not refresh_token:
            return None
        normalized = {
            'type': 'antigravity',
            'provider': 'antigravity',
            'access_token': str(access_token),
            'refresh_token': str(refresh_token),
            'email': str(email or ''),
            'disabled': bool(payload.get('disabled')),
            'attributes': {
                'account_email': str(email or ''),
            },
            'metadata': {
                'file_schema': 'cliproxyapi-auth-v1',
                'provider': 'antigravity',
                'normalized_at': datetime.now(timezone.utc).isoformat(),
            },
        }
        if project_id:
            normalized['project_id'] = str(project_id)
        if expired:
            normalized['expired'] = expired
        if timestamp:
            normalized['timestamp'] = int(timestamp)
        return normalized

    return None


def _write_runtime_auth_payload(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _backup_auth_file_for_migration(path: Path, backup_root: Path):
    try:
        if path.resolve().is_relative_to(AUTH_DIR.resolve()):
            relative = path.resolve().relative_to(AUTH_DIR.resolve())
            target = backup_root / 'auth' / relative
        elif path.resolve().is_relative_to(ACTIVE_AUTH_DIR.resolve()):
            relative = path.resolve().relative_to(ACTIVE_AUTH_DIR.resolve())
            target = backup_root / 'runtime' / 'active-auth' / relative
        else:
            target = backup_root / 'other' / path.name
    except Exception:
        target = backup_root / 'other' / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(path, target)


def _migrate_auth_json_file(path: Path, target_dir: Path, backup_root: Path, source_label: str):
    payload = _read_auth_payload(path)
    if not isinstance(payload, dict):
        return {'changed': False, 'skipped': True, 'reason': 'invalid_json', 'path': str(path)}
    provider = detect_provider(payload, path.name)
    target_name = _normalized_auth_file_name(provider, payload, path.name)
    target_path = _unique_child_path(target_dir, target_name, path)
    normalized_payload = _normalize_runtime_oauth_payload(payload, provider, _detect_auth_payload_kind(payload))
    if not isinstance(normalized_payload, dict):
        normalized_payload = payload
    normalized_payload = _with_standard_auth_metadata(normalized_payload, provider, path.name, source_label)

    current_payload = _read_auth_payload(path)
    same_path = False
    try:
        same_path = target_path.resolve() == path.resolve()
    except Exception:
        same_path = target_path == path
    changed = (not same_path) or current_payload != normalized_payload
    if not changed:
        return {'changed': False, 'skipped': False, 'path': str(path)}

    _backup_auth_file_for_migration(path, backup_root)
    _write_runtime_auth_payload(target_path, normalized_payload)
    if not same_path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass
    return {'changed': True, 'from': str(path), 'to': str(target_path)}


def migrate_auth_storage_layout():
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_root = BACKUPS_DIR / f'auth-migration-{stamp}'
    report = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'backup_root': str(backup_root),
        'auth_changed': 0,
        'runtime_changed': 0,
        'skipped': 0,
        'items': [],
    }

    if AUTH_DIR.exists():
        for path in sorted(AUTH_DIR.rglob('*.json'), key=lambda item: item.as_posix().lower()):
            try:
                relative_parts = path.relative_to(AUTH_DIR).parts
            except Exception:
                relative_parts = path.parts
            if any(part in ('archive', '_archive', 'sources') for part in relative_parts):
                continue
            payload = _read_auth_payload(path)
            provider = detect_provider(payload, path.name)
            target_dir = AUTH_DIR / _auth_filename_token(_normalized_provider_name(provider), 'provider')
            result = _migrate_auth_json_file(path, target_dir, backup_root, 'storage_auth_library')
            report['items'].append(result)
            if result.get('changed'):
                report['auth_changed'] += 1
            if result.get('skipped'):
                report['skipped'] += 1

    if ACTIVE_AUTH_DIR.exists():
        for path in sorted(ACTIVE_AUTH_DIR.rglob('*.json'), key=lambda item: item.as_posix().lower()):
            payload = _read_auth_payload(path)
            provider = detect_provider(payload, path.name)
            target_dir = ACTIVE_AUTH_DIR / _auth_filename_token(_normalized_provider_name(provider), 'provider')
            result = _migrate_auth_json_file(path, target_dir, backup_root, 'runtime_active_pool')
            report['items'].append(result)
            if result.get('changed'):
                report['runtime_changed'] += 1
            if result.get('skipped'):
                report['skipped'] += 1

    report_path = BACKUPS_DIR / f'auth-migration-{stamp}.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    public_report = dict(report)
    public_report['items'] = [
        {
            key: value
            for key, value in item.items()
            if key in ('changed', 'skipped', 'reason')
        }
        for item in report.get('items', [])
    ]
    report_path.write_text(json.dumps(public_report, ensure_ascii=False, indent=2), encoding='utf-8')
    report['report_path'] = str(report_path)
    return report


def _find_matching_manual_auth_path(base_url: str, api_key: str, provider: str, api: str = ''):
    normalized_base_url = str(base_url or '').rstrip('/')
    normalized_provider = str(provider or '').strip().lower()
    normalized_api = str(api or '').strip()
    normalized_key = str(api_key or '').strip()
    if not MANUAL_AUTH_SAVE_DIR.exists():
        return None
    for path in _iter_auth_json_files(MANUAL_AUTH_SAVE_DIR):
        payload = _read_auth_payload(path)
        entry = _extract_manual_api_config(payload, path.name)
        if not entry:
            continue
        if str(entry.get('provider') or '').strip().lower() != normalized_provider:
            continue
        if str(entry.get('base_url') or '').rstrip('/') != normalized_base_url:
            continue
        if str(entry.get('api_key') or '').strip() != normalized_key:
            continue
        if str(entry.get('api') or '').strip() != normalized_api:
            continue
        return path, payload
    return None


def append_model_to_manual_auth(auth_ref: str, model: str, remark: str | None = None):
    normalized_model = str(model or '').strip()
    if not auth_ref or not normalized_model:
        raise ValueError('auth_ref and model are required.')
    if len(normalized_model) > 200:
        raise ValueError('model is too long.')

    resolved = resolve_auth_reference(auth_ref=auth_ref)
    if not resolved:
        raise FileNotFoundError(f'Auth entry not found: {auth_ref}')

    source_id, path = resolved
    payload = _read_auth_payload(path)
    entry = _extract_manual_api_config(payload, path.name)
    if not entry:
        raise ValueError('Target auth entry is not a manual API config.')
    normalized_model = normalize_provider_model_id(entry['provider'], normalized_model)

    existing_models = _extract_payload_models(payload)
    merged_models = []
    for value in existing_models + [normalized_model]:
        item = str(value or '').strip()
        if item and item not in merged_models:
            merged_models.append(item)

    payload.setdefault('metadata', {})
    payload['metadata']['remark'] = (remark or '').strip() or payload['metadata'].get('remark') or f'manual-entry:{entry["provider"]}'
    payload['metadata']['captured_at'] = int(time.time())
    payload['metadata']['source'] = payload['metadata'].get('source') or 'dashboard_manual_entry'
    payload['content'] = {
        'type': 'api_key',
        'provider': entry['provider'],
        'base_url': entry['base_url'],
        'model': merged_models[0],
        'api_key': entry['api_key'],
        'models': merged_models,
    }
    if entry.get('api'):
        payload['content']['api'] = entry['api']
    if entry.get('headers'):
        payload['content']['headers'] = entry['headers']

    _write_manual_auth_payload(path, payload)
    item = build_auth_item(source_id, path)
    item['manual'] = True
    item['modelCount'] = len(merged_models)
    item['appended'] = True
    return item


def _model_mapping_entry(call_id: str, provider: str, upstream_id: str, deleted: bool = False):
    return {
        'call_id': str(call_id or '').strip(),
        'provider': str(provider or '').strip().lower(),
        'upstream_id': str(upstream_id or '').strip(),
        'deleted': bool(deleted),
    }


def _normalize_model_mapping_entries(value, provider_key: str, upstream_value: str):
    entries = []

    def add_entry(raw_entry):
        if isinstance(raw_entry, dict):
            call_value = str(raw_entry.get('call_id') or '').strip()
            target_provider = str(raw_entry.get('provider') or provider_key).strip().lower()
            target_upstream_id = str(raw_entry.get('upstream_id') or upstream_value).strip()
            deleted = bool(raw_entry.get('deleted'))
        else:
            call_value = str(raw_entry or '').strip()
            target_provider = provider_key
            target_upstream_id = upstream_value
            deleted = False
        if call_value or deleted:
            entry = _model_mapping_entry(call_value, target_provider or provider_key, target_upstream_id or upstream_value, deleted)
            key = (entry['call_id'], entry['provider'], entry['upstream_id'], entry['deleted'])
            existing = {
                (item.get('call_id'), item.get('provider'), item.get('upstream_id'), item.get('deleted'))
                for item in entries
            }
            if key not in existing:
                entries.append(entry)

    if isinstance(value, dict):
        raw_entries = value.get('mappings') or value.get('aliases') or value.get('call_ids')
        if isinstance(raw_entries, list):
            for raw_entry in raw_entries:
                if isinstance(raw_entry, dict):
                    add_entry(raw_entry)
                else:
                    add_entry({
                        'call_id': raw_entry,
                        'provider': value.get('provider') or provider_key,
                        'upstream_id': value.get('upstream_id') or upstream_value,
                        'deleted': value.get('deleted'),
                    })
        else:
            add_entry(value)
    else:
        add_entry(value)
    return entries


def _primary_model_mapping_entry(entry: dict):
    mappings = entry.get('mappings') if isinstance(entry, dict) else []
    if isinstance(mappings, list):
        for item in mappings:
            if isinstance(item, dict) and not bool(item.get('deleted')) and str(item.get('call_id') or '').strip():
                return item
        for item in mappings:
            if isinstance(item, dict):
                return item
    return {}


def iter_model_mapping_entries(overrides: dict, provider: str, upstream_id: str):
    provider_key = _canonical_provider_name(provider)
    upstream_value = str(upstream_id or '').strip()
    entry = (overrides or {}).get(provider_key, {}).get(upstream_value, {})
    mappings = entry.get('mappings') if isinstance(entry, dict) else []
    if not isinstance(mappings, list):
        mappings = []
    return [item for item in mappings if isinstance(item, dict)]


def _load_model_mapping_overrides():
    if not MODEL_MAPPING_OVERRIDES_FILE.exists():
        return {}
    try:
        payload = json.loads(MODEL_MAPPING_OVERRIDES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized = {}
    for provider, model_map in payload.items():
        if not isinstance(model_map, dict):
            continue
        provider_key = str(provider or '').strip().lower()
        if not provider_key:
            continue
        normalized[provider_key] = {}
        for upstream_id, call_id in model_map.items():
            upstream_value = str(upstream_id or '').strip()
            if not upstream_value:
                continue
            entries = _normalize_model_mapping_entries(call_id, provider_key, upstream_value)
            if entries:
                normalized[provider_key][upstream_value] = {'mappings': entries}
    return normalized


def _dump_model_mapping_overrides(overrides: dict):
    dumped = {}
    for provider, model_map in (overrides or {}).items():
        provider_key = str(provider or '').strip().lower()
        if not provider_key or not isinstance(model_map, dict):
            continue
        dumped[provider_key] = {}
        for upstream_id, entry in model_map.items():
            upstream_value = str(upstream_id or '').strip()
            if not upstream_value:
                continue
            mappings = _normalize_model_mapping_entries(entry, provider_key, upstream_value)
            if not mappings:
                continue
            if len(mappings) == 1:
                dumped[provider_key][upstream_value] = mappings[0]
            else:
                dumped[provider_key][upstream_value] = {'mappings': mappings}
        if not dumped[provider_key]:
            dumped.pop(provider_key, None)
    return dumped


def _save_model_mapping_overrides(overrides: dict):
    MODEL_MAPPING_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_MAPPING_OVERRIDES_FILE.write_text(
        json.dumps(_dump_model_mapping_overrides(overrides), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def get_model_mapping_overrides():
    return _load_model_mapping_overrides()


def _default_clash_profile_path():
    config_dir = BASE_CONFIG.parent
    copied_profiles = sorted(config_dir.glob('clash-profile-*.yaml'))
    if copied_profiles:
        return copied_profiles[0]
    return None


def _parse_clash_proxy_names(profile_path: Path | None):
    if not profile_path or not profile_path.exists():
        return {'profile_path': '', 'mixed_port': 0, 'proxy_names': []}
    try:
        text = profile_path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return {'profile_path': str(profile_path), 'mixed_port': 0, 'proxy_names': []}

    mixed_port = 0
    mixed_match = re.search(r'(?m)^mixed-port:\s*(\d+)\s*$', text)
    if mixed_match:
        try:
            mixed_port = int(mixed_match.group(1))
        except Exception:
            mixed_port = 0

    proxy_names = []
    in_proxies = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_proxies and stripped == 'proxies:':
            in_proxies = True
            continue
        if in_proxies and re.match(r'^[A-Za-z0-9_-]+:\s*$', stripped):
            break
        if not in_proxies:
            continue
        name_match = re.search(r'name:\s*(?:"([^"]+)"|\'([^\']+)\'|([^,}]+))', line)
        if not name_match:
            continue
        value = next((group for group in name_match.groups() if group), '')
        value = str(value or '').strip()
        if value and value not in proxy_names:
            proxy_names.append(value)

    return {
        'profile_path': str(profile_path),
        'mixed_port': mixed_port,
        'proxy_names': proxy_names,
    }


def _pick_clash_proxy_name(proxy_names: list[str], region_tokens: list[str], preferred_suffix: str = '4'):
    normalized = [str(item or '').strip() for item in (proxy_names or []) if str(item or '').strip()]
    if not normalized:
        return ''
    for token in region_tokens:
        exact = next((name for name in normalized if token in name and f'- {preferred_suffix}' in name), '')
        if exact:
            return exact
    for token in region_tokens:
        first = next((name for name in normalized if token in name), '')
        if first:
            return first
    return ''


def _build_default_model_proxy_presets(profile_info: dict):
    mixed_port = int(profile_info.get('mixed_port') or 0)
    proxy_url = f'http://127.0.0.1:{mixed_port}' if mixed_port > 0 else ''
    proxy_names = profile_info.get('proxy_names') or []
    defaults = [
        ('clash-auto', 'Clash Mixed Port', ['自动选择', 'Auto'], 'Auto'),
        ('us-4', '美国 US - 4', ['美国 US - 4', 'US - 4', '美国 US'], 'US'),
        ('hk-4', '香港 HK - 4', ['香港 HK - 4', 'HK - 4', '香港 HK'], 'HK'),
        ('sg-4', '新加坡 SG - 4', ['新加坡 SG - 4', 'SG - 4', '新加坡 SG'], 'SG'),
        ('jp-4', '日本 JP - 4', ['日本 JP - 4', 'JP - 4', '日本 JP'], 'JP'),
    ]
    presets = [{
        'id': 'direct',
        'label': 'Direct',
        'region': 'DIRECT',
        'proxy_name': '',
        'proxy_url': 'direct',
        'enabled': True,
    }]
    for preset_id, label, tokens, region in defaults:
        presets.append({
            'id': preset_id,
            'label': label,
            'region': region,
            'proxy_name': _pick_clash_proxy_name(proxy_names, tokens),
            'proxy_url': proxy_url,
            'enabled': bool(proxy_url),
        })
    return presets


def _normalize_model_proxy_rules(value):
    if not isinstance(value, dict):
        return {}
    normalized = {}
    for provider_key, item in value.items():
        provider = str(provider_key or '').strip().lower()
        if not provider or not isinstance(item, dict):
            continue
        preset_id = str(item.get('preset_id') or '').strip()
        proxy_url = str(item.get('proxy_url') or '').strip()
        proxy_name = str(item.get('proxy_name') or '').strip()
        label = str(item.get('label') or '').strip()
        if not preset_id and not proxy_url:
            continue
        normalized[provider] = {
            'preset_id': preset_id,
            'proxy_url': proxy_url,
            'proxy_name': proxy_name,
            'label': label,
            'enabled': bool(item.get('enabled', True)),
        }
    return normalized


def get_model_proxy_settings():
    profile_path = _default_clash_profile_path()
    profile_info = _parse_clash_proxy_names(profile_path)
    defaults = {
        'profile_path': profile_info.get('profile_path') or '',
        'mixed_port': int(profile_info.get('mixed_port') or 0),
        'presets': _build_default_model_proxy_presets(profile_info),
        'rules': {},
    }
    if not MODEL_PROXY_SETTINGS_FILE.exists():
        return defaults
    try:
        payload = json.loads(MODEL_PROXY_SETTINGS_FILE.read_text(encoding='utf-8'))
    except Exception:
        return defaults
    if not isinstance(payload, dict):
        return defaults
    presets = payload.get('presets')
    normalized_presets = []
    if isinstance(presets, list):
        for item in presets:
            if not isinstance(item, dict):
                continue
            preset_id = str(item.get('id') or '').strip()
            if not preset_id:
                continue
            normalized_presets.append({
                'id': preset_id,
                'label': str(item.get('label') or preset_id).strip(),
                'region': str(item.get('region') or '').strip(),
                'proxy_name': str(item.get('proxy_name') or '').strip(),
                'proxy_url': str(item.get('proxy_url') or '').strip(),
                'enabled': bool(item.get('enabled', True)),
            })
    merged = dict(defaults)
    if normalized_presets:
        merged['presets'] = normalized_presets
    merged['rules'] = _normalize_model_proxy_rules(payload.get('rules'))
    return merged


def _save_model_proxy_settings(settings: dict):
    MODEL_PROXY_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_PROXY_SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def save_model_proxy_rules(rules: list[dict] | None):
    settings = get_model_proxy_settings()
    preset_map = {str(item.get('id') or '').strip(): item for item in (settings.get('presets') or []) if str(item.get('id') or '').strip()}
    next_rules = {}
    for item in rules or []:
        if not isinstance(item, dict):
            continue
        provider = str(item.get('provider') or '').strip().lower()
        preset_id = str(item.get('preset_id') or '').strip()
        enabled = bool(item.get('enabled', True))
        if not provider or not preset_id:
            continue
        preset = preset_map.get(preset_id)
        if not preset:
            continue
        next_rules[provider] = {
            'preset_id': preset_id,
            'proxy_url': str(preset.get('proxy_url') or '').strip(),
            'proxy_name': str(preset.get('proxy_name') or '').strip(),
            'label': str(preset.get('label') or preset_id).strip(),
            'enabled': enabled,
        }
    settings['rules'] = next_rules
    _save_model_proxy_settings(settings)
    return settings


def _model_proxy_rule_for_provider(provider: str):
    provider_name = str(provider or '').strip().lower()
    if not provider_name:
        return {}
    return get_model_proxy_settings().get('rules', {}).get(provider_name, {}) or {}


def _model_proxy_url_for_provider(provider: str):
    item = _model_proxy_rule_for_provider(provider)
    if not item or not bool(item.get('enabled', True)):
        return ''
    return str(item.get('proxy_url') or '').strip()


def _provider_model_override_deleted(overrides: dict, provider: str, upstream_id: str):
    provider_value = str(provider or '').strip().lower()
    upstream_value = str(upstream_id or '').strip()
    if not provider_value or not upstream_value:
        return False
    entry = overrides.get(provider_value, {}).get(upstream_value, {})
    mappings = entry.get('mappings') if isinstance(entry, dict) else []
    if isinstance(mappings, list) and mappings:
        return all(bool(item.get('deleted')) for item in mappings if isinstance(item, dict))
    return False


def set_provider_model_override(
    provider: str,
    upstream_id: str,
    call_id: str,
    target_provider: str | None = None,
    target_upstream_id: str | None = None,
):
    provider_value = str(provider or '').strip().lower()
    upstream_value = str(upstream_id or '').strip()
    call_value = str(call_id or '').strip()
    target_provider_value = str(target_provider or provider or '').strip().lower()
    target_upstream_value = str(target_upstream_id or upstream_id or '').strip()

    if not provider_value or not upstream_value or not call_value or not target_provider_value or not target_upstream_value:
        raise ValueError('provider, upstream_id, target_provider, target_upstream_id, and call_id are required.')
    if len(call_value) > 200:
        raise ValueError('call_id is too long.')

    overrides = _load_model_mapping_overrides()
    provider_map = overrides.setdefault(provider_value, {})
    current_entries = iter_model_mapping_entries(overrides, provider_value, upstream_value)
    next_entry = _model_mapping_entry(call_value, target_provider_value, target_upstream_value, False)
    next_entries = [
        item for item in current_entries
        if not bool(item.get('deleted')) and not (
            str(item.get('provider') or '').strip().lower() == target_provider_value
            and str(item.get('upstream_id') or '').strip() == target_upstream_value
            and str(item.get('call_id') or '').strip() == call_value
        )
    ]
    next_entries.append(next_entry)
    provider_map[upstream_value] = {'mappings': next_entries}
    _save_model_mapping_overrides(overrides)
    return {
        'provider': provider_value,
        'target_provider': target_provider_value,
        'upstream_id': upstream_value,
        'target_upstream_id': target_upstream_value,
        'call_id': call_value,
    }


def delete_provider_model_override(provider: str, upstream_id: str, call_id: str | None = None):
    provider_value = str(provider or '').strip().lower()
    upstream_value = str(upstream_id or '').strip()
    call_value = str(call_id or '').strip()
    if not provider_value or not upstream_value:
        raise ValueError('provider and upstream_id are required.')

    overrides = _load_model_mapping_overrides()
    provider_map = overrides.setdefault(provider_value, {})
    
    if call_value:
        current_entries = iter_model_mapping_entries(overrides, provider_value, upstream_value)
        next_entries = [
            item for item in current_entries
            if not (
                str(item.get('provider') or '').strip().lower() == provider_value
                and str(item.get('upstream_id') or '').strip() == upstream_value
                and str(item.get('call_id') or '').strip() == call_value
            )
        ]
        if not next_entries:
            provider_map[upstream_value] = {'mappings': [
                _model_mapping_entry('', provider_value, upstream_value, True)
            ]}
        else:
            provider_map[upstream_value] = {'mappings': next_entries}
    else:
        provider_map[upstream_value] = {'mappings': [
            _model_mapping_entry('', provider_value, upstream_value, True)
        ]}
        
    _save_model_mapping_overrides(overrides)
    return {
        'provider': provider_value,
        'upstream_id': upstream_value,
        'call_id': call_value,
        'deleted': True,
    }



def _load_aggregate_model_aliases():
    if not AGGREGATE_MODEL_ALIASES_FILE.exists():
        return {}
    try:
        payload = json.loads(AGGREGATE_MODEL_ALIASES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized = {}
    for alias_id, raw_members in payload.items():
        if str(alias_id or '').strip() == '__hidden_builtin__':
            continue
        alias_value = _safe_name(alias_id, '')
        if not alias_value:
            continue
        if isinstance(raw_members, dict):
            raw_members = raw_members.get('members') or []
        if not isinstance(raw_members, list):
            raw_members = []
        members = []
        seen = set()
        for raw_member in raw_members:
            if not isinstance(raw_member, dict):
                continue
            provider = str(raw_member.get('provider') or '').strip().lower()
            upstream_id = str(raw_member.get('upstream_id') or '').strip()
            if not provider or not upstream_id:
                continue
            key = (provider, upstream_id)
            if key in seen:
                continue
            seen.add(key)
            members.append({
                'provider': provider,
                'upstream_id': upstream_id,
            })
        normalized[alias_value] = members
    return normalized


def _builtin_aggregate_alias_ids():
    return {'auto', 'image', 'agent', 'coder', 'reasoning', 'chat'}


def _load_hidden_aggregate_aliases():
    if not AGGREGATE_MODEL_ALIASES_FILE.exists():
        return set()
    try:
        payload = json.loads(AGGREGATE_MODEL_ALIASES_FILE.read_text(encoding='utf-8'))
    except Exception:
        return set()
    hidden = payload.get('__hidden_builtin__') if isinstance(payload, dict) else []
    if not isinstance(hidden, list):
        return set()
    return {
        _safe_name(item, '')
        for item in hidden
        if _safe_name(item, '') in _builtin_aggregate_alias_ids()
    }


def _save_aggregate_model_aliases(aliases: dict, hidden_aliases: set | None = None):
    AGGREGATE_MODEL_ALIASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(aliases or {})
    if hidden_aliases is None:
        hidden_aliases = _load_hidden_aggregate_aliases()
    hidden_list = [
        alias_id for alias_id in ['auto', 'image', 'agent', 'coder', 'reasoning', 'chat']
        if alias_id in set(hidden_aliases or set())
    ]
    if hidden_list:
        payload['__hidden_builtin__'] = hidden_list
    AGGREGATE_MODEL_ALIASES_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _ordered_aggregate_alias_ids(alias_map: dict, saved_aliases: dict | None = None):
    saved_aliases = saved_aliases or {}
    builtin_priority = ['auto', 'image', 'agent', 'coder', 'reasoning', 'chat']
    ordered = []
    seen = set()

    for alias_id in saved_aliases.keys():
        if alias_id in alias_map and alias_id not in seen:
            ordered.append(alias_id)
            seen.add(alias_id)

    for alias_id in builtin_priority:
        if alias_id in alias_map and alias_id not in seen:
            ordered.append(alias_id)
            seen.add(alias_id)

    for alias_id in alias_map.keys():
        if alias_id not in seen:
            ordered.append(alias_id)
            seen.add(alias_id)

    return ordered


def list_custom_aggregate_aliases():
    return _load_aggregate_model_aliases()


def create_custom_aggregate_alias(alias_id: str):
    alias_value = _safe_name(alias_id, '')
    if not alias_value:
        raise ValueError('aggregate alias id is required.')
    aliases = _load_aggregate_model_aliases()
    hidden_aliases = _load_hidden_aggregate_aliases()
    hidden_aliases.discard(alias_value)
    aliases.setdefault(alias_value, [])
    _save_aggregate_model_aliases(aliases, hidden_aliases)
    return {'alias_id': alias_value, 'members': aliases.get(alias_value, [])}


def delete_custom_aggregate_alias(alias_id: str):
    alias_value = _safe_name(alias_id, '')
    if not alias_value:
        raise ValueError('aggregate alias id is required.')
    aliases = _load_aggregate_model_aliases()
    hidden_aliases = _load_hidden_aggregate_aliases()
    if alias_value in aliases:
        removed_members = aliases.pop(alias_value, [])
        _save_aggregate_model_aliases(aliases, hidden_aliases)
        return {
            'alias_id': alias_value,
            'removed_count': len(removed_members),
            'hidden_builtin': False,
        }
    if alias_value in _builtin_aggregate_alias_ids():
        hidden_aliases.add(alias_value)
        _save_aggregate_model_aliases(aliases, hidden_aliases)
        return {
            'alias_id': alias_value,
            'removed_count': 0,
            'hidden_builtin': True,
        }
    raise ValueError(f'aggregate alias not found: {alias_value}')


def move_custom_aggregate_alias(alias_id: str, direction: int):
    alias_value = _safe_name(alias_id, '')
    if not alias_value:
        raise ValueError('aggregate alias id is required.')
    aliases = _load_aggregate_model_aliases()
    keys = list(aliases.keys())
    if alias_value not in aliases:
        raise ValueError(f'aggregate alias not found: {alias_value}')
    try:
        step = int(direction)
    except Exception:
        step = 0
    if step == 0:
        return {
            'alias_id': alias_value,
            'members': aliases.get(alias_value, []),
            'moved': False,
        }
    index = keys.index(alias_value)
    target = index + (-1 if step < 0 else 1)
    if target < 0 or target >= len(keys):
        return {
            'alias_id': alias_value,
            'members': aliases.get(alias_value, []),
            'moved': False,
        }
    keys[index], keys[target] = keys[target], keys[index]
    reordered = {key: aliases.get(key, []) for key in keys}
    _save_aggregate_model_aliases(reordered)
    return {
        'alias_id': alias_value,
        'members': reordered.get(alias_value, []),
        'moved': True,
    }



def reorder_custom_aggregate_aliases(ordered_ids: list):
    aliases = _load_aggregate_model_aliases()
    reordered = {}
    for alias_id in ordered_ids:
        val = _safe_name(str(alias_id), '')
        if val in aliases:
            reordered[val] = aliases[val]
    # Add any missing ones at the end
    for key, value in aliases.items():
        if key not in reordered:
            reordered[key] = value
    _save_aggregate_model_aliases(reordered)
    return {
        'alias_id': ordered_ids[0] if ordered_ids else '',
        'ordered_ids': list(reordered.keys()),
        'moved': True,
    }


def rename_custom_aggregate_alias(alias_id: str, new_alias_id: str):
    alias_value = _safe_name(alias_id, '')
    new_alias_value = _safe_name(new_alias_id, '')
    if not alias_value or not new_alias_value:
        raise ValueError('aggregate alias id is required.')
    if alias_value == new_alias_value:
        aliases = _load_aggregate_model_aliases()
        return {
            'alias_id': alias_value,
            'old_alias_id': alias_value,
            'members': aliases.get(alias_value, []),
            'renamed': False,
        }
    if alias_value in _builtin_aggregate_alias_ids():
        raise ValueError('built-in aggregate aliases cannot be renamed.')
    if new_alias_value in _builtin_aggregate_alias_ids():
        raise ValueError('new aggregate alias id conflicts with a built-in alias.')

    aliases = _load_aggregate_model_aliases()
    if alias_value not in aliases:
        raise ValueError(f'aggregate alias not found: {alias_value}')
    if new_alias_value in aliases:
        raise ValueError(f'aggregate alias already exists: {new_alias_value}')

    reordered = {}
    for key, members in aliases.items():
        reordered[new_alias_value if key == alias_value else key] = members
    _save_aggregate_model_aliases(reordered)
    return {
        'alias_id': new_alias_value,
        'old_alias_id': alias_value,
        'members': reordered.get(new_alias_value, []),
        'renamed': True,
    }


def add_custom_aggregate_alias_members(alias_id: str, members: list[dict] | None):
    alias_value = _safe_name(alias_id, '')
    if not alias_value:
        raise ValueError('aggregate alias id is required.')
    aliases = _load_aggregate_model_aliases()
    alias_members = aliases.setdefault(alias_value, [])
    seen = {(str(item.get('provider') or '').strip().lower(), str(item.get('upstream_id') or '').strip()) for item in alias_members if isinstance(item, dict)}
    added = 0
    for raw_member in members or []:
        if not isinstance(raw_member, dict):
            continue
        provider = str(raw_member.get('provider') or '').strip().lower()
        upstream_id = str(raw_member.get('upstream_id') or '').strip()
        if not provider or not upstream_id:
            continue
        key = (provider, upstream_id)
        if key in seen:
            continue
        seen.add(key)
        alias_members.append({
            'provider': provider,
            'upstream_id': upstream_id,
        })
        added += 1
    _save_aggregate_model_aliases(aliases)
    return {
        'alias_id': alias_value,
        'members': alias_members,
        'added_count': added,
    }


def set_custom_aggregate_alias_members(alias_id: str, members: list[dict] | None):
    alias_value = _safe_name(alias_id, '')
    if not alias_value:
        raise ValueError('aggregate alias id is required.')
    aliases = _load_aggregate_model_aliases()
    normalized = []
    seen = set()
    for raw_member in members or []:
        if not isinstance(raw_member, dict):
            continue
        provider = str(raw_member.get('provider') or '').strip().lower()
        upstream_id = str(raw_member.get('upstream_id') or '').strip()
        if not provider or not upstream_id:
            continue
        key = (provider, upstream_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            'provider': provider,
            'upstream_id': upstream_id,
        })
    aliases[alias_value] = normalized
    _save_aggregate_model_aliases(aliases)
    return {
        'alias_id': alias_value,
        'members': normalized,
        'saved_count': len(normalized),
    }


def get_custom_aggregate_aliases_for_model(provider: str, upstream_id: str):
    provider_value = str(provider or '').strip().lower()
    upstream_value = str(upstream_id or '').strip()
    if not provider_value or not upstream_value:
        return []
    aliases = []
    hidden_aliases = _load_hidden_aggregate_aliases()
    for alias_id, members in _load_aggregate_model_aliases().items():
        if alias_id in hidden_aliases:
            continue
        if any(
            str(item.get('provider') or '').strip().lower() == provider_value
            and str(item.get('upstream_id') or '').strip() == upstream_value
            for item in (members or [])
            if isinstance(item, dict)
        ):
            aliases.append(alias_id)
    return aliases


def _extract_model_ids_from_provider_config(provider_config):
    if not isinstance(provider_config, dict):
        return []
    models = provider_config.get('models')
    if not isinstance(models, list):
        return []
    result = []
    for item in models:
        if isinstance(item, dict):
            value = str(item.get('id') or item.get('name') or '').strip()
        else:
            value = str(item or '').strip()
        if value and value not in result:
            result.append(value)
    return result


def _extract_manual_api_config(payload, file_name: str):
    if not isinstance(payload, dict):
        return None
    content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
    if str(content.get('type') or '').strip().lower() != 'api_key':
        return None

    provider = detect_provider(payload, file_name)
    base_url = str(content.get('base_url') or '').strip()
    api_key = str(content.get('api_key') or '').strip()
    models = _extract_payload_models(payload)
    headers = _extract_payload_headers(payload)
    api_type = str(content.get('api') or '').strip()

    if not provider or not base_url or not api_key or not models:
        return None

    return {
        'provider': provider,
        'base_url': base_url.rstrip('/'),
        'api_key': api_key,
        'models': models,
        'headers': headers,
        'api': api_type,
    }


def detect_provider(payload, file_name: str):
    provider = None
    auth_kind = _detect_auth_payload_kind(payload)
    if isinstance(payload, dict):
        content = payload.get('content') if isinstance(payload.get('content'), dict) else {}
        provider = content.get('provider') or payload.get('provider') or payload.get('type')
        if not provider:
            auth_mode = payload.get('auth_mode')
            if auth_mode == 'chatgpt':
                provider = 'codex'
        if not provider:
            if auth_kind in ('codex_chatgpt', 'codex_flat', 'codex_oauth_content', 'codex_oauth_flat'):
                provider = 'codex'
            elif auth_kind in ('antigravity_google', 'antigravity_oauth_content', 'antigravity_oauth_flat'):
                provider = 'antigravity'
            elif auth_kind in ('oauth_flat', 'oauth_content'):
                token_claims = _extract_token_claims(payload)
                if token_claims.get('openai_auth'):
                    provider = 'codex'

    if provider:
        provider = str(provider).strip().lower()
        if provider == 'openai-codex':
            provider = 'codex'
        if provider == 'google-antigravity':
            provider = 'antigravity'

    lower_name = file_name.lower()
    if not provider:
        for candidate in KNOWN_PROVIDERS:
            if lower_name.startswith(candidate + '-') or lower_name == f'{candidate}.json' or f'{candidate}-' in lower_name:
                provider = candidate
                break
    # Last resort: derive from the parent directory when the file sits under
    # storage/auth/<provider>/ (typical for dashboard-added API-key entries).
    if not provider:
        try:
            path = Path(file_name)
            parent_name = path.parent.name.strip().lower()
            if parent_name and parent_name not in ('archive', 'sources', '_archive', 'backups'):
                provider = parent_name
        except Exception:
            pass
    return provider or None


def detect_provider_from_manual_input(base_url: str, model: str, explicit_provider: str | None = None):
    if explicit_provider:
        return explicit_provider.strip().lower()

    host = ''
    try:
        host = (urlparse(base_url).hostname or '').lower()
    except Exception:
        host = ''
    model_lower = (model or '').lower()

    for provider, hints in MANUAL_PROVIDER_HOST_HINTS.items():
        if any(h in host for h in hints):
            return provider

    for provider, hints in MANUAL_PROVIDER_MODEL_HINTS.items():
        if any(model_lower.startswith(h) or h in model_lower for h in hints):
            return provider

    return 'custom'


def normalize_provider_model_id(provider: str, model_id: str):
    provider_key = str(provider or '').strip().lower()
    value = str(model_id or '').strip()
    if not value:
        return ''
    if provider_key == 'openrouter':
        if value.startswith('openrouter/'):
            return value
        return f'openrouter/{value.lstrip("/")}'
    if provider_key != 'antigravity':
        return value
    if value.startswith('google-antigravity/'):
        return value
    slug = value.lower()
    slug = slug.replace('&', ' and ')
    slug = re.sub(r'[\(\)\[\]]', ' ', slug)
    slug = slug.replace('.', '-')
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    if not slug:
        return value
    return f'google-antigravity/{slug}'


def iter_auth_source_dirs():
    for source_id, source_path in AUTH_SOURCE_DIRS.items():
        yield source_id, source_path


def resolve_auth_ref(auth_ref: str):
    source_id, file_name = parse_auth_ref(auth_ref)
    if not file_name:
        return None
    source_dir = AUTH_SOURCE_DIRS.get(source_id)
    if source_dir:
        for candidate_name in _auth_ref_path_candidates(file_name):
            path = source_dir / Path(candidate_name)
            if path.exists() and path.is_file():
                return source_id, path
        if '/' not in file_name:
            for candidate in _iter_auth_json_files(source_dir):
                if candidate.name == file_name:
                    return source_id, candidate
    if source_id == 'default' or not source_dir:
        candidate_names = _auth_ref_path_candidates(file_name)
        for fallback_source_id, fallback_source_dir in iter_auth_source_dirs():
            for candidate_name in candidate_names:
                for relative_name in _candidate_relative_names_for_source(fallback_source_id, candidate_name):
                    path = fallback_source_dir / Path(relative_name)
                    if path.exists() and path.is_file():
                        return fallback_source_id, path
            if '/' not in file_name:
                for candidate in _iter_auth_json_files(fallback_source_dir):
                    if candidate.name == file_name:
                        return fallback_source_id, candidate
    return None


def resolve_auth_reference(auth_ref: str | None = None, name: str | None = None):
    if auth_ref:
        resolved = resolve_auth_ref(auth_ref)
        if resolved:
            return resolved
    if name:
        # Backward compatibility: prefer default source by filename
        resolved = resolve_auth_ref(build_auth_ref('default', name))
        if resolved:
            return resolved
        # fallback: first matching filename in all sources
        for source_id, source_dir in iter_auth_source_dirs():
            candidate = source_dir / name
            if candidate.exists() and candidate.is_file():
                return source_id, candidate
            for path in _iter_auth_json_files(source_dir):
                if path.name == name:
                    return source_id, path
    return None


def canonicalize_auth_ref(auth_ref: str | None = None, name: str | None = None):
    resolved = resolve_auth_reference(auth_ref=auth_ref, name=name)
    if not resolved:
        return None
    source_id, path = resolved
    source_dir = AUTH_SOURCE_DIRS.get(source_id, path.parent)
    return build_auth_ref(source_id, _relative_auth_name(source_dir, path))


def _normalize_quota_match_value(value):
    text = str(value or '').strip().lower()
    return text or None


def _load_quota_cache_rows():
    try:
        payload = json.loads(QUOTA_CACHE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []
    rows = payload.get('data') if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _find_auth_quota(auth_item, quota_rows):
    if str(auth_item.get('provider') or '').strip().lower() != 'codex':
        return None
    email_value = _normalize_quota_match_value(auth_item.get('email'))
    account_value = _normalize_quota_match_value(auth_item.get('accountId'))
    id_values = {
        _normalize_quota_match_value(auth_item.get('id')),
        _normalize_quota_match_value(auth_item.get('name')),
    }
    id_values.discard(None)
    for row in quota_rows:
        if str(row.get('provider') or '').strip().lower() != 'openai-codex':
            continue
        row_email = _normalize_quota_match_value(row.get('email'))
        row_account_values = {
            _normalize_quota_match_value(row.get('accountId')),
            _normalize_quota_match_value(row.get('account_id')),
        }
        row_account_values.discard(None)
        row_id = _normalize_quota_match_value(row.get('id'))
        if email_value and row_email == email_value:
            return {
                'quota_weekly_rem': row.get('weekly_rem'),
                'quota_daily_rem': row.get('daily_rem'),
            }
        if account_value and account_value in row_account_values:
            return {
                'quota_weekly_rem': row.get('weekly_rem'),
                'quota_daily_rem': row.get('daily_rem'),
            }
        if row_id and row_id in id_values:
            return {
                'quota_weekly_rem': row.get('weekly_rem'),
                'quota_daily_rem': row.get('daily_rem'),
            }
    return None


def build_auth_item(source_id: str, path: Path, quota_rows=None):
    payload = _read_auth_payload(path)
    stat = path.stat()
    email, account_id = _extract_payload_fields(payload)
    provider = detect_provider(payload, path.name)
    auth_kind = _detect_auth_payload_kind(payload)
    manual_entry = _extract_manual_api_config(payload, path.name)
    source_dir = AUTH_SOURCE_DIRS.get(source_id, path.parent)
    relative_name = _relative_auth_name(source_dir, path)
    key_fingerprint = None
    if manual_entry and manual_entry.get('api_key'):
        key_fingerprint = hashlib.sha256(str(manual_entry.get('api_key')).encode('utf-8')).hexdigest()[-6:]
    item = {
        'id': build_auth_ref(source_id, relative_name),
        'name': path.name,
        'relativeName': relative_name,
        'sourceId': source_id,
        'sourcePath': str(path.parent),
        'path': str(path),
        'size': stat.st_size,
        'mtime': stat.st_mtime,
        'email': email,
        'accountId': account_id,
        'provider': provider,
        'authKind': auth_kind,
        'manual': bool(manual_entry),
        'keyFingerprint': key_fingerprint,
    }
    quota = _find_auth_quota(item, quota_rows or [])
    if quota:
        item.update(quota)
    return item


def get_auth_file_info(name: str):
    # Backward-compatible helper for old call sites
    resolved = resolve_auth_reference(name=name)
    if not resolved:
        return None
    source_id, path = resolved
    return build_auth_item(source_id, path)


def get_auth_file_info_by_ref(auth_ref: str):
    resolved = resolve_auth_reference(auth_ref=auth_ref)
    if not resolved:
        return None
    source_id, path = resolved
    return build_auth_item(source_id, path)


def list_auth_files():
    items = []
    quota_rows = _load_quota_cache_rows()
    for source_id, source_dir in iter_auth_source_dirs():
        for path in _iter_auth_json_files(source_dir):
            try:
                items.append(build_auth_item(source_id, path, quota_rows))
            except Exception:
                continue
    return items


def collect_provider_model_aliases(auth_refs: list[str] | None = None):
    overrides = _load_model_mapping_overrides()
    alias_map = {}
    for provider, entries in PROVIDER_MODEL_ALIASES.items():
        alias_map[provider] = [
            (name, alias)
            for name, alias in entries
            if not _provider_model_override_deleted(overrides, provider, name)
        ]
    for provider, entries in PROVIDER_AGGREGATE_ALIASES.items():
        alias_map.setdefault(provider, [])
        for name, alias in entries:
            if _provider_model_override_deleted(overrides, provider, name):
                continue
            if (name, alias) not in alias_map[provider]:
                alias_map[provider].append((name, alias))

    resolved_paths = []
    if auth_refs:
        for auth_ref in auth_refs:
            resolved = resolve_auth_reference(auth_ref=auth_ref)
            if resolved:
                resolved_paths.append(resolved)
    else:
        for source_id, source_dir in iter_auth_source_dirs():
            for path in _iter_auth_json_files(source_dir):
                resolved_paths.append((source_id, path))

    for source_id, path in resolved_paths:
        payload = _read_auth_payload(path)
        provider = detect_provider(payload, path.name)
        if not provider:
            continue
        models = _extract_payload_models(payload)
        if provider not in alias_map:
            alias_map[provider] = []
        existing_aliases = {alias for _name, alias in alias_map[provider]}
        for model_id in models:
            normalized_model_id = normalize_provider_model_id(provider, model_id)
            if _provider_model_override_deleted(overrides, provider, normalized_model_id):
                continue
            if normalized_model_id not in existing_aliases:
                alias_map[provider].append((normalized_model_id, normalized_model_id))
                existing_aliases.add(normalized_model_id)

    for provider, provider_overrides in overrides.items():
        if not isinstance(provider_overrides, dict):
            continue
        provider_value = str(provider or '').strip().lower()
        if not provider_value:
            continue
        alias_map.setdefault(provider_value, [])
        for upstream_id, entry in provider_overrides.items():
            upstream_value = str(upstream_id or '').strip()
            if not upstream_value:
                continue
            for override_entry in iter_model_mapping_entries(overrides, provider_value, upstream_value):
                if override_entry.get('deleted'):
                    continue
                call_value = str(override_entry.get('call_id') or '').strip()
                if not call_value or (upstream_value, call_value) in alias_map[provider_value]:
                    continue
                alias_map[provider_value].append((upstream_value, call_value))

    return alias_map


def collect_detected_providers(auth_refs: list[str] | None = None):
    providers = []
    resolved_paths = []

    if auth_refs:
        for auth_ref in auth_refs:
            resolved = resolve_auth_reference(auth_ref=auth_ref)
            if resolved:
                resolved_paths.append(resolved)
    else:
        for source_id, source_dir in iter_auth_source_dirs():
            for path in _iter_auth_json_files(source_dir):
                resolved_paths.append((source_id, path))

    for _source_id, path in resolved_paths:
        payload = _read_auth_payload(path)
        provider = detect_provider(payload, path.name)
        if provider and provider not in providers:
            providers.append(provider)

    return providers


def rewrite_auth_dir(config_text: str, auth_dir):
    auth_dir_value = Path(auth_dir).resolve().as_posix()
    lines = config_text.splitlines()
    replaced = False
    output = []
    for line in lines:
        if line.strip().startswith('auth-dir:'):
            output.append(f'auth-dir: "{auth_dir_value}"')
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f'auth-dir: "{auth_dir_value}"')
    return '\n'.join(output) + '\n'


def rewrite_host(config_text: str, host: str):
    host_value = (host or '127.0.0.1').strip() or '127.0.0.1'
    lines = config_text.splitlines()
    replaced = False
    output = []
    for line in lines:
        if line.strip().startswith('host:'):
            output.append(f'host: "{host_value}"')
            replaced = True
        else:
            output.append(line)
    if not replaced:
        output.append(f'host: "{host_value}"')
    return '\n'.join(output) + '\n'


def _strip_top_level_block(config_text: str, key_name: str):
    lines = config_text.splitlines()
    output = []
    skipping = False
    for line in lines:
        stripped = line.lstrip()
        top_level = bool(line) and not line.startswith((' ', '\t'))
        if stripped.startswith(f'{key_name}:') and top_level:
            skipping = True
            continue
        if skipping and top_level:
            skipping = False
        if not skipping:
            output.append(line)
    return '\n'.join(output).rstrip() + '\n'


def rewrite_api_keys(config_text: str, api_keys: list[str] | None = None):
    cleaned = _strip_top_level_block(config_text, 'api-keys').rstrip() + '\n\n'
    values = [str(item).strip() for item in (api_keys or []) if str(item).strip()]
    if not values:
        return cleaned
    lines = ['api-keys:']
    for value in values:
        lines.append(f'  - "{value}"')
    return cleaned + '\n'.join(lines) + '\n'


def rewrite_request_log(config_text: str, enabled: bool = True):
    cleaned = _strip_top_level_block(config_text, 'request-log').rstrip() + '\n\n'
    return cleaned + f'request-log: {str(bool(enabled)).lower()}\n'


def build_prefixed_alias(provider: str, alias: str):
    provider_value = str(provider or '').strip().lower()
    provider_token = _safe_name(provider_value, 'provider')
    alias_value = str(alias or '').strip()
    if provider_value and alias_value.lower().startswith(provider_value + '/'):
        alias_value = alias_value[len(provider_value) + 1:]
    alias_token = _safe_name(alias_value, 'model')
    if not alias_token:
        return provider_token
    return f'{provider_token}-{alias_token}'


def _canonical_provider_name(provider: str):
    value = str(provider or '').strip().lower()
    alias_map = {
        'google': 'googleai',
        'gemini': 'googleai',
        'googleai': 'googleai',
        'google-antigravity': 'antigravity',
        'antigravity': 'antigravity',
        'ark': 'volcengine',
        'openai-compatible': 'openai-compatibility',
        'openai-compatibility': 'openai-compatibility',
    }
    if value in alias_map:
        return alias_map[value]
    return value


# Only these providers use OAuth flows — everything else (including dynamically-added
# API-key providers) is routed through the openai-compatibility / claude-api-key layer.
_OAUTH_PROVIDERS = frozenset({
    'codex', 'googleai', 'gemini-cli', 'vertex', 'aistudio',
    'antigravity', 'qwen', 'kimi', 'iflow', 'claude',
})


def _provider_route_kind(provider: str, target_provider: str | None = None):
    provider_key = _canonical_provider_name(target_provider or provider)
    if provider_key in _OAUTH_PROVIDERS:
        return 'oauth-alias'
    # All other providers (known or dynamically-added) go through api-key mapping.
    return 'api-key-mapping'


def _is_known_provider_name(provider: str):
    """A provider is considered "known" if it ships preset aliases, uses OAuth, or
    has at least one auth file (including dynamically-added API-key entries)."""
    provider_key = _canonical_provider_name(provider)
    if not provider_key:
        return False
    if provider_key in _OAUTH_PROVIDERS:
        return True
    if provider_key in PROVIDER_MODEL_ALIASES:
        return True
    # Check whether any auth file under storage/auth/<provider>/ exists.
    provider_dir = POOL_AUTH_DIR / provider_key
    if provider_dir.is_dir() and any(_iter_auth_json_files(provider_dir)):
        return True
    return False


def _runtime_config_validation_issues(runtime_text: str, providers: list[str], selected_auth_refs: list[str] | None = None):
    issues = []
    text = str(runtime_text or '')
    if not text.strip():
        issues.append('runtime config is empty')
    if 'oauth-model-alias:' not in text:
        issues.append('oauth-model-alias block is missing')
    if providers and 'oauth-model-alias:\n' in text and len(text.split('oauth-model-alias:', 1)[1].strip()) == 0:
        issues.append('oauth-model-alias block has no entries')
    if selected_auth_refs is not None and not [str(ref or '').strip() for ref in selected_auth_refs if str(ref or '').strip()]:
        issues.append('no selected auth refs resolved')
    try:
        import yaml  # type: ignore
        try:
            parsed = yaml.safe_load(text)
        except Exception as exc:
            issues.append(f'yaml parse failed: {exc}')
        else:
            if not isinstance(parsed, dict):
                issues.append('runtime config root is not a mapping')
            elif 'oauth-model-alias' not in parsed:
                issues.append('parsed config does not contain oauth-model-alias')
    except Exception:
        # PyYAML is not guaranteed to be installed in this dashboard runtime.
        pass
    return issues


def _antigravity_runtime_model_id(model_id: str):
    value = str(model_id or '').strip()
    if not value:
        return ''
    if value.startswith('google-antigravity/'):
        value = value.split('/', 1)[1]
    slug = value.lower().replace('_', '-')
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    replacements = {
        'gemini-3-1-': 'gemini-3.1-',
        'gemini-2-5-': 'gemini-2.5-',
        'gemini-3-1': 'gemini-3.1',
        'gemini-2-5': 'gemini-2.5',
    }
    for source, target in replacements.items():
        if source in slug:
            slug = slug.replace(source, target)
    return slug


def default_provider_call_id(provider: str, upstream_id: str, alias: str | None = None):
    provider_key = _canonical_provider_name(provider)
    upstream_value = str(upstream_id or '').strip()
    alias_value = str(alias or '').strip()
    base_value = alias_value or upstream_value
    if provider_key == 'antigravity':
        return build_prefixed_alias('antigravity', _antigravity_runtime_model_id(upstream_value or base_value))
    if provider_key == 'googleai':
        value = upstream_value or base_value
        if value.startswith('googleai-'):
            value = value[len('googleai-'):]
        return value
    if provider_key == 'codex' and alias_value.lower() in ('codex5.5', 'codex-5.5'):
        return alias_value
    return build_prefixed_alias(provider_key, base_value)


def normalize_runtime_model_id(provider: str, model_id: str):
    provider_key = _canonical_provider_name(provider)
    value = str(model_id or '').strip()
    if not value:
        return ''
    if provider_key == 'antigravity':
        return _antigravity_runtime_model_id(value)
    if provider_key != 'openrouter':
        return value
    if value in ('openrouter/free', 'openrouter/auto'):
        return value
    if value.startswith('openrouter/'):
        return value[len('openrouter/'):]
    return value


def derive_global_aggregate_aliases(source_provider: str, source_model_id: str, runtime_upstream_id: str):
    provider_value = str(source_provider or '').strip().lower()
    source_value = str(source_model_id or '').strip().lower()
    runtime_value = str(runtime_upstream_id or '').strip().lower()
    haystack = ' '.join([provider_value, source_value, runtime_value])
    aliases = []

    def add(alias_name: str):
        alias_token = str(alias_name or '').strip().lower()
        if alias_token and alias_token not in aliases:
            aliases.append(alias_token)

    if '/auto' in haystack or haystack.endswith(' auto') or haystack.endswith('/auto') or source_value == 'zenmux/auto':
        add('auto')

    image_markers = (
        'image', 'veo', 'kling', 'seedream', 'seedance', 'hunyuan-image',
        'glm-image', '4.6v', 'gemma-3', 'riverflow'
    )
    if any(marker in haystack for marker in image_markers):
        add('image')

    agent_markers = (
        'minimax-m2.5', 'minimax-m2.1', 'qwen3-coder', 'trinity-large-preview',
        'nemotron-3-super', 'agent'
    )
    if any(marker in haystack for marker in agent_markers):
        add('agent')

    coder_markers = ('coding-', 'coder', 'kat-coder', 'kimi-for-coding')
    if any(marker in haystack for marker in coder_markers):
        add('coder')

    reasoning_markers = ('thinking', 'step-3.5-flash', 'reasoning')
    if any(marker in haystack for marker in reasoning_markers):
        add('reasoning')

    specialized_markers = (
        'embedding', 'robotics', 'tts', 'transcribe', 'transcription',
        'whisper', 'prompt-guard', 'safeguard', 'cogvideox'
    )
    is_specialized = any(marker in haystack for marker in specialized_markers)

    if not aliases and not is_specialized:
        add('chat')

    return aliases


def merge_provider_preset_models(provider: str, models: list[str] | None):
    provider_key = str(provider or '').strip().lower()
    merged = []
    for value in models or []:
        item = str(value or '').strip()
        if item and item not in merged:
            merged.append(item)
    for preset_name, _alias in PROVIDER_MODEL_ALIASES.get(provider_key, []):
        item = str(preset_name or '').strip()
        if item and item not in merged:
            merged.append(item)
    return merged


def _group_manual_entry_models(entry: dict, overrides: dict | None = None):
    grouped = {}
    grouped_seen = {}
    grouped_aggregate = {}
    grouped_aggregate_seen = {}
    source_provider = str(entry.get('provider') or '').strip().lower()
    merged_models = merge_provider_preset_models(source_provider, entry.get('models') or [])
    for upstream_id, override_entry in (overrides or _load_model_mapping_overrides()).get(source_provider, {}).items():
        upstream_value = str(upstream_id or '').strip()
        for mapping_entry in iter_model_mapping_entries(overrides or _load_model_mapping_overrides(), source_provider, upstream_value):
            if not isinstance(mapping_entry, dict) or bool(mapping_entry.get('deleted')):
                continue
            call_value = str(mapping_entry.get('call_id') or '').strip()
            if upstream_value and call_value and upstream_value not in merged_models:
                merged_models.append(upstream_value)
    aggregate_alias_ids = _aggregate_alias_id_set()
    test_results = _load_provider_model_test_results()
    strategy = _current_route_strategy()
    now_ts = int(time.time())
    aggregate_alias_map = {}
    for upstream_name, alias_name in PROVIDER_AGGREGATE_ALIASES.get(source_provider, []):
        aggregate_alias_map.setdefault(str(upstream_name or '').strip(), [])
        if alias_name not in aggregate_alias_map[str(upstream_name or '').strip()]:
            aggregate_alias_map[str(upstream_name or '').strip()].append(str(alias_name or '').strip())
    ordered_source_models = list(merged_models)
    if bool(strategy.get('enabled')) and not bool(strategy.get('aggregate_only')):
        ordered_source_models = [
            model for model, _alias in _prioritize_provider_alias_pairs(
                source_provider,
                [(model_id, model_id) for model_id in merged_models],
                overrides=overrides,
            )
        ]
    for model_id in ordered_source_models:
        source_model_id = normalize_provider_model_id(source_provider, model_id)
        if not source_model_id:
            continue
        for mapping in resolve_provider_mappings(source_provider, source_model_id, source_model_id, overrides=overrides):
            if bool(mapping.get('deleted')):
                continue
            target_provider = str(mapping.get('target_provider') or source_provider).strip().lower() or source_provider
            grouped.setdefault(target_provider, [])
            grouped_seen.setdefault(target_provider, set())
            runtime_upstream_id = normalize_runtime_model_id(
                target_provider,
                str(mapping.get('upstream_id') or source_model_id).strip() or source_model_id,
            )
            if not runtime_upstream_id:
                continue
            aliases = [str(mapping.get('call_id') or '').strip()]
            for extra_alias in aggregate_alias_map.get(source_model_id, []):
                if extra_alias and extra_alias not in aliases:
                    aliases.append(extra_alias)
            for global_alias in derive_global_aggregate_aliases(source_provider, source_model_id, runtime_upstream_id):
                if global_alias not in aliases:
                    aliases.append(global_alias)
            for custom_alias in get_custom_aggregate_aliases_for_model(source_provider, source_model_id):
                if custom_alias not in aliases:
                    aliases.append(custom_alias)
            for alias_value in aliases:
                item_key = (runtime_upstream_id, alias_value)
                if not alias_value or item_key in grouped_seen[target_provider]:
                    continue
                grouped_seen[target_provider].add(item_key)
                row = {
                    'name': runtime_upstream_id,
                    'alias': alias_value,
                }
                alias_is_aggregate = alias_value in aggregate_alias_ids
                if alias_is_aggregate or (bool(strategy.get('enabled')) and not bool(strategy.get('aggregate_only'))):
                    grouped_aggregate.setdefault(target_provider, {})
                    grouped_aggregate_seen.setdefault(target_provider, set())
                    aggregate_key = (runtime_upstream_id, alias_value)
                    if aggregate_key in grouped_aggregate_seen[target_provider]:
                        continue
                    grouped_aggregate_seen[target_provider].add(aggregate_key)
                    grouped_aggregate[target_provider].setdefault(alias_value, [])
                    grouped_aggregate[target_provider][alias_value].append({
                        'rank': _model_test_rank(str(mapping.get('call_id') or '').strip(), test_results, now_ts, strategy),
                        'row': row,
                    })
                else:
                    grouped[target_provider].append(row)

    for target_provider, alias_map in grouped_aggregate.items():
        grouped.setdefault(target_provider, [])
        for alias_value, entries in alias_map.items():
            entries.sort(key=lambda item: item.get('rank') or (1, 0, 0))
            grouped[target_provider].extend([item.get('row') for item in entries if isinstance(item.get('row'), dict)])
    return grouped


def resolve_provider_mapping(provider: str, upstream_id: str, alias: str | None = None, overrides: dict | None = None):
    provider_key = _canonical_provider_name(provider)
    upstream_value = str(upstream_id or '').strip()
    alias_value = str(alias or '').strip()
    override_map = overrides or _load_model_mapping_overrides()
    override_entry = _primary_model_mapping_entry(override_map.get(provider_key, {}).get(upstream_value, {}))
    if isinstance(override_entry, dict) and override_entry:
        if bool(override_entry.get('deleted')):
            return {
                'source_provider': provider_key,
                'target_provider': _canonical_provider_name(provider_key),
                'upstream_id': upstream_value,
                'call_id': '',
                'deleted': True,
            }
        target_provider = str(override_entry.get('provider') or provider_key).strip().lower()
        override_value = str(override_entry.get('call_id') or '').strip()
        target_upstream_id = str(override_entry.get('upstream_id') or upstream_value).strip()
    else:
        target_provider = provider_key
        override_value = str(override_entry or '').strip()
        target_upstream_id = upstream_value
    base_value = alias_value or upstream_value
    return {
        'source_provider': provider_key,
        'target_provider': _canonical_provider_name(target_provider or provider_key),
        'upstream_id': target_upstream_id or upstream_value,
        'call_id': override_value or default_provider_call_id(target_provider or provider_key, target_upstream_id or base_value, alias_value),
        'deleted': False,
    }


def resolve_provider_mappings(provider: str, upstream_id: str, alias: str | None = None, overrides: dict | None = None):
    provider_key = _canonical_provider_name(provider)
    upstream_value = str(upstream_id or '').strip()
    alias_value = str(alias or '').strip()
    override_map = overrides or _load_model_mapping_overrides()
    entries = iter_model_mapping_entries(override_map, provider_key, upstream_value)
    if alias_value and alias_value != upstream_value:
        matched_entries = [item for item in entries if str(item.get('call_id') or '').strip() == alias_value]
        if matched_entries:
            entries = matched_entries
    if not entries:
        return [resolve_provider_mapping(provider_key, upstream_value, alias_value, overrides=override_map)]
    mappings = []
    for override_entry in entries:
        if bool(override_entry.get('deleted')):
            continue
        target_provider = str(override_entry.get('provider') or provider_key).strip().lower()
        target_upstream_id = str(override_entry.get('upstream_id') or upstream_value).strip()
        override_value = str(override_entry.get('call_id') or '').strip()
        if not override_value:
            continue
        mappings.append({
            'source_provider': provider_key,
            'target_provider': _canonical_provider_name(target_provider or provider_key),
            'upstream_id': target_upstream_id or upstream_value,
            'call_id': override_value,
            'deleted': False,
        })
    if mappings:
        return mappings
    if any(bool(item.get('deleted')) for item in entries):
        return [{
            'source_provider': provider_key,
            'target_provider': _canonical_provider_name(provider_key),
            'upstream_id': upstream_value,
            'call_id': '',
            'deleted': True,
        }]
    return [resolve_provider_mapping(provider_key, upstream_value, alias_value, overrides=override_map)]


def resolve_provider_call_id(provider: str, upstream_id: str, alias: str | None = None, overrides: dict | None = None):
    return resolve_provider_mapping(provider, upstream_id, alias, overrides).get('call_id', '')


def build_openai_compatibility_block(entries):
    if not entries:
        return ''

    overrides = _load_model_mapping_overrides()
    grouped_entries = {}
    for entry in entries:
        grouped_models = _group_manual_entry_models(entry, overrides=overrides)
        for provider, models in grouped_models.items():
            headers = entry.get('headers') or {}
            model_proxy_url = _model_proxy_url_for_provider(provider)
            for model in models:
                model_name = str(model.get('name') or '').strip()
                alias_name = str(model.get('alias') or '').strip()
                if not model_name or not alias_name:
                    continue
                proxy_group_key = (
                    provider,
                    str(entry["base_url"]),
                    json.dumps(headers, ensure_ascii=False, sort_keys=True),
                    model_proxy_url,
                )
                proxy_group = grouped_entries.setdefault(proxy_group_key, {
                    'provider': provider,
                    'base_url': str(entry['base_url']),
                    'headers': headers,
                    'api_keys': [],
                    'models': [],
                    'seen_models': set(),
                    'proxy_url': model_proxy_url,
                })
                api_key = str(entry.get('api_key') or '').strip()
                if api_key and api_key not in proxy_group['api_keys']:
                    proxy_group['api_keys'].append(api_key)
                model_key = (model_name, alias_name)
                if model_key in proxy_group['seen_models']:
                    continue
                proxy_group['seen_models'].add(model_key)
                proxy_group['models'].append({
                    'name': model_name,
                    'alias': alias_name,
                })

    lines = ['openai-compatibility:']
    for group in grouped_entries.values():
        lines.extend([
            f'  - name: "{group["provider"]}"',
            f'    base-url: "{group["base_url"]}"',
            '    api-key-entries:',
        ])
        for api_key in group['api_keys']:
            lines.append(f'      - api-key: "{api_key}"')
            if group.get('proxy_url'):
                lines.append(f'        proxy-url: "{group["proxy_url"]}"')
        headers = group.get('headers') or {}
        if headers:
            lines.append('    headers:')
            for key, value in headers.items():
                lines.append(f'      {key}: "{value}"')
        lines.append('    models:')
        for model in group['models']:
            lines.extend([
                f'      - name: "{model["name"]}"',
                f'        alias: "{model["alias"]}"',
            ])
    return '\n'.join(lines) + '\n'


def rewrite_openai_compatibility(config_text: str, entries):
    cleaned = _strip_top_level_block(config_text, 'openai-compatibility')
    block = build_openai_compatibility_block(entries)
    if not block:
        return cleaned
    return cleaned.rstrip() + '\n\n' + block


def build_claude_api_key_block(entries):
    if not entries:
        return ''
    overrides = _load_model_mapping_overrides()
    lines = ['claude-api-key:']
    for entry in entries:
        grouped_models = _group_manual_entry_models(entry, overrides=overrides)
        for provider, models in grouped_models.items():
            proxy_url = _model_proxy_url_for_provider(provider)
            lines.extend([
                f'  - api-key: "{entry["api_key"]}"',
                f'    base-url: "{entry["base_url"]}"',
            ])
            if proxy_url:
                lines.append(f'    proxy-url: "{proxy_url}"')
            headers = entry.get('headers') or {}
            if headers:
                lines.append('    headers:')
                for key, value in headers.items():
                    lines.append(f'      {key}: "{value}"')
            lines.append('    models:')
            for model in models:
                lines.extend([
                    f'      - name: "{model["name"]}"',
                    f'        alias: "{model["alias"]}"',
                ])
    return '\n'.join(lines) + '\n'


def rewrite_claude_api_key(config_text: str, entries):
    cleaned = _strip_top_level_block(config_text, 'claude-api-key')
    block = build_claude_api_key_block(entries)
    if not block:
        return cleaned
    return cleaned.rstrip() + '\n\n' + block


def get_configured_provider_models(include_override_only: bool = True):
    provider_aliases = collect_provider_model_aliases()
    detected_providers = collect_detected_providers()
    overrides = _load_model_mapping_overrides()
    all_providers = []
    for provider in detected_providers:
        if provider not in all_providers:
            all_providers.append(provider)
    if include_override_only:
        for provider in overrides.keys():
            if provider not in all_providers:
                all_providers.append(provider)
    items = []
    for provider in all_providers:
        rows = []
        seen = set()
        for model_name, alias in provider_aliases.get(provider, []):
            upstream_value = (model_name or '').strip()
            alias_value = (alias or '').strip()
            if not upstream_value and not alias_value:
                continue
            for mapping in resolve_provider_mappings(provider, upstream_value, alias_value, overrides=overrides):
                if bool(mapping.get('deleted')):
                    continue
                call_id = mapping.get('call_id', '')
                key = (upstream_value, mapping.get('upstream_id', upstream_value), call_id)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    'source_provider': provider,
                    'lookup_upstream_id': upstream_value or alias_value,
                    'target_provider': mapping.get('target_provider', provider),
                    'upstream_id': mapping.get('upstream_id', upstream_value or alias_value),
                    'call_id': call_id,
                })
        for lookup_upstream_id, override_entry in overrides.get(provider, {}).items():
            if not isinstance(override_entry, dict):
                continue
            for mapping_entry in iter_model_mapping_entries(overrides, provider, lookup_upstream_id):
                if bool(mapping_entry.get('deleted')):
                    continue
                target_upstream_id = str(mapping_entry.get('upstream_id') or lookup_upstream_id).strip()
                call_id = str(mapping_entry.get('call_id') or '').strip()
                target_provider = str(mapping_entry.get('provider') or provider).strip().lower() or provider
                key = (str(lookup_upstream_id).strip(), target_upstream_id or lookup_upstream_id, call_id)
                if not (lookup_upstream_id and call_id) or key in seen:
                    continue
                seen.add(key)
                rows.append({
                    'source_provider': provider,
                    'lookup_upstream_id': str(lookup_upstream_id).strip(),
                    'target_provider': target_provider,
                    'upstream_id': target_upstream_id or str(lookup_upstream_id).strip(),
                    'call_id': call_id,
                })
        if not rows:
            continue
        items.append({
            'provider': rows[0].get('target_provider', provider) if rows else provider,
            'lookup_provider': provider,
            'rows': rows,
        })
    return _attach_provider_model_scores(items)


def filter_provider_models_by_runtime(items: list[dict], runtime_model_ids: list[str] | set[str] | tuple[str, ...]):
    runtime_ids = {str(item or '').strip() for item in (runtime_model_ids or []) if str(item or '').strip()}
    if not runtime_ids:
        return []

    annotated_items = annotate_provider_models_runtime(items, runtime_ids)
    filtered_items = []
    for item in annotated_items:
        rows = [dict(row) for row in (item.get('rows') or []) if bool(row.get('runtime_registered'))]
        if rows:
            next_item = dict(item)
            next_item['rows'] = rows
            filtered_items.append(next_item)
    return _attach_provider_model_scores(filtered_items)


def annotate_provider_models_runtime(items: list[dict], runtime_model_ids: list[str] | set[str] | tuple[str, ...]):
    runtime_ids = {str(item or '').strip() for item in (runtime_model_ids or []) if str(item or '').strip()}

    def _provider_row_registered(provider_name: str, call_id: str, upstream_id: str):
        provider_key = _canonical_provider_name(provider_name)
        call_value = str(call_id or '').strip()
        upstream_value = str(upstream_id or '').strip()

        if not runtime_ids:
            return False

        if provider_key == 'antigravity':
            if call_value.startswith('google-antigravity/') and call_value in runtime_ids:
                return True
            if upstream_value.startswith('google-antigravity/') and upstream_value in runtime_ids:
                return True
            if call_value.startswith('antigravity-') and call_value in runtime_ids:
                return True
            return False

        return call_value in runtime_ids or upstream_value in runtime_ids

    annotated = []
    for item in items or []:
        rows = []
        for row in item.get('rows') or []:
            next_row = dict(row)
            call_id = str(next_row.get('call_id') or '').strip()
            upstream_id = str(
                next_row.get('upstream_id')
                or next_row.get('lookup_upstream_id')
                or next_row.get('target_upstream_id')
                or ''
            ).strip()
            provider_name = str(next_row.get('target_provider') or item.get('provider') or item.get('lookup_provider') or '').strip()
            next_row['runtime_registered'] = _provider_row_registered(provider_name, call_id, upstream_id)
            rows.append(next_row)
        next_item = dict(item)
        next_item['rows'] = rows
        annotated.append(next_item)
    return _attach_provider_model_scores(annotated)


def get_configured_aggregate_models():
    provider_items = get_configured_provider_models()
    alias_map = {}
    saved_aliases = _load_aggregate_model_aliases()
    hidden_aliases = _load_hidden_aggregate_aliases()

    def ensure_alias(alias_id: str):
        alias_value = _safe_name(alias_id, '')
        if not alias_value:
            return None
        entry = alias_map.setdefault(alias_value, {
            'alias_id': alias_value,
            'builtin': alias_value in {'auto', 'image', 'agent', 'coder', 'reasoning', 'chat'},
            'members': [],
            'seen': set(),
        })
        return entry

    for item in provider_items:
        source_provider = str(item.get('lookup_provider') or item.get('provider') or '').strip().lower()
        for row in item.get('rows') or []:
            upstream_id = str(row.get('lookup_upstream_id') or row.get('upstream_id') or '').strip()
            runtime_upstream_id = str(row.get('upstream_id') or '').strip()
            call_id = str(row.get('call_id') or '').strip()
            if not source_provider or not upstream_id:
                continue
            global_aliases = derive_global_aggregate_aliases(source_provider, upstream_id, runtime_upstream_id)
            custom_aliases = get_custom_aggregate_aliases_for_model(source_provider, upstream_id)
            for alias_id in list(global_aliases) + list(custom_aliases):
                if alias_id in hidden_aliases:
                    continue
                if alias_id in saved_aliases:
                    continue
                entry = ensure_alias(alias_id)
                if not entry:
                    continue
                key = (source_provider, upstream_id, call_id)
                if key in entry['seen']:
                    continue
                entry['seen'].add(key)
                entry['members'].append({
                    'provider': source_provider,
                    'canonical_provider': _canonical_provider_name(source_provider),
                    'upstream_id': upstream_id,
                    'call_id': call_id,
                    'target_provider': str(row.get('target_provider') or source_provider).strip().lower() or source_provider,
                    'route_kind': _provider_route_kind(source_provider, str(row.get('target_provider') or source_provider).strip().lower() or source_provider),
                    'runtime_upstream_id': runtime_upstream_id or upstream_id,
                    'capability_score': int(row.get('capability_score') or 0),
                    'runtime_registered': bool(row.get('runtime_registered')),
                    'matched_auth_count': int(row.get('matched_auth_count') or 0),
                    'issue_code': str(row.get('issue_code') or '').strip() or None,
                    'issue_message': str(row.get('issue_message') or '').strip() or None,
                })

    for alias_id, members in saved_aliases.items():
        if alias_id in hidden_aliases:
            continue
        entry = ensure_alias(alias_id)
        if not entry:
            continue
        for member in members:
            provider = str(member.get('provider') or '').strip().lower()
            upstream_id = str(member.get('upstream_id') or '').strip()
            if not provider or not upstream_id:
                continue
            mapped = resolve_provider_mapping(provider, upstream_id, upstream_id)
            runtime_upstream_id = normalize_runtime_model_id(
                str(mapped.get('target_provider') or provider).strip(),
                str(mapped.get('upstream_id') or upstream_id).strip(),
            ) or upstream_id
            call_id = str(mapped.get('call_id') or '').strip()
            key = (provider, upstream_id, call_id)
            if key in entry['seen']:
                continue
            entry['seen'].add(key)
            entry['members'].append({
                'provider': provider,
                'canonical_provider': _canonical_provider_name(provider),
                'upstream_id': upstream_id,
                'call_id': call_id,
                'target_provider': str(mapped.get('target_provider') or provider).strip().lower() or provider,
                'route_kind': _provider_route_kind(provider, str(mapped.get('target_provider') or provider).strip().lower() or provider),
                'runtime_upstream_id': runtime_upstream_id,
                'capability_score': max(0, min(100, int(_model_capability_raw_score(provider, upstream_id, call_id)))),
                'runtime_registered': bool(mapped.get('runtime_registered')),
                'matched_auth_count': int(mapped.get('matched_auth_count') or 0),
                'issue_code': str(mapped.get('issue_code') or '').strip() or None,
                'issue_message': str(mapped.get('issue_message') or '').strip() or None,
            })

    for alias_id, entry in alias_map.items():
        saved_members = saved_aliases.get(alias_id) or []
        if not saved_members:
            entry['members'].sort(
                key=lambda item: (
                    -int(item.get('capability_score') or 0),
                    str(item.get('provider') or ''),
                    str(item.get('call_id') or ''),
                )
            )
            continue
        order_map = {
            (str(item.get('provider') or '').strip().lower(), str(item.get('upstream_id') or '').strip()): index
            for index, item in enumerate(saved_members)
            if isinstance(item, dict)
        }
        entry['members'].sort(
            key=lambda item: (
                order_map.get(
                    (
                        str(item.get('provider') or '').strip().lower(),
                        str(item.get('upstream_id') or '').strip(),
                    ),
                    10**9,
                ),
                -int(item.get('capability_score') or 0),
                str(item.get('provider') or ''),
                str(item.get('call_id') or ''),
            )
        )

    result = []
    hidden_aliases = _load_hidden_aggregate_aliases()
    for alias_id in _ordered_aggregate_alias_ids(alias_map, saved_aliases):
        if alias_id in hidden_aliases:
            continue
        entry = alias_map[alias_id]
        result.append({
            'alias_id': alias_id,
            'builtin': bool(entry.get('builtin')),
            'members': entry.get('members') or [],
            'member_count': len(entry.get('members') or []),
        })
    return result


def get_aggregate_route_health(auth_refs: list[str] | None = None):
    from backend.state import load_state
    from backend.tools import get_provider_model_test_state, query_models

    state = load_state()
    selected_refs = [str(ref or '').strip() for ref in (auth_refs if auth_refs is not None else (state.get('selected_auth_refs') or [])) if str(ref or '').strip()]
    if not selected_refs and auth_refs is None and state.get('selected_auth_ref'):
        selected_refs = [str(state.get('selected_auth_ref') or '').strip()]
    preview_auth_refs = selected_refs or None

    provider_models = get_configured_provider_models()
    runtime_model_ids = []
    runtime_loaded = False
    try:
        runtime_query = query_models()
        runtime_body = runtime_query.get('body') if isinstance(runtime_query, dict) else {}
        runtime_items = runtime_body.get('data') if isinstance(runtime_body, dict) else []
        if isinstance(runtime_items, list):
            runtime_model_ids = [
                str(model.get('id') or '').strip()
                for model in runtime_items
                if isinstance(model, dict) and str(model.get('id') or '').strip()
            ]
            runtime_loaded = True
    except Exception:
        runtime_model_ids = []
        runtime_loaded = False

    annotated_provider_models = annotate_provider_models_runtime(provider_models, runtime_model_ids) if runtime_loaded else provider_models
    runtime_lookup = {}
    for item in annotated_provider_models or []:
        lookup_provider = _canonical_provider_name(str(item.get('lookup_provider') or item.get('provider') or '').strip())
        provider_name = _canonical_provider_name(str(item.get('provider') or lookup_provider or '').strip())
        for row in item.get('rows') or []:
            row_provider = _canonical_provider_name(str(row.get('target_provider') or provider_name or lookup_provider or '').strip())
            call_id = str(row.get('call_id') or '').strip()
            upstream_id = str(row.get('upstream_id') or row.get('lookup_upstream_id') or '').strip()
            runtime_upstream_id = str(row.get('runtime_upstream_id') or upstream_id or '').strip()
            registered = bool(row.get('runtime_registered'))
            candidates = [
                (lookup_provider, call_id, upstream_id),
                (lookup_provider, call_id, runtime_upstream_id),
                (row_provider, call_id, upstream_id),
                (row_provider, call_id, runtime_upstream_id),
                (provider_name, call_id, upstream_id),
                (provider_name, call_id, runtime_upstream_id),
            ]
            for key in candidates:
                if not key[0] or not (key[1] or key[2]):
                    continue
                runtime_lookup[key] = registered

    test_state = get_provider_model_test_state()
    test_results = test_state.get('results') if isinstance(test_state, dict) else {}
    aggregate_items = get_configured_aggregate_models()

    def _member_runtime_registered(member: dict):
        provider_name = _canonical_provider_name(str(member.get('provider') or member.get('target_provider') or '').strip())
        target_provider = _canonical_provider_name(str(member.get('target_provider') or provider_name or '').strip())
        call_id = str(member.get('call_id') or '').strip()
        upstream_id = str(member.get('upstream_id') or '').strip()
        runtime_upstream_id = str(member.get('runtime_upstream_id') or upstream_id or '').strip()
        direct_ids = {call_id, upstream_id, runtime_upstream_id}
        if any(model_id and model_id in runtime_model_ids for model_id in direct_ids):
            return True
        candidates = [
            (provider_name, call_id, upstream_id),
            (provider_name, call_id, runtime_upstream_id),
            (target_provider, call_id, upstream_id),
            (target_provider, call_id, runtime_upstream_id),
        ]
        for key in candidates:
            if key in runtime_lookup:
                return bool(runtime_lookup[key])
        return False

    def _member_matched_count(member: dict, route_preview: dict | None):
        if not isinstance(route_preview, dict):
            return 0
        candidate_provider = _canonical_provider_name(str(member.get('provider') or member.get('target_provider') or '').strip())
        target_provider = _canonical_provider_name(str(member.get('target_provider') or candidate_provider or '').strip())
        call_id = str(member.get('call_id') or '').strip()
        upstream_id = str(member.get('upstream_id') or '').strip()
        runtime_upstream_id = str(member.get('runtime_upstream_id') or upstream_id or '').strip()
        matched_auths = route_preview.get('matched_auths') if isinstance(route_preview.get('matched_auths'), list) else []
        count = 0
        for auth_item in matched_auths:
            if not isinstance(auth_item, dict):
                continue
            matches = auth_item.get('matches') if isinstance(auth_item.get('matches'), list) else []
            matched = False
            for match in matches:
                if not isinstance(match, dict):
                    continue
                match_provider = _canonical_provider_name(str(match.get('provider') or '').strip())
                match_call_id = str(match.get('call_id') or '').strip()
                match_upstream_id = str(match.get('upstream_id') or '').strip()
                if call_id and match_call_id == call_id and match_provider in {candidate_provider, target_provider}:
                    matched = True
                    break
                if runtime_upstream_id and match_upstream_id == runtime_upstream_id and match_provider in {candidate_provider, target_provider}:
                    matched = True
                    break
                if upstream_id and match_upstream_id == upstream_id and match_provider in {candidate_provider, target_provider}:
                    matched = True
                    break
            if matched:
                count += 1
        return count

    rows = []
    for aggregate_item in aggregate_items:
        alias_id = str(aggregate_item.get('alias_id') or '').strip()
        members = [dict(member) for member in (aggregate_item.get('members') or [])]
        route_preview = None
        preview_error = ''
        try:
            route_preview = get_model_route_preview(alias_id, auth_refs=preview_auth_refs)
        except Exception as exc:
            preview_error = str(exc)

        enriched_members = []
        available_count = 0
        cooldown_count = 0
        config_only_count = 0
        issue_counts = {}
        issues = []
        for member in members:
            provider_name = str(member.get('provider') or '').strip().lower()
            canonical_provider = _canonical_provider_name(provider_name)
            target_provider = str(member.get('target_provider') or provider_name or '').strip().lower()
            route_kind = str(member.get('route_kind') or _provider_route_kind(provider_name, target_provider)).strip() or 'unknown'
            runtime_registered = bool(member.get('runtime_registered')) or _member_runtime_registered(member)
            matched_auth_count = _member_matched_count(member, route_preview)
            test_result = test_results.get(str(member.get('call_id') or '').strip()) if isinstance(test_results, dict) else None
            test_available = bool(test_result.get('available')) if isinstance(test_result, dict) else None

            issue_code = ''
            issue_message = ''
            if not _is_known_provider_name(provider_name):
                issue_code = 'unknown-provider'
                issue_message = '未知 provider'
            if not runtime_registered:
                issue_code = issue_code or 'config-only'
                issue_message = issue_message or '模型未进入 runtime'
                config_only_count += 1
            elif isinstance(test_result, dict) and test_available is False:
                issue_code = issue_code or 'cooldown'
                issue_message = issue_message or str(test_result.get('message') or '模型处于冷却或失败状态').strip()
                cooldown_count += 1
            elif not matched_auth_count:
                issue_code = issue_code or 'no-auth-match'
                issue_message = issue_message or '没有命中可用认证'
            else:
                available_count += 1

            if canonical_provider != provider_name and not issue_code:
                issue_code = 'canonicalized'
                issue_message = f'provider 规范化为 {canonical_provider}'

            member_row = dict(member)
            member_row.update({
                'provider': provider_name,
                'canonical_provider': canonical_provider,
                'route_kind': route_kind,
                'runtime_registered': runtime_registered,
                'matched_auth_count': matched_auth_count,
                'issue_code': issue_code or None,
                'issue_message': issue_message or None,
            })
            enriched_members.append(member_row)

            if issue_code:
                issue_key = (issue_code, issue_message)
                if issue_key not in issue_counts:
                    issue_counts[issue_key] = True
                    issues.append({
                        'provider': provider_name,
                        'canonical_provider': canonical_provider,
                        'upstream_id': str(member.get('upstream_id') or '').strip(),
                        'call_id': str(member.get('call_id') or '').strip(),
                        'route_kind': route_kind,
                        'issue_code': issue_code,
                        'issue_message': issue_message,
                    })

        blocking_reason = ''
        severity_order = ['config-only', 'unknown-provider', 'no-auth-match', 'cooldown', 'canonicalized']
        if issues:
            for code in severity_order:
                issue = next((item for item in issues if item.get('issue_code') == code), None)
                if issue:
                    blocking_reason = issue.get('issue_message') or code
                    break
            if not blocking_reason:
                blocking_reason = issues[0].get('issue_message') or issues[0].get('issue_code') or ''

        rows.append({
            'alias_id': alias_id,
            'builtin': bool(aggregate_item.get('builtin')),
            'member_count': len(enriched_members),
            'available_count': available_count,
            'cooldown_count': cooldown_count,
            'config_only_count': config_only_count,
            'runtime_registered': alias_id in runtime_model_ids or any(bool(member.get('runtime_registered')) for member in enriched_members),
            'matched_auth_count': sum(int(member.get('matched_auth_count') or 0) for member in enriched_members),
            'blocking_reason': blocking_reason,
            'issues': issues,
            'members': enriched_members,
            'route_preview': route_preview,
            'route_preview_error': preview_error or None,
        })

    rows.sort(key=lambda item: (
        -int(item.get('available_count') or 0),
        -int(item.get('member_count') or 0),
        str(item.get('alias_id') or ''),
    ))
    return {
        'ok': True,
        'runtime_loaded': runtime_loaded,
        'runtime_model_ids': runtime_model_ids,
        'selected_auth_refs': selected_refs,
        'items': rows,
    }


def get_manual_provider_presets():
    configured = {item['provider']: item for item in get_configured_provider_models()}
    providers = sorted(set(list(PROVIDER_BASE_URLS.keys()) + list(configured.keys())))
    items = []
    for provider in providers:
        rows = configured.get(provider, {}).get('rows') or []
        models = []
        seen = set()
        for row in rows:
            value = str(row.get('upstream_id') or row.get('lookup_upstream_id') or '').strip()
            if value and value not in seen:
                seen.add(value)
                models.append(value)
        for preset_name, _alias in PROVIDER_MODEL_ALIASES.get(provider, []):
            value = str(preset_name or '').strip()
            if value and value not in seen:
                seen.add(value)
                models.append(value)
        items.append({
            'provider': provider,
            'base_url': PROVIDER_BASE_URLS.get(provider, ''),
            'models': models,
        })
    return items


def get_model_route_preview(model_id: str, auth_refs: list[str] | None = None):
    model_value = str(model_id or '').strip()
    if not model_value:
        raise ValueError('model_id is required.')

    if auth_refs is None:
        from backend.state import load_state
        state = load_state()
        auth_refs = [ref for ref in (state.get('selected_auth_refs') or []) if ref]
        if not auth_refs and state.get('selected_auth_ref'):
            auth_refs = [state.get('selected_auth_ref')]

    auth_refs = [str(ref or '').strip() for ref in (auth_refs or []) if str(ref or '').strip()]
    auth_items = []
    auth_ref_order = {ref: index for index, ref in enumerate(auth_refs)}
    for auth_ref in auth_refs:
        resolved = resolve_auth_reference(auth_ref=auth_ref)
        if not resolved:
            continue
        source_id, path = resolved
        payload = _read_auth_payload(path)
        item = build_auth_item(source_id, path)
        provider = item.get('provider') or detect_provider(payload, path.name)
        manual_entry = _extract_manual_api_config(payload, path.name)

        candidate_rows = []
        if manual_entry:
            grouped_models = _group_manual_entry_models(manual_entry)
            for target_provider, models in grouped_models.items():
                for model in models:
                    call_id = str(model.get('alias') or '').strip()
                    upstream_id = str(model.get('name') or '').strip()
                    if call_id == model_value:
                        candidate_rows.append({
                            'provider': target_provider,
                            'call_id': call_id,
                            'upstream_id': upstream_id,
                        })
        else:
            alias_map = collect_provider_model_aliases(auth_refs=[auth_ref])
            for upstream_id, alias in alias_map.get(provider, []):
                mapping = resolve_provider_mapping(provider, upstream_id, alias)
                call_id = str(mapping.get('call_id') or '').strip()
                actual_upstream_id = str(mapping.get('upstream_id') or upstream_id).strip()
                runtime_upstream_id = normalize_runtime_model_id(
                    str(mapping.get('target_provider') or provider).strip(),
                    actual_upstream_id,
                )
                candidate_aliases = [call_id]
                for global_alias in derive_global_aggregate_aliases(provider, upstream_id, runtime_upstream_id):
                    if global_alias not in candidate_aliases:
                        candidate_aliases.append(global_alias)
                for custom_alias in get_custom_aggregate_aliases_for_model(provider, upstream_id):
                    if custom_alias not in candidate_aliases:
                        candidate_aliases.append(custom_alias)
                if model_value in candidate_aliases:
                    candidate_rows.append({
                        'provider': str(mapping.get('target_provider') or provider).strip(),
                        'call_id': model_value,
                        'upstream_id': actual_upstream_id,
                    })

        if candidate_rows:
            auth_items.append({
                'auth_ref': item.get('id'),
                'name': item.get('name'),
                'provider': item.get('provider'),
                'email': item.get('email'),
                'account_id': item.get('accountId'),
                'manual': bool(item.get('manual')),
                'key_fingerprint': item.get('keyFingerprint'),
                'matches': candidate_rows,
            })

    aggregate_order = {}
    for aggregate_item in get_configured_aggregate_models():
        if str(aggregate_item.get('alias_id') or '').strip() != model_value:
            continue
        for index, member in enumerate(aggregate_item.get('members') or []):
            aggregate_order[
                (
                    str(member.get('provider') or '').strip().lower(),
                    str(member.get('upstream_id') or '').strip(),
                    str(member.get('call_id') or '').strip(),
                )
            ] = index
        break

    if aggregate_order:
        for auth_item in auth_items:
            auth_item['matches'] = sorted(
                auth_item.get('matches') or [],
                key=lambda row: aggregate_order.get(
                    (
                        str(row.get('provider') or '').strip().lower(),
                        str(row.get('upstream_id') or '').strip(),
                        str(row.get('call_id') or '').strip(),
                    ),
                    10**9,
                ),
            )
        auth_items.sort(
            key=lambda auth_item: min(
                [
                    aggregate_order.get(
                        (
                            str(match.get('provider') or '').strip().lower(),
                            str(match.get('upstream_id') or '').strip(),
                            str(match.get('call_id') or '').strip(),
                        ),
                        10**9,
                    )
                    for match in (auth_item.get('matches') or [])
                ] or [10**9]
            )
        )
    else:
        auth_items.sort(
            key=lambda auth_item: auth_ref_order.get(str(auth_item.get('auth_ref') or '').strip(), 10**9)
        )

    return {
        'model_id': model_value,
        'strategy': 'round-robin',
        'matched_count': len(auth_items),
        'matched_auths': auth_items,
        'resolved': bool(auth_items),
    }


def build_oauth_model_alias_block(providers, auth_refs: list[str] | None = None):
    provider_aliases = collect_provider_model_aliases(auth_refs=auth_refs)
    overrides = _load_model_mapping_overrides()
    unique_providers = []
    for provider in providers or []:
        effective_provider = provider if provider in provider_aliases else 'codex'
        if effective_provider not in unique_providers:
            unique_providers.append(effective_provider)
    if not unique_providers:
        unique_providers = ['codex']
    aggregate_alias_ids = _aggregate_alias_id_set()
    test_results = _load_provider_model_test_results()
    strategy = _current_route_strategy()
    now_ts = int(time.time())

    lines = ['oauth-model-alias:']
    for effective_provider in unique_providers:
        lines.append(f'  {effective_provider}:')
        aggregate_rows = {}
        aggregate_seen = {}
        source_pairs = provider_aliases.get(effective_provider, [])
        if bool(strategy.get('enabled')) and not bool(strategy.get('aggregate_only')):
            source_pairs = _prioritize_provider_alias_pairs(
                effective_provider,
                source_pairs,
                overrides=overrides,
            )
        for model_name, alias in source_pairs:
            for mapping in resolve_provider_mappings(effective_provider, model_name, alias, overrides=overrides):
                if bool(mapping.get('deleted')):
                    continue
                actual_model_name = normalize_runtime_model_id(
                    str(mapping.get('target_provider') or effective_provider).strip(),
                    str(mapping.get('upstream_id', model_name) or model_name).strip(),
                ) or str(mapping.get('upstream_id', model_name) or model_name).strip()
                primary_call_id = str(mapping.get('call_id', '') or '').strip()
                call_ids = [primary_call_id]
                for global_alias in derive_global_aggregate_aliases(effective_provider, model_name, actual_model_name):
                    if global_alias not in call_ids:
                        call_ids.append(global_alias)
                for custom_alias in get_custom_aggregate_aliases_for_model(effective_provider, model_name):
                    if custom_alias not in call_ids:
                        call_ids.append(custom_alias)
                lines.extend([
                    f'    - name: "{actual_model_name}"',
                    f'      alias: "{actual_model_name}"',
                    '      fork: true',
                ])
                for call_id in call_ids:
                    if not call_id:
                        continue
                    alias_is_aggregate = call_id in aggregate_alias_ids
                    if alias_is_aggregate or (bool(strategy.get('enabled')) and not bool(strategy.get('aggregate_only'))):
                        aggregate_rows.setdefault(call_id, [])
                        aggregate_seen.setdefault(call_id, set())
                        if actual_model_name in aggregate_seen[call_id]:
                            continue
                        aggregate_seen[call_id].add(actual_model_name)
                        aggregate_rows[call_id].append({
                            'name': actual_model_name,
                            'alias': call_id,
                            'rank': _model_test_rank(primary_call_id, test_results, now_ts, strategy),
                        })
                    else:
                        lines.extend([
                            f'    - name: "{actual_model_name}"',
                            f'      alias: "{call_id}"',
                            '      fork: true',
                        ])
        for alias_id, rows in aggregate_rows.items():
            rows.sort(key=lambda item: item.get('rank') or (1, 0, 0))
            for row in rows:
                lines.extend([
                    f'    - name: "{row["name"]}"',
                    f'      alias: "{alias_id}"',
                    '      fork: true',
                ])
    return '\n'.join(lines) + '\n'


def rewrite_disable_cooling(config_text: str, disable_cooling: bool):
    cleaned = _strip_top_level_block(config_text, 'disable-cooling').rstrip() + '\n\n'
    return cleaned + f'disable-cooling: {str(bool(disable_cooling)).lower()}\n'


def rewrite_routing_config(config_text: str, strategy: str = 'round-robin', session_affinity: bool = False, session_affinity_ttl: str = '1h'):
    cleaned = _strip_top_level_block(config_text, 'routing').rstrip() + '\n\n'
    block = [
        'routing:',
        f'  strategy: "{strategy}"',
        f'  session-affinity: {str(bool(session_affinity)).lower()}',
        f'  session-affinity-ttl: "{session_affinity_ttl}"',
    ]
    return cleaned + '\n'.join(block) + '\n'


def rewrite_disable_image_generation(config_text: str, mode: str):
    cleaned = _strip_top_level_block(config_text, 'disable-image-generation').rstrip() + '\n\n'
    mode_value = str(mode or 'false').strip().lower()
    if mode_value == 'off':
        yaml_value = 'false'
    elif mode_value == 'all':
        yaml_value = 'true'
    elif mode_value == 'chat':
        yaml_value = '"chat"'
    else:
        yaml_value = 'false'
    return cleaned + f'disable-image-generation: {yaml_value}\n'


def rewrite_workers_and_flags(config_text: str, workers: int = 16, commercial_mode: bool = False, ws_auth: bool = False):
    text = _strip_top_level_block(config_text, 'auth-auto-refresh-workers').rstrip() + '\n\n'
    text = _strip_top_level_block(text, 'commercial-mode').rstrip() + '\n\n'
    text = _strip_top_level_block(text, 'ws-auth').rstrip() + '\n\n'
    lines = [
        f'auth-auto-refresh-workers: {max(1, min(256, int(workers or 16)))}',
        f'commercial-mode: {str(bool(commercial_mode)).lower()}',
        f'ws-auth: {str(bool(ws_auth)).lower()}',
    ]
    return text + '\n'.join(lines) + '\n'


def _yaml_str(value) -> str:
    return f'"{value}"' if value else '""'


def rewrite_amp_config(config_text: str, amp_config: dict | None = None):
    cleaned = _strip_top_level_block(config_text, 'ampcode').rstrip() + '\n\n'
    ac = amp_config or {}
    upstream_url = str(ac.get('upstream_url') or '').strip()
    upstream_api_key = str(ac.get('upstream_api_key') or '').strip()
    restrict_localhost = bool(ac.get('restrict_localhost', True))
    force_mappings = bool(ac.get('force_mappings', False))
    model_mappings = ac.get('model_mappings', [])
    if not isinstance(model_mappings, list):
        model_mappings = []

    lines = ['ampcode:']
    lines.append(f'  upstream-url: {_yaml_str(upstream_url)}')
    if upstream_api_key:
        lines.append(f'  upstream-api-key: {_yaml_str(upstream_api_key)}')
    else:
        lines.append('  upstream-api-key: ""')
    lines.append(f'  restrict-management-to-localhost: {str(restrict_localhost).lower()}')
    lines.append(f'  force-model-mappings: {str(force_mappings).lower()}')
    if model_mappings:
        lines.append('  model-mappings:')
        for m in model_mappings:
            from_val = str(m.get('from') or '').strip()
            to_val = str(m.get('to') or '').strip()
            regex_val = bool(m.get('regex', False))
            lines.append(f'    - from: {_yaml_str(from_val)}')
            lines.append(f'      to: {_yaml_str(to_val)}')
            lines.append(f'      regex: {str(regex_val).lower()}')
    else:
        lines.append('  model-mappings: []')
    return cleaned + '\n'.join(lines) + '\n'


def rewrite_oauth_model_aliases(config_text: str, providers, auth_refs: list[str] | None = None):
    cleaned = _strip_top_level_block(config_text, 'oauth-model-alias').rstrip() + '\n\n'
    return cleaned + build_oauth_model_alias_block(providers, auth_refs=auth_refs)


def delete_auth_entries(auth_refs: list[str]) -> dict:
    refs = []
    for auth_ref in auth_refs or []:
        ref = str(auth_ref or '').strip()
        if ref and ref not in refs:
            refs.append(ref)
    if not refs:
        raise ValueError('No auth refs provided.')

    deleted = []
    missing = []
    for auth_ref in refs:
        resolved = resolve_auth_reference(auth_ref=auth_ref)
        if not resolved:
            missing.append(auth_ref)
            continue
        _, source = resolved
        if not source.exists() or not source.is_file():
            missing.append(auth_ref)
            continue
        source.unlink()
        deleted.append(auth_ref)

    return {
        'deleted_auth_refs': deleted,
        'missing_auth_refs': missing,
    }


def build_runtime_config(
    selected_auth_refs: list[str] | None = None,
    selected_auth_ref: str | None = None,
    selected_auth_name: str | None = None,
    bind_host: str = '127.0.0.1',
    access_api_keys: list[str] | None = None,
    state: dict | None = None,
):
    _ = selected_auth_refs
    _ = selected_auth_ref
    _ = selected_auth_name
    current_state = state or load_state()
    refs: list[str] = []
    providers = []
    copied = []
    openai_compat_entries = []
    claude_compat_entries = []

    active_auth_entries = []
    for active_path in _iter_pool_auth_json_files():
            payload = _read_auth_payload(active_path)
            if not isinstance(payload, dict):
                continue
            compat_entry = _extract_manual_api_config(payload, active_path.name)
            if compat_entry:
                provider_key = str(compat_entry.get('provider') or '').strip().lower()
                if provider_key and provider_key not in providers:
                    providers.append(provider_key)
                if compat_entry.get('api') == 'anthropic-messages':
                    claude_compat_entries.append(compat_entry)
                else:
                    openai_compat_entries.append(compat_entry)
                continue
            provider = detect_provider(payload, active_path.name)
            auth_kind = _detect_auth_payload_kind(payload)
            active_auth_entries.append({
                'source': active_path,
                'source_name': active_path.name,
                'provider': provider,
                'auth_kind': auth_kind,
            })
            if provider not in providers:
                providers.append(provider)

    if not openai_compat_entries and not claude_compat_entries and not active_auth_entries:
        raise FileNotFoundError('No auth JSON files found in storage/auth. Put account files under storage/auth/<provider>/ first.')

    config_text = BASE_CONFIG.read_text(encoding='utf-8', errors='ignore')
    runtime_text = rewrite_host(config_text, bind_host)
    runtime_text = rewrite_auth_dir(runtime_text, POOL_AUTH_DIR)

    # Merge admin access keys with all active virtual API keys
    all_api_keys = list(access_api_keys or ['cliproxyapi'])
    try:
        from backend.api_keys import get_all_active_key_values
        virtual_key_values = get_all_active_key_values()
        for vk in virtual_key_values:
            if vk and vk not in all_api_keys:
                all_api_keys.append(vk)
    except Exception:
        pass
    runtime_text = rewrite_api_keys(runtime_text, all_api_keys)

    runtime_text = rewrite_request_log(runtime_text, False)
    runtime_text = rewrite_oauth_model_aliases(runtime_text, providers, auth_refs=None)
    runtime_text = rewrite_claude_api_key(runtime_text, claude_compat_entries)
    runtime_text = rewrite_openai_compatibility(runtime_text, openai_compat_entries)

    # New advanced config rewrites
    runtime_text = rewrite_disable_cooling(runtime_text, current_state.get('disable_cooling', False))
    runtime_text = rewrite_routing_config(
        runtime_text,
        strategy=current_state.get('route_strategy', {}).get('enabled', True) and 'round-robin' or 'round-robin',
        session_affinity=current_state.get('session_affinity_enabled', False),
        session_affinity_ttl=current_state.get('session_affinity_ttl', '1h'),
    )
    runtime_text = rewrite_disable_image_generation(runtime_text, current_state.get('disable_image_generation', 'off'))
    runtime_text = rewrite_workers_and_flags(
        runtime_text,
        workers=current_state.get('auth_auto_refresh_workers', 16),
        commercial_mode=current_state.get('commercial_mode', False),
        ws_auth=current_state.get('ws_auth', False),
    )
    amp_config = current_state.get('amp_config')
    if isinstance(amp_config, dict):
        runtime_text = rewrite_amp_config(runtime_text, amp_config)
    else:
        runtime_text = rewrite_amp_config(runtime_text, {})
    validation_refs = None
    validation_issues = _runtime_config_validation_issues(runtime_text, providers, validation_refs)
    if validation_issues:
        raise ValueError('Runtime config validation failed: ' + '; '.join(validation_issues))

    POOL_AUTH_DIR.mkdir(parents=True, exist_ok=True)

    RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temp_runtime_config = RUNTIME_CONFIG.with_suffix(RUNTIME_CONFIG.suffix + '.tmp') if RUNTIME_CONFIG.suffix else RUNTIME_CONFIG.with_name(RUNTIME_CONFIG.name + '.tmp')
    temp_runtime_config.write_text(runtime_text, encoding='utf-8')
    written_text = temp_runtime_config.read_text(encoding='utf-8', errors='ignore')
    if written_text != runtime_text:
        try:
            temp_runtime_config.unlink()
        except Exception:
            pass
        raise ValueError('Runtime config validation failed: temporary file contents do not match the generated config.')
    temp_runtime_config.replace(RUNTIME_CONFIG)
    return copied


def rebuild_runtime_config_from_state(state: dict | None = None):
    current_state = state or load_state()
    has_active_auth_files = any(True for _ in _iter_pool_auth_json_files())
    if not has_active_auth_files:
        return {'rebuilt': False, 'reason': 'no_auth_files', 'validation': {'ok': False, 'issues': ['no auth files in storage/auth'], 'message': 'No auth JSON files found in storage/auth.'}}
    try:
        copied = build_runtime_config(
            bind_host=get_proxy_bind_host(current_state),
            access_api_keys=[get_proxy_api_key(current_state)],
            state=current_state,
        )
    except Exception as exc:
        return {
            'rebuilt': False,
            'reason': 'validation_failed',
            'error': str(exc),
            'runtime_config': str(RUNTIME_CONFIG),
            'validation': {'ok': False, 'issues': [str(exc)], 'message': str(exc)},
        }
    return {'rebuilt': True, 'runtime_config': str(RUNTIME_CONFIG), 'copied_auth_count': len(copied), 'validation': {'ok': True, 'issues': [], 'message': 'Runtime config rebuilt successfully.'}}


def _safe_name(text: str, fallback='entry'):
    base = re.sub(r'[^a-zA-Z0-9._-]+', '-', (text or '').strip()).strip('-._')
    return base[:64] or fallback


def create_manual_auth_bundle_entry(
    base_url: str,
    models: list[str],
    api_key: str,
    provider: str | None = None,
    remark: str | None = None,
    headers: dict | None = None,
    api: str | None = None,
    metadata_extra: dict | None = None,
):
    base_url = (base_url or '').strip()
    api_key = (api_key or '').strip()
    explicit_provider = (provider or '').strip()
    models = [str(item or '').strip() for item in (models or []) if str(item or '').strip()]

    if explicit_provider and not base_url:
        base_url = PROVIDER_BASE_URLS.get(explicit_provider.strip().lower(), '')

    if not base_url or not models or not api_key:
        raise ValueError('base_url, models, and api_key are required.')

    parsed = urlparse(base_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('base_url must be a valid http/https URL.')

    if len(api_key) > 1024:
        raise ValueError('api_key is too long.')

    for model in models:
        if len(model) > 200:
            raise ValueError('model is too long.')

    detected_provider = detect_provider_from_manual_input(base_url, models[0], explicit_provider)
    models = [normalize_provider_model_id(detected_provider, item) for item in models]
    models = [item for item in models if item]
    header_values = {}
    if isinstance(headers, dict):
        header_values = {str(k): str(v) for k, v in headers.items() if str(k).strip()}

    save_dir = _manual_auth_save_dir(detected_provider)
    save_dir.mkdir(parents=True, exist_ok=True)
    host_token = _safe_name(parsed.hostname or 'host', 'host')
    provider_token = _safe_name(detected_provider, 'provider')
    ts = int(time.time() * 1000)
    file_name = f'{provider_token}-{host_token}-{ts}.json'
    save_path = save_dir / file_name

    metadata = {
        'remark': (remark or '').strip() or f'manual-entry:{detected_provider}',
        'captured_at': int(time.time()),
        'source': 'dashboard_manual_entry',
    }
    if isinstance(metadata_extra, dict):
        metadata.update(metadata_extra)

    payload = {
        'metadata': metadata,
        'content': {
            'type': 'api_key',
            'provider': detected_provider,
            'base_url': base_url.rstrip('/'),
            'model': models[0],
            'api_key': api_key,
            'models': models,
        },
    }
    if api:
        payload['content']['api'] = str(api).strip()
    if header_values:
        payload['content']['headers'] = header_values

    _write_manual_auth_payload(save_path, payload)
    item = build_auth_item('default', save_path)
    item['manual'] = True
    item['modelCount'] = len(models)
    item['models'] = list(models)
    return item


def create_manual_auth_entry(base_url: str, model: str, api_key: str, provider: str | None = None, remark: str | None = None):
    return create_manual_auth_bundle_entry(
        base_url=base_url,
        models=[model],
        api_key=api_key,
        provider=provider,
        remark=remark,
    )


def import_openclaw_provider(provider_id: str):
    provider_id = str(provider_id or '').strip()
    if not provider_id:
        raise ValueError('provider_id is required.')
    if not OPENCLAW_CONFIG_PATH.exists():
        raise FileNotFoundError(f'OpenClaw config not found: {OPENCLAW_CONFIG_PATH}')

    payload = _read_auth_payload(OPENCLAW_CONFIG_PATH)
    if not isinstance(payload, dict):
        raise ValueError('OpenClaw config is invalid.')

    providers = payload.get('models', {}).get('providers', {})
    if not isinstance(providers, dict):
        raise ValueError('OpenClaw config does not contain provider models.')

    provider_config = providers.get(provider_id)
    if not isinstance(provider_config, dict):
        raise FileNotFoundError(f'Provider not found in OpenClaw config: {provider_id}')

    base_url = str(provider_config.get('baseUrl') or '').strip()
    api_key = str(provider_config.get('apiKey') or '').strip()
    models = _extract_model_ids_from_provider_config(provider_config)
    headers = provider_config.get('headers') if isinstance(provider_config.get('headers'), dict) else {}

    if not base_url or not api_key or not models:
        raise ValueError(f'Provider {provider_id} is incomplete in OpenClaw config.')

    return create_manual_auth_bundle_entry(
        base_url=base_url,
        models=models,
        api_key=api_key,
        provider=provider_id,
        remark=f'imported-from-openclaw:{provider_id}',
        headers=headers,
        api=str(provider_config.get('api') or '').strip(),
        metadata_extra={
            'source': 'openclaw_config_import',
            'source_path': str(OPENCLAW_CONFIG_PATH),
            'provider_id': provider_id,
        },
    )
