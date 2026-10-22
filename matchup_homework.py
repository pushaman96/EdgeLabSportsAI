"""Pregame facts and bounded matchup candidates from complete, earlier ESPN boxes."""
import math
import json
import statistics
from collections import defaultdict
from nba_game_context import athlete_rows, completed_game, opponent_context, team_possessions, utc

VERSION='verified-matchup-homework-v1'


def mean(values):return statistics.mean(values)if values else None
def num(value):
    try:
        n=float(value)
        return n if math.isfinite(n)and n>=0 else None
    except (TypeError,ValueError):return None


def profiles(summaries, cutoff, field=None):
    teams=defaultdict(list);seen=set()
    for summary in summaries:
        if not completed_game(summary,cutoff):continue
        eid=str(summary['header']['id'])
        if eid in seen:continue
        seen.add(eid)
        c=summary['header']['competitions'][0]
        boxes=summary.get('boxscore',{}).get('teams',[])
        periods=c.get('status',{}).get('period')
        lengths=[len(t.get('linescores',[]))for t in c.get('competitors',[])]
        if not isinstance(periods,int)and len(lengths)==2 and lengths[0]==lengths[1]:periods=lengths[0]
        if not isinstance(periods,int)or periods<4 or len(boxes)!=2:continue
        duration=48+5*(periods-4);poss=[team_possessions(t)for t in boxes]
        athletes=athlete_rows(summary)
        entries=[]
        for box in boxes:
            tid=str(box.get('team',{}).get('id'))
            rows=[r for (team,_),r in athletes.items()if team==tid]
            active=[r for r in rows if r.get('didNotPlay')is False]
            if not active or any(r.get('didNotPlay')is None for r in rows):continue
            if any(r.get('minutes')is None for r in active)or abs(sum(r['minutes']for r in active)-5*duration)>5:continue
            def total(field):
                values=[r.get(field)for r in active]
                return sum(values)if all(num(v)is not None for v in values)else None
            fga,threes,fta=total('FGA'),total('FG3A'),total('FTA')
            starters=[r['minutes']for r in active if r.get('starter')is True]
            stat=total(field)if field else None
            entry={'game':eid,'date':c.get('date'),'pace':mean(poss)*48/duration if all(v is not None for v in poss)else None,
                'three_attempt_share':threes/fga if fga and threes is not None else None,
                'free_throw_rate':fta/fga if fga and fta is not None else None,
                'rotation_players':sum(r['minutes']>=10 for r in active),
                'starter_minutes':mean(starters)if len(starters)==5 else None,
                'stat_per48':stat*48/duration if stat is not None else None}
            entries.append((tid,entry))
        for tid,entry in entries:
            other=next((v for t,v in entries if t!=tid),{})
            entry['allowed_per48']=other.get('stat_per48')if entry['pace']is not None else None
            teams[tid].append(entry)
    return teams


