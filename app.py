import asyncio
import copy
import json
import os
import random
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from default_config import DEFAULT_CONFIG

ROOT = Path(__file__).parent
load_dotenv(ROOT / '.env')

CONFIG_PATH = ROOT / 'configure.json'
EFFORTS = {'off': 'Off', 'low': 'Low', 'medium': 'Medium', 'high': 'High'}
OPTION_VALUES = ['A', 'B', 'C', 'D']


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


# ---------------------------------------------------------------- AI call

class PipelineError(Exception):
    pass


async def ai_call(user_message):
    endpoint, token, model = settings.endpoint, settings.token, settings.model
    if not endpoint or not model:
        raise PipelineError('Chưa cấu hình AI. Mở trang /settings để đặt đường dẫn và tên mô hình.')
    body = {'model': model, 'messages': [{'role': 'user', 'content': user_message}], 'stream': True}
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


# ---------------------------------------------------------------- generation pipeline

async def run_pipeline(queue, user_input, reference=''):
    cfg = load_config()
    user_input = user_input or ''
    if not user_input.strip():
        raise PipelineError('Hãy nhập nội dung bạn muốn học.')
    try:
        reference_code = parse_reference(reference)
    except ValueError as exc:
        raise PipelineError(str(exc))
    reference_material = await fetch_reference_material(cfg, reference_code) if reference_code else ''
    steps = cfg['steps']

    material_text = user_input
    if steps['material']['enabled']:
        await queue.put({'stage': 'material'})
        prompt = steps['material']['template'] + '\n\n' + user_input
        if reference_material:
            prompt += '\n\n' + REFERENCE_PROMPT_LABEL + '\n' + reference_material
        reply = await ai_call(prompt)
        extracted = extract_block(reply, '```material', 'endmaterial```')
        material_text = extracted if extracted is not None else reply
        if not material_text.strip():
            raise PipelineError('Mô hình không trả về khối học liệu nào.')

    questions = []
    if steps['quiz']['enabled']:
        await queue.put({'stage': 'quiz'})
        reply = await ai_call(steps['quiz']['template'] + '\n\n' + material_text)
        extracted = extract_block(reply, '```quiz', 'endquiz```')
        raw_quiz = extracted if extracted is not None else reply
        try:
            parsed = parse_possibly_broken_json(raw_quiz)
            validate_quiz(parsed)
        except ValueError as exc:
            print('[trắc nghiệm] nội dung khối trắc nghiệm thô như sau', file=sys.stderr)
            print(raw_quiz, file=sys.stderr)
            raise PipelineError('Không phân tích được nội dung trắc nghiệm: ' + str(exc))
        questions = normalize_quiz(parsed, bool(cfg['randomize']))

    if steps['interactive']['enabled']:
        await queue.put({'stage': 'interactive'})
        reply = await ai_call(steps['interactive']['template'] + '\n\n' + material_text)
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


class GenerateRequest(BaseModel):
    input: str | None = Field(default=None, max_length=1000000)
    reference: str | None = Field(default=None, max_length=2000)


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    print('[request] validation error:', exc.errors(), file=sys.stderr)
    for err in exc.errors():
        if err.get('type') == 'string_too_long':
            return JSONResponse(status_code=422, content={'detail': 'Nội dung quá dài (giới hạn 1.000.000 ký tự).'})
    return JSONResponse(status_code=422, content={'detail': 'Dữ liệu gửi lên không hợp lệ. Vui lòng thử lại.'})


@app.post('/api/generate')
async def generate(body: GenerateRequest | None = None):
    queue = asyncio.Queue()

    async def produce():
        try:
            link = await run_pipeline(queue, body.input if body else '', body.reference if body else '')
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
