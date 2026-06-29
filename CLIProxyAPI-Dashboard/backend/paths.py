import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from backend.runtime_env import resolve_cli_binary, runtime_variant

DASHBOARD_ROOT = Path(os.environ.get('RELAYX_DASHBOARD_ROOT', '')).resolve() if os.environ.get('RELAYX_DASHBOARD_ROOT') else Path(__file__).resolve().parent.parent

# PyInstaller 6+ may place bundled files inside _internal/ subdirectory
if not (DASHBOARD_ROOT / 'index.html').exists():
    _internal = DASHBOARD_ROOT / '_internal'
    if _internal.is_dir() and (_internal / 'index.html').exists():
        DASHBOARD_ROOT = _internal

ROOT = DASHBOARD_ROOT


def _load_dotenv():
    env_file = DASHBOARD_ROOT / '.env'
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding='utf-8').splitlines():
        text = line.strip()
        if not text or text.startswith('#') or '=' not in text:
            continue
        key, value = text.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_proxy_root() -> Path:
    for key in ('CLIPROXYAPI_ROOT', 'RELAYX_CLIPROXYAPI_ROOT'):
        raw = os.environ.get(key, '').strip()
        if raw:
            return Path(raw).expanduser()
    sibling = DASHBOARD_ROOT.parent / 'CLIProxyAPI'
    return sibling


_load_dotenv()

# CLIProxyAPI proxy project root (sibling repo by default)
PROXY_ROOT = _resolve_proxy_root()
ROOT_DIR = PROXY_ROOT
PROJECT_ROOT = PROXY_ROOT
APP_DIR = PROXY_ROOT

LEGACY_DEV_ROOT = DASHBOARD_ROOT.parent / 'CLIProxyAPI_dev'
LEGACY_APP_DIR = LEGACY_DEV_ROOT / 'app'
LEGACY_INTERFACES_DIR = LEGACY_APP_DIR / 'interfaces'

STORAGE_DIR = PROXY_ROOT / 'storage'

CONFIG_DIR = STORAGE_DIR / 'config'
AUTH_DIR = STORAGE_DIR / 'auth'
POOL_AUTH_DIR = AUTH_DIR
AUTH_ARCHIVE_DIR = AUTH_DIR / 'archive'
LEGACY_AUTH_SOURCES_DIR = AUTH_DIR / 'sources'
MODELS_DIR = STORAGE_DIR / 'models'
RUNTIME_DIR = STORAGE_DIR / 'runtime'
CACHE_DIR = STORAGE_DIR / 'cache'
LOGS_DIR = STORAGE_DIR / 'logs'
BACKUPS_DIR = STORAGE_DIR / 'backups'
TEMP_DIR = RUNTIME_DIR / 'tmp'

LEGACY_AUTH_MANAGEMENT_DIR = LEGACY_INTERFACES_DIR / 'auth-management'
LEGACY_DASHBOARD_DIR = LEGACY_INTERFACES_DIR / 'dashboard-panel'
LEGACY_RUNTIME_DIR = LEGACY_DASHBOARD_DIR / 'runtime'
LEGACY_BASE_CONFIG = LEGACY_AUTH_MANAGEMENT_DIR / 'cliproxyapi-codex-config.yaml'
LEGACY_SOURCE_AUTH_DIR = LEGACY_AUTH_MANAGEMENT_DIR / 'cliproxyapi-auth'
LEGACY_QUOTA_CACHE_FILE = Path(r'E:\U_App\oauth-manager\quota_cache.json')
LEGACY_AUTH_SOURCE_DIRS = {
    'default': LEGACY_SOURCE_AUTH_DIR,
    'longcat': Path(r'E:\U_App\oauth-manager\accounts\longcat'),
    'zhipu': Path(r'E:\U_App\oauth-manager\accounts\zhipu'),
    'aihubmix': Path(r'E:\U_App\oauth-manager\accounts\aihubmix'),
}

CLI_EXE = resolve_cli_binary(PROXY_ROOT)
RUNTIME_VARIANT = runtime_variant()

BASE_CONFIG = CONFIG_DIR / 'base-config.yaml'
SOURCES_CONFIG_FILE = CONFIG_DIR / 'sources.json'
SOURCE_AUTH_DIR = AUTH_DIR
MANUAL_AUTH_SAVE_DIR = AUTH_DIR

