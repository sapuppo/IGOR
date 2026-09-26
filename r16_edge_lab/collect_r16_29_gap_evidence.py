"""Recover only missing observations from official daily USD-M archives.

Frozen files are never edited. The supplement has its own manifest and parent
fingerprint. No interpolation, Spot fallback, or replacement of existing bars.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import gzip
import hashlib
import io
import json
import zipfile
from urllib.parse import urlencode
import pandas as pd
from run_r16_28_collect_usdm import get, KCOL, BASE

INTERVAL = {"15m": 900000, "1h": 3600000, "4h": 14400000}
KEEP = ['open_time','open','high','low','close','volume','quote_volume','trades','taker_buy_base_volume','taker_buy_quote_volume']


def canonical(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="r16_edge_lab/usdm_history")
    parser.add_argument("--out", default="r16_edge_lab/r16_29_gap_evidence")
    args = parser.parse_args()
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = json.loads((root/"manifest.json").read_text())
    tasks = []
    for interval, step in INTERVAL.items():
        for path in sorted((root/"klines"/interval).glob("*.csv.gz")):
            x = pd.read_csv(path, usecols=["open_time"])
            missing = []
            times = x.open_time.to_numpy()
            for a, b in zip(times[:-1], times[1:]):
                if b-a > step:
                    missing.extend(range(int(a)+step, int(b), step))
            if missing:
                tasks.append((path.name.split('.')[0], interval, missing))
    print("GAP_FILES", len(tasks), "MISSING_BARS", sum(len(x[2]) for x in tasks), flush=True)

    def recover(task):
        symbol, interval, missing = task
        dates = sorted(set(pd.Timestamp(t, unit="ms", tz="UTC").strftime("%Y-%m-%d") for t in missing))
        frames = []; evidence = []; failures = []
        for date in dates:
            url = f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{date}.zip"
            try:
                raw = get(url)
                if raw is None:
                    failures.append({"url": url, "reason": "HTTP 404"}); continue
                digest = hashlib.sha256(raw).hexdigest()
                checksum = get(url+".CHECKSUM")
                if checksum is None:
                    failures.append({"url": url, "reason": "official checksum unavailable"}); continue
                expected = checksum.decode().split()[0]
                assert digest == expected, "official archive checksum mismatch"
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    name = next(n for n in archive.namelist() if n.endswith('.csv'))
                    with archive.open(name) as f:
                        x = pd.read_csv(f, header=None, names=KCOL)
                for col in KCOL:
                    x[col] = pd.to_numeric(x[col], errors="coerce")
                x = x.dropna(subset=KEEP)
                x.open_time = x.open_time.astype('int64')
                x.loc[x.open_time > 10**14, 'open_time'] //= 1000
                x = x[x.open_time.isin(missing)][KEEP]
                frames.append(x)
                evidence.append({"url": url, "archive_sha256": digest, "official_checksum": expected, "recovered": len(x)})
            except Exception as exc:
                failures.append({"url": url, "reason": f"{type(exc).__name__}: {exc}"})
        result = pd.concat(frames, ignore_index=True).drop_duplicates("open_time").sort_values("open_time") if frames else pd.DataFrame(columns=KEEP)
        # If an archive itself is incomplete, seek the same venue's historical
        # API. Keep the API response hash/URL as separate source evidence.
        unresolved = set(missing)-set(result.open_time)
        for date in dates:
            needed = sorted(t for t in unresolved if pd.Timestamp(t,unit='ms',tz='UTC').strftime('%Y-%m-%d')==date)
            if not needed:continue
            url='https://fapi.binance.com/fapi/v1/klines?'+urlencode({'symbol':symbol,'interval':interval,'startTime':needed[0],'endTime':needed[-1]+INTERVAL[interval]-1,'limit':1500})
            try:
                raw=get(url)
                assert raw is not None, 'REST source unavailable'
                page=json.loads(raw)
                assert isinstance(page,list), 'non-list REST response'
                x=pd.DataFrame(page,columns=KCOL)
                for col in KCOL:x[col]=pd.to_numeric(x[col],errors='coerce')
                x=x.dropna(subset=KEEP);x.open_time=x.open_time.astype('int64')
                x=x[x.open_time.isin(needed)][KEEP]
                result=pd.concat([result,x],ignore_index=True).drop_duplicates('open_time').sort_values('open_time')
                evidence.append({'url':url,'response_sha256':hashlib.sha256(raw).hexdigest(),'source_type':'official_REST','recovered':len(x)})
            except Exception as exc:
                failures.append({'url':url,'reason':f'{type(exc).__name__}: {exc}'})
        path = out/"klines"/interval/f"{symbol}.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(result.to_csv(index=False).encode(), mtime=0))
        row = {"symbol": symbol, "interval": interval, "expected_missing": len(missing), "recovered": len(result),
               "unresolved": sorted(set(missing)-set(result.open_time)), "path": str(path.relative_to(out)),
               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "sources": evidence, "failures": failures}
        print("RECOVERED", symbol, interval, len(result), "/", len(missing), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(recover, tasks))
    manifest = {"version": "R16.29.2-gap-evidence-v1", "parent_dataset_manifest_sha256": source['dataset_manifest_sha256'],
                "policy": "only missing original timestamps; official USD-M daily archive with checksum, then official historical REST if needed; no original bytes modified",
                "files": files, "missing": sum(x['expected_missing'] for x in files),
                "recovered": sum(x['recovered'] for x in files)}
    manifest['status'] = 'COMPLETE' if manifest['missing'] == manifest['recovered'] else 'INCOMPLETE'
    manifest['supplement_sha256'] = canonical(manifest)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'}, indent=2))


if __name__ == '__main__':
    main()
