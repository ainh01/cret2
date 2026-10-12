import asyncio
import copy
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from default_config import DEFAULT_CONFIG

ROOT = Path(__file__).parent
load_dotenv(ROOT / '.env')

CONFIG_PATH = ROOT / 'configure.json'
EFFORTS = {'off': 'Off', 'low': 'Low', 'medium': 'Medium', 'high': 'High'}
OPTION_VALUES = ['A', 'B', 'C', 'D']
MAX_REQUEST_BYTES = 50 * 1024 * 1024


def normalize_endpoint(endpoint):
    endpoint = (endpoint or '').strip().rstrip('/')
    if endpoint and not endpoint.endswith('/chat/completions'):
        endpoint += '/chat/completions'
    return endpoint


class GlobalSettings:
    def __init__(self):
        self.endpoint = normalize_endpoint(os.getenv('ENDPOINT', ''))
        self.token = os.getenv('TOKEN', '')
        self.model = os.getenv('MODEL', '')
        self.thinking_effort = EFFORTS.get(os.getenv('THINKING_EFFORT', 'off').strip().lower(), 'Off')

    def update(self, endpoint=None, token=None, model=None, thinking_effort=None):
        if endpoint is not None:
            self.endpoint = endpoint
        if token is not None:
            self.token = token
        if model is not None:
            self.model = model
        if thinking_effort is not None:
            self.thinking_effort = thinking_effort


settings = GlobalSettings()
PROXY = os.getenv('PROXY', '').strip() or None


@asynccontextmanager
async def lifespan(app):
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)
    timeout = httpx.Timeout(1800, connect=30, pool=None)
    app.state.client = httpx.AsyncClient(proxy=PROXY, trust_env=False, timeout=timeout, limits=limits)
    app.state.direct_client = httpx.AsyncClient(trust_env=False, timeout=timeout, limits=limits)
    try:
        yield
    finally:
        await app.state.client.aclose()
        await app.state.direct_client.aclose()


def api_client():
    return app.state.client if PROXY else app.state.direct_client


app = FastAPI(title='Cret2', lifespan=lifespan)


@app.middleware('http')
async def limit_request_size(request, call_next):
    """Cap the whole request body: attached images arrive base64-inflated."""
    try:
        length = int(request.headers.get('content-length') or 0)
    except ValueError:
        length = 0
    if length > MAX_REQUEST_BYTES:
        return JSONResponse(status_code=413, content={'detail': 'Nội dung yêu cầu quá lớn (tối đa 50 MiB).'})
    return await call_next(request)


# ---------------------------------------------------------------- pages

@app.get('/')
async def home():
    return FileResponse(ROOT / 'static' / 'home.html')


@app.get('/settings')
async def settings_page():
    return FileResponse(ROOT / 'static' / 'settings.html')


@app.get('/configure')
async def configure_page():
    return FileResponse(ROOT / 'static' / 'configure.html')


app.mount('/static', StaticFiles(directory=ROOT / 'static'))


# ---------------------------------------------------------------- settings (.env)

@app.get('/api/settings')
async def get_settings():
    return {
        'endpoint': settings.endpoint,
        'model': settings.model,
        'thinking_effort': settings.thinking_effort,
        'key_set': bool(settings.token),
    }


class SettingsRequest(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2000)
    api_key: str = Field(default='', max_length=10000)
    model: str = Field(default='', max_length=300)
    thinking_effort: str = Field(default='Off', max_length=20)


