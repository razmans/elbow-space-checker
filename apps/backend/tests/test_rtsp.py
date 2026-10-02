"""Actual loopback RTSP publisher -> decoder -> HTTP with loss and recovery."""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from apps.backend.elbow_room.rtsp import run_rtsp
from apps.backend.elbow_room.server import Observations, make_handler, read_config

ROOT = Path(__file__).resolve().parents[3]
MEDIA_SERVER = ROOT / 'data/local-services/rtsp/mediamtx'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class ColorDetector:
    name = 'controlled-color-detector'
    def __init__(self, *_):
        pass
    def count(self, frame):
        return 9 if float(frame[:, :, 2].mean()) > 100 else 1


@unittest.skipUnless(importlib.util.find_spec('cv2') and MEDIA_SERVER.exists() and shutil.which('ffmpeg'), 'Install optional video runtime and RTSP test server')
class RtspIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.port = free_port()
        path = root / 'mediamtx.yml'
        path.write_text(f'logLevel: error\nrtspAddress: 127.0.0.1:{self.port}\nrtspTransports: [tcp]\nrtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\npaths:\n  coach:\n    source: publisher\n')
        self.media = subprocess.Popen([str(MEDIA_SERVER), str(path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.addCleanup(self.stop_process, self.media)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=0.1):
                    break
            except OSError:
                if self.media.poll() is not None:
                    self.fail(self.media.stdout.read().decode())
                time.sleep(0.05)
        self.url = f'rtsp://127.0.0.1:{self.port}/coach'
        previous_env = os.environ.get('ELBOW_RTSP_TEST_URL')
        os.environ['ELBOW_RTSP_TEST_URL'] = self.url
        self.addCleanup(lambda: os.environ.pop('ELBOW_RTSP_TEST_URL', None) if previous_env is None else os.environ.__setitem__('ELBOW_RTSP_TEST_URL', previous_env))
        config_path = root / 'coach.json'
        config_path.write_text(json.dumps({'coach_id': 'live', 'coach_name': 'Live coach', 'capacity': 10,
            'source': 'rtsp', 'rtsp_url_env': 'ELBOW_RTSP_TEST_URL', 'interval_seconds': 0.5,
            'window_seconds': 0.2, 'sample_count': 3, 'open_timeout_seconds': 5,
            'read_timeout_seconds': 0.5, 'reconnect_seconds': 0.2, 'max_frame_age_seconds': 0.2,
            'reconnect_warmup_seconds': 0.1, 'verification': {'enabled': False}}))
        config = read_config(config_path)
        self.store = Observations(root / 'history.sqlite3', config)
        handler = make_handler(self.store)
        handler.log_message = lambda *_: None
        self.api = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.api_thread = threading.Thread(target=self.api.serve_forever, daemon=True)
        self.api_thread.start()
        self.stopped = threading.Event()
        self.worker = threading.Thread(target=run_rtsp, args=(config['coaches'][0], self.store, self.stopped, ColorDetector), daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_workers)

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if process.stderr:
            process.stderr.close()
        if process.stdout:
            process.stdout.close()

    def stop_workers(self):
        self.stopped.set()
        self.worker.join(timeout=10)
        self.api.shutdown()
        self.api.server_close()
        self.api_thread.join(timeout=2)

    def publish(self, color):
        process = subprocess.Popen(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-re', '-f', 'lavfi', '-i', f'color=c={color}:s=320x240:r=10', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-g', '10', '-pix_fmt', 'yuv420p', '-f', 'rtsp', '-rtsp_transport', 'tcp', self.url], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(self.stop_process, process)
        time.sleep(0.3)
        if process.poll() is not None:
            self.fail(process.stderr.read().decode())
        return process

    def wait_for(self, predicate):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with urlopen(f'http://127.0.0.1:{self.api.server_port}/api/state', timeout=2) as response:
                state = json.load(response)
            coach = state['coaches'][0]
            if predicate(coach):
                self.assertNotIn(self.url, json.dumps(state))
                return coach
            time.sleep(0.1)
        self.fail(f'RTSP state timed out: {coach}')

    def test_disconnect_expires_and_reconnect_discards_prior_generation(self):
        first = self.publish('red')
        before = self.wait_for(lambda c: c['passenger_count'] == 9)
        self.assertEqual(before['source'], 'rtsp')
        self.assertEqual(before['status'], 'red')
        self.stop_process(first)
        stale = self.wait_for(lambda c: c['availability'] == 'stale')
        self.assertIsNone(stale['passenger_count'])
        self.assertEqual(stale['status'], 'unknown')
        self.publish('blue')
        after = self.wait_for(lambda c: c['passenger_count'] == 1)
        self.assertEqual(after['status'], 'green')
        self.assertGreater(after['last_observation']['capture_generation'], before['last_observation']['capture_generation'])
        self.assertGreater(after['last_observation']['observed_at'], before['last_observation']['observed_at'])
        self.assertTrue(all(o['passenger_count'] in (1, 9) for o in self.store.history()))
