"""Start a three-coach local demo and clean up only the services it starts."""
import argparse
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.backend.elbow_room.server import read_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--video', type=Path, help='Replay a local file in coach 01')
    source.add_argument('--rtsp', action='store_true', help='Use COACH_01_RTSP_URL from the environment')
    source.add_argument('--rtsp-video', type=Path, help='Loop a local file through a private RTSP test server')
    source.add_argument('--config', type=Path, help='Run all sources in a prepared configuration')
    parser.add_argument('--without-verifier', action='store_true')
    parser.add_argument('--interval', type=float, default=3, help='Demo update interval; recorded mode uses media seconds')
    parser.add_argument('--speed', type=float, default=1, help='Recorded-file playback speed')
    parser.add_argument('--duration', type=float, help='Stop after this many seconds once ready')
    parser.add_argument('--no-web', action='store_true', help='API-only demonstration')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--web-port', type=int, default=5173)
    parser.add_argument('--verifier-port', type=int, default=8081)
    args = parser.parse_args()
    if not math.isfinite(args.interval) or args.interval <= 0 or not 0 < args.speed <= 100 or (args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0)):
        parser.error('Use positive interval/duration and a playback speed in (0, 100]')
    for path in (args.video, args.rtsp_video):
        if path and not path.is_file():
            parser.error('The selected video file does not exist')
    if args.rtsp and not os.environ.get('COACH_01_RTSP_URL'):
        parser.error('Set COACH_01_RTSP_URL before selecting --rtsp')
    try:
        config = read_config(args.config or ROOT / 'config/demo.json')
    except (ValueError, OSError) as error:
        parser.error(str(error))
    video_mode = bool(args.video or args.rtsp or args.rtsp_video or any(c['source'] != 'simulation' for c in config['coaches']))
    verify = video_mode and not args.without_verifier and (not args.config or any(c['verification']['enabled'] for c in config['coaches']))
    ports = [args.port] + ([] if args.no_web else [args.web_port]) + ([args.verifier_port] if verify else [])
    if len(set(ports)) != len(ports) or any(not 1 <= port <= 65535 for port in ports):
        parser.error('Service ports must be distinct valid port numbers')
    # Refuse to mistake someone else's service for this run's readiness.
    for port in ports:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                parser.error(f'Port {port} is in use; stop that service or select another port')
    run = ROOT / 'data/demo-runs' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid4().hex[:8])
    run.mkdir(parents=True)
    processes, logs = [], []
    environment = os.environ.copy()

    def start(name, command):
        log = (run / f'{name}.log').open('w')
        logs.append(log)
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append((name, process))
        return process

    def check():
        for name, process in processes:
            if process.poll() is not None:
                raise RuntimeError(f'{name} stopped; see {run / (name + ".log")}')

    def ready(url, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            check()
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(.2)
        raise RuntimeError(f'Service readiness timed out; see {run}')

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        if not args.config:
            for coach in config['coaches']:
                coach['interval_seconds'] = args.interval
            config['coaches'][0]['counts'] = [24, None, None, None, 81, 0]
        first = config['coaches'][0]
        if args.video:
            first.update(source='recorded_video', video_path=str(args.video.resolve()), playback_speed=args.speed)
        if args.rtsp or args.rtsp_video:
            first.update(source='rtsp', rtsp_url_env='COACH_01_RTSP_URL')
        if args.rtsp_video:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                rtsp_port = sock.getsockname()[1]
            media = ROOT / 'data/local-services/rtsp/mediamtx'
            if not media.is_file():
                raise RuntimeError('Install the optional test server: python3 scripts/setup-local-services.py --rtsp-test-server')
            path = run / 'mediamtx.yml'
            path.write_text(f'logLevel: error\nrtspAddress: 127.0.0.1:{rtsp_port}\nrtspTransports: [tcp]\nrtmp: false\nhls: false\nwebrtc: false\nsrt: false\nmoq: false\npaths:\n  coach:\n    source: publisher\n')
            start('rtsp', [str(media), str(path)])
            deadline = time.monotonic() + 10
            while True:
                check()
                try:
                    with socket.create_connection(('127.0.0.1', rtsp_port), timeout=.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('RTSP test server readiness timed out')
                    time.sleep(.1)
            environment['COACH_01_RTSP_URL'] = f'rtsp://127.0.0.1:{rtsp_port}/coach'
            start('publisher', ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-re', '-stream_loop', '-1', '-i', str(args.rtsp_video.resolve()), '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-g', '10', '-pix_fmt', 'yuv420p', '-f', 'rtsp', '-rtsp_transport', 'tcp', environment['COACH_01_RTSP_URL']])
            first['coach_name'] = 'Coach 01 · RTSP replay'
            config['train_name'] = 'Local RTSP replay demonstration'
        if video_mode and not args.config:
            first['window_seconds'] = min(2, args.interval)
            first['verification'] = {'enabled': verify, 'endpoint': f'http://127.0.0.1:{args.verifier_port}/v1/chat/completions'}
        if args.config:
            for coach in config['coaches']:
                if coach['source'] != 'simulation':
                    coach['verification']['enabled'] = coach['verification']['enabled'] and verify
                    coach['verification']['endpoint'] = f'http://127.0.0.1:{args.verifier_port}/v1/chat/completions'
        if verify:
            start('verifier', [sys.executable, 'scripts/run-verifier.py', '--port', str(args.verifier_port)])
            ready(f'http://127.0.0.1:{args.verifier_port}/health', timeout=120)
        path = run / 'config.json'
        path.write_text(json.dumps(config, indent=2) + '\n')
        start('api', [sys.executable, '-m', 'apps.backend.elbow_room.server', '--config', str(path), '--database', str(run / 'history.sqlite3'), '--port', str(args.port)])
        ready(f'http://127.0.0.1:{args.port}/api/health')
        if not args.no_web:
            environment['ELBOW_API_URL'] = f'http://127.0.0.1:{args.port}'
            start('web', ['npm', 'run', 'dev', '--workspace', '@elbow-room/web', '--', '--port', str(args.web_port), '--strictPort'])
            ready(f'http://127.0.0.1:{args.web_port}')
        print(f'Demo ready: http://127.0.0.1:{args.port if args.no_web else args.web_port}', flush=True)
        print(f'Run data and logs: {run}', flush=True)
        print('Ctrl+C stops all services started by this launcher; history is retained.', flush=True)
        deadline = time.monotonic() + args.duration if args.duration else float('inf')
        while time.monotonic() < deadline:
            check()
            time.sleep(.25)
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        for _, process in reversed(processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for _, process in reversed(processes):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for log in logs:
            log.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
