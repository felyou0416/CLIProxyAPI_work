from backend import system_proxy


def test_get_system_proxy_status_shape(monkeypatch):
    monkeypatch.setattr(system_proxy, 'get_system_proxy', lambda: (True, '127.0.0.1:10090'))
    monkeypatch.setattr(system_proxy, 'get_env_vars', lambda: {'HTTP_PROXY': 'http://127.0.0.1:10090'})
    monkeypatch.setattr(system_proxy, 'list_available_ports', lambda: [10090, 7890])

    result = system_proxy.get_system_proxy_status()
    assert result['ok'] is True
    assert result['item']['proxy_enabled'] is True
    assert result['item']['current_port'] == 10090
    assert result['item']['available_ports'] == [10090, 7890]
    assert result['proxy_enabled'] is True


def test_configure_system_proxy_success(monkeypatch):
    calls = {}

    monkeypatch.setattr(system_proxy, 'list_available_ports', lambda: [10090])
    monkeypatch.setattr(system_proxy, 'pick_best_port', lambda ports=None: 10090)

    def fake_set_system_proxy(enable, server=''):
        calls['set_system'] = (enable, server)

    def fake_set_env(proxy_url):
        calls['set_env'] = proxy_url

    monkeypatch.setattr(system_proxy, 'set_system_proxy', fake_set_system_proxy)
    monkeypatch.setattr(system_proxy, 'set_env_vars', fake_set_env)

    result = system_proxy.configure_system_proxy()
    assert result['ok'] is True
    assert result['port'] == 10090
    assert calls['set_system'] == (True, '127.0.0.1:10090')
    assert calls['set_env'] == 'http://127.0.0.1:10090'


def test_toggle_system_proxy_stop(monkeypatch):
    calls = {}
    monkeypatch.setattr(system_proxy, 'get_system_proxy', lambda: (True, '127.0.0.1:7890'))

    def fake_set_system_proxy(enable, server=''):
        calls['set_system'] = (enable, server)

    def fake_clear():
        calls['cleared'] = True

    monkeypatch.setattr(system_proxy, 'set_system_proxy', fake_set_system_proxy)
    monkeypatch.setattr(system_proxy, 'clear_env_vars', fake_clear)

    result = system_proxy.toggle_system_proxy()
    assert result['ok'] is True
    assert result['proxy_enabled'] is False
    assert calls['set_system'] == (False, '')
    assert calls['cleared'] is True


def test_restore_default(monkeypatch):
    calls = {}
    monkeypatch.setattr(system_proxy, 'set_system_proxy', lambda enable, server='': calls.setdefault('set_system', (enable, server)))
    monkeypatch.setattr(system_proxy, 'clear_env_vars', lambda: calls.setdefault('cleared', True))

    result = system_proxy.restore_system_proxy_default()
    assert result['ok'] is True
    assert result['proxy_enabled'] is False
    assert calls['set_system'] == (False, '')
    assert calls['cleared'] is True
