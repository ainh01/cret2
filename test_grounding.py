"""Offline regression tests for the source-grounded generation pipeline."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf
import app


SCHEMA = {'concepts': [{'concept': 'THD+N', 'details': '-95 dB at 20 mW',
                        'evidence': 'THD+N = -95 dB (20 mW)', 'location': 'PDF page 1'}],
          'uncertainties': ['No latency is specified'], 'outline': ['Audio specifications']}
QUESTION = {'question': 'At what power?', 'options': [
    {'label': v, 'value': v} for v in 'ABCD'], 'correct': 'A', 'explanation': '20 mW'}
CONFIG = {'quiz_frontend_base': 'https://example.com', 'quiz_backend_base': 'https://example.com',
          'randomize': False, 'steps': {'material': {'enabled': True, 'template': 'ENRICH'},
          'quiz': {'enabled': True, 'template': 'Generate 6 questions'},
          'interactive': {'enabled': False, 'template': ''}}}
SOURCE = '[Trang PDF 1]\nTHD+N = -95 dB (20 mW)\nSidetone function; no latency specified.'


def material_review(text):
    return app.REVIEW_MATERIAL_BEGIN + '\n' + text + '\n' + app.REVIEW_MATERIAL_END


def quiz_review(questions):
    return app.REVIEW_QUIZ_BEGIN + '\n' + json.dumps(questions, ensure_ascii=False) + '\n' + app.REVIEW_QUIZ_END


class GroundingTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_stage_gets_original_and_verified_output_is_shared(self):
        calls, saved = [], []
        async def fake_ai(prompt, images=None):
            calls.append(prompt)
            if prompt.startswith('STAGE: KNOWLEDGE'):
                return json.dumps(SCHEMA)
            if prompt.startswith('STAGE: CREATE'):
                return '```material\nDraft with 0 ms latency\nendmaterial```'
            if prompt.startswith('ENRICH'):
                return '```material\nEnriched with 0 ms latency\nendmaterial```'
            if prompt.startswith('Generate'):
                return '```quiz\n' + json.dumps([QUESTION]) + '\nendquiz```'
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                return material_review('Corrected: latency is not specified.')
            if prompt.startswith('STAGE: SOURCE REVIEW QUIZ'):
                return quiz_review([QUESTION])
            self.fail('Unexpected prompt')
        async def fake_share(config, state):
            saved.append(state)
            return 'https://example.com/abcdef'
        queue = asyncio.Queue()
        with patch.object(app, 'load_config', return_value=CONFIG), patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'share_state', fake_share):
            await app.run_pipeline(queue, SOURCE, question_count=1)
        self.assertEqual(len(calls), 6)
        for prompt in calls:
            self.assertIn(SOURCE, prompt)
        self.assertIn('Draft with 0 ms', calls[2])
        self.assertIn('Enriched with 0 ms', calls[4])
        self.assertEqual(saved[0]['material'], 'Corrected: latency is not specified.')
        self.assertEqual(len(saved[0]['questions']), 1)
        self.assertEqual([queue.get_nowait()['stage'] for _ in range(queue.qsize())],
                         ['schema', 'draft', 'material', 'quiz', 'verify', 'share'])

    async def test_invalid_review_prevents_publication(self):
        async def fake_ai(prompt, images=None):
            if prompt.startswith('STAGE: KNOWLEDGE'):
                return json.dumps(SCHEMA)
            if prompt.startswith('STAGE: CREATE') or prompt.startswith('ENRICH'):
                return '```material\nDraft\nendmaterial```'
            if prompt.startswith('Generate'):
                return '```quiz\n' + json.dumps([QUESTION]) + '\nendquiz```'
            return '{bad json'
        with patch.object(app, 'load_config', return_value=CONFIG), patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'share_state') as share:
            with self.assertRaisesRegex(app.PipelineError, 'chưa chia sẻ'):
                await app.run_pipeline(asyncio.Queue(), SOURCE, question_count=1)
            share.assert_not_called()

    def test_schema_json_repaired_locally(self):
        malformed = json.dumps(SCHEMA)[:-1] + ',}'
        self.assertEqual(app.schema_from_reply(malformed), SCHEMA)

    def test_schema_invalid_falls_back_to_raw_text(self):
        self.assertEqual(app.schema_from_reply('{not valid json'), '{not valid json')

    def test_schema_fenced_json_stripped(self):
        self.assertEqual(app.schema_from_reply('```json\n' + json.dumps(SCHEMA) + '\n```'), SCHEMA)

    async def test_invalid_schema_json_does_not_block_publication(self):
        captured = []

        async def fake_ai(prompt, images=None):
            captured.append(prompt)
            if prompt.startswith('STAGE: KNOWLEDGE'):
                return '{not valid json'
            if prompt.startswith('STAGE: CREATE'):
                return '```material\nDraft\nendmaterial```'
            if prompt.startswith('ENRICH'):
                return '```material\nEnriched\nendmaterial```'
            if prompt.startswith('Generate'):
                return '```quiz\n' + json.dumps([QUESTION]) + '\nendquiz```'
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                return material_review('Final lesson')
            if prompt.startswith('STAGE: SOURCE REVIEW QUIZ'):
                return quiz_review([QUESTION])
            self.fail('Unexpected prompt')

        with patch.object(app, 'load_config', return_value=CONFIG), patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'share_state') as share:
            await app.run_pipeline(asyncio.Queue(), SOURCE, question_count=1)
        share.assert_called_once()
        self.assertIn('{not valid json', captured[1])

    async def test_legacy_image_visible_in_every_source_stage(self):
        seen = []
        image = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,abc'}}]
        async def fake_ai(prompt, images=None):
            seen.append(images)
            if prompt.startswith('STAGE: KNOWLEDGE'):
                return json.dumps(SCHEMA)
            if prompt.startswith('STAGE: CREATE') or prompt.startswith('ENRICH'):
                return '```material\nDraft\nendmaterial```'
            if prompt.startswith('Generate'):
                return '```quiz\n' + json.dumps([QUESTION]) + '\nendquiz```'
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                return material_review('Draft')
            return quiz_review([QUESTION])
        async def share(config, state):
            return 'https://example.com/abcdef'
        with patch.object(app, 'load_config', return_value=CONFIG), patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'share_state', share):
            await app.run_pipeline(asyncio.Queue(), '', images=image, question_count=1)
        self.assertEqual(len(seen), 6)
        self.assertTrue(all(item == image for item in seen))

    async def test_long_markdown_never_needs_json_escaping(self):
        lesson = '# Công thức\n\n$\\frac{a}{b}$\n\n```interactive\n<div>"A"</div>\n```\n' + ('Dòng dài.\n' * 2000)
        async def fake_ai(prompt, images=None):
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                return material_review(lesson)
            return quiz_review([QUESTION])
        with patch.object(app, 'ai_call', fake_ai):
            reviewed, questions = await app.review_material_and_quiz(SOURCE, SCHEMA, lesson, [QUESTION], None)
        self.assertEqual(reviewed, lesson.strip())
        self.assertEqual(questions, [QUESTION])

    async def test_review_retries_missing_marker_and_bad_quiz(self):
        attempts = {'material': 0, 'quiz': 0}
        async def fake_ai(prompt, images=None):
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                attempts['material'] += 1
                return 'truncated' if attempts['material'] == 1 else material_review('Đã sửa.')
            attempts['quiz'] += 1
            return quiz_review([]) if attempts['quiz'] == 1 else quiz_review([QUESTION])
        with patch.object(app, 'ai_call', fake_ai):
            material, questions = await app.review_material_and_quiz(SOURCE, SCHEMA, 'Bài', [QUESTION], None)
        self.assertEqual((material, questions), ('Đã sửa.', [QUESTION]))
        self.assertEqual(attempts, {'material': 2, 'quiz': 2})

    async def test_quiz_json_repair_reused(self):
        malformed = json.dumps([QUESTION], ensure_ascii=False).replace('"20 mW"}', '"20 mW",}')
        async def fake_ai(prompt, images=None):
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                return material_review('Đã sửa.')
            return app.REVIEW_QUIZ_BEGIN + '\n' + malformed + '\n' + app.REVIEW_QUIZ_END
        with patch.object(app, 'ai_call', fake_ai):
            material, questions = await app.review_material_and_quiz(SOURCE, SCHEMA, 'Bài', [QUESTION], None)
        self.assertEqual(material, 'Đã sửa.')
        self.assertEqual(questions, [QUESTION])

    async def test_bad_review_question_count_does_not_publish(self):
        async def fake_ai(prompt, images=None):
            if prompt.startswith('STAGE: KNOWLEDGE'):
                return json.dumps(SCHEMA)
            if prompt.startswith('STAGE: CREATE') or prompt.startswith('ENRICH'):
                return '```material\nDraft\nendmaterial```'
            if prompt.startswith('Generate'):
                return '```quiz\n' + json.dumps([QUESTION]) + '\nendquiz```'
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                return material_review('Draft')
            return quiz_review([])
        with patch.object(app, 'load_config', return_value=CONFIG), patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'share_state') as share:
            with self.assertRaisesRegex(app.PipelineError, 'Kiểm tra trắc nghiệm'):
                await app.run_pipeline(asyncio.Queue(), SOURCE, question_count=1)
            share.assert_not_called()


class PdfEvidenceTests(unittest.TestCase):
    def test_page_and_tabular_numbers_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            filename = Path(tmp) / 'table.pdf'
            doc = pymupdf.open()
            page = doc.new_page()
            xs, ys = [50, 180, 280, 370], [120, 150, 180]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            for x, text in zip(xs, ['Parameter', 'Condition', 'Value']):
                page.insert_text((x + 5, 140), text)
            for x, text in zip(xs, ['THD+N', '20mW', '-0.94']):
                page.insert_text((x + 5, 170), text)
            doc.new_page().insert_text((60, 100), 'Second page')
            doc.save(filename)
            doc.close()
            text, _figures = app.convert_pdf(str(filename))
            self.assertIn('[Trang PDF 1]', text)
            self.assertIn('[Trang PDF 2]', text)
            self.assertRegex(text, r'\["THD\+N", (?:"", )?"20mW", (?:"", )?"-0\.94"\]')


if __name__ == '__main__':
    unittest.main()
