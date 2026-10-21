"""Chronological NFL totals and offensive anytime-TD opportunity candidates.

2024 calibrates distributions; 2025 is a development holdout, not a record of
historical sportsbook returns. Current season outcomes never fit those gates.
"""
import math
import statistics
from collections import defaultdict
from datetime import datetime,timezone

TD_VERSION='NFL offensive anytime TD opportunities v1 / 2024 calibration / 2025 development'
TOTAL_VERSION='NFL scoring total v1 / 2024 calibration / 2025 development'
def num(v):
    try:
        v=float(v);return v if math.isfinite(v)else None
    except (TypeError,ValueError):return None
def mean(v):return statistics.mean(v)if v else None
def complete_td(r):
    values=[num(r.get(k))for k in ('carries','targets','rushing_tds','receiving_tds')]
    return all(v is not None and v>=0 for v in values)
def td_index(players):
    groups=defaultdict(list);league=defaultdict(lambda:[0.,0.])
    for r in players:
        groups[r['season'],r['player_id']].append(r)
        if complete_td(r):
            key=(r['season'],r.get('position'));league[key][0]+=r['rushing_tds']+r['receiving_tds'];league[key][1]+=r['carries']+r['targets']
    for values in groups.values():values.sort(key=lambda r:(r['week'],r['game_id']))
    return groups,dict(league)
def td_estimate(pid,season,week,team,idx):
    groups,league=idx
    prior=groups.get((season-1,pid),[])
    observed=[r for r in groups.get((season,pid),[])if r['week']<week]
    last_other=max((r['week']for r in observed if r['team']!=team),default=0)
    current=[r for r in observed if r['team']==team and r['week']>last_other]
    if len(prior)<4 or not all(complete_td(r)for r in prior+current):return None
    def opp(r):return r['carries']+r['targets']
    def td(r):return r['rushing_tds']+r['receiving_tds']
    volume=mean([opp(r)for r in prior]);recent=current[-4:]
    if volume<2:return None
    league_tds,league_opp=league.get((season-1,prior[-1].get('position')),(0,0))
    if league_opp<=0:return None
    rate=(sum(td(r)for r in prior)+20*league_tds/league_opp)/(sum(opp(r)for r in prior)+20)
    weight=len(current)/(len(current)+4.)
    now_volume=mean([opp(r)for r in recent])if recent else volume
    now_rate=(sum(td(r)for r in recent)+20*rate)/(sum(opp(r)for r in recent)+20)
    expected=(1-weight)*volume+weight*now_volume
    lam=expected*((1-weight)*rate+weight*now_rate)
    baseline=(sum(td(r)>0 for r in prior)+1)/(len(prior)+2)
    return {'projected':lam,'baseline':mean([td(r)for r in prior]),'opportunities':expected,'probability':max(.01,min(.95,1-math.exp(-lam))),'baseline_probability':baseline,'role_uncertain':(prior[-1]['team']!=team or bool(last_other))and len(current)<4,'current_games':len(current),'prior_games':len(prior),'latest_week':current[-1]['week']if current else None,'method':'Carries + targets × smoothed offensive TDs/opportunity; passing TDs are not scored TDs; return TDs, red-zone roles and lineup redistribution are not modeled'}
def temperature(p,t):return 1/(1+math.exp(-t*math.log(p/(1-p))))
def td_validate(players):
    idx=td_index(players);cal=[];later=defaultdict(list)
    for r in players:
        if r['season']not in (2024,2025)or not complete_td(r):continue
        f=td_estimate(r['player_id'],r['season'],r['week'],r['team'],idx)
        if not f or f['role_uncertain']:continue
        value=(f['probability'],int(r['rushing_tds']+r['receiving_tds']>0),f['baseline_probability'])
        if r['season']==2024:cal.append(value)
        else:later[r['game_id']].append(value)
    t=min((1.,.75,.5,1.25),key=lambda t:mean([(temperature(p,t)-y)**2 for p,y,b in cal]))if cal else 1.
    score=mean([mean([(temperature(p,t)-y)**2 for p,y,b in v])for v in later.values()])
    baseline=mean([mean([(b-y)**2 for p,y,b in v])for v in later.values()])
    return {'calibration_examples':len(cal),'validation_games':len(later),'validation_examples':sum(map(len,later.values())),'temperature':t,'brier':score,'baseline_brier':baseline,'passed':bool(len(cal)>=100 and len(later)>=20 and score<baseline),'scope':'Offensive scoring occurrence only; returns not modeled. 2025 development holdout, not historical odds profitability.'}