ACTIVE_AUTH_DIR = RUNTIME_DIR / 'active-auth'
STATE_FILE = RUNTIME_DIR / 'state.json'
MODEL_MAPPING_OVERRIDES_FILE = MODELS_DIR / 'provider_model_overrides.json'
AGGREGATE_MODEL_ALIASES_FILE = MODELS_DIR / 'aggregate_model_aliases.json'
PROVIDER_MODEL_TEST_STATE_FILE = MODELS_DIR / 'provider_model_test_state.json'
MODEL_PROXY_SETTINGS_FILE = MODELS_DIR / 'model_proxy_settings.json'
QUOTA_CACHE_FILE = CACHE_DIR / 'quota_cache.json'

DEVICE_LOGIN_STDOUT = LOGS_DIR / 'device-login.stdout.log'
DEVICE_LOGIN_STDERR = LOGS_DIR / 'device-login.stderr.log'
PROXY_STDOUT = LOGS_DIR / 'proxy.stdout.log'
PROXY_STDERR = LOGS_DIR / 'proxy.stderr.log'
RUNTIME_CONFIG = RUNTIME_DIR / 'cliproxyapi-active-config.yaml'
REQUEST_LOG_DIR = LOGS_DIR / 'request_logs'
REQUEST_ARCHIVE_DIR = LOGS_DIR / 'request_archive'
TOOL_LOGS_DIR = LOGS_DIR / 'tool_logs'

IGNORED_AUTH_SOURCE_DIRS = {'_archive', 'archive', 'backups', 'logs', 'sources'}


def _copy_file_if_missing(source: Path, target: Path, manifest: list[dict]):
    if not source.exists() or not source.is_file() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    manifest.append({'kind': 'file', 'source': str(source), 'target': str(target)})


def _copy_dir_if_missing(source: Path, target: Path, manifest: list[dict]):
    if not source.exists() or not source.is_dir() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    manifest.append({'kind': 'dir', 'source': str(source), 'target': str(target)})


