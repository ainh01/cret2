"""Attachment tests: YouTube links, remove-before-send, empty-input rule, image pass-through.

Run with `python test_attachments.py`. The browser-helper checks need the optional
quickjs development package; they are skipped when it is missing.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
import app

try:
    import quickjs
except ImportError:
    quickjs = None

ROOT = Path(__file__).parent
client = TestClient(app.app)
IMAGE = 'data:image/png;base64,iVBORw0KGgo='  # 9 raw bytes, allowed mimetype


# ---------------------------------------------------------------- YouTube links (server side)

VALID_LINKS = [
    'https://youtu.be/abc123',
    'https://www.youtube.com/watch?v=abc123',
    'https://m.youtube.com/watch?v=abc123&t=30s',
    'https://youtube.com/watch?feature=share&v=abc123',
    'https://www.youtube.com/shorts/abc123?feature=share',
    'https://youtube.com/embed/abc123',
    'https://youtu.be/abc123?si=xyz',
]
for link in VALID_LINKS:
    assert app.youtube_source(link) == link, link

for link in ['https://example.com/watch?v=abc123', 'xem https://youtu.be/abc123 nhé',
             'https://www.youtube.com/playlist?list=PLabc123', 'https://youtu.be/',
             'youtu.be/abc123', 'https://youtube.com/watch?v=abc', '']:
    try:
        app.youtube_source(link)
    except ValueError:
        pass
    else:
        raise AssertionError('liên kết phải bị từ chối: ' + repr(link))


# ---------------------------------------------------------------- /api/convert with a YouTube link

with patch.object(app, 'convert_link', return_value='Nội dung bài giảng'):
    response = client.post('/api/convert', data={'url': 'https://youtu.be/abc123'})
assert response.status_code == 200, response.text
assert response.json() == {'text': 'Nội dung bài giảng'}

assert client.post('/api/convert', data={'url': 'https://example.com/watch?v=abc123'}).status_code == 400
assert client.post('/api/convert', data={}).status_code == 400
assert client.post('/api/convert', data={'url': 'https://youtu.be/abc123'},
                   files={'file': ('a.txt', b'x')}).status_code == 400


def failing_link(url):
    raise RuntimeError('Internal youtube error')


with patch.object(app, 'convert_link', failing_link):
    response = client.post('/api/convert', data={'url': 'https://youtu.be/abc123'})
assert response.status_code == 422 and 'Internal youtube error' not in response.text
with patch.object(app, 'convert_link', return_value='  \n '):
    assert client.post('/api/convert', data={'url': 'https://youtu.be/abc123'}).status_code == 422
with patch.object(app, 'convert_link', return_value='x' * 1000001):
    assert client.post('/api/convert', data={'url': 'https://youtu.be/abc123'}).status_code == 413


# ---------------------------------------------------------------- generate: input, sources, images

MATERIAL_ONLY_CONFIG = {
    'quiz_frontend_base': 'https://vtask.fun',
    'quiz_backend_base': 'https://api.vtask.fun',
    'randomize': False,
    'steps': {
        'material': {'enabled': True, 'template': 'HỌC LIỆU'},
        'quiz': {'enabled': False, 'template': ''},
        'interactive': {'enabled': False, 'template': ''},
    },
}

calls = []
shared = []


async def fake_ai_call(user_message, images=None):
    calls.append({'message': user_message, 'images': images})
    return '```material\nnội dung\nendmaterial```'


async def fake_share_state(cfg, state):
    shared.append(state)
    return 'https://vtask.fun/abcdef'


def run_generate(payload):
    response = client.post('/api/generate', json=payload)
    assert response.status_code == 200, response.text
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


with patch.object(app, 'load_config', return_value=MATERIAL_ONLY_CONFIG), \
        patch.object(app, 'ai_call', fake_ai_call), \
        patch.object(app, 'share_state', fake_share_state):

    # No typed input and no attachment at all: the Vietnamese empty-input error, nothing runs.
    calls.clear()
    shared.clear()
    assert run_generate({'input': '   '}) == [{'error': 'Hãy nhập nội dung bạn muốn học.'}]
    assert not calls and not shared

    # No typed input but one image: the run is allowed.
    calls.clear()
    shared.clear()
    events = run_generate({'input': '', 'images': [{'type': 'image_url', 'image_url': {'url': IMAGE}}]})
    assert events[-1] == {'done': True, 'link': 'https://vtask.fun/abcdef'}, events
    assert calls[0]['images'] == [{'type': 'image_url', 'image_url': {'url': IMAGE}}]
    # Images are never stored in the published lesson state.
    assert 'images' not in shared[0] and IMAGE not in json.dumps(shared[0], ensure_ascii=False)

    # Converted attachment text lands after the typed input, in insertion order.
    calls.clear()
    run_generate({'input': 'đề bài',
                  'sources': [{'name': 'a.docx', 'text': 'NGUỒN A'},
                              {'name': 'b.mp3', 'text': 'NGUỒN B'}]})
    assert 'đề bài\n\nNGUỒN A\n\nNGUỒN B' in calls[0]['message']
    assert not calls[0]['images']

    # Plain data URLs and OpenAI-style content parts are both accepted.
    for images in ([IMAGE], [{'data_url': IMAGE}],
                   [{'type': 'image_url', 'image_url': {'url': IMAGE}}]):
        calls.clear()
        run_generate({'input': 'x', 'images': images})
        assert calls[0]['images'] == [{'type': 'image_url', 'image_url': {'url': IMAGE}}], images


# ---------------------------------------------------------------- limits

assert client.post('/api/generate', json={'input': '', 'images': [IMAGE] * 11}).status_code == 422
assert client.post('/api/generate', json={'input': '', 'sources': [{'text': 'x'}] * 21}).status_code == 422
assert client.post('/api/generate', json={'input': 'x', 'images': ['data:image/bmp;base64,AAAA']}).status_code == 422
assert client.post('/api/generate', json={'input': 'x', 'images': ['not-a-data-url']}).status_code == 422
with patch.object(app, 'MAX_IMAGE_RAW_BYTES', 8):
    assert client.post('/api/generate', json={'input': 'x', 'images': [IMAGE]}).status_code == 413
with patch.object(app, 'MAX_REQUEST_BYTES', 16):
    assert client.post('/api/generate', json={'input': 'x' * 100}).status_code == 413


# ---------------------------------------------------------------- ai_call content parts

async def collect_ai_call_bodies():
    bodies = []

    async def provider(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                              text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as mock_client:
        with patch.object(app, 'api_client', lambda: mock_client), \
                patch.object(app.settings, 'endpoint', 'https://example.com/v1/chat/completions'), \
                patch.object(app.settings, 'model', 'test-model'):
            await app.ai_call('xin chào')
            await app.ai_call('xin chào', [{'type': 'image_url', 'image_url': {'url': IMAGE}}])
    return bodies


bodies = asyncio.run(collect_ai_call_bodies())
assert bodies[0]['messages'][0]['content'] == 'xin chào'
content = bodies[1]['messages'][0]['content']
assert isinstance(content, list) and len(content) == 2, content
assert content[0] == {'type': 'text', 'text': 'xin chào'}
assert content[1] == {'type': 'image_url', 'image_url': {'url': IMAGE}}


# ---------------------------------------------------------------- browser helpers (quickjs)

html = (ROOT / 'static' / 'home.html').read_text(encoding='utf-8')
order = [html.index('id="input"'), html.index('id="attachments"'), html.index('id="addFiles"'),
         html.index('id="reference"'), html.index('id="learn"')]
assert order == sorted(order), 'the attachment list must sit directly above "Thêm file"'
assert html.index('/static/attachments.js') < html.index('const store = newAttachmentStore()')

if quickjs is None:
    print('quickjs is not installed: skipping the browser-side attachment checks')
else:
    source = (ROOT / 'static' / 'attachments.js').read_text(encoding='utf-8')
    assert 'fetch(' not in source and 'XMLHttpRequest' not in source, 'intake must stay offline'
    ctx = quickjs.Context()
    ctx.eval(source)

    for link in VALID_LINKS:
        assert ctx.eval('String(isYouTubeUrl(' + json.dumps(link) + '))') == link, link
    for text in ['https://example.com/watch?v=abc123', 'xem https://youtu.be/abc123 nhé',
                 'https://www.youtube.com/playlist?list=PLabc123', 'hello', '', 'youtu.be/abc123']:
        assert ctx.eval('String(isYouTubeUrl(' + json.dumps(text) + '))') == 'null', text

    # Pasting a lone YouTube link is intercepted; anything else pastes as text.
    assert ctx.eval('JSON.stringify(planPaste("input", [], "https://youtu.be/abc123"))') == \
        '{"action":"youtube","url":"https://youtu.be/abc123"}'
    assert ctx.eval('JSON.stringify(planPaste("input", [], "xem https://youtu.be/abc123 nhé"))') == '{"action":"text"}'
    # The reference field is never hijacked.
    assert ctx.eval('JSON.stringify(planPaste("reference", [], "https://youtu.be/abc123"))') == '{"action":"text"}'
    # A clipboard image wins over clipboard text.
    assert ctx.eval('JSON.stringify(planPaste("input", [{type: "image/png", name: "a.png", size: 4}], "hi"))') == \
        '{"action":"image","index":0}'

    # Removing an item is local and instant, and it never reaches the submission plan.
    ctx.eval('''
      var store = newAttachmentStore();
      addAttachment(store, {kind: 'document', name: 'a.docx', size: 10});
      addAttachment(store, {kind: 'youtube', name: 'https://youtu.be/abc123', size: 0});
      addAttachment(store, {kind: 'image', name: 'b.png', size: 20, mime: 'image/png'});
      var removed = store.items[0].id;
      removeAttachment(store, removed);
    ''')
    assert ctx.eval('store.items.length') == 2
    assert ctx.eval('submissionPlan(store).map(function (item) { return item.name; }).join(",")') == \
        'https://youtu.be/abc123,b.png'
    assert ctx.eval('attachmentSizeLabel(store.items[0])') == 'YouTube'
    assert ctx.eval('attachmentTypeLabel(store.items[1])') == 'Hình ảnh'

    # Intake caps: 20 attachments in total, 10 of them images.
    ctx.eval('''
      var capStore = newAttachmentStore();
      for (var i = 0; i < 20; i++) addAttachment(capStore, {kind: 'document', name: 'd' + i, size: 1});
      var capError = addAttachment(capStore, {kind: 'document', name: 'x', size: 1}).error;
      var imgStore = newAttachmentStore();
      for (var j = 0; j < 10; j++) addAttachment(imgStore, {kind: 'image', name: 'i' + j, size: 1, mime: 'image/png'});
      var imgError = addAttachment(imgStore, {kind: 'image', name: 'x', size: 1, mime: 'image/png'}).error;
    ''')
    assert ctx.eval('capError') == 'Tối đa 20 tệp đính kèm.'
    assert ctx.eval('imgError') == 'Tối đa 10 ảnh.'

    # ---- composer wiring: the real inline script driven by a fake DOM ----
    # `fetch` and `FileReader` are deliberately undefined here: intake must not touch
    # the network, so any upload attempt while adding/removing would raise.
    inline = html.split('<script>', 1)[1].split('</script>', 1)[0]
    page = quickjs.Context()
    page.eval(source)
    page.eval('''
      var elements = {};
      function makeElement(id) {
        return {
          id: id, value: '', hidden: false, innerHTML: '', files: [], disabled: false, handlers: {},
          classList: { add: function () {}, remove: function () {}, contains: function () { return false; } },
          addEventListener: function (type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); },
          dispatch: function (type, event) { (this.handlers[type] || []).forEach(function (fn) { fn(event); }); },
          click: function () { this.dispatch('click', {}); },
          appendChild: function () {}, setAttribute: function () {}
        };
      }
      var documentHandlers = {};
      var document = {
        getElementById: function (id) { return elements[id] || (elements[id] = makeElement(id)); },
        createElement: function (tag) { return makeElement(tag); },
        addEventListener: function (type, fn) { (documentHandlers[type] = documentHandlers[type] || []).push(fn); }
      };
      function firePaste(targetId, files, text) {
        var prevented = 0;
        (documentHandlers.paste || []).forEach(function (fn) {
          fn({ target: { id: targetId }, clipboardData: { files: files, getData: function () { return text; } },
               preventDefault: function () { prevented = 1; } });
        });
        return prevented;
      }
      function clickRemove(id) {
        elements['attachments'].dispatch('click', {
          target: { closest: function () { return { getAttribute: function () { return String(id); } }; } }
        });
      }
    ''')
    page.eval(inline)
    assert page.eval('store.items.length') == 0
    assert page.eval('document.getElementById("attachments").hidden') is True

    # A lone YouTube link becomes a YouTube attachment and never reaches the textarea.
    assert page.eval('firePaste("input", [], "https://youtu.be/abc123")') == 1
    assert page.eval('store.items.length') == 1
    assert page.eval('store.items[0].kind') == 'youtube'
    assert page.eval('attachmentSizeLabel(store.items[0])') == 'YouTube'
    assert page.eval('document.getElementById("input").value') == ''

    # A clipboard screenshot becomes an image attachment (no picker).
    assert page.eval('firePaste("input", [{type: "image/png", name: "shot.png", size: 2048}], "")') == 1
    assert page.eval('store.items.length') == 2
    assert page.eval('store.items[1].kind') == 'image'
    assert page.eval('attachmentTypeLabel(store.items[1])') == 'Hình ảnh'
    assert page.eval('attachmentSizeLabel(store.items[1])') == '2.0 KB'

    # Normal text is not hijacked, and neither is a paste into the reference field.
    assert page.eval('firePaste("input", [], "xem https://youtu.be/abc123 nhé")') == 0
    assert page.eval('firePaste("input", [], "hello")') == 0
    assert page.eval('firePaste("reference", [], "https://youtu.be/abc123")') == 0
    assert page.eval('store.items.length') == 2

    # Every row renders a type label, a name, a size and its own remove button.
    assert page.eval('document.getElementById("attachments").hidden') is False
    assert page.eval('document.getElementById("attachments").innerHTML').count('data-remove=') == 2

    # Remove is instant and local: the item leaves the list before anything is sent.
    page.eval('clickRemove(store.items[0].id)')
    assert page.eval('store.items.length') == 1
    assert page.eval('store.items[0].kind') == 'image'
    assert page.eval('submissionPlan(store).length') == 1
    assert page.eval('document.getElementById("attachments").innerHTML').count('data-remove=') == 1

print('YouTube link handling, remove-before-send, composer paste rules, empty-input rule, '
      'image pass-through and limits passed.')
