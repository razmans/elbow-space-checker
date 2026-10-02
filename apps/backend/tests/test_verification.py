"""Local verifier HTTP -> observation persistence/SSE state, using controlled replies."""
import base64
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from apps.backend.elbow_room.server import Observations, make_handler, read_config
from apps.backend.elbow_room.verification import VerificationManager, validate_endpoint

HAS_VIDEO = importlib.util.find_spec('cv2') is not None


@unittest.skipUnless(HAS_VIDEO, 'Run with the video virtual environment')
class VerificationTest(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reply = {'assessable': True, 'passenger_count': 90}
        self.delay = 0
        self.redirect = False
        self.samples = []
        self.calls = 0
        owner = self

        class VerifierHandler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                import cv2
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls += 1
                assert payload['response_format']['json_schema']['schema']['required'] == ['assessable', 'passenger_count']
                image_url = payload['messages'][0]['content'][1]['image_url']['url']
                image = cv2.imdecode(np.frombuffer(base64.b64decode(image_url.split(',')[1]), dtype=np.uint8), cv2.IMREAD_COLOR)
                owner.samples.append(round(float(image.mean())))
                time.sleep(owner.delay)
                if owner.redirect:
                    self.send_response(302)
                    self.send_header('Location', 'https://example.com/never-send-images')
                    self.end_headers()
                    return
                body = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(owner.reply)}}]}).encode()
                try:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass
        self.service = ThreadingHTTPServer(('127.0.0.1', 0), VerifierHandler)
        self.service_thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.service_thread.start()
        self.addCleanup(self.stop_service)
        self.path = self.root / 'config.json'
        self.path.write_text(json.dumps({
            'coach_id': 'test', 'coach_name': 'Test', 'capacity': 100, 'interval_seconds': 1,
            'source': 'recorded_video', 'video_path': 'unused.avi',
            'verification': {'enabled': True, 'endpoint': f'http://127.0.0.1:{self.service.server_port}/v1/chat/completions', 'timeout_seconds': 2},
        }))
        self.config = read_config(self.path)
        self.coach = self.config['coaches'][0]
        self.store = Observations(self.root / 'history.sqlite3', self.config)
        self.store.set_source_state(self.coach, 'playing')
        handler = make_handler(self.store)
        handler.log_message = lambda *_: None
        self.api = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.api_thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.api_thread.start()
        self.addCleanup(self.stop_api)
        self.manager = VerificationManager(self.store, self.config['coaches'])
        self.addCleanup(self.manager.close)
        self.images = [np.full((32, 32, 3), color, dtype=np.uint8) for color in (20, 80, 140)]

    def stop_service(self):
        self.service.shutdown()
        self.service.server_close()
        self.service_thread.join(timeout=2)

    def stop_api(self):
        self.api.shutdown()
        self.api.server_close()
        self.api_thread.join(timeout=2)

    def get(self, path):
        with urlopen(f'http://127.0.0.1:{self.api.server_port}' + path, timeout=3) as response:
            return json.load(response)

    def wait_done(self, observation_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            observation = next(o for o in self.store.history() if o['id'] == observation_id)
            if observation['verification']['status'] in ('verified', 'unavailable'):
                return observation
            time.sleep(0.02)
        self.fail('Verification did not complete')

    def submit(self, count=20, clock=0, observed_at=None):
        observation = self.store.publish(self.coach, count, observed_at=observed_at)
        self.manager.submit(self.coach, observation, self.images, clock)
        return observation

    def test_disagreement_uses_ai_preserves_original_and_same_samples(self):
        original = self.submit()
        checked = self.wait_done(original['id'])
        self.assertEqual(self.samples, [20, 80, 140])
        self.assertEqual(checked['regular_passenger_count'], 20)
        self.assertEqual(checked['passenger_count'], 90)
        self.assertEqual(checked['status'], 'red')
        self.assertTrue(checked['verification']['disagreement'])
        self.assertEqual(checked['observed_at'], original['observed_at'])
        self.assertEqual(self.get('/api/state')['coaches'][0]['passenger_count'], 90)
        self.assertEqual(self.get('/api/observations')[0], checked)

    def test_delayed_check_updates_history_not_newer_live_reading(self):
        self.delay = 0.1
        original = self.submit()
        newer = self.store.publish(self.coach, 40)
        self.wait_done(original['id'])
        current = self.get('/api/state')['coaches'][0]
        self.assertEqual(current['last_observation']['id'], newer['id'])
        self.assertEqual(current['passenger_count'], 40)
        self.assertEqual(current['last_verification']['observation_id'], original['id'])
        self.assertTrue(current['last_verification']['disagreement'])

    def test_first_sample_then_30_minute_schedule(self):
        first = self.submit(clock=2)
        self.wait_done(first['id'])
        self.assertEqual(self.calls, 3)
        early = self.submit(clock=1801)
        self.assertEqual(early['verification']['status'], 'not_due')
        self.assertEqual(self.calls, 3)
        due = self.submit(clock=1802)
        self.wait_done(due['id'])
        self.assertEqual(self.calls, 6)

    def test_success_does_not_refresh_expired_timestamp(self):
        original = self.submit(observed_at=datetime.now(timezone.utc) - timedelta(seconds=10))
        checked = self.wait_done(original['id'])
        current = self.get('/api/state')['coaches'][0]
        self.assertEqual(current['status'], 'unknown')
        self.assertEqual(current['availability'], 'stale')
        self.assertEqual(checked['observed_at'], original['observed_at'])

    def test_invalid_unassessable_and_redirect_preserve_regular_count(self):
        cases = [({'assessable': True, 'passenger_count': True}, False),
                 ({'assessable': False, 'passenger_count': None}, False),
                 ({'assessable': True, 'passenger_count': -1}, False),
                 ({'assessable': True, 'passenger_count': 90}, True)]
        for index, (reply, redirect) in enumerate(cases):
            self.reply, self.redirect = reply, redirect
            original = self.submit(clock=index * 1800)
            checked = self.wait_done(original['id'])
            self.assertEqual(checked['verification']['status'], 'unavailable')
            self.assertEqual(checked['passenger_count'], 20)
            self.assertEqual(checked['status'], 'green')

    def test_timeout_is_unavailable_and_does_not_block_regular_updates(self):
        self.coach['verification']['timeout_seconds'] = 0.05
        self.delay = 0.2
        first = self.submit()
        newer = self.store.publish(self.coach, 55)
        self.assertEqual(self.get('/api/state')['coaches'][0]['passenger_count'], 55)
        checked = self.wait_done(first['id'])
        self.assertEqual(checked['verification']['status'], 'unavailable')
        self.assertEqual(self.get('/api/state')['coaches'][0]['last_observation']['id'], newer['id'])

    def test_restart_marks_abandoned_pending_check_unavailable(self):
        observation = self.store.publish(self.coach, 25)
        self.store.mark_verification_pending(observation['id'], 'test')
        restarted = Observations(self.root / 'history.sqlite3', self.config)
        self.assertEqual(restarted.history()[0]['verification']['status'], 'unavailable')
        self.assertEqual(restarted.history()[0]['passenger_count'], 25)


class LocalOnlyVerifierTest(unittest.TestCase):
    def test_nonlocal_and_credential_urls_are_rejected(self):
        for url in ('https://example.com/v1/chat/completions', 'http://192.168.1.10:8081', 'http://user:pass@127.0.0.1:8081', 'http://127.0.0.1.example.com'):
            with self.assertRaises(ValueError):
                validate_endpoint(url)