def _write_migration_manifest(manifest: list[dict]):
    if not manifest:
        return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    manifest_path = BACKUPS_DIR / f'migration-{stamp}.json'
    manifest_path.write_text(
        json.dumps(
            {
                'created_at': datetime.now().isoformat(timespec='seconds'),
                'root_dir': str(ROOT_DIR),
                'app_dir': str(APP_DIR),
                'storage_dir': str(STORAGE_DIR),
                'items': manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding='utf-8',
    )


def _default_sources_config():
    payload = {}
    for source_dir in sorted(AUTH_DIR.iterdir(), key=lambda path: path.name.lower()) if AUTH_DIR.exists() else []:
        if not source_dir.is_dir():
            continue
        source_id = source_dir.name.strip().lower()
        if not source_id or source_id in IGNORED_AUTH_SOURCE_DIRS:
            continue
        if not any(path.is_file() for path in source_dir.rglob('*.json')):
            continue
        payload[source_id] = str(source_dir)
    return payload


def _ensure_sources_config():
    SOURCES_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOURCES_CONFIG_FILE.write_text(
        json.dumps(_default_sources_config(), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _migrate_storage_layout():
    manifest: list[dict] = []
    auth_storage_initialized = SOURCES_CONFIG_FILE.exists()
    if not auth_storage_initialized and AUTH_DIR.exists():
        auth_storage_initialized = any(
            provider_dir.is_dir()
            and provider_dir.name.strip().lower() not in IGNORED_AUTH_SOURCE_DIRS
            and any(path.is_file() for path in provider_dir.rglob('*.json'))
            for provider_dir in sorted(AUTH_DIR.iterdir(), key=lambda path: path.name.lower())
        )

    _copy_file_if_missing(LEGACY_BASE_CONFIG, BASE_CONFIG, manifest)

    if not auth_storage_initialized:
        _copy_dir_if_missing(LEGACY_SOURCE_AUTH_DIR, LEGACY_AUTH_SOURCES_DIR / 'default', manifest)

        for source_id, source_dir in LEGACY_AUTH_SOURCE_DIRS.items():
            if source_id == 'default':
                continue
            _copy_dir_if_missing(source_dir, LEGACY_AUTH_SOURCES_DIR / source_id, manifest)

    _copy_dir_if_missing(LEGACY_RUNTIME_DIR / 'active-auth', ACTIVE_AUTH_DIR, manifest)
    _copy_file_if_missing(LEGACY_RUNTIME_DIR / 'state.json', STATE_FILE, manifest)
    _copy_file_if_missing(LEGACY_RUNTIME_DIR / 'cliproxyapi-active-config.yaml', RUNTIME_CONFIG, manifest)
    _copy_file_if_missing(LEGACY_RUNTIME_DIR / 'provider_model_overrides.json', MODEL_MAPPING_OVERRIDES_FILE, manifest)
    _copy_file_if_missing(LEGACY_RUNTIME_DIR / 'aggregate_model_aliases.json', AGGREGATE_MODEL_ALIASES_FILE, manifest)
    _copy_file_if_missing(LEGACY_RUNTIME_DIR / 'provider_model_test_state.json', PROVIDER_MODEL_TEST_STATE_FILE, manifest)
    _copy_dir_if_missing(LEGACY_RUNTIME_DIR / 'backups', BACKUPS_DIR, manifest)
    _copy_dir_if_missing(LEGACY_RUNTIME_DIR / 'tool_logs', TOOL_LOGS_DIR, manifest)

    for source_name, target_path in (
        ('device-login.stdout.log', DEVICE_LOGIN_STDOUT),
        ('device-login.stderr.log', DEVICE_LOGIN_STDERR),
        ('proxy.stdout.log', PROXY_STDOUT),
        ('proxy.stderr.log', PROXY_STDERR),
    ):
        _copy_file_if_missing(LEGACY_RUNTIME_DIR / source_name, target_path, manifest)

    _copy_file_if_missing(LEGACY_QUOTA_CACHE_FILE, QUOTA_CACHE_FILE, manifest)

    _write_migration_manifest(manifest)


def _merge_dir_contents(source: Path, target: Path):
    if not source.exists() or not source.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda path: path.name.lower()):
        destination = target / item.name
        if item.is_dir():
            _merge_dir_contents(item, destination)
        else:
            if destination.exists():
                continue
            shutil.move(str(item), str(destination))
    try:
        source.rmdir()
    except Exception:
        pass


def _archive_auth_metadata(source: Path, provider_name: str):
    if not source.exists() or source.suffix.lower() == '.json':
        return
    archive_target = AUTH_ARCHIVE_DIR / 'default' / 'metadata' / provider_name.lower()
    archive_target.mkdir(parents=True, exist_ok=True)
    destination = archive_target / source.name
    if destination.exists():
        try:
            source.unlink()
        except Exception:
            pass
        return
    shutil.move(str(source), str(destination))


def _move_auth_json_files(source: Path, target: Path, provider_name: str):
    if not source.exists() or not source.is_dir():
        return
    target.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda path: path.name.lower()):
        if item.is_dir():
            _move_auth_json_files(item, target, provider_name)
            try:
                item.rmdir()
            except Exception:
                pass
            continue
        if item.suffix.lower() == '.json':
            destination = target / item.name
            if destination.exists():
                try:
                    item.unlink()
                except Exception:
                    pass
                continue
            shutil.move(str(item), str(destination))
            continue
        _archive_auth_metadata(item, provider_name)
    try:
        source.rmdir()
    except Exception:
        pass


def _clean_provider_directory(provider_dir: Path):
    provider_name = provider_dir.name.lower()
    bak_target = AUTH_ARCHIVE_DIR / 'default' / 'bak-files' / provider_name
    bak_target.mkdir(parents=True, exist_ok=True)
    for item in sorted(provider_dir.iterdir(), key=lambda path: path.name.lower()):
        if item.is_dir():
            _move_auth_json_files(item, provider_dir, provider_name)
            continue
        if item.suffix.lower() == '.bak':
            destination = bak_target / item.name
            if not destination.exists():
                shutil.move(str(item), str(destination))
            continue
        if item.suffix.lower() != '.json':
            _archive_auth_metadata(item, provider_name)


def _normalize_auth_layout():
    if not LEGACY_AUTH_SOURCES_DIR.exists() or SOURCES_CONFIG_FILE.exists():
        for provider_dir in sorted(AUTH_DIR.iterdir(), key=lambda path: path.name.lower()):
            if not provider_dir.is_dir() or provider_dir.name.lower() in IGNORED_AUTH_SOURCE_DIRS:
                continue
            _clean_provider_directory(provider_dir)
        return

    default_dir = LEGACY_AUTH_SOURCES_DIR / 'default'
    oauth_dir = default_dir / 'oauth'
    api_dir = default_dir / 'api'
    accounts_dir = default_dir / 'accounts'
    providers_dir = default_dir / 'providers'
    archive_dir = default_dir / '_archive'

    if oauth_dir.exists():
        for provider_dir in oauth_dir.iterdir():
            if provider_dir.is_dir():
                _merge_dir_contents(provider_dir, AUTH_DIR / provider_dir.name)
    if api_dir.exists():
        for provider_dir in api_dir.iterdir():
            if provider_dir.is_dir():
                _merge_dir_contents(provider_dir, AUTH_DIR / provider_dir.name)
    if accounts_dir.exists():
        for provider_dir in accounts_dir.iterdir():
            if provider_dir.is_dir():
                normalized_name = provider_dir.name.replace("'", '').strip() or provider_dir.name
                _merge_dir_contents(provider_dir, AUTH_DIR / normalized_name)
    if providers_dir.exists():
        for provider_dir in providers_dir.iterdir():
            if provider_dir.is_dir():
                _merge_dir_contents(provider_dir, AUTH_DIR / provider_dir.name)
    if archive_dir.exists():
        _merge_dir_contents(archive_dir, AUTH_ARCHIVE_DIR / 'default' / '_archive')

    for provider_dir in sorted(LEGACY_AUTH_SOURCES_DIR.iterdir(), key=lambda path: path.name.lower()):
        if not provider_dir.is_dir() or provider_dir.name.lower() == 'default':
            continue
        _move_auth_json_files(provider_dir, AUTH_DIR / provider_dir.name.lower(), provider_dir.name.lower())

    for provider_dir in sorted(AUTH_DIR.iterdir(), key=lambda path: path.name.lower()):
        if not provider_dir.is_dir() or provider_dir.name.lower() in IGNORED_AUTH_SOURCE_DIRS:
            continue
        _clean_provider_directory(provider_dir)

    try:
        LEGACY_AUTH_SOURCES_DIR.rmdir()
    except Exception:
        pass


def _load_sources_config():
    if not SOURCES_CONFIG_FILE.exists():
        return _default_sources_config()
    try:
        payload = json.loads(SOURCES_CONFIG_FILE.read_text(encoding='utf-8'))
    except Exception:
        return _default_sources_config()
    if isinstance(payload, dict):
        result = {}
        for source_id, source_path in payload.items():
            key = str(source_id or '').strip().lower()
            path_value = str(source_path or '').strip()
            if key and key not in IGNORED_AUTH_SOURCE_DIRS and path_value:
                result[key] = path_value
        if result:
            return result
    return _default_sources_config()


def load_auth_source_dirs():
    result = {}
    for source_id, source_path in _load_sources_config().items():
        key = str(source_id or '').strip().lower()
        if not key or key in IGNORED_AUTH_SOURCE_DIRS:
            continue
        path = Path(source_path)
        if path.exists() and path.is_dir():
            result[key] = path
    return result


for directory in (
    STORAGE_DIR,
    CONFIG_DIR,
    AUTH_DIR,
    AUTH_ARCHIVE_DIR,
    MODELS_DIR,
    RUNTIME_DIR,
    ACTIVE_AUTH_DIR,
    CACHE_DIR,
    LOGS_DIR,
    REQUEST_ARCHIVE_DIR,
    BACKUPS_DIR,
    TEMP_DIR,
    TOOL_LOGS_DIR,
):
    directory.mkdir(parents=True, exist_ok=True)

_migrate_storage_layout()
_normalize_auth_layout()
_ensure_sources_config()

AUTH_SOURCE_DIRS = load_auth_source_dirs()
