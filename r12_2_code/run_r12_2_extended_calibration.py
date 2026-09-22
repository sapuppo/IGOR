from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.ensemble import HistGradientBoostingRegressor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'trade-r8'))

from r11_multitimeframe_rank_engine import (
    config_for_timeframe, resample_universe, make_dataset, rank_model, R11_FEATURES, _slice
)
from r8_setup_experts_engine import add_indicators, _profit_factor
from run_r8_real import DEV_CANDIDATES, OUTER_HOLDOUT, download_universe, START, END
from run_r11_3_execution_fix import build_signals, simulate_fixed, calc_exit
from run_r11_5_nested_stability import (
    canonical_data, canonical_frame, frame_hash, simulate_concentration,
    gate_checks, STRICT_PURGE_HOURS
)

TF = '4h'
TOP_K = 2
MIN_RANK_Z = 1.0
KIND = 'STOP_ONLY'

# R12.2 frozen geometry. Calibration and verification are separate windows.
TRAIN_DAYS = 360
CALIBRATION_DAYS = 120
VERIFICATION_DAYS = 30
TEST_DAYS = 30
PURGE_HOURS = 48

ABS_TARGET_CLIP = (-0.04, 0.08)
CALIBRATION_BINS = 12
CALIBRATION_PSEUDOCOUNT = 50.0
MIN_CALIBRATOR_ROWS = 300
MIN_CALIBRATOR_BINS = 5

# pred_abs -> observed net return. Since calibrated edge is already net of modeled
# round-trip costs, a margin m is algebraically equivalent to requiring
# calibrated_gross > roundtrip_cost + m. This avoids double-counting costs.
EDGE_MARGINS = (0.0, 0.0005, 0.0010, 0.0015, 0.0020, 0.0030)

# Keep R12 preregistered gates unchanged.
SELECT_MIN_N = 20
SELECT_MIN_SYMBOLS = 6
SELECT_MIN_AVG = 0.0005
SELECT_MIN_PF = 1.08
SELECT_MIN_PRECISION = 0.40
SELECT_MAX_SHARE = 0.35

VERIFY_MIN_N = 8
VERIFY_MIN_SYMBOLS = 4
VERIFY_MIN_AVG = 0.0
VERIFY_MIN_PF = 1.05
VERIFY_MIN_PRECISION = 0.38
VERIFY_MAX_SHARE = 0.45


def attach_stop_only_targets(ds, data, cfg, development_symbols):
    inds = {s: add_indicators(d) for s, d in data.items()}
    out = ds.copy()
    gross = []
    for ts, row in out.iterrows():
        d = inds.get(row.symbol)
        if d is None:
            gross.append(np.nan)
            continue
        e = calc_exit(d, ts, cfg, KIND)
        gross.append(float(e[0]) if e is not None else np.nan)
    out['stop_gross_target'] = gross
    out['stop_net_target'] = out.stop_gross_target - cfg.roundtrip_cost
    out = out.dropna(subset=['stop_net_target']).copy()

    devset = set(development_symbols)
    devmask = out.symbol.isin(devset)
    out['target_rank'] = np.nan
    out.loc[devmask, 'target_rank'] = (
        out[devmask].groupby(level=0).stop_net_target.rank(pct=True, method='average')
    )
    if (~devmask).any():
        refs = {ts: g.stop_net_target.to_numpy() for ts, g in out[devmask].groupby(level=0)}
        vals = []
        for ts, row in out[~devmask].iterrows():
            ref = refs.get(ts)
            vals.append(float(np.mean(ref <= row.stop_net_target)) if ref is not None and len(ref) else np.nan)
        out.loc[~devmask, 'target_rank'] = vals
    return out.dropna(subset=['target_rank'])


def absolute_model(cfg):
    return HistGradientBoostingRegressor(
        loss='absolute_error',
        learning_rate=.035,
        max_iter=240,
        max_leaf_nodes=11,
        min_samples_leaf=80,
        l2_regularization=8.0,
        random_state=cfg.random_state,
    )


