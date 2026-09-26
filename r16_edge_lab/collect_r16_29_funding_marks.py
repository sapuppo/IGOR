"""Read-only supplementary official API evidence. Never rewrites frozen inputs."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import time
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="r16_edge_lab/usdm_history")
    parser.add_argument("--out", default="r16_edge_lab/r16_29_funding_marks")
    args = parser.parse_args()
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    source = json.loads((root/"manifest.json").read_text())
    report = {"source_dataset_sha256": source["dataset_manifest_sha256"], "endpoint": "https://fapi.binance.com/fapi/v1/fundingRate",
              "status": "COMPLETE", "symbols": [], "frozen_input_modified": False}
    for item in source["symbols"]:
        if not item["eligible"]:
            continue
        symbol = item["symbol"]
        expected = pd.read_csv(root/"funding"/f"{symbol}.csv.gz")
        first, last = int(expected.fundingTime.min()), int(expected.fundingTime.max())
        cursor = first; records = []
        try:
            while cursor <= last:
                url = report["endpoint"]+"?"+urlencode({"symbol": symbol, "startTime": cursor, "endTime": last, "limit": 1000})
                for attempt in range(3):
                    try:
                        with urlopen(Request(url, headers={"User-Agent": "IGOR-integrity-audit/1.0"}), timeout=30) as response:
                            page = json.load(response)
                        break
                    except HTTPError as exc:
                        if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                            raise
                        time.sleep(2*(attempt+1))
                assert isinstance(page, list), "non-list API response"
                if not page:
                    break
                records.extend(page)
                next_cursor = int(page[-1]["fundingTime"])+1
                assert next_cursor > cursor
                cursor = next_cursor
                time.sleep(.15)
            actual = {int(x["fundingTime"]): x for x in records}
            missing = []; mismatched = []
            for row in expected.itertuples(index=False):
                x = actual.get(int(row.fundingTime))
                if not x or float(x.get("markPrice", 0) or 0) <= 0:
                    missing.append(int(row.fundingTime))
                elif abs(float(x["fundingRate"])-float(row.fundingRate)) > 1e-12:
                    mismatched.append(int(row.fundingTime))
            payload = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
            path = out/f"{symbol}.json.gz"
            path.write_bytes(gzip.compress(payload, mtime=0))
            report["symbols"].append({"symbol": symbol, "expected": len(expected), "received": len(records),
                                      "missing_mark_price": len(missing), "rate_mismatches": len(mismatched),
                                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            if missing or mismatched:
                report["status"] = "INCOMPLETE"
            print(symbol, report["symbols"][-1], flush=True)
        except (HTTPError, URLError, AssertionError, ValueError, KeyError) as exc:
            report["status"] = "BLOCKED"
            report["blocking_error"] = str(exc)
            report["blocked_symbol"] = symbol
            # No proxy/region evasion or repeated requests after an access restriction.
            break
    (out/"manifest.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
