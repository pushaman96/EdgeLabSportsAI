"""Current roster identifies the team; completed stat rows describe prior usage.
A team mismatch indicates a roster/history transition, not a verified transaction type.
"""
import re

def key(name):return re.sub(r'[^a-z0-9]','',str(name).lower())

def player_context(name,team,season,week,players):
    history=[r for r in players if (r['season'],r['week'])<(season,week) and key(r.get('player_display_name'))==key(name)]
    ids={r['player_id'] for r in history if r.get('player_id')}
    if len(ids)!=1:return None,'Player history cannot be matched uniquely across teams.'
    pid=next(iter(ids));history=sorted([r for r in history if r['player_id']==pid],key=lambda r:(r['season'],r['week']))
    prior=history[-1]['team'];current=[r for r in history if r['season']==season and r['team']==team]
    # Do not count a previous stint with this team before a later move elsewhere.
    away=[(r['season'],r['week']) for r in history if r['team']!=team]
    last_away=max(away) if away else None
    stint=[r for r in current if last_away is None or (r['season'],r['week'])>last_away]
    transition=prior!=team or (last_away is not None and last_away[0]==season)
    return {'player_id':pid,'Current roster team':team,'Latest historical team':prior,'Current-team games':len(stint),'Roster/history status':'New-team role needs verification' if transition and len(stint)<4 else 'Team change observed in history' if transition else 'Current team matches history','Team-change flag':transition},''

def transition_reason(context):
    if context['Current-team games']>=4:return None
    if context['Team-change flag']:
        return (f"Current roster: {context['Current roster team']}; latest historical team: {context['Latest historical team']}. "
                f"New-team role has only {context['Current-team games']} completed game(s); four are required. "
                'Previous-team targets, snap share and workload are not treated as the new role. No zero-game projection is assumed.')
    return None

def new_teammates(roster_names,team,season,week,players):
    names={key(n):n for n in roster_names};arrivals=[]
    for normalized,name in names.items():
        # Only observed same-season changes are warnings; rookies are not called trades.
        rows=[r for r in players if r['season']==season and r['week']<week and key(r.get('player_display_name'))==normalized]
        if not rows or len({r['player_id'] for r in rows})!=1:continue
        if not any(r['team']!=team for r in rows):continue
        context,_=player_context(name,team,season,week,rows)
        if context and context['Team-change flag'] and context['Current-team games']<4:arrivals.append(name)
    return sorted(arrivals)