def score_heads(rank_m, abs_m, frame):
    if frame.empty:
        return pd.DataFrame()
    z = frame[['symbol', 'target_rank', 'stop_net_target', 'stop_gross_target']].copy()
    z['pred_rank'] = rank_m.predict(frame[R11_FEATURES])
    z['pred_abs_net'] = abs_m.predict(frame[R11_FEATURES])
    parts = []
    for ts, g in z.groupby(level=0, sort=True):
        q = g.reset_index()
        tcol = q.columns[0]
        q = q.rename(columns={tcol: '__ts'})
        q = q.sort_values(['pred_rank', 'symbol'], ascending=[False, True], kind='mergesort')
        med = float(q.pred_rank.median())
        sd = float(q.pred_rank.std(ddof=0))
        den = sd if np.isfinite(sd) and sd > 1e-9 else 1.0
        q['rank_z'] = (q.pred_rank - med) / den
        q['pred_order'] = np.arange(1, len(q) + 1)
        q['rank_selected'] = (q.pred_order <= TOP_K) & (q.rank_z >= MIN_RANK_Z)
        parts.append(q.set_index('__ts'))
    return pd.concat(parts).sort_index()


def _weighted_mean(x, w):
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    den = float(np.sum(w))
    return float(np.sum(x * w) / den) if den > 0 else float(np.mean(x))


def fit_economic_calibrator(cal_scored):
    """Fit a conservative monotone mapping pred_abs_net -> observed net return.

    The absolute model was trained only on the preceding training window. Therefore
    its predictions in the calibration window are OOS relative to the model. We fit
    a binned, shrinkage-regularized isotonic map on *all* development candidates to
    stabilize the weak absolute signal. Entry selection still requires the rank gate.
    """
    z = cal_scored[['pred_abs_net', 'stop_net_target']].dropna().copy()
    if len(z) < MIN_CALIBRATOR_ROWS or z.pred_abs_net.nunique() < MIN_CALIBRATOR_BINS:
        return None, {
            'status': 'INSUFFICIENT_CALIBRATOR_EVIDENCE',
            'rows': int(len(z)),
            'unique_predictions': int(z.pred_abs_net.nunique()),
        }

    # Equalize timestamps so a cross-section with more listed assets does not receive
    # disproportionate influence merely because more rows happened to exist then.
    counts = z.groupby(level=0).size()
    z['weight'] = [1.0 / float(counts.loc[t]) for t in z.index]
    z['y_clip'] = z.stop_net_target.clip(*ABS_TARGET_CLIP)

    # Quantile-bin first, then shrink bin means toward the global mean. This prevents
    # isotonic regression from creating noisy micro-steps from a weak absolute head.
    q = min(CALIBRATION_BINS, int(z.pred_abs_net.nunique()))
    try:
        z['bin'] = pd.qcut(z.pred_abs_net, q=q, duplicates='drop')
    except ValueError:
        return None, {'status': 'QCUT_FAIL', 'rows': int(len(z))}

    global_mean = _weighted_mean(z.y_clip, z.weight)
    rows = []
    for _, g in z.groupby('bin', observed=True, sort=True):
        if g.empty:
            continue
        n_eff = float(g.weight.sum())
        x_mean = _weighted_mean(g.pred_abs_net, g.weight)
        y_mean = _weighted_mean(g.y_clip, g.weight)
        shrunk = (n_eff * y_mean + CALIBRATION_PSEUDOCOUNT * global_mean) / (
            n_eff + CALIBRATION_PSEUDOCOUNT
        )
        rows.append({
            'pred_mean': x_mean,
            'observed_mean': y_mean,
            'shrunk_mean': float(shrunk),
            'effective_weight': n_eff,
            'raw_rows': int(len(g)),
        })
    bins = pd.DataFrame(rows).sort_values('pred_mean')
    if len(bins) < MIN_CALIBRATOR_BINS:
        return None, {'status': 'INSUFFICIENT_CALIBRATOR_BINS', 'rows': int(len(z)), 'bins': int(len(bins))}

    iso = IsotonicRegression(
        increasing=True,
        out_of_bounds='clip',
        y_min=ABS_TARGET_CLIP[0],
        y_max=ABS_TARGET_CLIP[1],
    )
    iso.fit(
        bins.pred_mean.to_numpy(),
        bins.shrunk_mean.to_numpy(),
        sample_weight=bins.effective_weight.to_numpy(),
    )
    bins['calibrated_mean'] = iso.predict(bins.pred_mean.to_numpy())

    pearson = z[['pred_abs_net', 'stop_net_target']].corr(method='pearson').iloc[0, 1]
    spearman = z[['pred_abs_net', 'stop_net_target']].corr(method='spearman').iloc[0, 1]
    mae = _weighted_mean(np.abs(bins.observed_mean - bins.calibrated_mean), bins.effective_weight)
    diag = {
        'status': 'OK',
        'rows': int(len(z)),
        'bins': int(len(bins)),
        'global_observed_net': float(global_mean),
        'pearson_raw_abs_to_observed': float(pearson) if np.isfinite(pearson) else None,
        'spearman_raw_abs_to_observed': float(spearman) if np.isfinite(spearman) else None,
        'binned_calibration_mae': float(mae),
        'table': bins.to_dict(orient='records'),
    }
    return iso, diag