@app.post('/api/settings')
async def save_settings(body: SettingsRequest):
    endpoint = body.endpoint.strip().rstrip('/')
    try:
        parts = urlsplit(endpoint)
        valid = parts.scheme in ('http', 'https') and parts.hostname and not parts.username and not parts.password and not parts.query and not parts.fragment
        _ = parts.port
    except ValueError:
        valid = False
    if not valid or any(char.isspace() for char in endpoint):
        raise HTTPException(400, 'Hãy nhập endpoint HTTP(S) không chứa thông tin đăng nhập, tham số truy vấn hoặc fragment.')
    endpoint = normalize_endpoint(endpoint)
    token = body.api_key.strip() or settings.token
    if token and any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise HTTPException(400, 'Hãy nhập khóa API hợp lệ, không chứa khoảng trắng.')
    model = body.model.strip()
    effort = EFFORTS.get(body.thinking_effort.strip().lower())
    if effort is None:
        raise HTTPException(400, 'Mức suy luận phải là Tắt, Thấp, Trung bình hoặc Cao.')
    # Stage updates together, preserving the other environment settings.
    target = ROOT / '.env'
    staged = ROOT / '.env.settings.tmp'
    try:
        staged.write_text(target.read_text(encoding='utf-8') if target.exists() else '', encoding='utf-8')
        set_key(str(staged), 'ENDPOINT', endpoint)
        set_key(str(staged), 'TOKEN', token)
        set_key(str(staged), 'MODEL', model)
        set_key(str(staged), 'THINKING_EFFORT', effort)
        os.replace(staged, target)
    except OSError:
        raise HTTPException(500, 'Không lưu được cài đặt. Kiểm tra quyền ghi file môi trường.')
    finally:
        staged.unlink(missing_ok=True)
    settings.update(endpoint=endpoint, token=token, model=model, thinking_effort=effort)
    return {'status': 'saved'}


# ---------------------------------------------------------------- configure (configure.json)

def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        for key in ('quiz_frontend_base', 'quiz_backend_base', 'randomize'):
            if key in data:
                cfg[key] = data[key]
        steps = data.get('steps') if isinstance(data.get('steps'), dict) else {}
        for name in ('material', 'quiz', 'interactive'):
            step = steps.get(name)
            if isinstance(step, dict):
                if 'enabled' in step:
                    cfg['steps'][name]['enabled'] = bool(step['enabled'])
                if 'template' in step:
                    cfg['steps'][name]['template'] = str(step['template'])
    return cfg


@app.get('/api/configure')
async def get_configure():
    return load_config()


class StepConfig(BaseModel):
    enabled: bool = True
    template: str = Field(default='', max_length=200000)


class ConfigureRequest(BaseModel):
    quiz_frontend_base: str = Field(min_length=1, max_length=2000)
    quiz_backend_base: str = Field(min_length=1, max_length=2000)
    randomize: bool = True
    material: StepConfig
    quiz: StepConfig
    interactive: StepConfig


@app.post('/api/configure')
async def save_configure(body: ConfigureRequest):
    urls = {
        'ứng dụng học': body.quiz_frontend_base.strip().rstrip('/'),
        'kho lưu trữ': body.quiz_backend_base.strip().rstrip('/'),
    }
    for label, url in urls.items():
        try:
            parts = urlsplit(url)
            valid = parts.scheme in ('http', 'https') and parts.hostname and not parts.query and not parts.fragment
        except ValueError:
            valid = False
        if not valid:
            raise HTTPException(400, f'Hãy nhập URL HTTP(S) hợp lệ cho {label}.')
    cfg = {
        'quiz_frontend_base': urls['ứng dụng học'],
        'quiz_backend_base': urls['kho lưu trữ'],
        'randomize': bool(body.randomize),
        'steps': {
            'material': {'enabled': bool(body.material.enabled), 'template': body.material.template},
            'quiz': {'enabled': bool(body.quiz.enabled), 'template': body.quiz.template},
            'interactive': {'enabled': bool(body.interactive.enabled), 'template': body.interactive.template},
        },
    }
    staged = ROOT / 'configure.tmp.json'
    try:
        staged.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(staged, CONFIG_PATH)
    except OSError:
        raise HTTPException(500, 'Không lưu được configure.json. Kiểm tra quyền ghi file.')
    finally:
        staged.unlink(missing_ok=True)
    return {'status': 'saved'}


# ---------------------------------------------------------------- attachment conversion (MarkItDown)

MAX_CONVERT_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_CONVERT_TEXT_CHARS = 1_000_000
INVALID_LINK_ERROR = 'Liên kết YouTube không hợp lệ.'
YOUTUBE_ID = r'[A-Za-z0-9_-]{5,}'
YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be', 'm.youtu.be'}
# Exactly the link shapes the composer accepts: /watch?v=, youtu.be/, /shorts/ and /embed/
# (www. and m. tolerated, extra query parameters tolerated).
YOUTUBE_PATTERNS = (
    re.compile(rf'^https?://(?:www\.|m\.)?youtube\.com/watch/?\?(?:[^#]*&)?v={YOUTUBE_ID}(?:&[^#]*)?(?:#.*)?$', re.IGNORECASE),
    re.compile(rf'^https?://(?:www\.|m\.)?youtu\.be/{YOUTUBE_ID}(?:\?[^#]*)?(?:#.*)?$', re.IGNORECASE),
    re.compile(rf'^https?://(?:www\.|m\.)?youtube\.com/(?:shorts|embed)/{YOUTUBE_ID}(?:[?#].*)?$', re.IGNORECASE),
)

