import json
import time
from pathlib import Path
from typing import Any

from backend.paths import MODEL_THINKING_CONFIGS_FILE


THINKING_MODE_DEFAULT = 'default'
THINKING_MODE_FORCE_ON = 'force_on'
THINKING_MODE_FORCE_OFF = 'force_off'
VALID_MODES = (THINKING_MODE_DEFAULT, THINKING_MODE_FORCE_ON, THINKING_MODE_FORCE_OFF)

REASONING_EFFORT_LEVELS = ('', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')

LEVELS_PRESET_STANDARD_3 = ('low', 'medium', 'high')
LEVELS_PRESET_EXTENDED_5 = ('low', 'medium', 'high', 'xhigh', 'max')
LEVELS_PRESET_FULL_6 = ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')

# Heuristic tokens that identify models likely to support reasoning/thinking.
THINKING_HINT_TOKENS = (
    'thinking',
    'reasoning',
    'reasoner',
    'kimi-k2-thinking',
    'claude-opus-4-6-thinking',
    'claude-sonnet-4-5-thinking',
    'gemini-2.5-flash-thinking',
    'glm-4.1v-thinking',
    'glm-4.1v-thinking-flash',
    'glm-4',
    'hunyuan-2.0-thinking',
    'step-3.5-flash',
    'step-3',
    'agnes-2.0-flash',
    # OpenAI Reasoning models
    'o1-',
    'o3-',
    'o4-',
    'o1',
    'o3',
    'o4',
    'o1-mini',
    'o1-preview',
    # GPT 5.x series
    'gpt-5.6',
    'gpt-5.5',
    'gpt-5',
    'sol',
    'terra',
    'luna',
    # DeepSeek Reasoning / R1 models
    '-r1',
    'deepseek-r',
    'deepseek-reasoner',
    'r1',
    # Qwen reasoning
    'qwq',
    'qwen-max-thinking',
    # Newer reasoning-capable versions
    'claude-3-7',
    'claude-3.7',
    'gemini-2.5',
    'grok-3',
    'kimi-k2',
)


def _ensure_config_file() -> None:
    MODEL_THINKING_CONFIGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not MODEL_THINKING_CONFIGS_FILE.exists():
        MODEL_THINKING_CONFIGS_FILE.write_text(
            json.dumps(_default_config(), ensure_ascii=False, indent=2),
            encoding='utf-8',
        )


def _default_config() -> dict:
    return {
        'version': 1,
        'updated_at': int(time.time()),
        'configs': {},
    }


def load_model_thinking_configs() -> dict:
    """Load persisted model thinking/reasoning configurations."""
    _ensure_config_file()
    try:
        raw = MODEL_THINKING_CONFIGS_FILE.read_text(encoding='utf-8')
        payload = json.loads(raw) if raw.strip() else _default_config()
    except Exception:
        payload = _default_config()
    if not isinstance(payload, dict):
        payload = _default_config()
    payload.setdefault('version', 1)
    payload.setdefault('updated_at', 0)
    payload.setdefault('configs', {})
    if not isinstance(payload['configs'], dict):
        payload['configs'] = {}
    return payload


def save_model_thinking_configs(payload: dict) -> dict:
    """Validate and persist model thinking/reasoning configurations."""
    if not isinstance(payload, dict):
        raise ValueError('Payload must be an object.')
    configs = payload.get('configs')
    if not isinstance(configs, dict):
        raise ValueError('configs must be an object.')

    cleaned: dict[str, dict[str, Any]] = {}
    for model_id, item in configs.items():
        model_id = str(model_id or '').strip()
        if not model_id:
            continue
        if not isinstance(item, dict):
            continue
        mode = str(item.get('mode') or THINKING_MODE_DEFAULT).strip().lower()
        if mode not in VALID_MODES:
            mode = THINKING_MODE_DEFAULT

        effort = str(item.get('reasoning_effort') or '').strip().lower()
        if effort not in REASONING_EFFORT_LEVELS[1:]:
            effort = ''

        budget_raw = item.get('thinking_budget')
        budget = None
        if budget_raw is not None and budget_raw != '':
            try:
                budget = int(budget_raw)
            except (TypeError, ValueError):
                budget = None

        levels_raw = item.get('thinking_levels')
        thinking_levels = None
        if isinstance(levels_raw, str):
            levels_list = [x.strip() for x in levels_raw.split(',') if x.strip()]
            thinking_levels = []
            for lvl in levels_list:
                token = str(lvl or '').strip().lower()
                if token and token not in thinking_levels:
                    thinking_levels.append(token)
        elif isinstance(levels_raw, (list, tuple)):
            thinking_levels = []
            for lvl in levels_raw:
                token = str(lvl or '').strip().lower()
                if token and token not in thinking_levels:
                    thinking_levels.append(token)

        entry = {
            'mode': mode,
            'provider': str(item.get('provider') or '').strip() or None,
            'upstream_id': str(item.get('upstream_id') or '').strip() or None,
            'reasoning_effort': effort or None,
            'thinking_budget': budget,
            'thinking_levels': thinking_levels,
        }
        # Only keep entries that actually change something from the default or have explicit settings.
        if (
            mode != THINKING_MODE_DEFAULT
            or entry['reasoning_effort']
            or entry['thinking_budget'] is not None
            or entry['thinking_levels'] is not None
        ):
            cleaned[model_id] = entry

    result = {
        'version': 1,
        'updated_at': int(time.time()),
        'configs': cleaned,
    }
    _ensure_config_file()
    MODEL_THINKING_CONFIGS_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return result


def looks_thinking_capable(model_id: str, upstream_id: str = '', provider: str = '') -> bool:
    """Heuristic to decide whether a model likely supports thinking/reasoning."""
    text = ' '.join([
        str(model_id or '').lower(),
        str(upstream_id or '').lower(),
        str(provider or '').lower(),
    ])
    return any(token in text for token in THINKING_HINT_TOKENS)


def get_model_thinking_config(model_id: str) -> dict | None:
    """Return a single model's thinking config, or None if using default."""
    payload = load_model_thinking_configs()
    return payload['configs'].get(str(model_id or '').strip())


def collect_thinking_candidates() -> list[dict]:
    """Collect all provider and aggregate models categorized by provider with effective thinking levels."""
    from backend.auth import (
        get_configured_provider_models,
        get_configured_aggregate_models,
        _openai_compat_thinking_levels,
    )

    candidates: dict[str, dict] = {}

    def add(model_id: str, provider: str, upstream_id: str, source: str):
        model_id = str(model_id or '').strip()
        if not model_id:
            return
        key = model_id.lower()
        effective = (
            _openai_compat_thinking_levels(upstream_id)
            or _openai_compat_thinking_levels(model_id)
            or ()
        )
        existing = candidates.get(key)
        if existing:
            existing['sources'].add(source)
            if provider and existing.get('provider') in ('', '-', 'custom', '其他/自定义'):
                existing['provider'] = provider
            if upstream_id and not existing.get('upstream_id'):
                existing['upstream_id'] = upstream_id
            if effective and not existing.get('effective_levels'):
                existing['effective_levels'] = list(effective)
            return
        candidates[key] = {
            'model_id': model_id,
            'provider': str(provider or '').strip() or '其他/自定义',
            'upstream_id': str(upstream_id or '').strip(),
            'sources': {str(source or '').strip()},
            'effective_levels': list(effective),
            'thinking_hint': looks_thinking_capable(model_id, upstream_id, provider),
        }

    for item in get_configured_provider_models(include_override_only=False):
        provider = str(item.get('lookup_provider') or item.get('provider') or '').strip().lower()
        for row in item.get('rows') or []:
            call_id = str(row.get('call_id') or '').strip()
            upstream_id = str(row.get('upstream_id') or '').strip()
            if call_id:
                add(call_id, provider, upstream_id, 'provider')
            if upstream_id and upstream_id != call_id:
                add(upstream_id, provider, upstream_id, 'provider')

    for aggregate in get_configured_aggregate_models():
        alias_id = str(aggregate.get('alias_id') or '').strip()
        if alias_id:
            add(alias_id, 'aggregate', '', 'aggregate')
        for member in aggregate.get('members') or []:
            member_provider = str(member.get('provider') or '').strip().lower()
            member_upstream = str(member.get('upstream_id') or '').strip()
            member_call = str(member.get('call_id') or '').strip()
            if member_call:
                add(member_call, member_provider or 'aggregate', member_upstream, f'aggregate:{alias_id}')
            if member_upstream and member_upstream != member_call:
                add(member_upstream, member_provider or 'aggregate', member_upstream, f'aggregate:{alias_id}')

    result = sorted(candidates.values(), key=lambda x: (x['provider'], x['model_id']))
    for item in result:
        item['sources'] = sorted(item['sources'])
    return result


_cached_all_models = None
_cached_all_models_time = 0.0


def collect_all_configured_models() -> list[str]:
    """Collect all provider and aggregate model IDs currently configured."""
    global _cached_all_models, _cached_all_models_time
    now = time.time()
    if _cached_all_models is not None and (now - _cached_all_models_time) < 3.0:
        return _cached_all_models

    from backend.auth import get_configured_provider_models, get_configured_aggregate_models

    models = set()

    for item in get_configured_provider_models(include_override_only=False):
        for row in item.get('rows') or []:
            call_id = str(row.get('call_id') or '').strip()
            upstream_id = str(row.get('upstream_id') or '').strip()
            if call_id:
                models.add(call_id)
            if upstream_id:
                models.add(upstream_id)

    for aggregate in get_configured_aggregate_models():
        alias_id = str(aggregate.get('alias_id') or '').strip()
        if alias_id:
            models.add(alias_id)
        for member in aggregate.get('members') or []:
            member_upstream = str(member.get('upstream_id') or '').strip()
            member_call = str(member.get('call_id') or '').strip()
            if member_call:
                models.add(member_call)
            if member_upstream:
                models.add(member_upstream)

    res = sorted(list(models), key=lambda s: s.lower())
    _cached_all_models = res
    _cached_all_models_time = now
    return res