def apply_calibrator(scored, calibrator, cfg):
    z = scored.copy()
    if z.empty:
        z['calibrated_net_edge'] = []
        z['calibrated_gross_edge'] = []
        return z
    pred = z.pred_abs_net.to_numpy(dtype=float)
    z['calibrated_net_edge'] = calibrator.predict(pred)
    z['calibrated_gross_edge'] = z.calibrated_net_edge + cfg.roundtrip_cost
    return z


def metrics(frame, margin):
    if frame.empty:
        return {'n': 0, 'symbols': 0, 'avg': None, 'precision': None, 'pf': None, 'max_share': None}
    z = frame[frame.rank_selected & (frame.calibrated_net_edge >= margin)].copy()
    if z.empty:
        return {'n': 0, 'symbols': 0, 'avg': None, 'precision': None, 'pf': None, 'max_share': None}
    r = z.stop_net_target
    pf = _profit_factor(r)
    vc = z.symbol.value_counts()
    return {
        'n': int(len(z)),
        'symbols': int(z.symbol.nunique()),
        'avg': float(r.mean()),
        'precision': float((r > 0).mean()),
        'pf': float(pf) if pf is not None and np.isfinite(pf) else (999.0 if pf is not None else None),
        'max_share': float(vc.iloc[0] / len(z)),
    }


def select_pass(m):
    return (
        m['n'] >= SELECT_MIN_N and m['symbols'] >= SELECT_MIN_SYMBOLS and
        m['avg'] is not None and m['avg'] >= SELECT_MIN_AVG and
        m['pf'] is not None and m['pf'] >= SELECT_MIN_PF and
        m['precision'] is not None and m['precision'] >= SELECT_MIN_PRECISION and
        m['max_share'] is not None and m['max_share'] <= SELECT_MAX_SHARE
    )


def verify_pass(m):
    return (
        m['n'] >= VERIFY_MIN_N and m['symbols'] >= VERIFY_MIN_SYMBOLS and
        m['avg'] is not None and m['avg'] > VERIFY_MIN_AVG and
        m['pf'] is not None and m['pf'] >= VERIFY_MIN_PF and
        m['precision'] is not None and m['precision'] >= VERIFY_MIN_PRECISION and
        m['max_share'] is not None and m['max_share'] <= VERIFY_MAX_SHARE
    )


def choose_margin(cal_scored, ver_scored, cfg):
    candidates = []
    details = []
    for margin in EDGE_MARGINS:
        cm = metrics(cal_scored, margin)
        rec = {
            'net_margin': margin,
            'equivalent_gross_threshold': float(cfg.roundtrip_cost + margin),
            'calibration': cm,
        }
        details.append(rec)
        if select_pass(cm):
            score = float(cm['avg'] * math.sqrt(cm['n']))
            candidates.append((score, margin, cm))
    if not candidates:
        return None, details, None

    # Prefer stronger economic score; tie-break toward the more conservative margin.
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    _, chosen, cm = candidates[0]
    vm = metrics(ver_scored, chosen)
    for d in details:
        if d['net_margin'] == chosen:
            d['chosen_on_calibration'] = True
            d['verification'] = vm
    decision = {
        'chosen_net_margin': chosen,
        'equivalent_gross_threshold': float(cfg.roundtrip_cost + chosen),
        'calibration': cm,
        'verification': vm,
        'status': 'OPEN' if verify_pass(vm) else 'VERIFY_FAIL',
    }
    if not verify_pass(vm):
        return None, details, decision
    return chosen, details, decision


