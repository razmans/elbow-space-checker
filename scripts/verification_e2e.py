"""Controlled local verifier with real video decoding, detector, API and persistence."""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

from apps.backend.elbow_room.server import ROOT, main


class Verifier(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert payload['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        time.sleep(0.3)
        body = json.dumps({'choices': [{'finish_reason': 'stop', 'message': {
            'content': json.dumps({'assessable': True, 'passenger_count': 9})}}]}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    output = ROOT / 'data/verification-e2e'
    output.mkdir(parents=True, exist_ok=True)
    video = output / 'sample.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'MJPG'), 10, (320, 240))
    if not writer.isOpened():
        raise SystemExit('MJPG encoder unavailable')
    for _ in range(400):
        writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
    writer.release()
    service = ThreadingHTTPServer(('127.0.0.1', 0), Verifier)
    threading.Thread(target=service.serve_forever, daemon=True).start()
    config = json.loads((ROOT / 'config/demo.json').read_text())
    config['coaches'][2]['counts'] = [None]
    config['coaches'][0].update(source='recorded_video', video_path=str(video), capacity=10,
        interval_seconds=6, window_seconds=1, playback_speed=1, sample_count=3,
        verification={'endpoint': f'http://127.0.0.1:{service.server_port}/v1/chat/completions'})
    path = output / 'config.json'
    path.write_text(json.dumps(config))
    database = output / 'history.sqlite3'
    database.unlink(missing_ok=True)
    sys.argv = ['verification_e2e', '--config', str(path), '--database', str(database), '--port', '8013']
    try:
        main()
    finally:
        service.shutdown()
        service.server_close()
