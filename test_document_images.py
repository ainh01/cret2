"""PDF figures and placing those images into the rewritten lesson."""
import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

import app

client = TestClient(app.app)
PNG = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 24, 16), 0)
PNG.set_rect(PNG.irect, (20, 40, 200))
PNG_BYTES = PNG.tobytes('png')
PNG_URL = 'data:image/png;base64,' + base64.b64encode(PNG_BYTES).decode('ascii')


def figure_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(80, 160, 420, 420), color=(0, 0, 0), width=2)
    page.insert_text((100, 200), 'ADC', fontsize=16)
    page.insert_text((160, 450), 'Figure 1. Block', fontsize=12)
    page.insert_text((72, 520), 'Doan chu thich duoi hinh, khong thuoc so do.', fontsize=11)
    doc.save(path)
    doc.close()


def scan_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 400), 0)
    pix.set_rect(pix.irect, (240, 240, 240))
    page.insert_image(page.rect, pixmap=pix)
    doc.save(path)
    doc.close()


with tempfile.TemporaryDirectory() as tmp:
    figure_path = Path(tmp) / 'figure.pdf'
    scan_path = Path(tmp) / 'scan.pdf'
    figure_pdf(figure_path)
    scan_pdf(scan_path)
    figure = client.post('/api/convert', files={'file': ('figure.pdf', figure_path.read_bytes(), 'application/pdf')})
    assert figure.status_code == 200, figure.text
    body = figure.json()
    assert '[[fig:1]]' in body['text'], body['text']
    assert 'Figure 1. Block' in body['text']
    assert len(body['images']) == 1, body['images']
    assert body['images'][0]['id'] == '1'
    assert body['images'][0]['data_url'].startswith('data:image/png;base64,')
    scan = client.post('/api/convert', files={'file': ('scan.pdf', scan_path.read_bytes(), 'application/pdf')})
    assert scan.status_code == 200, scan.text
    assert len(scan.json()['images']) == 1, scan.text


MATERIAL = '# Sơ đồ\n\nĐây là đoạn giải thích đủ dài về sơ đồ khối và đường tín hiệu.\n'
calls = []


async def fake_ai(prompt, images=None):
    calls.append({'prompt': prompt, 'images': images})
    if prompt.startswith('HỌC'):
        return '```material\n' + MATERIAL + '\n![bịa](http://evil.example/x.png)\n[Image #1]\nendmaterial```'
    if prompt.startswith('Generate'):
        return '```quiz\n' + json.dumps(quiz) + '\nendquiz```'
    if 'placement failed' in prompt:
        return json.dumps([{'image': 1, 'section': 0}])
    return 'không phải json'


cfg = {
    'quiz_frontend_base': 'https://vtask.fun',
    'quiz_backend_base': 'https://api.vtask.fun',
    'randomize': False,
    'steps': {
        'material': {'enabled': True, 'template': 'HỌC'},
        'quiz': {'enabled': True, 'template': 'Generate 6 questions'},
        'interactive': {'enabled': False, 'template': ''},
    },
}
quiz = [{'question': 'Q', 'options': [{'label': letter, 'value': letter} for letter in 'ABCD'], 'correct': 'A'}]


async def fake_share(config, state):
    shared.append(state)
    return 'https://vtask.fun/abcdef'


shared = []
with tempfile.TemporaryDirectory() as tmp, \
        patch.object(app, 'IMAGE_DIR', Path(tmp)), \
        patch.object(app, 'load_config', return_value=cfg), \
        patch.object(app, 'ai_call', fake_ai), \
        patch.object(app, 'share_state', fake_share):
    response = client.post('/api/generate', json={
        'input': 'đề',
        'browser_base_url': 'https://cret.example/prefix',
        'question_count': 1,
        'parts': [
            {'kind': 'image', 'name': 'anh-dan.png', 'data_url': PNG_URL},
            {'kind': 'source', 'name': 'a.pdf', 'text': 'Nguồn có [[fig:1]] ngay sơ đồ.',
             'images': [{'id': '1', 'caption': 'Figure 1. Block', 'data_url': PNG_URL}]},
        ],
    })
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]['done'] is True, events
    assert [event['stage'] for event in events if 'stage' in event] == ['material', 'figures', 'quiz', 'share']
    assert '[Image #1]' in calls[0]['prompt'] and '[Image #2]' in calls[0]['prompt']
    assert '[[fig:1]]' not in calls[0]['prompt']
    stamped = base64.b64decode(calls[0]['images'][0]['image_url']['url'].split(',', 1)[1])
    assert pymupdf.Pixmap(stamped).height > 16
    assert b'Image #1' not in PNG_BYTES
    quiz_call = next(call for call in calls if call['prompt'].startswith('Generate'))
    assert quiz_call['images']
    material = shared[0]['material']
    assert 'http://evil.example' not in material
    assert material.count('https://cret.example/prefix/generated-images/') == 2
    assert '![Image #1]' in material and '![Image #2]' in material
    assert PNG_URL not in json.dumps(shared[0])
    saved = list(Path(tmp).iterdir())
    assert len(saved) == 2
    assert pymupdf.Pixmap(saved[0].read_bytes()).height == 16

assert client.post('/api/generate', json={
    'input': 'x',
    'parts': [{'kind': 'image', 'data_url': PNG_URL}] * 41,
}).status_code == 422

print('pdf figures, placement and image cap passed.')