def _window_geometry(test0, purge):
    test1 = test0 + pd.Timedelta(days=TEST_DAYS)
    ver1 = test0 - purge
    ver0 = ver1 - pd.Timedelta(days=VERIFICATION_DAYS)
    cal1 = ver0 - purge
    cal0 = cal1 - pd.Timedelta(days=CALIBRATION_DAYS)
    tr1 = cal0 - purge
    tr0 = tr1 - pd.Timedelta(days=TRAIN_DAYS)
    return tr0, tr1, cal0, cal1, ver0, ver1, test0, test1


def make_dual_oos(ds, cfg, development_symbols):
    devset = set(development_symbols)
    start = ds.index.min().floor('D')
    end = ds.index.max().ceil('D')
    purge = pd.Timedelta(hours=PURGE_HOURS)

    # First test begins only after all three historical windows plus the three purges.
    cursor = start + pd.Timedelta(days=TRAIN_DAYS + CALIBRATION_DAYS + VERIFICATION_DAYS) + 3 * purge
    rows = []
    folds = []

    while cursor + pd.Timedelta(days=TEST_DAYS) <= end:
        tr0, tr1, cal0, cal1, ver0, ver1, test0, test1 = _window_geometry(cursor, purge)
        tr = canonical_frame(_slice(ds, tr0, tr1, devset))
        cal = canonical_frame(_slice(ds, cal0, cal1, devset))
        ver = canonical_frame(_slice(ds, ver0, ver1, devset))
        te = canonical_frame(_slice(ds, test0, test1, devset))

        base = {
            'test_start': str(test0), 'test_end': str(test1),
            'train_start': str(tr0), 'train_end': str(tr1),
            'calibration_start': str(cal0), 'calibration_end': str(cal1),
            'verification_start': str(ver0), 'verification_end': str(ver1),
            'train_rows': len(tr), 'calibration_rows': len(cal),
            'verification_rows': len(ver), 'test_rows': len(te),
            'purge_hours': PURGE_HOURS,
        }
        if len(tr) < cfg.min_training_rows or len(cal) < MIN_CALIBRATOR_ROWS or len(ver) < 40 or len(te) == 0:
            folds.append({**base, 'status': 'SKIP'})
            cursor = test1
            continue

        rm = rank_model(cfg)
        am = absolute_model(cfg)
        rm.fit(tr[R11_FEATURES], tr.target_rank)
        y = tr.stop_net_target.clip(*ABS_TARGET_CLIP)
        am.fit(tr[R11_FEATURES], y)

        cal_scored_raw = score_heads(rm, am, cal)
        calibrator, cal_diag = fit_economic_calibrator(cal_scored_raw)
        if calibrator is None:
            folds.append({**base, 'status': 'NO_TRADE_CALIBRATOR', 'calibrator': json.dumps(cal_diag, separators=(',', ':'))})
            cursor = test1
            continue

        cal_scored = apply_calibrator(cal_scored_raw, calibrator, cfg)
        ver_scored = apply_calibrator(score_heads(rm, am, ver), calibrator, cfg)
        chosen, grid, decision = choose_margin(cal_scored, ver_scored, cfg)

        ts = apply_calibrator(score_heads(rm, am, te), calibrator, cfg)
        ts['fold_test_start'] = str(test0)
        ts['edge_margin'] = chosen if chosen is not None else np.nan
        ts['selected'] = False
        if chosen is not None:
            ts['selected'] = ts.rank_selected & (ts.calibrated_net_edge >= chosen)
            status = 'R12_2_OPEN'
        else:
            status = 'NO_TRADE_R12_2_CALIBRATION'
        rows.append(ts)

        raw_abs_corr = ts[['pred_abs_net', 'stop_net_target']].corr().iloc[0, 1] if len(ts) > 2 else np.nan
        cal_abs_corr = ts[['calibrated_net_edge', 'stop_net_target']].corr().iloc[0, 1] if len(ts) > 2 else np.nan
        rank_corr = ts[['pred_rank', 'target_rank']].corr().iloc[0, 1] if len(ts) > 2 else np.nan
        folds.append({
            **base,
            'status': status,
            'chosen_margin': chosen,
            'calibrator': json.dumps(cal_diag, separators=(',', ':')),
            'selection_grid': json.dumps(grid, separators=(',', ':')),
            'decision': json.dumps(decision, separators=(',', ':')) if decision else None,
            'selected_test': int(ts.selected.sum()),
            'test_raw_abs_corr': float(raw_abs_corr) if np.isfinite(raw_abs_corr) else None,
            'test_calibrated_abs_corr': float(cal_abs_corr) if np.isfinite(cal_abs_corr) else None,
            'test_rank_corr': float(rank_corr) if np.isfinite(rank_corr) else None,
        })
        cursor = test1

    return (pd.concat(rows).sort_index() if rows else pd.DataFrame()), pd.DataFrame(folds)


