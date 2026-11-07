"""Offline tests for per-browser question count; no external services are used."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


def question(index):
    return {
        'question': f'Câu {index}',
        'options': [{'label': value, 'value': value} for value in 'ABCD'],
        'correct': 'A',
        'explanation': '',
    }


class QuestionCountTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.config = {
            'quiz_frontend_base': 'https://example.com',
            'quiz_backend_base': 'https://example.com',
            'randomize': False,
            'steps': {
                'material': {'enabled': False, 'template': ''},
                'quiz': {'enabled': True, 'template': 'Generate 6 questions. Custom instructions.'},
                'interactive': {'enabled': False, 'template': ''},
            },
        }
        self.prompts = []
        self.saved = []
        self.responses = []

    def request(self, payload, responses):
        self.responses = list(responses)

        async def fake_ai(prompt, images=None):
            self.prompts.append(prompt)
            data = self.responses.pop(0)
            return '```quiz\n' + json.dumps([question(i) for i in range(data)]) + '\nendquiz```'

        async def fake_share(config, state):
            self.saved.append(state)
            return 'https://example.com/abcdef'

        with patch.object(app, 'load_config', return_value=self.config), \
             patch.object(app, 'ai_call', fake_ai), \
             patch.object(app, 'share_state', fake_share):
            response = self.client.post('/api/generate', json=payload)
        return response, [json.loads(line) for line in response.text.splitlines() if line]

    def test_default_six_and_custom_count(self):
        response, events = self.request({'input': 'đề bài'}, [6])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(events[-1]['done'])
        self.assertEqual(len(self.saved[-1]['questions']), 6)
        self.assertIn('Generate exactly 6 questions', self.prompts[-1])

        response, events = self.request({'input': 'đề bài', 'question_count': 3}, [3])
        self.assertTrue(events[-1]['done'])
        self.assertEqual(len(self.saved[-1]['questions']), 3)
        self.assertIn('Generate 3 questions. Custom instructions.', self.prompts[-1])
        self.assertNotIn('Generate 6 questions', self.prompts[-1])

    def test_wrong_count_is_retried_and_not_published(self):
        response, events = self.request({'input': 'đề bài', 'question_count': 2}, [1, 2])
        self.assertTrue(events[-1]['done'])
        self.assertIn('Cần đúng 2 câu hỏi', self.prompts[-1])
        self.assertEqual(len(self.saved[-1]['questions']), 2)

        self.saved.clear()
        response, events = self.request({'input': 'đề bài', 'question_count': 2}, [1, 1, 1])
        self.assertIn('Cần đúng 2 câu hỏi', events[-1]['error'])
        self.assertFalse(self.saved)

    def test_invalid_counts_rejected(self):
        for count in (0, -1, 51, 1.5, '3', True):
            with self.subTest(count=count):
                response = self.client.post('/api/generate', json={'input': 'x', 'question_count': count})
                self.assertEqual(response.status_code, 422)


if __name__ == '__main__':
    unittest.main()
