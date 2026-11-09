"""Offline tests for illustration generation and persistent public image URLs."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
import app

PNG = b'\x89PNG\r\n\x1a\n' + b'test image bytes'
MATERIAL = '# Bài học\n\nĐây là đoạn kiến thức rất quan trọng về tế bào.\n\n```interactive\nSome code that should not be considered.\n```\n'


class IllustrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_pipeline_and_public_route(self):
        calls, shared, stages = [], [], []
        cfg = {'quiz_frontend_base': 'https://example.org', 'quiz_backend_base': 'https://example.org',
               'randomize': False, 'steps': {
                   'material': {'enabled': True, 'template': 'MATERIAL'},
                   'quiz': {'enabled': True, 'template': 'Generate 6 questions'},
                   'interactive': {'enabled': False, 'template': ''}}}
        quiz = [{'question': 'Q', 'options': [{'label': x, 'value': x} for x in 'ABCD'], 'correct': 'A'}]

        async def fake_ai(prompt, images=None):
            calls.append(prompt)
            if prompt.startswith('MATERIAL'):
                return '```material\n' + MATERIAL + 'endmaterial```'
            if prompt.startswith('Generate'):
                return '```quiz\n' + json.dumps(quiz) + '\nendquiz```'
            return json.dumps([{'section': 0, 'prompt': 'A detailed diagram of a cell', 'alt': 'Sơ đồ tế bào'}])

        async def fake_share(config, state):
            shared.append(state)
            return 'https://example.org/abcdef'

        async def image_provider(request):
            self.assertEqual(request.headers['authorization'], 'Bearer image-secret')
            payload = json.loads(request.content)
            self.assertEqual(payload['model'], 'image-model')
            self.assertIn('cell', payload['prompt'])
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(PNG).decode()}]})

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'IMAGE_DIR', Path(tmp)), \
             patch.object(app, 'load_config', return_value=cfg), \
             patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'share_state', fake_share), \
             patch.object(app.settings, 'image_endpoint', 'https://images.example.com/v1/images/generations'), \
             patch.object(app.settings, 'image_token', 'image-secret'), \
             patch.object(app.settings, 'image_model', 'image-model'):
            async with httpx.AsyncClient(transport=httpx.MockTransport(image_provider)) as image_client:
                with patch.object(app, 'api_client', return_value=image_client):
                    transport = httpx.ASGITransport(app=app.app)
                    async with httpx.AsyncClient(transport=transport, base_url='https://internal.example') as client:
                        response = await client.post('/api/generate', json={'input': 'topic', 'question_count': 1,
                                                                          'generate_illustration': True,
                                                                          'browser_base_url': 'https://cret.example.com/prefix'})
                        events = [json.loads(line) for line in response.text.splitlines() if line]
                        self.assertEqual([e['stage'] for e in events if 'stage' in e],
                                         ['material', 'quiz', 'illustration', 'share'])
                        self.assertTrue(events[-1]['done'])
                        material = shared[-1]['material']
                        self.assertIn('![Sơ đồ tế bào](https://cret.example.com/prefix/generated-images/', material)
                        self.assertIn(MATERIAL.splitlines()[2], material)
                        filename = list(Path(tmp).iterdir())[0].name
                        image = await client.get('/generated-images/' + filename)
                        self.assertEqual(image.content, PNG)
                        self.assertEqual(image.headers['access-control-allow-origin'], '*')
                        self.assertEqual((await client.get('/generated-images/../../secret')).status_code, 404)
                        self.assertEqual(len(calls), 3)
                        self.assertIn('factual accuracy', calls[2])

    async def test_multiple_images_and_failure_cleanup(self):
        material = ('# Giới thiệu\n\nĐây là nội dung đầu tiên về tế bào và cấu trúc.\n\n'
                    '## Phần hai\n\nĐây là nội dung thứ hai về chức năng của tế bào.\n\n'
                    '## Phần ba\n\nĐây là nội dung thứ ba về sự phát triển của tế bào.\n')
        plans = [
            {'section': 2, 'prompt': 'growth', 'alt': 'Phát triển'},
            {'section': 0, 'prompt': 'structure', 'alt': 'Cấu trúc'},
            {'section': 1, 'prompt': 'function', 'alt': 'Chức năng'},
        ]
        calls = []
        async def fake_ai(prompt):
            self.assertIn('up to 8 distinct illustrations', prompt)
            self.assertIn('heading: Phần hai', prompt)
            return json.dumps(plans)
        async def fake_generate(prompt):
            calls.append(prompt)
            return PNG, 'png'
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'IMAGE_DIR', Path(tmp)), \
             patch.object(app, 'ai_call', fake_ai), patch.object(app, 'generated_image_bytes', fake_generate):
            result = await app.add_illustration(material, 'https://cret.example')
            self.assertEqual(len(calls), 3)
            self.assertEqual(result.count('!['), 3)
            self.assertEqual(len(list(Path(tmp).iterdir())), 3)
            self.assertLess(result.index('Cấu trúc]'), result.index('## Phần hai'))
            self.assertLess(result.index('Chức năng]'), result.index('## Phần ba'))
            self.assertGreater(result.index('Phát triển]'), result.index('## Phần ba'))

        async def failing_generate(prompt):
            if prompt == 'function':
                raise app.PipelineError('provider error')
            return PNG, 'png'
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'IMAGE_DIR', Path(tmp)), \
             patch.object(app, 'ai_call', fake_ai), patch.object(app, 'generated_image_bytes', failing_generate):
            result = await app.add_illustration(material, 'https://cret.example')
            self.assertEqual(result.count('!['), 2)
            self.assertNotIn('Chức năng]', result)
            self.assertEqual(len(list(Path(tmp).iterdir())), 2)

    async def test_reject_invalid_illustration_plans(self):
        material = 'Đây là một đoạn kiến thức dài và có nội dung rõ ràng.\n'
        invalid = [[], [{'section': 0, 'prompt': 'x', 'alt': 'a'}] * 2,
                   [{'section': 5, 'prompt': 'x', 'alt': 'a'}],
                   [{'section': 0, 'prompt': '', 'alt': 'a'}]]
        for plan in invalid:
            async def fake_ai(prompt):
                return json.dumps(plan)
            with self.subTest(plan=plan), patch.object(app, 'ai_call', fake_ai):
                with self.assertRaises(app.PipelineError):
                    await app.illustration_plan(material)

    async def test_image_url_download_and_private_address_rejection(self):
        async def provider(request):
            if request.method == 'POST':
                return httpx.Response(200, json={'data': [{'url': 'https://cdn.example.com/picture.jpg'}]})
            self.assertEqual(request.url.host, '93.184.216.34')
            self.assertEqual(request.headers['host'], 'cdn.example.com')
            self.assertEqual(request.extensions['sni_hostname'], 'cdn.example.com')
            return httpx.Response(200, content=PNG)

        def dns(ip):
            return [(2, 1, 6, '', (ip, 443))]

        with patch.object(app.settings, 'image_endpoint', 'https://api.example.com/v1/images/generations'), \
             patch.object(app.settings, 'image_token', 'secret'), \
             patch.object(app.settings, 'image_model', 'image-model'):
            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                with patch.object(app, 'api_client', return_value=client), \
                     patch.object(app.app.state, 'direct_client', client, create=True):
                    with patch('socket.getaddrinfo', return_value=dns('93.184.216.34')):
                        data, extension = await app.generated_image_bytes('diagram')
                        self.assertEqual((data, extension), (PNG, 'png'))
                    with patch('socket.getaddrinfo', return_value=dns('127.0.0.1')):
                        with self.assertRaises(app.PipelineError):
                            await app.generated_image_bytes('diagram')

    def test_settings_are_independent_and_secret(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(app, 'ROOT', Path(tmp)), \
             patch.object(app, 'settings', app.GlobalSettings()):
            client = TestClient(app.app)
            payload = {'endpoint': 'https://text.example/v1', 'api_key': 'text-secret', 'model': 'text-model',
                       'image_endpoint': 'https://images.example/v1', 'image_api_key': 'image-secret',
                       'image_model': 'image-model'}
            response = client.post('/api/settings', json=payload)
            self.assertEqual(response.status_code, 200)
            loaded = client.get('/api/settings').json()
            self.assertEqual(loaded['image_endpoint'], 'https://images.example/v1/images/generations')
            self.assertNotIn('public_base_url', loaded)
            self.assertTrue(loaded['image_key_set'])
            self.assertNotIn('image-secret', json.dumps(loaded))
            self.assertNotIn('text-secret', json.dumps(loaded))
            payload['image_api_key'] = ''
            self.assertEqual(client.post('/api/settings', json=payload).status_code, 200)
            self.assertEqual(app.settings.image_token, 'image-secret')
            payload['image_endpoint'] = 'https://user:pass@example.com'
            self.assertEqual(client.post('/api/settings', json=payload).status_code, 400)

    async def test_detect_browser_url_and_fallback(self):
        seen = []
        async def capture(queue, user_input, reference, images, question_count, enabled, public_url, document_images=None):
            seen.append(public_url)
            return 'https://example.org/abcdef'
        with patch.object(app, 'run_pipeline', capture):
            transport = httpx.ASGITransport(app=app.app)
            async with httpx.AsyncClient(transport=transport, base_url='http://internal:3004') as client:
                await client.post('/api/generate', json={'input': 'x', 'generate_illustration': True,
                                                         'browser_base_url': 'https://public.example/prefix'})
                self.assertEqual(seen[-1], 'https://public.example/prefix')
                await client.post('/api/generate', json={'input': 'x'})
                self.assertEqual(seen[-1], 'http://internal:3004')

    async def test_disabled_and_error_do_not_publish(self):
        cfg = {'quiz_frontend_base': 'https://example.org', 'quiz_backend_base': 'https://example.org',
               'randomize': False, 'steps': {
                   'material': {'enabled': False, 'template': ''},
                   'quiz': {'enabled': False, 'template': ''},
                   'interactive': {'enabled': False, 'template': ''}}}
        async def no_image(material, url):
            raise app.PipelineError('Không tạo được ảnh')
        async def share(config, state):
            return 'https://example.org/abcdef'
        with patch.object(app, 'load_config', return_value=cfg), patch.object(app, 'add_illustration', no_image), \
             patch.object(app, 'share_state', share):
            transport = httpx.ASGITransport(app=app.app)
            async with httpx.AsyncClient(transport=transport, base_url='https://cret.example') as client:
                disabled = await client.post('/api/generate', json={'input': 'topic'})
                self.assertIn('"done": true', disabled.text)
                enabled = await client.post('/api/api/generate', json={'input': 'topic', 'generate_illustration': True})
                self.assertEqual(enabled.status_code, 404)
                enabled = await client.post('/api/generate', json={'input': 'topic', 'generate_illustration': True})
                self.assertIn('"done": true', enabled.text)
                self.assertNotIn('Không tạo được ảnh', enabled.text)


    def test_ascii_replacement_does_not_leave_an_open_fence(self):
        diagram = '┌──────────────┐\n│ USB Audio    │\n└──────────────┘\n'
        material = (
            '# Bản chất\n\n**ALC5686** là một giải pháp SoC.\n\n'
            '```\n' + diagram + '```\n\n'
            '**Chip** tích hợp các thành phần.\n\n'
            '### Mục sau\n\nĐoạn sau phải còn là markdown.\n'
        )
        spans = app.diagram_replacement_spans(material)
        self.assertEqual(len(spans), 1)
        start, end, text = spans[0]
        self.assertIn('USB Audio', text)
        self.assertTrue(material[start:end].startswith('```'))
        self.assertTrue(material[start:end].rstrip().endswith('```'))
        replaced = material[:start] + '\n\n![Sơ đồ](https://cret.example/generated-images/a.jpg)\n\n' + material[end:]
        self.assertNotIn('```', replaced)
        self.assertNotRegex(replaced, r'\]\([^)\n]+\)`')
        self.assertIn('### Mục sau', replaced)
        self.assertIn('**Chip**', replaced)
        self.assertLess(replaced.index('![Sơ đồ]'), replaced.index('### Mục sau'))

    def test_label_before_fence_does_not_keep_the_fence(self):
        material = 'Trước.\n\n[Sơ đồ khối]\n```\n┌──┐\n│A │\n└──┘\n```\n\n### Sau\n'
        spans = app.diagram_replacement_spans(material)
        start, end, _text = spans[0]
        self.assertIn('```', material[start:end])
        replaced = material[:start] + '\n\n![Sơ đồ](https://cret.example/a.jpg)\n\n' + material[end:]
        self.assertNotIn('```', replaced)
        self.assertIn('[Sơ đồ khối]', replaced)
        self.assertIn('### Sau', replaced)
        self.assertIn('Trước.', replaced)

    def test_unclosed_diagram_fence_does_not_swallow_the_lesson(self):
        material = '# Đầu\n\n```\n┌──┐\n│x │\n└──┘\n\n**Đậm** sau sơ đồ.\n\n### Mục\n'
        spans = app.diagram_replacement_spans(material)
        start, end, _text = spans[0]
        self.assertTrue(material[start:end].startswith('```'))
        self.assertNotIn('**Đậm**', material[start:end])
        replaced = material[:start] + '\n\n![Sơ đồ](https://cret.example/a.jpg)\n\n' + material[end:]
        self.assertNotIn('```', replaced)
        self.assertIn('**Đậm** sau sơ đồ.', replaced)
        self.assertIn('### Mục', replaced)

    def test_interactive_fence_stays_closed(self):
        material = '```interactive\n┌──┐\n│x │\n└──┘\n```\n\n**Sau**\n'
        spans = app.diagram_replacement_spans(material)
        start, end, _text = spans[0]
        self.assertFalse(material[start:end].startswith('```'))
        replaced = material[:start] + '\n\n![Sơ đồ](https://cret.example/a.jpg)\n\n' + material[end:]
        self.assertIn('```interactive', replaced)
        self.assertLess(replaced.index('```interactive'), replaced.index('![Sơ đồ]'))
        self.assertLess(replaced.index('![Sơ đồ]'), replaced.rindex('```'))
        self.assertGreater(replaced.index('**Sau**'), replaced.rindex('```'))

    async def test_generated_ascii_image_replaces_the_fence(self):
        material = '# Bài\n\n```\n┌──┐\n│A │\n└──┘\n```\n\n### Còn lại\n\n**Không** bị nuốt.\n'
        async def fake_generate(prompt):
            self.assertIn('┌', prompt)
            return PNG, 'jpg'
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'IMAGE_DIR', Path(tmp)), \
             patch.object(app, 'generated_image_bytes', fake_generate):
            result = await app.add_illustration(material, 'https://cret.example')
        self.assertEqual(result.count('```'), 0)
        self.assertIn('![Sơ đồ](https://cret.example/generated-images/', result)
        self.assertNotRegex(result, r'\]\([^)\n]+\)`')
        self.assertLess(result.index('![Sơ đồ]'), result.index('### Còn lại'))
        self.assertIn('**Không** bị nuốt.', result)


if __name__ == '__main__':
    unittest.main()
