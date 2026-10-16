"""Pregame workload stress tests and descriptive score-state review.
Outcome-conditioned histories are stress scenarios, not predicted game scripts.
"""
import math
import statistics

def workload_risk(player,season,week,team,line,idx,schedule):
    games={g['game_id']:g for g in schedule}
    history=sorted([r for (year,pid),rows in idx[0].items() if pid==player and season-2<=year<=season for r in rows if (r['season'],r['week'])<(season,week) and r.get('position')=='QB' and (r.get('attempts') or 0)>=15],key=lambda r:(r['season'],r['week']))[-24:]
    scenarios={'Team won by 8+':[],'Finished within 7':[],'Team lost by 8+':[]}
    values=[]
    for r in history:
        g=games.get(r['game_id'],{})
        try:margin=float(g['home_score'])-float(g['away_score'])
        except (KeyError,TypeError,ValueError):continue
        margin=margin if g['home_team']==r['team'] else -margin
        label='Team won by 8+' if margin>=8 else 'Team lost by 8+' if margin<=-8 else 'Finished within 7'
        scenarios[label].append(r['attempts']);values.append(r['attempts'])
    if len(values)<8:return None
    ordered=sorted(values)
    return {'Prior starter games':len(values),'Historical high-volume attempts (80th percentile)':ordered[math.ceil(.8*len(ordered))-1],
            'Prior attempts above quoted line %':round(100*sum(v>line for v in values)/len(values),1) if line is not None else None,
            'Scenarios':[{'Historical outcome context':label,'Games':len(v),'Average passing attempts':round(statistics.mean(v),1) if len(v)>=3 else None,'Status':'Stress context only; includes overtime and different opponents' if len(v)>=3 else 'Too few games'} for label,v in scenarios.items()]}

def play_review(data):
    competition=data.get('header',{}).get('competitions',[{}])[0]
    competitors=competition.get('competitors',[])
    home=next((str(t['id']) for t in competitors if t.get('homeAway')=='home'),None)
    names={str(t['id']):t.get('team',{}).get('displayName',str(t['id'])) for t in competitors}
    buckets={};seen=set();previous=(0,0)
    drives=list(data.get('drives',{}).get('previous',[]));current=data.get('drives',{}).get('current')
    if isinstance(current,dict):drives.append(current)
    plays=[(p,d) for d in drives for p in d.get('plays',[])]
    plays.sort(key=lambda pair:int(pair[0].get('sequenceNumber') or 0))
    for p,d in plays:
        if not p.get('id') or p['id'] in seen:continue
        seen.add(p['id'])
        before=previous
        if p.get('homeScore') is not None and p.get('awayScore') is not None:previous=(p['homeScore'],p['awayScore'])
        text=str(p.get('text','')).lower();kind=str(p.get('type',{}).get('text','')).lower()
        if 'no play' in text or 'penalty' in kind:continue
        period=p.get('period',{}).get('number')
        team=str(p.get('start',{}).get('team',{}).get('id') or d.get('team',{}).get('id',''))
        if not isinstance(period,int) or team not in names:continue
        sack='sack' in kind or 'sacked' in text
        attempt=not sack and (any(w in kind for w in ('pass','interception')) or 'spike' in kind or 'spikes the ball' in text)
        run='rush' in kind or 'scrambl' in text or 'kneel' in text
        if not (attempt or sack or run):continue
        margin=before[0]-before[1] if team==home else before[1]-before[0]
        state='Trailing by 8+' if margin<=-8 else 'Leading by 8+' if margin>=8 else 'Within 7'
        key=(names[team],'Overtime' if period>4 else 'Regulation',state)
        row=buckets.setdefault(key,{'Team':key[0],'Phase':key[1],'Score before play':state,'Passing attempts':0,'Sacks':0,'Rushing plays':0})
        row['Passing attempts']+=int(attempt);row['Sacks']+=int(sack);row['Rushing plays']+=int(run)
    totals=[]
    for block in data.get('boxscore',{}).get('players',[]):
        team=block.get('team',{}).get('displayName');official=[]
        for group in block.get('statistics',[]):
            if group.get('name')!='passing':continue
            for a in group.get('athletes',[]):
                raw=dict(zip(group.get('labels',[]),a.get('stats',[]))).get('C/ATT')
                try:official.append(int(str(raw).split('/')[-1]))
                except ValueError:pass
        reg=sum(r['Passing attempts'] for r in buckets.values() if r['Team']==team and r['Phase']=='Regulation')
        ot=sum(r['Passing attempts'] for r in buckets.values() if r['Team']==team and r['Phase']=='Overtime')
        reconciled=bool(official) and reg+ot==sum(official)
        totals.append({'Team':team,'Regulation attempts':reg if reconciled else None,'Overtime attempts':ot if reconciled else None,'Official total attempts':sum(official) if official else None,'Coverage':'Reconciled with box score' if reconciled else 'Incomplete/unreconciled play feed; split withheld'})
    return {'attempt_totals':totals,'score_states':list(buckets.values())}
