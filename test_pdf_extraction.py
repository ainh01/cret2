"""Regression tests for PDF extraction and model-only page evidence."""
import asyncio
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf

import app
import pdf_images


class PdfExtractionTests(unittest.TestCase):
    def test_background_does_not_erase_text_and_vector_is_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'slide.pdf'
            doc = pymupdf.open()
            page = doc.new_page(width=792, height=612)
            strip = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 1, 500), 0)
            strip.set_rect(strip.irect, (210, 220, 230))
            page.insert_image(pymupdf.Rect(0, 0, 792, 612), pixmap=strip)
            page.insert_text((70, 150), '1.2 Neighborhood definitions remain visible', fontsize=18)
            page.draw_circle((400, 350), 75, color=(1, 0, 0), fill=(.5, .5, .5))
            page.insert_text((390, 360), 'A', fontsize=18)
            doc.save(path)
            doc.close()
            text, figures, evidence = pdf_images.extract(path, True)
            self.assertIn('Neighborhood definitions remain visible', text)
            self.assertEqual(len(figures), 1)
            self.assertEqual(figures[0]['page'], 1)
            self.assertIn('[[fig:1]]', text)
            self.assertEqual(len(evidence), 1)
            pix = pymupdf.Pixmap(figures[0]['bytes'])
            self.assertGreater(pix.width, 100)
            self.assertGreater(pix.height, 100)
            self.assertLess(pix.height, 1000)

    def test_repeated_large_raster_is_not_rejected_as_logo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'repeated.pdf'
            doc = pymupdf.open()
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), 0)
            pix.set_rect(pix.irect, (255, 255, 255))
            pix.set_rect(pymupdf.IRect(20, 20, 180, 180), (20, 20, 20))
            for _ in range(3):
                page = doc.new_page(width=600, height=800)
                page.insert_text((40, 100), 'Diagram below')
                page.insert_image(pymupdf.Rect(100, 200, 450, 550), pixmap=pix)
            doc.save(path)
            doc.close()
            text, figures = pdf_images.extract(path)
            self.assertEqual([f['page'] for f in figures], [1, 2, 3])
            self.assertEqual([f['id'] for f in figures], ['1', '2', '3'])
            self.assertEqual(text.count('[[fig:'), 3)

    def test_repeated_header_logo_is_not_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'headers.pdf'
            doc = pymupdf.open()
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 60), 0)
            pix.set_rect(pix.irect, (255, 255, 255))
            pix.set_rect(pymupdf.IRect(40, 10, 260, 50), (10, 20, 200))
            for _ in range(3):
                page = doc.new_page(width=600, height=800)
                page.insert_image(pymupdf.Rect(70, 85, 520, 175), pixmap=pix)
                page.insert_text((70, 250), 'Document text')
            doc.save(path)
            doc.close()
            text, figures = pdf_images.extract(path)
            self.assertFalse(figures)
            self.assertIn('Document text', text)

    def test_tall_figure_and_same_page_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'tall.pdf'
            doc = pymupdf.open()
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 300), 0)
            pix.set_rect(pix.irect, (255, 255, 255))
            pix.set_rect(pymupdf.IRect(5, 20, 55, 250), (0, 0, 0))
            page = doc.new_page(width=600, height=800)
            page.insert_image(pymupdf.Rect(300, 120, 380, 550), pixmap=pix)
            page.insert_image(pymupdf.Rect(100, 135, 180, 565), pixmap=pix)
            doc.save(path)
            doc.close()
            _, figures = pdf_images.extract(path)
            self.assertEqual(len(figures), 2)
            self.assertEqual([f['id'] for f in figures], ['1', '2'])
            self.assertLess(figures[0]['bbox'][0], figures[1]['bbox'][0])
            self.assertGreater(pymupdf.Pixmap(figures[0]['bytes']).height, 500)

    def test_user_sample_when_available(self):
        path = Path(r'C:\Users\Ainh\Downloads\Giải tích (P1\1. Giới hạn + tính liên tục hàm nhiều biến\Các khái niệm.pdf')
        if not path.exists():
            self.skipTest('User-provided PDF is not available')
        text, figures, evidence = pdf_images.extract(path, True)
        page3 = text.split('[Trang PDF 3]')[1].split('[Trang PDF 4]')[0]
        self.assertIn('1.2. Lân cận', page3)
        self.assertEqual(len(evidence), 11)
        self.assertTrue(any(f['page'] == 6 for f in figures))
        for figure in figures:
            self.assertNotIn(figure['page'], (1, 2, 3))
            pix = pymupdf.Pixmap(figure['bytes'])
            self.assertGreater(pix.width, 1)
            self.assertLess(pix.height, 2000)


class EvidencePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_pdfs_evidence_is_labeled_and_budgeted(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), 0)
        pix.set_rect(pix.irect, (10, 20, 30))
        url = 'data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode()
        parts = [app.OrderedPart(kind='source', name='a.pdf', text='A',
                                 evidence=[{'page': i, 'data_url': url} for i in range(1, 21)]),
                 app.OrderedPart(kind='source', name='b.pdf', text='B',
                                 evidence=[{'page': 1, 'data_url': url}])]
        source, figures, evidence = app.assemble_parts('', parts)
        self.assertEqual(len(evidence), 20)
        self.assertIn('[Ảnh trang nguồn Doc 2: b.pdf]', source)
        self.assertIn('Không kèm ảnh các trang PDF do giới hạn ảnh nguồn: 1', source)
        self.assertEqual(figures, [])

    async def test_evidence_reaches_grounding_but_is_not_published(self):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
        pix.set_rect(pix.irect, (200, 100, 50))
        data = pix.tobytes('png')
        url = 'data:image/png;base64,' + base64.b64encode(data).decode()
        part = app.OrderedPart(kind='source', name='source.pdf', text='[Trang PDF 1] example',
                               evidence=[{'page': 1, 'data_url': url}])
        source, figures, evidence = app.assemble_parts('', [part])
        self.assertEqual(figures, [])
        self.assertEqual(len(evidence), 1)
        cfg = {'quiz_frontend_base': 'https://example.com', 'quiz_backend_base': 'https://example.com',
               'randomize': False, 'steps': {'material': {'enabled': True, 'template': 'ENRICH'},
                                             'quiz': {'enabled': False}, 'interactive': {'enabled': False}}}
        saved, calls = [], []
        schema = {'concepts': [{'concept': 'Example', 'details': 'Example', 'evidence': 'example',
                                'location': 'Trang PDF 1'}], 'uncertainties': [], 'outline': ['Example']}
        async def fake_ai(prompt, images=None):
            import json
            calls.append(images)
            if prompt.startswith('STAGE: KNOWLEDGE'):
                return json.dumps(schema)
            if prompt.startswith('STAGE: SOURCE REVIEW MATERIAL'):
                return app.REVIEW_MATERIAL_BEGIN + '\nBài học\n' + app.REVIEW_MATERIAL_END
            if prompt.startswith('STAGE: SOURCE REVIEW QUIZ'):
                return app.REVIEW_QUIZ_BEGIN + '\n[]\n' + app.REVIEW_QUIZ_END
            return 'Bài học'
        async def share(config, state):
            saved.append(state)
            return 'https://example.com/abcdef'
        with patch.object(app, 'load_config', return_value=cfg), patch.object(app, 'share_state', share), \
             patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'stamped_image_parts', wraps=app.stamped_image_parts) as stamped:
            await app.run_pipeline(asyncio.Queue(), source, document_images=figures, evidence_images=evidence)
        self.assertEqual(stamped.call_count, 1)
        self.assertTrue(calls)
        self.assertTrue(all(images and len(images) == 1 for images in calls))
        self.assertEqual(stamped.call_args.args[0][0]['label'], 'Doc 1 - PDF page 1')
        self.assertNotIn('![', saved[0]['material'])
        self.assertNotIn(url, str(saved[0]))


if __name__ == '__main__':
    unittest.main()