def score_games(schedule):
    games=[];seen=set()
    for r in schedule:
        hs,aws=num(r.get('home_score')),num(r.get('away_score'))
        if r.get('game_type')!='REG'or hs is None or aws is None or min(hs,aws)<0:continue
        if r['game_id']in seen:continue
        seen.add(r['game_id']);games.append(dict(r,season=int(r['season']),week=int(r['week']),home_score=hs,away_score=aws))
    return sorted(games,key=lambda r:(r['gameday'],r['game_id']))
def total_estimate(game,games):
    year=int(game['season']);cutoff=game['gameday']
    earlier=[g for g in games if g['gameday']<cutoff and g['season']in (year-1,year)]
    prior=[g for g in earlier if g['season']==year-1]
    if len(prior)<100:return None
    league=mean([g['home_score']+g['away_score']for g in prior])
    def rates(team):
        own=[g for g in earlier if team in (g['home_team'],g['away_team'])]
        p=[g for g in own if g['season']==year-1];c=[g for g in own if g['season']==year][-6:]
        if len(p)<8:return None
        def score(g):return (g['home_score'],g['away_score'])if g['home_team']==team else (g['away_score'],g['home_score'])
        weight=len(c)/(len(c)+6.)
        return tuple((1-weight)*mean([score(g)[i]for g in p])+weight*mean([score(g)[i]for g in c]or[mean([score(g)[i]for g in p])])for i in (0,1))
    h,a=rates(game['home_team']),rates(game['away_team'])
    if not h or not a:return None
    home=(h[0]+a[1])/2;away=(a[0]+h[1])/2
    return {'projected':home+away,'home_points':home,'away_points':away,'baseline':league,'method':'Last-season offense and opponent points allowed blended with strictly earlier current-season games. No injury/weather multiplier; overtime stays in final scores.'}
def total_validate(schedule):
    games=score_games(schedule);cal=[];test=[]
    for g in games:
        if g['season']not in (2024,2025):continue
        f=total_estimate(g,games)
        if not f:continue
        actual=g['home_score']+g['away_score']
        if g['season']==2024:cal.append(actual-f['projected'])
        else:test.append((g,f,actual))
    mae=mean([abs(y-f['projected'])for g,f,y in test]);base=mean([abs(y-f['baseline'])for g,f,y in test])
    def over(f,line):return (1+sum(e>line-f['projected']for e in cal))/(len(cal)+2)
    brier=mean([(over(f,math.floor(f['baseline'])+.5)-int(y>math.floor(f['baseline'])+.5))**2 for g,f,y in test])if cal else None
    return {'calibration_examples':len(cal),'validation_games':len(test),'forecast_mae':mae,'baseline_mae':base,'brier':brier,'baseline_brier':.25,'passed':bool(len(cal)>=100 and len(test)>=100 and mae<base and brier<.25),'residuals':sorted(cal),'scope':'2024 residual calibration; 2025 stat and synthetic league-total threshold development test; not historical sportsbook returns'}
