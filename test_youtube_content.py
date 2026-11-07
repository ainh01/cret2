"""Test hồi quy OFFLINE cho t11 — KHÔNG gọi youtube.com, KHÔNG gọi AI,
KHÔNG ghi gì lên backend production.

Chạy:  python test_youtube_content.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
import app

client = TestClient(app.app, raise_server_exceptions=False)

# --------------------------------------------------------------------------
# Hai hình dạng HỎNG lấy từ bằng chứng thật của t7
# --------------------------------------------------------------------------

# (a) Footer boilerplate: MarkItDown fallback sang HtmlConverter khi trang video
#     không có ytInitialData. Chuỗi này giống hệt nhau ở mọi link chết.
FOOTER_BOILERPLATE = (
    "[Giới thiệu](https://www.youtube.com/about/)[Báo chí](https://www.youtube.com/t/press)"
    "[Bản quyền](https://www.youtube.com/about/copyright/)[Liên hệ](https://www.youtube.com/t/contact_us/)"
    "[Nhà sáng tạo](https://www.youtube.com/creators/)[Quảng cáo](https://www.youtube.com/ads/)"
    "[Nhà phát triển](https://developers.google.com/youtube)"
    "[Điều khoản](https://www.youtube.com/t/terms)[Quyền riêng tư](https://www.youtube.com/t/privacy)"
    "[Chính sách & An toàn](https://www.youtube.com/about/policies/)"
    "[Cách YouTube hoạt động](https://www.youtube.com/howyoutubeworks?utm_campaign=ytgen&utm_source=ythp&utm_medium=LeftNav&utm_content=txt&u=https%3A%2F%2Fwww.youtube.com%2Fhowyoutubeworks%3Futm_source%3Dythp%26utm_medium%3DLeftNav%26utm_campaign%3Dytgen)"
    "[Thử YouTube mới](https://www.youtube.com/new)"
    "© 2026 Google LLC"
)

# (b) Title-only: video CÓ tồn tại nhưng THIẾU TRANSCRIPT — đúng ca JhHcch của
#     người dùng. MarkItDown nuốt exception lấy transcript và bỏ luôn mục đó.
TITLE_ONLY = "# YouTube\n\n## Rick Astley - Never Gonna Give You Up (Official Video)\n"

# --------------------------------------------------------------------------
# Các hình dạng THẬT phải tiếp tục được CHẤP NHẬN (chống từ chối nhầm)
# --------------------------------------------------------------------------

REAL_WITH_TRANSCRIPT = (
    "# YouTube\n\n## Rick Astley - Never Gonna Give You Up (Official Video)\n\n"
    "### Video Metadata\n- **Keywords:** rick astley, never gonna give you up\n\n"
    "### Transcript\n\n[00:00] We're no strangers to love\n[00:04] You know the rules and so do I\n"
)

REAL_WITH_DESCRIPTION = (
    "# YouTube\n\n## Some Talk About Code\n\n"
    "### Description\n\nA short talk about writing tests.\n"
)

# Tệp tải lên bình thường: KHÔNG có hình dạng YouTube, phải đi qua nguyên vẹn.
PLAIN_UPLOAD = "Xin chào, đây là ghi chú của tôi.\n"


def run_convert_url(monkey_payload):
    """Gọi /api/convert nhánh URL với convert_link đã bị thay bằng stub."""
    original = app.convert_link
    app.convert_link = lambda url: monkey_payload
    try:
        return client.post('/api/convert', data={'url': 'https://youtu.be/dQw4w9WgXcQ'})
    finally:
        app.convert_link = original


def run_convert_upload(payload):
    """Gọi /api/convert nhánh upload với convert_upload đã bị thay bằng stub."""
    original = app.convert_upload
    app.convert_upload = lambda path: payload
    try:
        return client.post('/api/convert', files={'file': ('note.txt', b'noi dung', 'text/plain')})
    finally:
        app.convert_upload = original


failures = 0


def check(name, condition, detail=''):
    global failures
    if condition:
        print(f'PASS  {name}')
    else:
        failures += 1
        print(f'FAIL  {name}')
        if detail:
            print(f'        {detail}')


print('=== NHÓM 1: text KHÔNG phải nội dung video -> phải bị TỪ CHỐI 422 ===')

r = run_convert_url(FOOTER_BOILERPLATE)
body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
check('(a) footer boilerplate -> 422', r.status_code == 422, f'status={r.status_code} body={r.text[:200]}')
check('(a) thông báo tiếng Việt đúng chuỗi', body.get('detail') == app.EMPTY_VIDEO_ERROR,
      f'detail={body.get("detail")!r}')
check('(a) KHÔNG trả về {"text": ...}', 'text' not in body, f'body={body}')

r = run_convert_url(TITLE_ONLY)
body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
check('(b) title-only (ca JhHcch) -> 422', r.status_code == 422, f'status={r.status_code} body={r.text[:200]}')
check('(b) thông báo tiếng Việt đúng chuỗi', body.get('detail') == app.EMPTY_VIDEO_ERROR,
      f'detail={body.get("detail")!r}')
check('(b) KHÔNG trả về {"text": ...}', 'text' not in body, f'body={body}')


print()
print('=== NHÓM 2: nội dung video THẬT -> phải VẪN được chấp nhận 200 ===')

r = run_convert_url(REAL_WITH_TRANSCRIPT)
body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
check('video thật có ### Transcript -> 200', r.status_code == 200, f'status={r.status_code} body={r.text[:200]}')
check('video thật -> text nguyên vẹn', body.get('text') == REAL_WITH_TRANSCRIPT, f'text={body.get("text")!r}')

r = run_convert_url(REAL_WITH_DESCRIPTION)
body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
check('video thật có ### Description -> 200', r.status_code == 200, f'status={r.status_code} body={r.text[:200]}')
check('video thật -> text nguyên vẹn', body.get('text') == REAL_WITH_DESCRIPTION, f'text={body.get("text")!r}')


print()
print('=== NHÓM 3: nhánh UPLOAD không bị ảnh hưởng ===')

r = run_convert_upload(PLAIN_UPLOAD)
body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
check('upload .txt thường -> 200', r.status_code == 200, f'status={r.status_code} body={r.text[:200]}')
check('upload -> text nguyên vẹn', body.get('text') == PLAIN_UPLOAD, f'text={body.get("text")!r}')

# Tệp tải lên chứa ĐÚNG chuỗi footer: đây là nội dung người dùng thật, KHÔNG được chặn.
r = run_convert_upload(FOOTER_BOILERPLATE)
body = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
check('upload chứa chuỗi footer -> VẪN 200 (không chặn nhầm)',
      r.status_code == 200, f'status={r.status_code} body={r.text[:200]}')

r = run_convert_upload('')
check('upload rỗng -> vẫn 422 với lỗi cũ', r.status_code == 422, f'status={r.status_code}')


print()
print('=== NHÓM 4: join_source giữ URL nguồn trong prompt (Fix 2) ===')

joined = app.join_source('', [{'name': 'https://youtu.be/dQw4w9WgXcQ', 'text': TITLE_ONLY}])
check('có nhãn "Nguồn:" + URL', 'Nguồn: https://youtu.be/dQw4w9WgXcQ' in joined, f'joined={joined[:160]!r}')
check('text gốc vẫn còn nguyên', TITLE_ONLY.strip() in joined, f'joined={joined[:160]!r}')

joined = app.join_source('Dạy tôi bài này', [
    {'name': 'https://youtu.be/aaa', 'text': 'TEXT A'},
    {'name': 'https://youtu.be/bbb', 'text': 'TEXT B'},
])
check('input người dùng đứng ĐẦU', joined.startswith('Dạy tôi bài này'), f'joined={joined[:120]!r}')
check('giữ đúng thứ tự sources', joined.index('youtu.be/aaa') < joined.index('youtu.be/bbb'), f'joined={joined[:200]!r}')

joined = app.join_source('', [{'name': '', 'text': 'TEXT KHONG TEN'}])
check('source không có name -> không thêm nhãn rỗng', joined == 'TEXT KHONG TEN', f'joined={joined!r}')

joined = app.join_source('', [{'name': 'https://x/1', 'text': '   '}])
check('source text rỗng -> bị bỏ qua như cũ', joined == '', f'joined={joined!r}')

print()
if failures:
    print(f'{failures} FAILED')
    sys.exit(1)
print('tất cả assertion PASS')
