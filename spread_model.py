"""Independent margin research. Never turns unvalidated estimates into betting picks."""
from collections import defaultdict, deque
from datetime import date, datetime
from math import isfinite
from statistics import mean


def day(value):
    if isinstance(value, datetime): return value.date()
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def prepare(games):
    history = defaultdict(lambda: deque(maxlen=12))
    margins = []
    predictions = []
    valid = []
    for g in games:
        try:
            h, a = float(g['home_score']), float(g['away_score'])
            if not all(isfinite(v) and v >= 0 for v in (h, a)): continue
            valid.append((day(g['date']), g, h-a))
        except (KeyError, TypeError, ValueError): continue
    valid.sort(key=lambda x:x[0])
    from itertools import groupby
    for played, batch in groupby(valid, key=lambda x:x[0]):
        batch = list(batch)
        advantage = mean(margins[-1000:]) if margins else 0.0
        for _, g, actual in batch:
            home, away = history[g['home_team']], history[g['away_team']]
            if len(home)>=8 and len(away)>=8 and len(margins)>=100:
                projected = advantage + .5*(mean(home)-mean(away))
                predictions.append({'date':played,'season':g.get('season',played.year),'projection':projected,'actual':actual,'baseline':advantage,'residual':actual-projected})
        for _, g, actual in batch:
            history[g['home_team']].append(actual)
            history[g['away_team']].append(-actual)
            margins.append(actual)
    seasons = sorted({r['season'] for r in predictions})
    # Keep current partial season out of this descriptive completed-year comparison.
    test = seasons[-2] if len(seasons)>=3 else None
    sample = [r for r in predictions if r['season']==test]
    return {'history':dict(history),'advantage':mean(margins[-1000:]) if margins else 0.0,
            'cutoff':valid[-1][0] if valid else None,
            'validation_games':len(sample),'validation_season':test,
            'mae':mean(abs(r['actual']-r['projection']) for r in sample) if sample else None,
            'baseline_mae':mean(abs(r['actual']-r['baseline']) for r in sample) if sample else None}


def forecast(prepared, home, away, kickoff):
    cutoff=prepared['cutoff']
    if cutoff is None or day(kickoff)<=cutoff: return None
    h=prepared['history'].get(home,[]);a=prepared['history'].get(away,[])
    if len(h)<8 or len(a)<8:return None
    return round(prepared['advantage']+.5*(mean(h)-mean(a)),1)


def cover_result(margin, spread):
    if margin is None or spread is None:return None
    value=float(margin)+float(spread)
    if not isfinite(value):return None
    return 'Win' if value>0 else 'Loss' if value<0 else 'Push'


def rows(events, models):
    output=[]
    for e in events:
        context=models.get((e.get('home_team'),e.get('away_team')),{})
        margin=context.get('spread_margin')
        if margin is None:continue
        for b in e.get('bookmakers',[]):
            for m in b.get('markets',[]):
                if m.get('key')!='spreads':continue
                for o in m.get('outcomes',[]):
                    team=o.get('name')
                    if team not in (e.get('home_team'),e.get('away_team')):continue
                    try:line=float(o['point'])
                    except (KeyError,ValueError,TypeError):continue
                    if not isfinite(line):continue
                    selected=margin if team==e['home_team'] else -margin
                    output.append({'Game':e['away_team']+' at '+e['home_team'],'Team':team,
                        'Spread':f'{line:+g}','Projected margin':selected,
                        'Projection vs line':'Cover' if selected+line>0 else 'Does not cover' if selected+line<0 else 'At line',
                        'Decision':'Pass — spread model not validated',
                        'Sportsbook':b.get('title',b.get('key')),
                        'Quote updated UTC':m.get('last_update') or b.get('last_update')})
    return output


def render(events, models):
    import streamlit as st
    with st.expander('Plus/minus lines — experimental margin research'):
        st.caption('Positive margin means that team is projected to win by that many points. A minus line requires winning by more than the line; a plus line allows losing by fewer points. An exact final tie against a whole-point line is a push. These research estimates are not spread recommendations or calibrated cover probabilities.')
        data=rows(events,models)
        if data:st.dataframe(data,hide_index=True,use_container_width=True)
        else:st.info('No supported spread comparison in the loaded game lines. No additional odds request was made.')
        reports=[c.get('spread_validation') for c in models.values() if c.get('spread_validation')]
        if reports:
            r=reports[0]
            st.write(f"Chronological margin check: {r['validation_games']} games, season {r['validation_season']}; model mean absolute error {r['mae']:.2f} points vs home-margin baseline {r['baseline_mae']:.2f} points." if r.get('mae') is not None else 'Not enough historical games for a chronological margin comparison.')
        st.caption('Uses up to 12 prior team game margins and prior league home advantage. Does not numerically model injuries, lineups or weather. Actual historical sportsbook lines and chronological cover-probability validation are still required before any Take recommendation. Research rows are excluded from the pick score.')