def reviews(event,scoreboard,research,injuries,rosters,now=None):
    from nfl_prop_model import event_context,name_key,ALIASES
    from pick_history import verified_pregame_start
    now=now or datetime.now(timezone.utc);context=event_context(event,scoreboard)
    if not context or not context['regular']:return []
    try:verified_pregame_start(context['espn_event'],event['commence_time'],now)
    except (ValueError,TypeError,KeyError):return []
    home=ALIASES.get(context['home']['abbreviation'],context['home']['abbreviation']);away=ALIASES.get(context['away']['abbreviation'],context['away']['abbreviation'])
    matched=[g for g in research['schedule']if int(g['season'])==context['season']and g.get('game_type')=='REG'and g['gameday']==str(context['date'])and g['home_team']==home and g['away_team']==away]
    if len(matched)!=1:return []
    schedule=matched[0];td_report=research.get('td_report')or td_validate(research['players']);total_report=research.get('total_report')or total_validate(research['schedule']);idx=td_index(research['players']);games=score_games(research['schedule']);out=[]
    for book in event.get('bookmakers',[]):
        for market in book.get('markets',[]):
            if market.get('key')not in ('player_anytime_td','totals'):continue
            is_td=market['key']=='player_anytime_td'
            for quote in market.get('outcomes',[]):
                player=(quote.get('description')or quote.get('name'))if is_td else event['away_team']+' at '+event['home_team']
                row={'Game':event['away_team']+' at '+event['home_team'],'Player':player,'Category':'Anytime touchdown'if is_td else'Game total points','Selection':'Over'if is_td else quote.get('name'),'Line':.5 if is_td else quote.get('point'),'Odds':quote.get('price'),'Sportsbook':book['title'],'Quote updated UTC':market.get('last_update')or book.get('last_update'),'Model':TD_VERSION if is_td else TOTAL_VERSION,'Decision':'Pass','Reason':'','Estimated win %':None,'Model edge (pp)':None}
                out.append(row)
                try:age=(now-datetime.fromisoformat(row['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()
                except (ValueError,TypeError,KeyError,AttributeError):age=99999
                odds,line=num(row['Odds']),num(row['Line'])
                if not 0<=age<=900 or odds is None or abs(odds)<100 or line is None or line<0 or row['Selection']not in ('Over','Under'):
                    row['Reason']='Fresh valid quote required';continue
                if not is_td and line%1!=.5:row['Reason']='Total model currently requires half-point lines; integer totals need push-aware pricing';continue
                if is_td and quote.get('description')and str(quote.get('name')).lower()not in ('yes','over',str(player).lower()):row['Reason']='Only affirmative anytime scorer prices supported';continue
                if is_td:
                    matches=[(side,p)for side in ('home','away')for p in rosters.get(context[side]['displayName'],[])if name_key(p['name'])==name_key(player)]
                    if len(matches)!=1:row['Reason']='Unique current roster match unavailable';continue
                    side,athlete=matches[0];team=context[side]['displayName']
                    try:
                        fresh=-600<=(now-datetime.fromisoformat(injuries['source_updated'].replace('Z','+00:00'))).total_seconds()<=21600 and 0<=(now-datetime.fromisoformat(injuries['retrieved'])).total_seconds()<=900 and injuries['season']==context['season']
                    except (KeyError,ValueError,TypeError):fresh=False
                    status=injuries.get('statuses',{}).get((team,name_key(player)),'Not listed')
                    if not fresh or team not in injuries.get('teams',set())or str(athlete.get('status')).lower()!='active'or status.lower()not in ('active','not listed'):row['Reason']='Fresh verified availability required';continue
                    ids={r['player_id']for r in research['players']if name_key(r['player_display_name'])==name_key(player)}
                    code=home if side=='home'else away
                    f=td_estimate(next(iter(ids)),context['season'],int(schedule['week']),code,idx)if len(ids)==1 else None
                    if not f:row['Reason']='Complete prior rushing/receiving TD and opportunity history unavailable';continue
                    team_games={r['game_id']for r in sorted((r for r in research['teams']if r['season']==context['season']and r['team']==code and r['week']<int(schedule['week'])),key=lambda r:r['week'])[-4:]}
                    appearances={r['game_id']for r in research['players']if r['player_id']==next(iter(ids))and r['season']==context['season']and r['team']==code and r['week']<int(schedule['week'])}
                    gap=bool(team_games-appearances)
                    report=td_report;p=temperature(f['probability'],report['temperature']);reason=f['method']
                    row['Expected opportunities']=f['opportunities'];row['Opportunity type']='Carries + targets'
                    from nfl_forecast_evidence import restriction
                    limit=restriction(injuries,team,player,now)['Review required']
                    eligible=not f['role_uncertain']and not gap and not limit
                else:
                    f=total_estimate(dict(schedule,season=context['season']),games)
                    if not f:row['Reason']='Complete prior team scoring history unavailable';continue
                    report=total_report;errors=report.get('residuals',[])
                    if len(errors)<100:row['Reason']='Insufficient earlier total residuals';continue
                    p=(1+sum(e>line-f['projected']for e in errors))/(len(errors)+2)
                    if row['Selection']=='Under':p=1-p
                    reason=f['method']
                    try:
                        eligible=injuries['season']==context['season']and -600<=(now-datetime.fromisoformat(injuries['source_updated'].replace('Z','+00:00'))).total_seconds()<=21600 and 0<=(now-datetime.fromisoformat(injuries['retrieved'])).total_seconds()<=900 and all(context[s]['displayName']in injuries['teams']for s in ('home','away'))
                    except (ValueError,TypeError,KeyError):eligible=False
                be=100/(odds+100)if odds>0 else abs(odds)/(abs(odds)+100)
                row.update({'Projection (count)':round(f['projected'],3),'Base projection':f['projected'],'Base model':row['Model'],'Base estimated win %':100*p,'Estimated win %':round(100*p,1),'Break-even %':round(100*be,1),'Model edge (pp)':round(100*(p-be),1),'Validation':{k:v for k,v in report.items()if k!='residuals'},'Validation details':{k:v for k,v in report.items()if k!='residuals'},'Statistics retrieved UTC':research.get('retrieved'),'Reason':reason})
                from online_learning import adjust_probability
                p=adjust_probability(row,p,now=now,sport='NFL')
                row['Estimated win %']=round(100*p,1);row['Model edge (pp)']=round(100*(p-be),1)
                if not eligible:row['Reason']+=' Role, workload limit or player-history coverage is unverified.'
                elif not report['passed']:row['Reason']+=' Historical development gate failed; projection only.'
                elif p-be<.05:row['Reason']+=' Estimated edge below five percentage points.'
                else:row['Decision']='Watch — experimental';row['Reason']+=(' Offensive-only probability estimate; return TDs are not modeled.'if is_td else' Availability coverage checked; injuries and weather are not numerically adjusted.')+' Not verified profitability.'
                row['Evidence explanation']=row['Reason']
    return out

def render_validation(sport):
    import json
    from pathlib import Path
    import streamlit as st
    with st.expander('New model validation — touchdowns, totals and PRA'):
        try:report=json.loads(Path('scoring_model_validation.json').read_text())
        except (OSError,ValueError):report={}
        if sport=='NFL':
            st.write('**Offensive anytime-touchdown opportunity model**');st.write(report.get('NFL_anytime_touchdown','Awaiting historical run'))
            st.write('**Game scoring total model**');st.write(report.get('NFL_game_total','Awaiting historical run'))
        else:st.write(report.get('NBA_PRA','PRA validates against earlier/later player games when its history loads.'))
        st.caption('These are historical development comparisons, not a sportsbook win rate. Touchdowns use carries and targets, excluding passing touchdowns credited to quarterbacks. Return touchdowns, red-zone roles, injury redistribution and weather are not numerical inputs. PRA uses observed same-game points + rebounds + assists and calibrates the combined residuals directly. New recommendations remain experimental and require fresh quotes, verified availability and the relevant model gate.')