_markitdown = None
_markitdown_lock = threading.Lock()


def markitdown_reader():
    """Shared MarkItDown instance, built lazily because it loads a detection model."""
    global _markitdown
    if _markitdown is None:
        with _markitdown_lock:
            if _markitdown is None:
                from markitdown import MarkItDown
                _markitdown = MarkItDown()
    return _markitdown


def markitdown_text(result):
    return getattr(result, 'markdown', None) or result.text_content


def convert_upload(path):
    """Convert one uploaded file to Markdown/text. Blocking: call through asyncio.to_thread."""
    return markitdown_text(markitdown_reader().convert_local(path))


def convert_link(url):
    """Convert one validated YouTube link to text. Blocking: call through asyncio.to_thread."""
    return markitdown_text(markitdown_reader().convert(url))


def youtube_source(value):
    """Return the trimmed URL when `value` is exactly one supported YouTube link."""
    raw = (value or '').strip()
    if not raw or any(char.isspace() for char in raw):
        raise ValueError(INVALID_LINK_ERROR)
    if not any(pattern.match(raw) for pattern in YOUTUBE_PATTERNS):
        raise ValueError(INVALID_LINK_ERROR)
    if (urlsplit(raw).hostname or '').lower() not in YOUTUBE_HOSTS:
        raise ValueError(INVALID_LINK_ERROR)
    return raw


def safe_upload_name(filename):
    """Basename only: traversal-style names (../../x.txt) must never escape the temp folder."""
    name = os.path.basename((filename or '').replace('\\', '/')).strip()
    return name or 'upload'


@app.post('/api/convert')
async def convert_attachment(file: UploadFile | None = File(None), url: str | None = Form(None)):
    """One attachment -> {"text": ...}: either a multipart upload or a YouTube link."""
    has_file = file is not None
    has_url = bool((url or '').strip())
    if has_file == has_url:
        raise HTTPException(400, 'Hãy chọn một tệp hoặc dán một liên kết YouTube.')

    if has_file:
        data = await file.read()
        if not data:
            raise HTTPException(400, 'Tệp rỗng, không có nội dung để chuyển đổi.')
        if len(data) > MAX_CONVERT_UPLOAD_BYTES:
            raise HTTPException(413, 'Tệp quá lớn (tối đa 25 MiB).')
        directory = Path(tempfile.mkdtemp(prefix='cret2-convert-'))
        try:
            path = directory / safe_upload_name(file.filename)
            path.write_bytes(data)
            try:
                text = await asyncio.to_thread(convert_upload, str(path))
            except Exception as exc:
                print(f'[chuyển đổi] lỗi khi đọc tệp: {exc.__class__.__name__}: {exc}', file=sys.stderr)
                raise HTTPException(422, 'Không chuyển được tệp sang văn bản.')
        finally:
            shutil.rmtree(directory, ignore_errors=True)
    else:
        try:
            source = youtube_source(url)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        try:
            text = await asyncio.to_thread(convert_link, source)
        except Exception as exc:
            print(f'[chuyển đổi] lỗi khi đọc liên kết YouTube: {exc.__class__.__name__}: {exc}', file=sys.stderr)
            raise HTTPException(422, 'Không chuyển được liên kết YouTube sang văn bản.')

    if not isinstance(text, str) or not text.strip():
        raise HTTPException(422, 'Nội dung sau khi chuyển đổi rỗng.')
    if len(text) > MAX_CONVERT_TEXT_CHARS:
        raise HTTPException(413, 'Nội dung sau khi chuyển đổi quá dài (tối đa 1.000.000 ký tự).')
    return {'text': text}


# ---------------------------------------------------------------- AI call

class PipelineError(Exception):
    pass