def nba_facts(summaries,cutoff,team,opponent,field,prepared=None):
    # Field-specific opponent totals come only from complete played rows.
    own=profiles(summaries,cutoff,field)if prepared is None else prepared
    def profile(tid):
        rows=sorted(own.get(str(tid),[]),key=lambda r:(str(r['date']),r['game']))[-12:]
        result={'verified_games':len(rows)}
        for key in ('pace','three_attempt_share','free_throw_rate','rotation_players','starter_minutes','allowed_per48'):
            values=[r[key]for r in rows if r[key]is not None]
            result[key]=mean(values)if len(values)>=3 else None
            result[key+'_games']=len(values)
        result['Three-point attempt share %']=round(100*result['three_attempt_share'],1)if result['three_attempt_share']is not None else None
        result['Free throws per 100 field-goal attempts']=round(100*result['free_throw_rate'],1)if result['free_throw_rate']is not None else None
        return result
    league=[]
    for tid in own:
        if tid==str(opponent):continue
        allowed=profile(tid)['allowed_per48']
        if allowed is not None:league.append(allowed)
    own_profile,opp_profile=profile(team),profile(opponent)
    own_pace,opp_pace=own_profile['pace'],opp_profile['pace']
    pace_ratio=(own_pace+opp_pace)/(2*own_pace)if own_pace and opp_pace else None
    reference=mean(league)if len(league)>=3 else None
    allowed=opp_profile['allowed_per48']
    defense_ratio=allowed/reference if allowed is not None and reference else None
    available=pace_ratio is not None and defense_ratio is not None
    factor=max(.85,min(1.15,1+.25*(pace_ratio-1)+.2*(defense_ratio-1)))if available else 1.
    return {'version':VERSION,'cutoff':str(cutoff),'team':str(team),'opponent':str(opponent),
            'own_tendencies':own_profile,'opponent_tendencies':opp_profile,
            'opponent_stat_allowed_per48':allowed,'reference_teams':len(league),'reference_allowed_per48':reference,
            'pace_ratio':pace_ratio,'defense_ratio':defense_ratio,'candidate_factor':factor,'complete_matchup':available,
            'interpretation':'Observed pace, shot mix and rotation tendencies are measurable behavior, not proof of a coaching scheme. Reference teams are limited to verified loaded boxes, not a league-wide rank. Injury redistribution and historical unconfirmed starting roles are not numerically inferred.'}


def dossier(row,sport):
    """Explain exactly which measured inputs affect this forecast versus context only."""
    if row.get('Category')=='Moneyline':
        return {'version':VERSION,'sport':sport,'factors':[
            {'Factor':'Team win model','Evidence':str(row.get('History source','Historical regular-season team results')),'Effect':'Historical Elo ratings and chronological probability shrinkage applied'},
            {'Factor':'Quoted moneyline price','Evidence':str(row.get('Odds')),'Effect':'Compared with estimated win probability; sportsbook break-even probability is not a model forecast'},
            {'Factor':'Availability','Evidence':str(row.get('Injury verification reason','Current availability must be reviewed')),'Effect':'Warning evidence; no invented numerical injury adjustment'}],
            'probability_meaning':'Chance of the selected team winning the game; distinct from player-prop probability and price break-even rate',
            'limitation':'Current injury replacements and coaching changes are not fully numerically modeled. No historical sportsbook-return proof.'}
    if sport=='NBA':
        candidate=row.get('Opportunity candidate')or {}
        matchup=row.get('Matchup homework')or {}
        applied=row.get('Opportunity model applied')is True
        facts=[{'Factor':'Player minutes and usage','Evidence':row.get('Minutes forecast',row.get('Expected opportunities')),'Effect':'Applied in the selected model'},
               {'Factor':'Shot volume and conversion','Evidence':candidate.get('shots'),'Effect':'Applied after historical checks'if applied else'Candidate benchmarked; incumbent retained'},
               {'Factor':'Opponent and team tendencies','Evidence':matchup,'Effect':'Applied in validated matchup candidate'if row.get('Matchup model applied')else'Researched; candidate has not passed all checks'},
               {'Factor':'Availability and restrictions','Evidence':{'availability':row.get('Availability checked UTC'),'restriction':row.get('Minutes restriction check'),'lineup':row.get('Starting lineup check')},'Effect':'Eligibility checked; numerical redistribution not assumed'},
               {'Factor':'Absent teammates','Evidence':row.get('Teammate absence usage'),'Effect':'Matched historical association; no causal redistribution assumed'}]
    else:
        facts=[{'Factor':'Player workload and efficiency','Evidence':{'method':row.get('Workload method'),'expected':row.get('Expected opportunities'),'conversion':row.get('Conversion rate %')},'Effect':'Applied by selected forecast model'},
               {'Factor':'Team and opponent behavior','Evidence':{'observed':row.get('NFL opponent workload context'),'candidate':row.get('Matchup homework')},'Effect':'Team-share and opponent workload candidate applied after chronological checks'if row.get('Matchup model applied')else'Existing model opponent feature where available; no duplicate multiplier'},
               {'Factor':'Depth, injuries and snap trends','Evidence':{'depth':row.get('NFL depth check'),'snaps':row.get('NFL snap trend'),'restrictions':row.get('NFL restriction check')},'Effect':'Eligibility and research; numerical effects only where selected model validates them'},
               {'Factor':'Game situation','Evidence':row.get('NFL workload sensitivity',row.get('Game-script risk')),'Effect':'Scenario and risk evidence; future score state is unknown'}]
    for fact in facts:
        fact['Evidence']=json.dumps(fact['Evidence'],ensure_ascii=False,default=str)if fact['Evidence']is not None else 'Unavailable in the checked sources'
    return {'version':VERSION,'sport':sport,'factors':facts,'probability_meaning':'Estimated chance of the quoted selection winning, not player shooting percentage or verified hit rate',
            'limitation':'No program watches the future or establishes why a single outcome occurred. New numerical context effects require earlier-fit/later-test comparisons.'}


