"""Explicit combined-stat and scoring evidence. Missing is never zero."""
import math
import re
def num(v):
    try:
        x=float(v);return x if math.isfinite(x)and x>=0 else None
    except (ValueError,TypeError):return None
def key(s):return re.sub('[^a-z0-9]','',str(s).lower())
def nba_minutes(player,data):
    values=[]
    for team in data.get('boxscore',{}).get('players',[]):
        for group in team.get('statistics',[]):
            for a in group.get('athletes',[]):
                if key(a.get('athlete',{}).get('displayName'))!=key(player):continue
                raw=dict(zip(group.get('labels',[]),a.get('stats',[]))).get('MIN')
                try:
                    parts=str(raw).split(':');value=num(parts[0])
                    if len(parts)==2:value=value+float(parts[1])/60 if value is not None and 0<=float(parts[1])<60 else None
                except (ValueError,TypeError):value=None
                if value is not None:values.append(value)
    return values[0]if len(values)==1 else None
def current_value(category,player,data):
    if category=='Game total points':
        teams=data.get('header',{}).get('competitions',[{}])[0].get('competitors',[])
        values=[num(t.get('score'))for t in teams]
        return sum(values)if len(values)==2 and all(v is not None for v in values)else None
    entries=[]
    for team in data.get('boxscore',{}).get('players',[]):
        for group in team.get('statistics',[]):
            for a in group.get('athletes',[]):
                if key(a.get('athlete',{}).get('displayName'))==key(player):entries.append((group, a,dict(zip(group.get('labels',[]),a.get('stats',[])))))
    if category=='PRA':
        values=[]
        for group,a,stats in entries:
            if a.get('didNotPlay')is True:continue
            components=[num(stats.get(k))for k in ('PTS','REB','AST')]
            if all(v is not None for v in components):values.append(sum(components))
        return values[0]if len(values)==1 else None
    if category!='Anytime touchdown':return None
    ids={a.get('athlete',{}).get('id')for g,a,s in entries}
    if not entries or len(ids)!=1:return None
    plays=data.get('scoringPlays')
    if not isinstance(plays,list):return None
    scored=[]
    for play in plays:
        kind=play.get('scoringType',{}).get('name')
        if not kind:return None
        if kind!='touchdown':continue
        match=re.match(r'^(.+?)\s+\d+\s+Yd\b',str(play.get('text','')),re.I)
        if not match:return None
        scored.append(key(match.group(1)))
    # A positive official scorer occurrence is sufficient. A zero requires a
    # complete scoring ledger through final score and verified participation.
    if key(player)in scored:return scored.count(key(player))
    teams=data.get('header',{}).get('competitions',[{}])[0].get('competitors',[])
    scores={t.get('homeAway'):num(t.get('score'))for t in teams}
    if set(scores)!= {'home','away'}or any(v is None for v in scores.values()):return None
    if plays:
        last=plays[-1]
        if num(last.get('homeScore'))!=scores['home']or num(last.get('awayScore'))!=scores['away']:return None
    elif scores['home']+scores['away']!=0:return None
    # No offensive stat row means no verified appearance, not a zero or DNP.
    participated=False
    for g,a,stats in entries:
        label={'passing':'C/ATT','rushing':'CAR','receiving':'REC'}.get(g.get('name'))
        value=num(str(stats.get(label,'')).split('/')[-1])if label else None
        if value is not None and value>0:participated=True
    return 0 if participated else None