async def ai_call(user_message, images=None):
    endpoint, token, model = settings.endpoint, settings.token, settings.model
    if not endpoint or not model:
        raise PipelineError('Chưa cấu hình AI. Mở trang /settings để đặt đường dẫn và tên mô hình.')
    # Multimodal turns send a content part array; plain turns keep the string form.
    content = user_message
    if images:
        content = [{'type': 'text', 'text': user_message}] + [dict(part) for part in images]
    body = {'model': model, 'messages': [{'role': 'user', 'content': content}], 'stream': True}
    effort = (settings.thinking_effort or 'Off').strip().lower()
    if effort and effort != 'off':
        body['reasoning_effort'] = effort
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    chunks = []
    try:
        async with api_client().stream('POST', endpoint, headers=headers, json=body) as response:
            if response.is_error:
                await response.aread()
                raise PipelineError(f'AI trả về HTTP {response.status_code}: {response.text.strip()[:300]}')
            if 'application/json' in response.headers.get('content-type', ''):
                # Provider answered non-streaming anyway.
                data = json.loads(await response.aread())
                content = data['choices'][0]['message'].get('content') or ''
                if isinstance(content, list):
                    content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
                return content
            async for line in response.aiter_lines():
                if not line.startswith('data:'):
                    continue
                payload = line[5:].strip()
                if payload == '[DONE]':
                    break
                try:
                    data = json.loads(payload)
                except ValueError:
                    continue
                if data.get('error'):
                    raise PipelineError('Nhà cung cấp báo lỗi khi sinh nội dung. Vui lòng thử lại.')
                for choice in data.get('choices', []):
                    text = choice.get('delta', {}).get('content')
                    if text:
                        chunks.append(text)
    except httpx.HTTPError as exc:
        raise PipelineError(f'Không kết nối được tới endpoint AI ({endpoint}): {exc.__class__.__name__}: {exc}') from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise PipelineError('Endpoint AI trả về định dạng không hợp lệ.') from exc
    content = ''.join(chunks)
    if not content.strip():
        raise PipelineError('Mô hình trả về phản hồi rỗng.')
    return content


# ---------------------------------------------------------------- fence extraction

def extract_block(text, open_tag, close_tag):
    """Content between e.g. ```material ... endmaterial```. None when no fence at all."""
    t = text.replace('\r\n', '\n').replace('\r', '\n')
    word = close_tag[:-3]  # 'endmaterial' / 'endquiz'
    t = re.sub(re.escape(word) + r'[ \t]*\n[ \t]*```', close_tag, t)
    t = re.sub(r'```[ \t]*\n[ \t]*' + re.escape(open_tag[3:]), open_tag, t)
    i = t.find(open_tag)
    if i == -1:
        return None
    start = i + len(open_tag)
    if t.startswith('\n', start):
        start += 1
    j = t.find(close_tag, start)
    if j == -1:
        return t[start:].strip()
    return t[start:j].strip()


# ---------------------------------------------------------------- quiz repair (ported from quiz.html)

def find_next_non_space(text, start_index):
    for i in range(start_index, len(text)):
        if not text[i].isspace():
            return text[i]
    return ''


def replace_smart_quotes(text):
    return (text.replace('\u201c', '"').replace('\u201d', '"')
                .replace('\u2018', "'").replace('\u2019', "'"))


