"""Pregame season priors and strict ESPN regular-season game-log normalization."""
import math
import statistics
from datetime import datetime


def season_year(row):
    if row.get('season') is not None:return int(row['season'])
    d=datetime.fromisoformat(row['date']);return d.year+int(d.month>=7)


def season_projection(history,field,target_year,team,cutoff):
    before=[r for r in history if r['date']<str(cutoff)]
    prior=[r for r in before if season_year(r)==target_year-1]
    current=[r for r in before if season_year(r)==target_year and r['team']==team]
    prior.sort(key=lambda r:(r['date'],r['game']));current.sort(key=lambda r:(r['date'],r['game']))
    if len(prior)<8:return None
    # Season-long efficiency is less sensitive to a short hot/cold stretch.
    prior_minutes=statistics.mean(r['minutes'] for r in prior)
    prior_rate=sum(r[field] for r in prior)/sum(r['minutes'] for r in prior)
    weight=len(current)/(len(current)+8.)
    recent=current[-12:]
    current_minutes=statistics.mean(r['minutes'] for r in recent) if recent else prior_minutes
    current_rate=sum(r[field] for r in recent)/sum(r['minutes'] for r in recent) if recent else prior_rate
    minutes=max(1.,min(40.,(1-weight)*prior_minutes+weight*current_minutes))
    rate=(1-weight)*prior_rate+weight*current_rate
    changed=prior[-1]['team']!=team
    baseline=statistics.mean(r[field] for r in prior) if len(current)<8 else statistics.mean(r[field] for r in current[-8:])
    return dict(projected=minutes*rate,minutes=minutes,baseline=baseline,prior_games=len(prior),current_games=len(current),current_weight=weight,role_uncertain=changed and len(current)<3,team_changed=changed,uncertainty=math.sqrt(1+.5*(1-weight)+(.5 if changed and len(current)<3 else 0)),history_through=max(r['date'] for r in prior+current),cohort='Early season (0–7 appearances)' if len(current)<8 else 'Established season')


def normalize_espn_logs(data,year,athlete_id,player_name):
    """Require matching season label and explicit regular-season event rows."""
    season=str(year-1)+'-'+str(year)[-2:]
    selected=[f for f in data.get('filters',[]) if f.get('name')=='season']
    if len(selected)!=1 or str(selected[0].get('value'))!=str(year):raise ValueError('ESPN player-log season mismatch')
    groups=[s for s in data.get('seasonTypes',[]) if s.get('displayName')==season+' Regular Season']
    if not groups:return []
    labels=data.get('labels',[]);events=data.get('events',{});rows=[];seen=set()
    for group in groups:
        for category in group.get('categories',[]):
            if category.get('type')!='event':continue
            for item in category.get('events',[]):
                eid=str(item.get('eventId'));event=events.get(eid)
                if not event or event.get('gameResult') not in ('W','L'):continue
                if eid in seen:raise ValueError('Duplicate ESPN player game')
                seen.add(eid)
                stats=dict(zip(labels,item.get('stats',[])))
                try:
                    minute=str(stats['MIN']);minutes=float(minute.split(':')[0])+float(minute.split(':')[1])/60 if ':' in minute else float(minute)
                    values={k:float(stats[k]) for k in ('PTS','REB','AST')};values['FG3M']=float(str(stats['3PT']).replace('/','-').split('-')[0])
                    when=datetime.fromisoformat(event['gameDate'].replace('Z','+00:00')).date().isoformat()
                    team=str(event['team']['id'])
                except (KeyError,ValueError,TypeError,IndexError):continue
                if not all(math.isfinite(v) and v>=0 for v in [minutes,*values.values()]) or minutes<=0:continue
                rows.append(dict(player='espn:'+str(athlete_id),name=player_name,team=team,date=when,game=eid,minutes=minutes,season=year,source='ESPN regular-season game logs',**values))
    return sorted(rows,key=lambda r:(r['date'],r['game']))


def fetch_espn_logs(year,athlete_id,player_name):
    import json
    from urllib.request import urlopen
    url=f'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{athlete_id}/gamelog?season={year}&seasontype=2'
    with urlopen(url,timeout=15) as response:data=json.load(response)
    return normalize_espn_logs(data,year,athlete_id,player_name)
