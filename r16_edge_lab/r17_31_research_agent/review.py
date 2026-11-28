"""Review matured labels only. Propose changes; never rewrite policy or code."""
import math


def review(records, *, as_of_ms):
    seen, errors, scores = set(), [], []
    for row in records:
        try:
            identifier = row['decision_id']
            if not isinstance(identifier,str) or not identifier or identifier in seen:
                raise ValueError('duplicate or missing decision id')
            seen.add(identifier)
            p, y = row['probability'], row['outcome']
            if type(p) not in (int,float) or not math.isfinite(p) or not 0<=p<=1 or type(y) is not int or y not in (0,1):
                raise ValueError('invalid probability/outcome')
            decision, matured, known = (row[k] for k in ('decision_ms','matured_ms','label_known_ms'))
            if any(type(t) is not int for t in (decision,matured,known)) or not 0<=decision<matured<=known<=as_of_ms:
                raise ValueError('unmatured or future label')
            source=row['label_source_sha256']
            if not isinstance(source,str) or len(source)!=64 or any(c not in '0123456789abcdef' for c in source):
                raise ValueError('missing label provenance')
            scores.append((p-y)**2)
        except (ValueError,KeyError,TypeError) as exc:
            errors.append(str(exc))
    return dict(label_count=len(scores), rejected_labels=len(errors), errors=errors,
                brier_score=sum(scores)/len(scores) if scores else None,
                calibration_status='DESCRIPTIVE_ONLY' if scores else 'NOT_MEASURED_NO_MATURED_LABELS',
                automatic_code_changes=0, automatic_promotions=0,
                next_action='Collect independent matured labels and compare costs before any promotion.')
