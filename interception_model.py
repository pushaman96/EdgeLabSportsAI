"""Pregame 0.5 interception research. No current-game outcomes or odds in fitting."""
import math

def estimate(player, season, week, team, opponent, idx):
    pi, ti, defense = idx
    history = sorted([r for (year,pid),rows in pi.items() if pid==player and season-1<=year<=season for r in rows if (r['season'],r['week'])<(season,week) and r.get('attempts') is not None and r['attempts']>=15 and r.get('passing_interceptions') is not None],key=lambda r:(r['season'],r['week']))[-12:]
    recent=[r for r in history if r['season']==season and r['team']==team]
    if len(history)<8 or len(recent)<3:return None,'Interception model needs eight starter games and three current-team games.'
    league=[r for rows in ti.values() for r in rows if r['season']==season and r['week']<week and r.get('attempts') is not None and r['attempts']>0 and r.get('passing_interceptions') is not None]
    allowed=[r for r in defense.get((season,opponent),[]) if r['week']<week and r.get('attempts') is not None and r['attempts']>0 and r.get('passing_interceptions') is not None][-8:]
    if len(league)<40 or len(allowed)<4:return None,'Interception/opponent coverage insufficient; missing values are not zero.'
    rate=sum(r['passing_interceptions'] for r in league)/sum(r['attempts'] for r in league)
    attempts=.6*sum(r['attempts'] for r in recent[-2:])/2+.4*sum(r['attempts'] for r in recent[-4:])/len(recent[-4:])
    qb_rate=(sum(r['passing_interceptions'] for r in history)+100*rate)/(sum(r['attempts'] for r in history)+100)
    opp_rate=(sum(r['passing_interceptions'] for r in allowed)+100*rate)/(sum(r['attempts'] for r in allowed)+100)
    expected=attempts*qb_rate*max(.75,min(1.25,opp_rate/rate)) if rate else 0
    baseline=sum(r['passing_interceptions']>0 for r in history)/len(history)
    frequency=(sum(r['passing_interceptions']>0 for r in history)+4*(1-math.exp(-attempts*rate)))/(len(history)+4)
    p=.5*frequency+.5*(1-math.exp(-expected))
    return {'probability':max(.05,min(.95,p)),'expected':expected,'attempts':attempts,'frequency':baseline,'games':len(history)},''

def validation(players,teams):
    from nfl_prop_model import indexes
    idx=indexes(players,teams); losses=[]; baseline=[]
    for r in players:
        if r['season']!=2025 or r.get('position')!='QB' or (r.get('attempts') or 0)<15 or r.get('passing_interceptions') is None:continue
        f,_=estimate(r['player_id'],r['season'],r['week'],r['team'],r['opponent_team'],idx)
        if f:
            actual=float(r['passing_interceptions']>0)
            losses.append((f['probability']-actual)**2);baseline.append((f['frequency']-actual)**2)
    n=len(losses)
    return {'games':n,'brier':sum(losses)/n if n else None,'baseline_brier':sum(baseline)/n if n else None,'constant_50_brier':.25,'passed':n>=100 and sum(losses)<min(sum(baseline),.25*n)}
