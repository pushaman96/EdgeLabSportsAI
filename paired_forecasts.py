"""Frozen same-quote base versus issued comparisons; no retrospective refitting."""
import math
from collections import defaultdict
from datetime import datetime
def num(v):
    return float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) else None
def capture(row):
    count=row.get('Projection (count)')
    projection=count if num(count)is not None else row.get('Projection (yards)')
    return {'version':1,'base_projection':num(row.get('Base projection')),
            'issued_projection':num(projection),
            'base_workload':num(row.get('Base expected opportunities')),
            'issued_workload':num(row.get('Expected opportunities')),
            'base_probability':num(row.get('Base estimated win %'))/100 if num(row.get('Base estimated win %'))is not None else None,
            'issued_probability':num(row.get('Estimated win %'))/100 if num(row.get('Estimated win %'))is not None else None,
            'learning_version':row.get('Online version'),
            'scope':'Frozen unadjusted base versus actually issued forecast; not hypothetical candidate'}
def summary(records,sport):
    selected={}
    for r in sorted(records,key=lambda r:(r.get('published_utc')or'9999',r.get('id',''))):
        if r.get('sport','NFL')!=sport or r.get('strategy')not in ('Original','Analysis') or r.get('evidence')not in ('Personal paper record','Published before kickoff') or r.get('season_type')!='Regular season':continue
        try:
            if datetime.fromisoformat(r['published_utc'].replace('Z','+00:00'))>=datetime.fromisoformat(r['starts_utc'].replace('Z','+00:00')):continue
        except (ValueError,KeyError,TypeError):continue
        pair=r.get('paired_forecast')or{}
        if pair.get('version')!=1:continue
        key=(r.get('event_id'),r.get('player'),r.get('category'),r.get('base_model')or r.get('model'))
        selected.setdefault(key,r)
    groups=defaultdict(list)
    for key,r in selected.items():groups[key[2],key[3]].append(r)
    output=[]
    for (category,model),rows in sorted(groups.items()):
        result={'Category':category,'Model':model,'Frozen forecasts':len(rows),'Distinct games':len({r['event_id']for r in rows})}
        for label,base,issued,actual in [('Projection MAE','base_projection','issued_projection','actual'),('Workload MAE','base_workload','issued_workload','actual_opportunities'),('Brier','base_probability','issued_probability',None)]:
            games=defaultdict(list);n=0
            for r in rows:
                if r.get('result')not in ('Win','Loss','Push'):continue
                p=r['paired_forecast'];a=num(p.get(base));b=num(p.get(issued))
                if a is None or b is None:continue
                if actual:
                    y=num(r.get(actual))
                    if y is None:continue
                    errors=(abs(a-y),abs(b-y))
                else:
                    if r['result']=='Push'or not (0<a<1 and 0<b<1):continue
                    y=int(r['result']=='Win');errors=((a-y)**2,(b-y)**2)
                games[r['event_id']].append(errors);n+=1
            def avg(i):
                return sum(sum(v[i]for v in values)/len(values)for values in games.values())/len(games)if games else None
            a,b=avg(0),avg(1)
            result.update({label+' comparisons':n,label+' games':len(games),'Base '+label:a,'Issued '+label:b,'Issued minus base '+label:b-a if a is not None else None})
        output.append(result)
    return output
def render(records,sport):
    import json
    from pathlib import Path
    import streamlit as st
    try:analyzed=json.loads(Path('analyzed_forecasts.json').read_text())['records']
    except (OSError,ValueError,KeyError):analyzed=[]
    # Prefer fresh graded published rows when the same record is present twice.
    merged={r['id']:r for r in analyzed}
    merged.update({r['id']:r for r in records})
    with st.expander('Original versus adjusted — frozen future-game comparison'):
        rows=summary(list(merged.values()),sport)
        if rows:st.dataframe(rows,hide_index=True,use_container_width=True)
        else:st.info('Waiting for new paired forecasts. Older base forecasts are not reconstructed after results.')
        st.caption('Includes usable analyzed passes and recommendations, separate from official pick accuracy. Earliest player/game/category/model counts once; paired errors are averaged equally by game. Negative issued-minus-base errors favor the issued forecast. Missing statistics are excluded independently. An unchanged forecast is not evidence that learning helped; lower observed error alone does not prove future improvement.')
