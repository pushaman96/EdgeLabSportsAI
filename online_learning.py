"""Bounded per-game feedback. Experimental updates, not validated improvements.

Rebuild from frozen prospective records, in grade-time order. One game receives
one update per model/category, regardless of quotes, lines or correlated props.
"""
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PATH = 'online_learning_state.json'
METHOD = 'per-game-feedback-v1'
RATE = 1 / 13  # Twelve games of neutral prior weight; learn from game one.
MAX_BIAS = .15


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def utc(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def key(record):
    return json.dumps([record.get('sport', 'NFL'), record.get('base_model') or record.get('model', 'Unknown'), record.get('category'), record.get('season_type', 'Regular season')], separators=(',', ':'))


def eligible(record, asof):
    try:
        return (record.get('strategy') in ('Original', 'Analysis')
                and record.get('evidence') in ('Personal paper record', 'Published before kickoff')
                and record.get('season_type') == 'Regular season'
                and record.get('result') in ('Win', 'Loss', 'Push')
                and bool(record.get('event_id')) and bool(record.get('player'))
                and utc(record['published_utc']) < utc(record['starts_utc']) < utc(record['graded_utc']) <= asof)
    except (KeyError, TypeError, ValueError):
        return False


def clip(value, bound):
    return max(-bound, min(bound, value))


def scale_probability(probability, temperature):
    probability = max(.001, min(.999, probability))
    return max(.05, min(.95, 1 / (1 + math.exp(-temperature * math.log(probability / (1 - probability))))))


def forecast_value(record):
    for field in ('base_projection', 'projected_count', 'projected_yards'):
        value = number(record.get(field))
        if value is not None:
            return value
    return None


def build_state(records, asof=None):
    asof = asof or datetime.now(timezone.utc)
    groups = defaultdict(list)
    for record in records:
        if eligible(record, asof):
            groups[key(record)].append(record)
    fitted = {}
    for group, rows in sorted(groups.items()):
        events = defaultdict(list)
        for row in rows:
            events[str(row['event_id'])].append(row)
        state = dict(games=0, forecast_games=0, probability_games=0, bias=0., workload_bias=0., temperature=1., issued_comparisons=0, base_brier_sum=0., issued_brier_sum=0.)
        comparisons = []
        for event, batch in sorted(events.items(), key=lambda item: (max(utc(r['graded_utc']) for r in item[1]), item[0])):
            # Keep the earliest frozen original forecast per player. Extra books,
            # lines and directions do not create extra training observations.
            players = {}
            for row in sorted(batch, key=lambda r: (utc(r['published_utc']), str(r.get('id', '')))):
                players.setdefault(row['player'], row)
            residuals, workloads, gradients, game_deltas = [], [], [], []
            for row in players.values():
                baseline, actual = forecast_value(row), number(row.get('actual'))
                if baseline is not None and baseline > 0 and actual is not None and actual >= 0:
                    residuals.append(clip((actual - baseline) / max(1., baseline), .5))
                expected = number(row.get('base_expected_opportunities', row.get('expected_opportunities')))
                observed = number(row.get('actual_opportunities'))
                if expected is not None and expected > 0 and observed is not None and observed >= 0:
                    workloads.append(clip((observed - expected) / max(1., expected), .5))
                p = number(row.get('online_input_probability', row.get('raw_probability', row.get('probability'))))
                if p is not None and 0 < p < 1 and row['result'] in ('Win', 'Loss'):
                    y = int(row['result'] == 'Win')
                    gradients.append(clip((scale_probability(p, state['temperature']) - y) * math.log(p / (1 - p)), 1.))
                # Compare forecasts actually frozen before this game's outcome,
                # never a retrospective score using the newly fitted state.
                base_p = number(row.get('base_probability'))
                issued = number(row.get('candidate_probability', row.get('probability')))
                base_projection = number(row.get('base_projection'))
                candidate_projection = number(row.get('candidate_projection'))
                if row.get('online_version') and base_projection is not None and candidate_projection is not None and actual is not None:
                    scale = max(1., abs(base_projection))
                    game_deltas.append(clip(((candidate_projection-actual)/scale)**2 - ((base_projection-actual)/scale)**2, 1.))
                if row.get('online_version') and base_p is not None and issued is not None and row['result'] in ('Win', 'Loss'):
                    y = int(row['result'] == 'Win')
                    state['issued_comparisons'] += 1
                    state['base_brier_sum'] += (base_p - y) ** 2
                    state['issued_brier_sum'] += (issued - y) ** 2
                    game_deltas.append((issued-y)**2-(base_p-y)**2)
            if game_deltas:comparisons.append(statistics.mean(game_deltas))
            if residuals:
                state['bias'] = clip((1 - RATE) * state['bias'] + RATE * statistics.mean(residuals), MAX_BIAS)
                state['forecast_games'] += 1
            if workloads:
                state['workload_bias'] = clip((1 - RATE) * state['workload_bias'] + RATE * statistics.mean(workloads), MAX_BIAS)
            if gradients:
                state['temperature'] = max(.5, min(1.5, state['temperature'] - .1 * statistics.mean(gradients)))
                state['probability_games'] += 1
            state['games'] += 1
        # Each game's frozen candidate versus baseline contributes once. A
        # recently harmful candidate is damped, then rolled back if sustained.
        recent=comparisons[-20:]
        mean_delta=statistics.mean(recent) if recent else 0.
        lower=mean_delta-1.96*statistics.stdev(recent)/math.sqrt(len(recent)) if len(recent)>1 else -1.
        factor=0. if len(recent)>=10 and mean_delta>.01 and lower>0 else .5 if len(recent)>=5 and mean_delta>.01 else 1.
        state.update(comparison_games=len(recent),candidate_loss_delta=mean_delta,comparison_lower_bound=lower,application_weight=factor,guard_status='Rolled back to base forecast' if factor==0 else 'Reduced learning weight' if factor==.5 else 'Experimental learning active')
        state['trained_through'] = max(utc(r['graded_utc']) for r in rows).isoformat()
        state['version'] = hashlib.sha256(json.dumps([group, state], sort_keys=True).encode()).hexdigest()[:12]
        fitted[group] = state
    return dict(schema=1, method=METHOD, generated_utc=asof.isoformat(), groups=fitted,
                status='Experimental per-game updates; improvement is not yet established')


def write_state(records, path=PATH, asof=None):
    state = build_state(records, asof)
    target = Path(path)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(target)
    return state


def fitted_state(row, now=None, state=None, sport='NFL'):
    now = now or datetime.now(timezone.utc)
    try:
        state = state if state is not None else json.loads(Path(PATH).read_text())
        if state.get('schema') != 1 or state.get('method') != METHOD:
            return {}
        if not 0 <= (now - utc(state['generated_utc'])).total_seconds() <= 30 * 86400:
            return {}
        lookup = dict(sport=sport, base_model=row.get('Base model') or row.get('Model'), category=row.get('Category'), season_type='Regular season')
        fitted = state.get('groups', {}).get(key(lookup), {})
        if not fitted or utc(fitted['trained_through']) > utc(state['generated_utc']) or utc(fitted['trained_through']) >= now or fitted['games'] < 1:
            return {}
        if not all(number(fitted.get(k)) is not None for k in ('bias', 'workload_bias', 'temperature')):
            return {}
        if number(fitted.get('application_weight',1.)) not in (0.,.5,1.):return {}
        if abs(fitted['bias']) > MAX_BIAS or abs(fitted['workload_bias']) > MAX_BIAS or not .5 <= fitted['temperature'] <= 1.5:
            return {}
        return fitted
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def adjust_forecast(row, projected, workload, now=None, state=None, sport='NFL'):
    row['Base projection'] = projected
    row['Base expected opportunities'] = workload
    fitted = fitted_state(row, now, state, sport)
    if not fitted:
        return projected, workload
    row['Online version'] = fitted['version']
    row['Online learning status'] = fitted.get('guard_status','Experimental learning active') + f"; {fitted['games']} completed games"
    row['Candidate projection'] = max(0., projected * (1 + fitted['bias']))
    weight=fitted.get('application_weight',1.)
    return max(0., projected * (1 + weight*fitted['bias'])), max(0., workload * (1 + weight*fitted['workload_bias']))


def adjust_probability(row, probability, now=None, state=None, sport='NFL'):
    row['Online input win %'] = probability * 100
    row.setdefault('Base estimated win %', probability * 100)
    fitted = fitted_state(row, now, state, sport)
    if not fitted:
        return probability
    row['Online version'] = fitted['version']
    row['Online learning status'] = fitted.get('guard_status','Experimental learning active') + f"; {fitted['games']} completed games"
    weight=fitted.get('application_weight',1.)
    candidate_input=number(row.get('Candidate input win %'))
    row['Candidate win %'] = 100*scale_probability(candidate_input/100 if candidate_input is not None else probability, fitted['temperature'])
    return probability if weight==0 else scale_probability(probability, 1+weight*(fitted['temperature']-1))