def validate_nba_context(logs,summaries,cutoff,opportunity_reports=None):
    from nba_prop_model import normalized,MARKETS
    from nba_season_prior import season_projection,season_year
    from nba_opportunity import estimate,VARIANTS
    from forecast_benchmark import validate
    histories=defaultdict(list);names=defaultdict(set)
    for r in logs:
        if r['date']<str(cutoff):
            histories[r['player']].append(r);names[normalized(r['name'])].add(r['player'])
    samples=defaultdict(list);seen=set();facts_cache={};profile_cache={}
    for data in summaries:
        if not completed_game(data,str(cutoff)+'T00:00:00+00:00'):continue
        c=data['header']['competitions'][0];eid=str(data['header']['id'])
        if eid in seen:continue
        seen.add(eid)
        start=c.get('date');date=str(start)[:10]
        teams=[str(t.get('team',{}).get('id'))for t in c.get('competitors',[])]
        if len(teams)!=2:continue
        for (team,_),actual in athlete_rows(data).items():
            if actual.get('didNotPlay')is not False or not actual.get('minutes'):continue
            ids=names.get(normalized(actual['name']),set())
            if len(ids)!=1:continue
            history=histories[next(iter(ids))]
            earlier=[r for r in history if r['date']<date]
            if not earlier:continue
            # Resolve ESPN/NBA.com namespaces by a uniquely matched prior log
            # for this very event. No team-code guess can cross namespaces.
            target=[r for r in history if str(r['game']).lstrip('0')==eid.lstrip('0')]
            if len(target)!=1:continue
            log=target[0];year=season_year(log);opponent=next(t for t in teams if t!=team)
            variants={variant:estimate(earlier,year,log['team'],date,variant)for variant in VARIANTS}
            for _,field in MARKETS.values():
                base=season_projection(earlier,field,year,log['team'],date)
                if not base or base['role_uncertain']or actual.get(field)is None:continue
                variant=(opportunity_reports or {}).get((field,base['cohort']),{}).get('selected_variant','median-minutes')
                candidate=variants[variant]
                key=(eid,team,field)
                if key not in facts_cache:
                    if (start,field)not in profile_cache:profile_cache[start,field]=profiles(summaries,start,field)
                    facts_cache[key]=nba_facts(summaries,start,team,opponent,field,profile_cache[start,field])
                facts=facts_cache[key]
                if not facts['complete_matchup']:continue
                projected=candidate['values'].get(field)if candidate else None
                minutes=candidate['minutes']if projected is not None else base['minutes']
                projected=projected if projected is not None else base['projected']
                samples[field,base['cohort']].append({'date':date,'season':year,'game':eid,
                    'candidate':projected*facts['candidate_factor'],'base':base['projected'],'base_uncertainty':base['uncertainty'],
                    'baseline':base['baseline'],'actual':actual[field],
                    'workload':minutes,'base_workload':base['minutes'],'actual_workload':actual['minutes']})
    return {key:validate(rows,allow_date_split=True)for key,rows in samples.items()}
