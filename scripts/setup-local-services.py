"""Explicit downloads of pinned optional local verifier and RTSP test runtimes."""
import argparse
import hashlib
import tarfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    'llama': ('https://github.com/ggml-org/llama.cpp/releases/download/b11146/llama-b11146-bin-ubuntu-x64.tar.gz', 'c150306eb16b5ab696f76a8bdf810c35fd98a24e82158742e6fa28f420ff8410', 'llama.tar.gz'),
    'model': ('https://huggingface.co/ggml-org/SmolVLM-500M-Instruct-GGUF/resolve/72e986006ef53e37cdd3f6d4241c90b0f01df376/SmolVLM-500M-Instruct-Q8_0.gguf', '9d4612de6a42214499e301494a3ecc2be0abdd9de44e663bda63f1152fad1bf4', 'SmolVLM-500M-Instruct-Q8_0.gguf'),
    'projector': ('https://huggingface.co/ggml-org/SmolVLM-500M-Instruct-GGUF/resolve/72e986006ef53e37cdd3f6d4241c90b0f01df376/mmproj-SmolVLM-500M-Instruct-Q8_0.gguf', 'd1eb8b6b23979205fdf63703ed10f788131a3f812c7b1f72e0119d5d81295150', 'mmproj-SmolVLM-500M-Instruct-Q8_0.gguf'),
    'rtsp': ('https://github.com/bluenviron/mediamtx/releases/download/v1.21.1/mediamtx_v1.21.1_linux_amd64.tar.gz', '653abc672a3e693f8d3b2717752492fdcfb8072291ec108d03d3dd857411b0ee', 'mediamtx.tar.gz'),
}


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install(key):
    url, expected, name = ASSETS[key]
    directory = ROOT / 'data/local-services'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if not target.exists() or checksum(target) != expected:
        part = target.with_suffix('.download')
        try:
            print(f'Downloading {name}', flush=True)
            with urlopen(url, timeout=60) as response, part.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if checksum(part) != expected:
                raise ValueError(f'Checksum mismatch: {name}')
            part.replace(target)
        finally:
            part.unlink(missing_ok=True)
    if name.endswith('.tar.gz'):
        with tarfile.open(target) as archive:
            archive.extractall(directory / key, filter='data')
    print(f'Verified {name}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verifier', action='store_true')
    parser.add_argument('--rtsp-test-server', action='store_true')
    args = parser.parse_args()
    if not (args.verifier or args.rtsp_test_server):
        parser.error('Select --verifier and/or --rtsp-test-server')
    if args.verifier:
        for key in ('llama', 'model', 'projector'):
            install(key)
    if args.rtsp_test_server:
        install('rtsp')
