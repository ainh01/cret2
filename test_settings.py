import tempfile
from pathlib import Path
from unittest.mock import patch

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import app as server

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / '.env').write_text('MODEL=test-model\nPROXY=http://127.0.0.1:3128\n')
    with patch.object(server, 'ROOT', root):
        server.settings = server.GlobalSettings()
        with TestClient(server.app) as client:
            response = client.post('/api/settings', json={
                'endpoint': 'https://example.com/v1',
                'api_key': 'test-secret',
                'model': 'test-model',
                'thinking_effort': 'Low',
            })
            assert response.status_code == 200
            assert response.json() == {'status': 'saved'}
            loaded = client.get('/api/settings').json()
            assert loaded['endpoint'] == 'https://example.com/v1/chat/completions'
            assert loaded['model'] == 'test-model'
            assert loaded['thinking_effort'] == 'Low'
            assert loaded['key_set'] is True
            assert 'test-secret' not in client.get('/api/settings').text
            saved = dotenv_values(root / '.env')
            assert saved['TOKEN'] == 'test-secret'
            assert saved['MODEL'] == 'test-model'
            assert saved['THINKING_EFFORT'] == 'Low'
            # A blank key keeps the stored secret; the endpoint still updates.
            assert client.post('/api/settings', json={
                'endpoint': 'https://example.org/v1/chat/completions', 'api_key': '',
            }).status_code == 200
            assert dotenv_values(root / '.env')['TOKEN'] == 'test-secret'
            assert client.get('/api/settings').json()['endpoint'] == 'https://example.org/v1/chat/completions'
            # Rejected endpoints and efforts never touch the saved settings.
            for endpoint in ['file:///tmp/test', 'https://user:password@example.org', 'https://example.org/?key=value']:
                assert client.post('/api/settings', json={'endpoint': endpoint}).status_code == 400
            assert client.post('/api/settings', json={
                'endpoint': 'https://example.org/v1', 'thinking_effort': 'max',
            }).status_code == 400
            assert server.settings.endpoint == 'https://example.org/v1/chat/completions'
            assert not (root / '.env.settings.tmp').exists()
            with patch.object(server, 'PROXY', 'http://127.0.0.1:3128'):
                assert server.api_client() is server.app.state.client
            with patch.object(server, 'PROXY', None):
                assert server.api_client() is server.app.state.direct_client
print('Settings persistence, blank-key preservation, secret omission, endpoint validation, atomic saves and proxy selection passed')
