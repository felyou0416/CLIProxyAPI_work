import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import local_workspace


class LocalWorkspaceTests(unittest.TestCase):
    def _config(self):
        return {
            'title': 'My local workspace',
            'links': [{
                'id': 'monitor',
                'label': 'Monitor',
                'url': 'http://127.0.0.1:3000/',
            }],
            'services': [{
                'id': 'demo-service',
                'label': 'Demo service',
                'url': 'http://127.0.0.1:3000/',
                'commands': {
                    'start': ['tool', 'start'],
                    'stop': ['tool', 'stop'],
                },
            }],
        }

    def test_public_workspace_never_returns_commands_or_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / 'dashboard-actions.json'
            config_file.write_text(json.dumps(self._config()), encoding='utf-8')
            with patch.object(local_workspace, 'LOCAL_WORKSPACE_FILE', config_file):
                item = local_workspace.public_local_workspace()

        self.assertTrue(item['configured'])
        self.assertEqual(item['services'][0]['actions'], ['start', 'stop'])
        self.assertNotIn('commands', item['services'][0])
        self.assertNotIn('cwd', item['services'][0])

    def test_invalid_url_hides_local_workspace(self):
        payload = self._config()
        payload['links'][0]['url'] = 'file:///C:/private'
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / 'dashboard-actions.json'
            config_file.write_text(json.dumps(payload), encoding='utf-8')
            with patch.object(local_workspace, 'LOCAL_WORKSPACE_FILE', config_file):
                item = local_workspace.public_local_workspace()

        self.assertFalse(item['configured'])
        self.assertIn('http(s)', item['config_error'])

    def test_action_can_only_use_whitelisted_service_operation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / 'dashboard-actions.json'
            payload = self._config()
            payload['services'][0]['cwd'] = str(root)
            config_file.write_text(json.dumps(payload), encoding='utf-8')
            with patch.object(local_workspace, 'LOCAL_WORKSPACE_FILE', config_file), patch.object(
                local_workspace, 'LOCAL_WORKSPACE_DIR', root
            ), patch('backend.local_workspace.subprocess.Popen') as popen:
                popen.return_value.pid = 42
                result = local_workspace.run_local_service_action('demo-service', 'start')
                with self.assertRaisesRegex(ValueError, 'not configured'):
                    local_workspace.run_local_service_action('demo-service', 'restart')
                with self.assertRaisesRegex(ValueError, 'Unknown local service'):
                    local_workspace.run_local_service_action('not-configured', 'start')

        self.assertTrue(result['ok'])
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ['tool', 'start'])
        self.assertFalse(popen.call_args.kwargs['shell'])

    def test_service_requires_an_operation(self):
        payload = self._config()
        payload['services'][0]['commands'] = {}
        with self.assertRaisesRegex(ValueError, 'at least one operation'):
            local_workspace._normalize_config(payload)

    def test_legacy_config_moves_to_storage_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_file = root / 'legacy' / 'dashboard-actions.json'
            storage_file = root / 'storage' / 'dashboard-actions.json'
            legacy_file.parent.mkdir()
            legacy_file.write_text(json.dumps(self._config()), encoding='utf-8')
            with patch.object(local_workspace, 'LEGACY_LOCAL_WORKSPACE_FILE', legacy_file), patch.object(
                local_workspace, 'LOCAL_WORKSPACE_FILE', storage_file
            ):
                item = local_workspace.public_local_workspace()

            self.assertTrue(item['configured'])
            self.assertTrue(storage_file.is_file())
            self.assertFalse(legacy_file.exists())

    def test_existing_storage_config_is_never_overwritten_by_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy_file = root / 'legacy' / 'dashboard-actions.json'
            storage_file = root / 'storage' / 'dashboard-actions.json'
            legacy_file.parent.mkdir()
            storage_file.parent.mkdir()
            legacy_file.write_text(json.dumps(self._config()), encoding='utf-8')
            storage_file.write_text(json.dumps({
                'title': 'Storage config', 'links': [], 'services': []
            }), encoding='utf-8')
            with patch.object(local_workspace, 'LEGACY_LOCAL_WORKSPACE_FILE', legacy_file), patch.object(
                local_workspace, 'LOCAL_WORKSPACE_FILE', storage_file
            ):
                item = local_workspace.public_local_workspace()

            self.assertEqual(item['title'], 'Storage config')
            self.assertTrue(legacy_file.is_file())
