# -*- mode: python ; coding: utf-8 -*-

import os

ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, 'index.html'), '.'),
        (os.path.join(ROOT, 'dashboard.css'), '.'),
        (os.path.join(ROOT, 'sections'), 'sections'),
        (os.path.join(ROOT, 'js'), 'js'),
        (os.path.join(ROOT, 'css'), 'css'),
    ],
    hiddenimports=[
        'backend',
        'backend.server',
        'backend.paths',
        'backend.processes',
        'backend.auth',
        'backend.state',
        'backend.runtime_env',
        'backend.security',
        'backend.tools',
        'backend.terminals',
        'backend.api_keys',
        'backend.proxy_env',
        'backend.routes',
        'backend.routes.get_routes',
        'backend.routes.post_routes',
        'backend.routes.helpers',
        'backend.request_metrics',
        'backend.request_metrics.__init__',
        'backend.request_metrics.parsing',
        'backend.request_metrics.merge',
        'backend.request_metrics.summary',
        'backend.request_metrics.observability',
        'backend.data_transfer',
        'backend.settings',
        'pywinpty',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='dashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='dashboard',
    contents_directory='.',
)
