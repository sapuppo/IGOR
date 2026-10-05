#!/usr/bin/env python3
"""Prepared dedicated-clock runner for public capture and paper only; not deployed."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from r17_cloud_capture import next_window
from r17_forward_capture import BAR_MS, CaptureError, save_snapshot, verify_chain
from r17_okx_cohort_capture import capture, fixed_universe
from r17_okx_public_capture import PublicOKX
from r17_okx_paper import WARMUP_SHA256

BUFFER_MS = 90000
HERE = Path(__file__).resolve().parent


def next_deadline(now_ms):
    base=now_ms//BAR_MS*BAR_MS+BUFFER_MS
    return base if base>now_ms else base+BAR_MS


def check_seed(archive,paper):
    archive,paper=Path(archive),Path(paper)
    if archive.resolve()==paper.resolve():
        raise CaptureError('dados de mercado e paper precisam de diretórios distintos')
    state=verify_chain(archive)
    if not state['snapshots']:
        raise CaptureError('importar cadeia original e warmup antes de executar')
    warmups=list(archive.glob('warmup-*.json'))
    if len(warmups)!=1 or hashlib.sha256(warmups[0].read_bytes()).hexdigest()!=WARMUP_SHA256:
        raise CaptureError('warmup congelado ausente ou alterado')
    source=hashlib.sha256((HERE/'r17_okx_cohort_capture.py').read_bytes()).hexdigest()
    if state['source_sha256']!=source:
        raise CaptureError('coletor diverge da cadeia original')
    fixed_universe(HERE/'R17_03_OKX_UNIVERSE.json')
    return state


def run_once(archive,paper,clock_ms=None,client=None,run_paper=True):
    check_seed(archive,paper)
    now=int(time.time()*1000) if clock_ms is None else clock_ms
    window=next_window(archive,now)
    path=None
    if window is not None:
        source=hashlib.sha256((HERE/'r17_okx_cohort_capture.py').read_bytes()).hexdigest()
        snap=capture(client or PublicOKX(),fixed_universe(HERE/'R17_03_OKX_UNIVERSE.json'),
                     *window,clock_ms=clock_ms,source_sha=source)
        path=save_snapshot(archive,snap)
        print(json.dumps({'type':'CAPTURE','file':str(path),'class':snap['snapshot_class'],
                          'status':snap['status']},ensure_ascii=False),flush=True)
    if run_paper:
        # schedule means the dedicated wall-clock event, documented in the addendum.
        # The original paper engine independently blocks stale and historical captures.
        subprocess.run([sys.executable,str(HERE/'r17_okx_paper.py'),
                        '--archive',str(archive),'--out-dir',str(paper),
                        '--event-name','schedule'],check=True,timeout=100)
    return path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True)
    p.add_argument('--paper',required=True)
    p.add_argument('--once',action='store_true')
    p.add_argument('--check',action='store_true')
    args=p.parse_args()
    state=check_seed(args.archive,args.paper)
    if args.check:
        print(json.dumps({'status':'SEED_VERIFIED','snapshots':state['snapshots'],
                          'next_deadline_ms':next_deadline(int(time.time()*1000)),
                          'deployed':False,'live':False}))
        return
    lock=Path(args.archive)/'dedicated-runner.lock'
    try:
        with lock.open('x') as handle:
            handle.write('Dedicated local writer; remove lock only after confirming process ended.\n')
    except FileExistsError as exc:
        raise CaptureError('executor concorrente ou lock de falha; investigar antes de iniciar') from exc
    try:
        if args.once:
            run_once(args.archive,args.paper)
            return
        while True:
            deadline=next_deadline(int(time.time()*1000))
            print(json.dumps({'type':'WAIT','deadline_ms':deadline,'live':False}),flush=True)
            while int(time.time()*1000)<deadline:
                time.sleep(min(30,max(.1,(deadline-time.time()*1000)/1000)))
            run_once(args.archive,args.paper)
    finally:
        lock.unlink(missing_ok=True)


if __name__=='__main__':
    main()