def strip_code_fence_noise(text):
    text = re.sub(r'^\s*```(?:json|javascript|js)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.IGNORECASE)
    return text


def convert_single_quoted_strings(text):
    def repl(match):
        value = match.group(1).replace("\\'", "'").replace('\\n', '\n')
        return json.dumps(value, ensure_ascii=False)
    return re.sub(r"'([^'\\]*(?:\\.[^'\\]*)*)'", repl, text)


def quote_unquoted_keys(text):
    def repl(match):
        return match.group(1) + json.dumps(match.group(2)) + match.group(3)
    return re.sub(r'([{,]\s*)([A-Za-z_$][A-Za-z0-9_$-]*)(\s*:)', repl, text)


def quote_unquoted_simple_values(text):
    def repl(match):
        raw_value, spacing = match.group(1), match.group(2)
        value = raw_value.strip()
        if value == '':
            return ': ' + raw_value + spacing
        if re.match(r'^-?\d+(\.\d+)?([eE][+-]?\d+)?$', value):
            return ': ' + value + spacing
        if re.match(r'^(true|false|null)$', value, re.IGNORECASE):
            return ': ' + value.lower() + spacing
        return ': ' + json.dumps(value, ensure_ascii=False) + spacing
    return re.sub(r':\s*([^"\{\[\]\},\n][^,\}\]\n]*?)(\s*)(?=,|\}|\])', repl, text)


def escape_bad_characters_inside_strings(text):
    result = []
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
                escaped = False
            continue
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == '\\':
            result.append(ch)
            escaped = True
            continue
        if ch == '"':
            next_non_space = find_next_non_space(text, i + 1)
            if next_non_space in (',', '}', ']', ':', ''):
                result.append(ch)
                in_string = False
            else:
                result.append('\\"')
            continue
        if ch == '\n':
            result.append('\\n')
            continue
        if ch == '\t':
            result.append('\\t')
            continue
        result.append(ch)
    return ''.join(result)


def remove_trailing_commas(text):
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def repair_json_like_text(text):
    result = text.replace('\ufeff', '')
    result = result.replace('\r\n', '\n').replace('\r', '\n')
    result = replace_smart_quotes(result)
    result = strip_code_fence_noise(result)
    result = convert_single_quoted_strings(result)
    result = quote_unquoted_keys(result)
    result = quote_unquoted_simple_values(result)
    result = escape_bad_characters_inside_strings(result)
    result = remove_trailing_commas(result)
    return result.strip()


def parse_possibly_broken_json(text):
    attempts = [text, repair_json_like_text(text), repair_json_like_text(repair_json_like_text(text))]
    last_error = None
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except ValueError as exc:
            last_error = exc
    raise ValueError('Phân tích JSON thất bại: ' + str(last_error))


def validate_quiz(value):
    if not isinstance(value, list):
        raise ValueError('Khối trắc nghiệm không chứa mảng JSON.')
    for i, question in enumerate(value, 1):
        if not isinstance(question, dict):
            raise ValueError(f'Câu #{i} không phải là một object.')
        if 'question' not in question:
            raise ValueError(f'Câu #{i} thiếu nội dung đề bài.')
        options = question.get('options')
        if not isinstance(options, list):
            raise ValueError(f'Câu #{i} thiếu mảng đáp án.')
        if len(options) != 4:
            raise ValueError(f'Câu #{i} phải có đúng 4 đáp án.')
        for j, option in enumerate(options, 1):
            if not isinstance(option, dict):
                raise ValueError(f'Câu #{i}, đáp án #{j} không phải là một object.')
            if 'label' not in option or 'value' not in option:
                raise ValueError(f'Câu #{i}, đáp án #{j} thiếu label hoặc value.')
        if 'correct' not in question:
            raise ValueError(f'Câu #{i} thiếu đáp án đúng.')
        correct = str(question['correct'])
        matches = sum(1 for option in options if str(option['value']) == correct)
        if matches != 1:
            raise ValueError(f'Đáp án đúng của câu #{i} không khớp đúng với một giá trị đáp án: {json.dumps(question["correct"], ensure_ascii=False)}')
    return value


def normalize_quiz(parsed, do_randomize):
    questions = []
    for question in parsed:
        options = list(question['options'])
        if do_randomize:
            random.shuffle(options)
        correct = str(question['correct'])
        new_correct = ''
        new_options = []
        for index, option in enumerate(options):
            label = OPTION_VALUES[index]
            if str(option['value']) == correct:
                new_correct = label
            new_options.append({'label': option['label'], 'value': label})
        questions.append({
            'id': 0,
            'question': question['question'],
            'options': new_options,
            'correct': new_correct,
            'explanation': question.get('explanation', ''),
        })
    if do_randomize:
        random.shuffle(questions)
    for index, question in enumerate(questions, 1):
        question['id'] = index
    return questions


# ---------------------------------------------------------------- share

async def share_state(cfg, state):
    backend = cfg['quiz_backend_base'].rstrip('/')
    detail_prefix = f'Không tạo được liên kết học (quiz backend tại {backend})'
    try:
        response = await app.state.direct_client.post(backend + '/newmaterial', json={'text': json.dumps(state, ensure_ascii=False)})
    except httpx.HTTPError as exc:
        raise PipelineError(f'{detail_prefix}: {exc.__class__.__name__}: {exc}') from exc
    if response.is_error:
        raise PipelineError(f'{detail_prefix}: HTTP {response.status_code} {response.text.strip()[:200]}')
    try:
        data = response.json()
        material_id = data['id']
    except (ValueError, KeyError, TypeError) as exc:
        raise PipelineError(f'{detail_prefix}: phản hồi không hợp lệ.') from exc
    if not isinstance(material_id, str) or len(material_id) != 6:
        raise PipelineError(f'{detail_prefix}: mã trả về không hợp lệ.')
    return cfg['quiz_frontend_base'].rstrip('/') + '/' + material_id


# ---------------------------------------------------------------- reference (existing vtask.fun lesson)

REFERENCE_LINK_RE = re.compile(r'^https://vtask\.fun/(?P<path>[^?#]*)$', re.IGNORECASE)
REFERENCE_CODE_RE = re.compile(r'^[A-Za-z0-9_-]{6}$')
REFERENCE_INVALID_ERROR = 'Liên kết tham chiếu không hợp lệ.'
REFERENCE_PROMPT_LABEL = (
    'REFERENCE MATERIAL (existing lesson; use it to clarify and deepen the specific hard part '
    "of the user's topic; keep its technical terms/notation consistent; do NOT copy its quiz):"
)


def parse_reference(value):
    """Resolve an optional reference to its 6-character lesson code.

    Accepts exactly two forms: the full link https://vtask.fun/<code> (whitespace
    and a trailing slash tolerated) or a bare code such as UmezbI. Returns '' for
    an empty value and raises ValueError(REFERENCE_INVALID_ERROR) for anything else.
    """
    raw = re.sub(r'\s+', '', value or '')
    if not raw:
        return ''
    match = REFERENCE_LINK_RE.match(raw)
    if match:
        segments = [segment for segment in match.group('path').split('/') if segment]
        code = segments[-1] if segments else ''
    else:
        code = raw
    if not REFERENCE_CODE_RE.match(code):
        raise ValueError(REFERENCE_INVALID_ERROR)
    return code


async def fetch_reference_material(cfg, code):
    """Load the lesson state for `code` and return ONLY its "material" text.

    The state's "questions" (quiz) part is deliberately never used.
    """
    backend = cfg['quiz_backend_base'].rstrip('/')
    detail_prefix = f'Không tải được bài tham chiếu (quiz backend tại {backend})'
    try:
        response = await app.state.direct_client.get(backend + '/material/' + code)
    except httpx.HTTPError as exc:
        raise PipelineError(f'{detail_prefix}: {exc.__class__.__name__}: {exc}') from exc
    if response.status_code == 404:
        raise PipelineError(f'Không tìm thấy bài tham chiếu với mã {code}.')
    if response.is_error:
        raise PipelineError(f'{detail_prefix}: HTTP {response.status_code} {response.text.strip()[:200]}')
    try:
        payload = response.json()
        state = json.loads(payload['text'])
    except (ValueError, KeyError, TypeError) as exc:
        raise PipelineError(f'{detail_prefix}: phản hồi không hợp lệ.') from exc
    material = state.get('material') if isinstance(state, dict) else None
    if not isinstance(material, str) or not material.strip():
        raise PipelineError(f'Bài tham chiếu với mã {code} không chứa nội dung học liệu hợp lệ.')
    return material


# ---------------------------------------------------------------- quiz feedback repair

QUIZ_REPAIR_ATTEMPTS = 2


def build_quiz_repair_prompt(original_prompt, broken_reply, error_text):
    """One feedback message: the original task, the exact broken reply, the exact error."""
    return (
        'Your previous answer to this quiz task failed the validation check.\n\n'
        'TASK (original prompt):\n' + original_prompt + '\n\n'
        'YOUR PREVIOUS ANSWER (broken output):\n' + broken_reply + '\n\n'
        'VALIDATION ERROR:\n' + error_text + '\n\n'
        'Fix the quiz so it passes the check. Return ONLY the corrected quiz in the same '
        'contract: a single fenced block ```quiz ... endquiz``` containing a valid JSON '
        'array of questions in Vietnamese, no extra text outside the fence.'
    )


# ---------------------------------------------------------------- generate request (input + attachments)

MAX_INPUT_CHARS = 1_000_000
MAX_ATTACHMENTS = 20
MAX_IMAGES = 10
MAX_IMAGE_RAW_BYTES = 20 * 1024 * 1024
IMAGE_DATA_URL_RE = re.compile(r'^data:(image/(?:png|jpeg|webp|gif));base64,([A-Za-z0-9+/]+={0,2})$', re.IGNORECASE)


class SourcePart(BaseModel):
    """Text converted from one document, audio file or YouTube link."""

    name: str = Field(default='', max_length=500)
    text: str = Field(min_length=1, max_length=MAX_CONVERT_TEXT_CHARS)


class ImageUrlPart(BaseModel):
    url: str = Field(min_length=1, max_length=MAX_REQUEST_BYTES)


class ImagePart(BaseModel):
    type: str = 'image_url'
    image_url: ImageUrlPart


class GenerateRequest(BaseModel):
    input: str | None = Field(default=None, max_length=MAX_INPUT_CHARS)
    reference: str | None = Field(default=None, max_length=2000)
    sources: list[SourcePart] = Field(default_factory=list)
    images: list[ImagePart] = Field(default_factory=list)

    @field_validator('sources', mode='before')
    @classmethod
    def _normalize_sources(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        normalized = []
        for item in value:
            if isinstance(item, str):
                normalized.append({'text': item})
            elif isinstance(item, dict) and 'text' in item:
                normalized.append({'name': str(item.get('name') or ''), 'text': item['text']})
            else:
                normalized.append(item)
        return normalized

    @field_validator('images', mode='before')
    @classmethod
    def _normalize_images(cls, value):
        """Accept plain data URLs, {'data_url': ...} or OpenAI-style image content parts."""
        if value is None:
            return []
        if not isinstance(value, list):
            return value
        normalized = []
        for item in value:
            if isinstance(item, str):
                normalized.append({'type': 'image_url', 'image_url': {'url': item}})
            elif isinstance(item, dict):
                if isinstance(item.get('data_url'), str):
                    normalized.append({'type': 'image_url', 'image_url': {'url': item['data_url']}})
                elif isinstance(item.get('image_url'), str):
                    normalized.append({'type': 'image_url', 'image_url': {'url': item['image_url']}})
                elif isinstance(item.get('image_url'), dict):
                    normalized.append({'type': 'image_url', 'image_url': dict(item['image_url'])})
                else:
                    normalized.append(item)
            else:
                normalized.append(item)
        return normalized


def validate_attachments(body):
    """Attachment caps and image checks; raises before any generation starts."""
    sources, images = body.sources, body.images
    if len(sources) + len(images) > MAX_ATTACHMENTS:
        raise HTTPException(422, f'Tối đa {MAX_ATTACHMENTS} tệp đính kèm.')
    if len(images) > MAX_IMAGES:
        raise HTTPException(422, f'Tối đa {MAX_IMAGES} ảnh.')
    for part in images:
        match = IMAGE_DATA_URL_RE.match(part.image_url.url.strip())
        if match is None or len(match.group(2)) % 4:
            raise HTTPException(422, 'Ảnh không hợp lệ (chỉ chấp nhận PNG, JPEG, WebP, GIF dạng data URL).')
        if len(match.group(2)) // 4 * 3 > MAX_IMAGE_RAW_BYTES:
            raise HTTPException(413, 'Ảnh quá lớn (tối đa 20 MiB mỗi ảnh).')
    return sources, images


def join_source(user_input, sources):
    """Typed input first, then the converted attachment text as source material, in insertion order."""
    chunks = []
    if (user_input or '').strip():
        chunks.append(user_input.strip())
    for source in sources:
        text = (source.get('text') or '').strip()
        if text:
            chunks.append(text)
    return '\n\n'.join(chunks)


# ---------------------------------------------------------------- generation pipeline

async def run_pipeline(queue, user_input, reference='', images=None):
    cfg = load_config()
    user_input = user_input or ''
    images = list(images or [])
    if not user_input.strip() and not images:
        raise PipelineError('Hãy nhập nội dung bạn muốn học.')
    try:
        reference_code = parse_reference(reference)
    except ValueError as exc:
        raise PipelineError(str(exc))
    reference_material = await fetch_reference_material(cfg, reference_code) if reference_code else ''
    steps = cfg['steps']
    # Images ride along with the first enabled step that consumes the raw input.
    image_step = next((name for name in ('material', 'quiz', 'interactive') if steps[name]['enabled']), None)

    material_text = user_input
    if steps['material']['enabled']:
        await queue.put({'stage': 'material'})
        prompt = steps['material']['template'] + '\n\n' + user_input
        if reference_material:
            prompt += '\n\n' + REFERENCE_PROMPT_LABEL + '\n' + reference_material
        reply = await ai_call(prompt, images if image_step == 'material' else None)
        extracted = extract_block(reply, '```material', 'endmaterial```')
        material_text = extracted if extracted is not None else reply
        if not material_text.strip():
            raise PipelineError('Mô hình không trả về khối học liệu nào.')

    questions = []
    if steps['quiz']['enabled']:
        await queue.put({'stage': 'quiz'})
        quiz_prompt = steps['quiz']['template'] + '\n\n' + material_text
        quiz_images = images if image_step == 'quiz' else None
        reply = await ai_call(quiz_prompt, quiz_images)
        parsed = None
        for attempt in range(QUIZ_REPAIR_ATTEMPTS + 1):
            extracted = extract_block(reply, '```quiz', 'endquiz```')
            raw_quiz = extracted if extracted is not None else reply
            try:
                parsed = parse_possibly_broken_json(raw_quiz)
                validate_quiz(parsed)
                break
            except ValueError as exc:
                print('[trắc nghiệm] nội dung khối trắc nghiệm thô như sau', file=sys.stderr)
                print(raw_quiz, file=sys.stderr)
                if attempt >= QUIZ_REPAIR_ATTEMPTS:
                    raise PipelineError('Không phân tích được nội dung trắc nghiệm: ' + str(exc))
                print(f'[trắc nghiệm] yêu cầu sửa lỗi lần {attempt + 1}/{QUIZ_REPAIR_ATTEMPTS}: {exc}', file=sys.stderr)
                reply = await ai_call(build_quiz_repair_prompt(quiz_prompt, reply, str(exc)), quiz_images)
        questions = normalize_quiz(parsed, bool(cfg['randomize']))

    if steps['interactive']['enabled']:
        await queue.put({'stage': 'interactive'})
        reply = await ai_call(steps['interactive']['template'] + '\n\n' + material_text,
                              images if image_step == 'interactive' else None)
        extracted = extract_block(reply, '```material', 'endmaterial```')
        replacement = extracted if extracted is not None else reply
        if replacement.strip():
            material_text = replacement

    await queue.put({'stage': 'share'})
    state = {
        'version': '1.0',
        'material': material_text,
        'questions': questions,
        'originalMessage': user_input,
        'timestamp': int(time.time() * 1000),
    }
    return await share_state(cfg, state)


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    print('[request] validation error:', exc.errors(), file=sys.stderr)
    for err in exc.errors():
        if err.get('type') == 'string_too_long':
            return JSONResponse(status_code=422, content={'detail': 'Nội dung quá dài (giới hạn 1.000.000 ký tự).'})
    return JSONResponse(status_code=422, content={'detail': 'Dữ liệu gửi lên không hợp lệ. Vui lòng thử lại.'})


@app.post('/api/generate')
async def generate(body: GenerateRequest | None = None):
    body = body or GenerateRequest()
    sources, images = validate_attachments(body)
    source_payload = [{'name': source.name, 'text': source.text} for source in sources]
    image_payload = [part.model_dump() for part in images]
    # Converted attachments land after the typed input, as extra source material.
    material_input = join_source(body.input or '', source_payload)
    if len(material_input) > MAX_INPUT_CHARS:
        raise HTTPException(422, 'Nội dung quá dài (giới hạn 1.000.000 ký tự).')
    queue = asyncio.Queue()

    async def produce():
        try:
            link = await run_pipeline(queue, material_input, body.reference or '', image_payload)
            await queue.put({'done': True, 'link': link})
        except PipelineError as exc:
            await queue.put({'error': str(exc)})
        except Exception:
            import traceback
            traceback.print_exc()
            await queue.put({'error': 'Tạo nội dung thất bại ngoài dự kiến.'})
        await queue.put(None)

    async def ping():
        try:
            while True:
                await asyncio.sleep(10)
                await queue.put({'ping': True})
        except asyncio.CancelledError:
            pass

    producer = asyncio.create_task(produce())
    pinger = asyncio.create_task(ping())

    async def events():
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + '\n'
        finally:
            pinger.cancel()
            producer.cancel()

    return StreamingResponse(events(), media_type='application/x-ndjson', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
