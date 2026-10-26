"""Synthetic ASGI requests: no inference, private documents or HTTP client dependency."""
import asyncio
import copy
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from demo.local_pdf_ocr.backend import app as api


def upload(fields, filename, payload):
    boundary = 'vietdoc-synthetic-review'
    body = b''
    for key, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
    body += payload + f'\r\n--{boundary}--\r\n'.encode()
    return body, f'multipart/form-data; boundary={boundary}'


def request(path, fields, filename, payload):
    body, kind = upload(fields, filename, payload)
    messages = []
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
             'method': 'POST', 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
             'query_string': b'', 'headers': [(b'host', b'127.0.0.1:8765'),
                 (b'content-type', kind.encode()), (b'content-length', str(len(body)).encode())],
             'server': ('127.0.0.1', 8765), 'client': ('127.0.0.1', 40000)}
    async def receive():
        return {'type': 'http.request', 'body': body, 'more_body': False}
    async def send(message):
        messages.append(message)
    asyncio.run(api.app(scope, receive, send))
    return messages[0]['status'], dict(messages[0]['headers']), b''.join(m.get('body', b'') for m in messages[1:])


def png():
    from PIL import Image
    data = io.BytesIO()
    Image.new('RGB', (100, 50), 'white').save(data, 'PNG')
    return data.getvalue()


class ReviewApiTests(unittest.TestCase):
    def test_busy_preview_refuses_more_render_work(self):
        with patch.object(api, '_preview_lock', SimpleNamespace(locked=lambda: True)):
            status, _, _ = request('/api/number-review/preview', {
                'page': 1, 'polygon': '[[10,10],[60,10],[60,30],[10,30]]',
                'render_width': 100, 'render_height': 50}, 'synthetic.png', png())
        self.assertEqual(status, 429)

    def test_preview_is_model_free_png_and_not_cached(self):
        with patch.object(api, 'get_engine', side_effect=AssertionError('preview must not load OCR')):
            status, headers, payload = request('/api/number-review/preview', {
                'page': 1, 'polygon': '[[10,10],[60,10],[60,30],[10,30]]',
                'render_width': 100, 'render_height': 50}, 'synthetic.png', png())
        self.assertEqual(status, 200)
        self.assertEqual(headers[b'content-type'], b'image/png')
        self.assertEqual(headers[b'cache-control'], b'no-store')
        self.assertTrue(payload.startswith(b'\x89PNG'))

    def test_invalid_geometry_rejected_before_model_initialization(self):
        with patch.object(api, 'get_engine', side_effect=AssertionError('no OCR')):
            status, _, _ = request('/api/number-review/preview', {
                'page': 1, 'polygon': '[[0,0],[NaN,0],[20,20],[0,20]]',
                'render_width': 100, 'render_height': 50}, 'synthetic.png', png())
        self.assertEqual(status, 400)

    def test_hybrid_refuses_images_before_model_initialization(self):
        with patch.object(api, 'get_engine', side_effect=AssertionError('no OCR')):
            status, _, _ = request('/api/ocr', {'mode': 'hybrid_h1'}, 'synthetic.png', png())
        self.assertEqual(status, 400)

    def test_explicit_hybrid_runs_ocr_and_preserves_full_baseline(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=300, height=100)
        page.insert_text((20, 40), 'Synthetic evidence', fontsize=11)
        pdf = doc.tobytes()
        doc.close()
        raw = {'method': 'vietocr_ocr', 'used_ocr': True, 'page_count': 1, 'line_count': 1,
               'elapsed_ms': 1, 'decoder_limit_hits': 0, 'text': 'Synthetic evidence',
               'pages': [{'page': 1, 'width': 600, 'height': 200, 'text': 'Synthetic evidence',
                   'lines': [{'line_index': 1, 'text': 'Synthetic evidence',
                              'polygon': [[30,50],[250,50],[250,90],[30,90]]}]}]}
        before = copy.deepcopy(raw)
        calls = []
        engine = SimpleNamespace(recognizer=SimpleNamespace(metadata={'vocab': 'Synthetic evidence'}),
                                 process=lambda content, name: (calls.append((content, name)) or raw))
        with patch.object(api, 'get_engine', return_value=engine):
            status, _, payload = request('/api/ocr', {'mode': 'hybrid_h1'}, 'synthetic.pdf', pdf)
        self.assertEqual(status, 200, payload)
        result = json.loads(payload)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['method'], 'hybrid_h1')
        self.assertTrue(result['experimental'])
        self.assertEqual(result['ocr_result'], before)
        self.assertEqual(raw, before)
        self.assertEqual(result['pages'][0]['lines'][0]['ocr_text'], before['text'])