def fold_stability_r12_2(trades, fold_meta):
    folds = [str(x) for x in fold_meta.loc[fold_meta.status != 'SKIP', 'test_start'].tolist()]
    rows = []
    for f in folds:
        g = trades[trades.fold_test_start.astype(str) == f] if not trades.empty else trades
        pnl = float(g.pnl_cash.sum()) if len(g) and 'pnl_cash' in g else 0.0
        avg = float(g.net_return.mean()) if len(g) else 0.0
        rows.append({'fold_test_start': f, 'trades': int(len(g)), 'pnl_cash': pnl, 'avg_net': avg, 'positive': bool(pnl > 0)})
    if not rows:
        return {'folds': 0, 'positive_folds': 0, 'positive_share': 0.0, 'median_fold_pnl': 0.0, 'rows': []}
    d = pd.DataFrame(rows)
    return {
        'folds': int(len(d)), 'positive_folds': int(d['positive'].sum()),
        'positive_share': float(d['positive'].mean()),
        'median_fold_pnl': float(d['pnl_cash'].median()), 'rows': rows,
    }


def evaluate(name, pred, data, cfg, folds, concentration):
    sig = build_signals(pred, data, cfg, KIND)
    if concentration:
        tr, port = simulate_concentration(sig, data, cfg, 0.0)
        trs, stress = simulate_concentration(sig, data, cfg, 2 * cfg.slippage_side)
    else:
        tr, port = simulate_fixed(sig, data, cfg, 0.0)
        trs, stress = simulate_fixed(sig, data, cfg, 2 * cfg.slippage_side)
    stability = fold_stability_r12_2(tr, folds)
    checks = gate_checks(port, stress, stability)
    if not sig.empty:
        sig.to_csv(f'r12_2_{name.lower()}_signals.csv', index=False)
    if not tr.empty:
        tr.to_csv(f'r12_2_{name.lower()}_trades.csv', index=False)
    if not trs.empty:
        trs.to_csv(f'r12_2_{name.lower()}_trades_2x_slippage.csv', index=False)
    return {
        'signals': int(len(sig)), 'portfolio': port, 'double_slippage': stress,
        'fold_stability': stability, 'checks': checks, 'development_pass': all(checks.values()),
    }


