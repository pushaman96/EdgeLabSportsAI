"""Measured postgame error decomposition; no retrospective causal claims or refits."""
import math


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def review_pick(record):
    """Caller selects prospective originals. Preserve missing values and frozen inputs."""
    r = record
    out = {'Pick ID': r.get('id'), 'Game': r.get('game'), 'Player': r.get('player'),
           'Category': r.get('category'), 'Selection': r.get('direction'),
           'Book line': r.get('line'), 'Result': r.get('result'),
           'Saved reasoning': r.get('reason', ''),
           'Learning version used': r.get('online_version'),
           'Interpretation': 'Pending final evidence; no error assigned'}
    if r.get('result') not in ('Win', 'Loss', 'Push'):
        return out
    actual = number(r.get('actual'))
    projection = number(r.get('projected_count'))
    if projection is None:
        projection = number(r.get('projected_yards'))
    expected = number(r.get('expected_opportunities'))
    observed = number(r.get('actual_opportunities'))
    probability = number(r.get('probability'))
    out.update({'Forecast': projection, 'Actual': actual,
                'Expected workload': expected, 'Actual workload': observed,
                'Actual minus forecast': actual-projection if actual is not None and projection is not None else None,
                'Workload error': observed-expected if observed is not None and expected is not None else None})
    if probability is not None and 0 < probability < 1 and r['result'] in ('Win', 'Loss'):
        out['Estimated win %'] = 100*probability
        out['Brier error'] = (probability-int(r['result']=='Win'))**2
    if actual is not None and projection is not None and expected is not None and expected > 0 and observed is not None and observed >= 0:
        rate = projection/expected
        workload_component = (observed-expected)*rate
        production_component = actual-observed*rate
        out.update({'Workload component': workload_component,
                    'Production component': production_component,
                    'Actual at forecast rate': observed*rate})
        out['Interpretation'] = ('Larger measured component: workload' if abs(workload_component)>abs(production_component)
                                 else 'Larger measured component: production per opportunity')
    else:
        out['Interpretation'] = 'Incomplete workload/rate evidence; no component attribution'
    if r.get('category') == 'Moneyline':
        out['Interpretation'] = 'Outcome and probability error only; team-score causes require separate evidence'
    out['Interpretation'] += '; descriptive arithmetic, not a proven cause'
    return out


def build_diagnostics(records):
    """Earliest valid original per player/game/category/model; no duplicate-book weighting."""
    from slate_review import eligible
    seen = set()
    rows = []
    for record in sorted(records, key=lambda r: (str(r.get('published_utc') or '9999'), str(r.get('id') or ''))):
        if not eligible(record):
            continue
        identity = (record.get('sport', 'NFL'), record.get('event_id'), record.get('player'),
                    record.get('category'), record.get('base_model') or record.get('model'))
        if identity in seen:
            continue
        seen.add(identity)
        rows.append(review_pick(record))
    return rows


def render(rows):
    import streamlit as st
    if not rows:
        return
    st.write('**Pick-by-pick forecast review**')
    st.caption('The bookmaker sets the line; the app estimates the outcome. Workload component = workload error × forecast production rate. Production component is the remaining error. Together they equal actual minus forecast. Neither component proves an injury, matchup or coaching cause. A winning pick can still have an inaccurate forecast.')
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.caption('Review both wins and losses. Missing statistics stay blank. Existing bounded learning updates future forecasts by exact model/category; new formulas or selection thresholds must pass earlier-fit/later-test validation and frozen future-game comparisons before being called improvements.')
