#!/usr/bin/env python3
"""Run one public market capture against a durable, sequential snapshot directory."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from r17_forward_capture import (BAR_MS, ONE_MINUTE, CaptureError, PublicUSDm,
                                 capture_batch, fixed_universe, save_snapshot,
                                 verify_chain)


def next_window(directory, now_ms):
    state = verify_chain(directory)
    end_ms = (now_ms - ONE_MINUTE) // BAR_MS * BAR_MS
    if not state['snapshots']:
        return end_ms - BAR_MS, end_ms
    last = sorted(Path(directory).glob('capture-*.json'))[-1]
    previous = json.loads(last.read_bytes())
    previous_end = int(datetime.fromisoformat(previous['end_exclusive_utc'].replace('Z', '+00:00')).timestamp() * 1000)
    if previous_end >= end_ms:
        return None
    if end_ms - previous_end > 24 * 60 * ONE_MINUTE:
        raise CaptureError('lacuna superior a 24 h; investigar antes de retomar a cadeia')
    return previous_end, end_ms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args()
    window = next_window(args.out_dir, int(time.time() * 1000))
    if window is None:
        print(json.dumps({'status': 'SKIPPED', 'reason': 'janela corrente já coletada'}))
        return
    source_sha = hashlib.sha256(Path(__file__).with_name('r17_forward_capture.py').read_bytes()).hexdigest()
    snapshot = capture_batch(PublicUSDm(), fixed_universe(args.manifest), *window, source_sha=source_sha)
    path = save_snapshot(args.out_dir, snapshot)
    print(json.dumps({'status': snapshot['status'], 'path': str(path),
                      'class': snapshot['snapshot_class'], 'problems': snapshot['problems']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
