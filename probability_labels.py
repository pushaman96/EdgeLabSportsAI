"""Display-only probability labels. Never changes frozen forecasts or pick eligibility."""
import math

GROUPS = ('High probability', 'Low probability', 'Probability unavailable')
LEGEND = '🔵 High: 60% or more · 🟠 Low: below 60% · ⚪ Unavailable. Model estimates, not verified hit rates or guarantees. Live groups use the frozen pregame estimate, not an updated in-game probability.'

def indicator(value, *, percent=False):
    if isinstance(value, bool):
        value = None
    try:
        p = float(value)
        if percent:
            p /= 100
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        return {'group': GROUPS[2], 'label': '⚪ Probability unavailable', 'percent': None}
    high = p >= .60
    group = GROUPS[0] if high else GROUPS[1]
    return {'group': group, 'label': ('🔵 ' if high else '🟠 ') + group + f' · {100*p:.1f}%', 'percent': 100*p}

def decorate(row):
    result = dict(row)
    for key in ('Estimated win %', 'Model win %', 'Frozen model probability %'):
        if key in row:
            badge = indicator(row[key], percent=True)
            return {'Probability indicator': badge['label'], **result}
    return result

def grouped(rows):
    groups = {name: [] for name in GROUPS}
    for row in rows:
        badge = indicator(row.get('Frozen model probability %'), percent=True)
        groups[badge['group']].append({'Probability indicator': badge['label'], **row})
    for values in groups.values():
        values.sort(key=lambda r: -(indicator(r.get('Frozen model probability %'), percent=True)['percent'] if indicator(r.get('Frozen model probability %'), percent=True)['percent'] is not None else -1))
    return groups
