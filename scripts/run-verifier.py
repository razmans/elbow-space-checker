"""Run the downloaded CPU vision model, bound only to this machine."""
import argparse
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'data/local-services'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--port', type=int, default=8081)
args = parser.parse_args()
binary = root / 'llama/llama-b11146/llama-server'
model = root / 'SmolVLM-500M-Instruct-Q8_0.gguf'
projector = root / 'mmproj-SmolVLM-500M-Instruct-Q8_0.gguf'
if not all(path.exists() for path in (binary, model, projector)):
    raise SystemExit('Run python3 scripts/setup-local-services.py --verifier first')
os.execv(str(binary), [str(binary), '-m', str(model), '--mmproj', str(projector),
                       '--host', '127.0.0.1', '--port', str(args.port), '--alias', 'elbow-verifier',
                       '--threads', '2', '--threads-batch', '2', '--parallel', '1',
                       '--ctx-size', '4096', '--n-gpu-layers', '0', '--no-mmproj-offload'])