def main():
    base_cfg = config_for_timeframe(TF)
    cfg = replace(
        base_cfg,
        train_days=TRAIN_DAYS,
        calibration_days=CALIBRATION_DAYS,
        calibration_verify_days=VERIFICATION_DAYS,
        test_days=TEST_DAYS,
    )

    raw, skipped = download_universe(DEV_CANDIDATES)
    dev = [s for s in DEV_CANDIDATES if s in raw]
    raw = canonical_data(raw, dev)
    data = canonical_data(resample_universe(raw, TF), dev)

    ds = canonical_frame(make_dataset(data, 'BTCUSDT', cfg, development_symbols=dev))
    ds = canonical_frame(attach_stop_only_targets(ds, data, cfg, dev))
    dshash = frame_hash(ds, ['symbol', 'target_rank', 'stop_net_target'] + R11_FEATURES)

    pred1, folds = make_dual_oos(ds, cfg, dev)
    pred2, _ = make_dual_oos(ds, cfg, dev)
    hash_cols = [
        'symbol', 'pred_rank', 'pred_abs_net', 'calibrated_net_edge', 'rank_z',
        'pred_order', 'rank_selected', 'edge_margin', 'selected', 'fold_test_start',
    ]
    ph1 = frame_hash(pred1, hash_cols)
    ph2 = frame_hash(pred2, hash_cols)
    reproducible = ph1 == ph2
    if not reproducible:
        raise RuntimeError(f'R12.2 reproducibility failed {ph1} != {ph2}')

    open_status = 'R12_2_OPEN'
    result = {
        'version': 'V10-R12.2-EXTENDED-CALIBRATION-ABSOLUTE-EDGE',
        'period': [str(START), str(END)],
        'timeframe': TF, 'top_k': TOP_K, 'min_rank_z': MIN_RANK_Z, 'exit': KIND,
        'geometry': {
            'train_days': TRAIN_DAYS,
            'calibration_days': CALIBRATION_DAYS,
            'verification_days': VERIFICATION_DAYS,
            'test_days': TEST_DAYS,
            'strict_purge_hours': PURGE_HOURS,
            'windows_are_sequential': True,
        },
        'absolute_head': {
            'model': 'HistGradientBoostingRegressor absolute_error',
            'raw_target': 'STOP_ONLY net return after modeled costs',
            'target_clip': ABS_TARGET_CLIP,
            'economic_calibration': 'quantile-binned shrinkage isotonic pred_abs_net -> observed net return',
            'calibration_bins': CALIBRATION_BINS,
            'calibration_pseudocount': CALIBRATION_PSEUDOCOUNT,
            'edge_margins': EDGE_MARGINS,
            'economic_rule': 'rank high AND calibrated_gross_edge > roundtrip_cost + chosen_margin; equivalently calibrated_net_edge > chosen_margin',
        },
        'threshold_protocol': 'Choose margin on 120d calibration only; fixed calibrator+margin must independently pass 30d verification; 30d test never selects or refits.',
        'selection_min_n_preserved': SELECT_MIN_N,
        'development_symbols': dev, 'skipped': skipped, 'dataset_rows': int(len(ds)),
        'dataset_hash': dshash, 'prediction_hash_1': ph1, 'prediction_hash_2': ph2,
        'prediction_reproducible': reproducible,
        'outer_holdout_preregistered': OUTER_HOLDOUT,
        'outer_holdout_opened': False,
        'outer_holdout_reason': 'R12.2 remains a development stage. Holdout stays sealed until the frozen primary arm passes development gates.',
        'folds_total': int(len(folds)),
        'folds_open': int((folds.status == open_status).sum()) if len(folds) else 0,
        'arms': {},
    }
    result['arms']['DUAL_HEAD_CALIBRATED'] = evaluate('DUAL_HEAD_CALIBRATED', pred1, data, cfg, folds, False)
    result['arms']['DUAL_HEAD_CALIBRATED_CONC'] = evaluate('DUAL_HEAD_CALIBRATED_CONC', pred1, data, cfg, folds, True)
    result['primary_arm'] = 'DUAL_HEAD_CALIBRATED_CONC'
    result['primary_development_pass'] = result['arms']['DUAL_HEAD_CALIBRATED_CONC']['development_pass']

    folds.to_csv('r12_2_folds.csv', index=False)
    if not pred1.empty:
        pred1[pred1.selected].to_csv('r12_2_selected_predictions.csv')
    Path('r12_2_result.json').write_text(json.dumps(result, indent=2, default=str))
    Path('r12_2_report.md').write_text(
        '# V10 R12.2 Extended Calibration / Absolute Edge\n\n' + json.dumps(result, indent=2, default=str) + '\n'
    )
    print('===R12_2_RESULT_JSON===')
    print(json.dumps(result, separators=(',', ':'), default=str))
    print('===END_R12_2_RESULT_JSON===')


if __name__ == '__main__':
    main()
