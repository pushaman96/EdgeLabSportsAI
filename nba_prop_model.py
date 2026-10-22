"""Experimental minutes x per-minute NBA props with chronological validation.
No current-season aggregates are used to predict earlier games.
"""
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MODEL = 'NBA season-prior minutes-rate v5 / verified context and calibration audit'
from nba_season_prior import season_projection, season_year, fetch_espn_logs
MARKETS = {'player_points':('Points','PTS'),'player_rebounds':('Rebounds','REB'),'player_assists':('Assists','AST'),'player_threes':('Three-pointers made','FG3M'),'player_points_rebounds_assists':('PRA','PRA')}


def number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):
        return None


def normalized(value):
    return re.sub('[^a-z0-9]','',str(value).lower())


def day(value):
    text=str(value)
    try:return datetime.fromisoformat(text.replace('Z','+00:00')).date()
    except ValueError:return datetime.strptime(text,'%b %d, %Y').date()


def normalize_logs(rows, year):
    result=[];seen=set()
    for r in rows:
        if str(r.get('SEASON_ID')) != '2'+str(year-1):
            raise ValueError('NBA player log season/type mismatch')
        if r.get('WL') not in ('W','L'):continue
        minutes=number(r.get('MIN'))
        if minutes is None or minutes<=0:continue
        fields={k:number(r.get(k)) for k in ('PTS','REB','AST','FG3M')}
        if any(v is None or v<0 for v in fields.values()):continue
        invalid_threes=False
        for made,attempted in (('FGM','FGA'),('FG3M','FG3A'),('FTM','FTA')):
            m,a=number(r.get(made)),number(r.get(attempted))
            valid=m is not None and a is not None and 0<=m<=a
            if made=='FG3M'and m is not None and a is not None and not valid:invalid_threes=True
            if made!='FG3M':fields[made]=m if valid else None
            fields[attempted]=a if valid else None
        if invalid_threes:continue
        identity=(str(r['GAME_ID']),str(r['PLAYER_ID']))
        if identity in seen:raise ValueError('Duplicate NBA player/game')
        seen.add(identity)
        result.append(dict(player=str(r['PLAYER_ID']),name=r['PLAYER_NAME'],team=str(r['TEAM_ID']),date=day(r['GAME_DATE']).isoformat(),game=str(r['GAME_ID']),minutes=minutes,season=year,source='NBA.com regular-season game logs',**fields))
    return sorted(result,key=lambda r:(r['date'],r['game'],r['player']))


def projection(history, field):
    recent=history[-12:]
    if len(recent)<8:return None
    minute_values=[r['minutes'] for r in recent]
    minutes=max(5.,min(40.,.65*statistics.mean(minute_values[-5:])+.35*statistics.mean(minute_values)))
    total_minutes=sum(minute_values)
    rate=sum(r[field] for r in recent)/total_minutes
    return minutes*rate,minutes,statistics.mean(r[field] for r in recent[-8:])


def research(logs, cutoff):
    """Earlier errors calibrate; later games validate each season-stage cohort."""
    logs=[dict(r,PRA=r['PTS']+r['REB']+r['AST']) for r in logs]
    older=[r for r in logs if r['date']<str(cutoff)]
    dates=sorted({r['date'] for r in older})
    # Hold out a complete completed season. A percentile of calendar dates can
    # land after opening week and leave early-season validation empty even
    # when several complete historical seasons were successfully loaded.
    target_year=season_year({'date':str(cutoff)})
    validation_year=max((season_year(r) for r in older if season_year(r)<target_year),default=None)
    validation_dates=[r['date'] for r in older if season_year(r)==validation_year]
    earlier=[r for r in older if validation_year is not None and season_year(r)<validation_year]
    full_season_split=bool(validation_dates and earlier)
    split=min(validation_dates) if full_season_split else dates[int(.65*len(dates))] if dates else str(cutoff)
    history=defaultdict(list);players=defaultdict(list);errors=defaultdict(list);validation=defaultdict(lambda:defaultdict(list))
    cohort_errors=defaultdict(list);cohort_validation=defaultdict(lambda:defaultdict(list));opportunity_samples=defaultdict(lambda:defaultdict(list))
    for r in sorted(older,key=lambda r:(r['date'],r['game'],r['player'])):
        h=history[r['player'],r['team']]
        before=[x for x in h if x['date']<r['date']]
        from nba_opportunity import estimate as opportunity_estimate,VARIANTS
        candidate_variants={variant:opportunity_estimate(players[r['player']],season_year(r),r['team'],r['date'],variant)for variant in VARIANTS}
        for _,field in MARKETS.values():
            detail=season_projection(players[r['player']],field,season_year(r),r['team'],r['date'])
            f=(detail['projected'],detail['minutes'],detail['baseline']) if detail else projection(before,field)
            if not f:continue
            forecast,minutes,baseline=f
            cohort=detail['cohort'] if detail else 'Established season'
            scale=detail['uncertainty'] if detail else 1.
            for variant,candidate in candidate_variants.items():
                if candidate and candidate['values'].get(field)is not None and season_year(r)<target_year and (not detail or not detail['role_uncertain']):
                    opportunity_samples[field,cohort][variant].append({'date':r['date'],'season':season_year(r),'game':r['game'],
                        'candidate':candidate['values'][field],'base':forecast,'base_uncertainty':scale,'baseline':baseline,'actual':r[field],
                        'workload':candidate['minutes'],'base_workload':minutes,'actual_workload':r['minutes']})
            error=(r[field]-forecast)/max(1.,math.sqrt(forecast))/scale
            if r['date']<split:
                errors[field].append(error);cohort_errors[field,cohort].append(error)
            elif not full_season_split or season_year(r)==validation_year:
                pair=(abs(r[field]-forecast),abs(r[field]-baseline),error,r[field]-forecast)
                validation[field][r['game']].append(pair)
                if not detail or not detail['role_uncertain']:cohort_validation[field,cohort][r['game']].append(pair)
        h.append(r);players[r['player']].append(r)
    def report(label,groups,calibration):
        from nba_forecast_quality import quantile
        fm=statistics.mean(statistics.mean(v[0] for v in values) for values in groups.values()) if groups else None
        bm=statistics.mean(statistics.mean(v[1] for v in values) for values in groups.values()) if groups else None
        low,high=(quantile(calibration,.1),quantile(calibration,.9)) if len(calibration)>=50 else (None,None)
        coverage=statistics.mean(statistics.mean(low<=v[2]<=high for v in values) for values in groups.values()) if groups and low is not None else None
        bias=statistics.mean(statistics.mean(v[3] for v in values) for values in groups.values()) if groups else None
        return dict(category=label,validation_games=len(groups),calibration_examples=len(calibration),forecast_mae=fm,baseline_mae=bm,passed=bool(len(groups)>=20 and len(calibration)>=50 and fm<bm),split_date=split,validation_season=validation_year if full_season_split else None,split_method='Complete later season' if full_season_split else 'Chronological date split; incomplete historical coverage',empirical_band_validation_coverage=coverage,mean_actual_minus_forecast=bias)
    reports={field:report(label,validation[field],errors[field]) for label,field in MARKETS.values()}
    cohort_reports={(field,cohort):report(label,cohort_validation[field,cohort],cohort_errors[field,cohort]) for label,field in MARKETS.values() for cohort in ('Early season (0–7 appearances)','Established season')}
    from workload_candidates import validate_nba
    workload_reports=validate_nba(older)
    from forecast_benchmark import validate_variants as validate_opportunity
    opportunity_reports={key:validate_opportunity(values)for key,values in opportunity_samples.items()}
    return dict(opportunity_reports=opportunity_reports,workload_reports=workload_reports,history=history,players=players,errors=errors,reports=reports,cohort_errors=cohort_errors,cohort_reports=cohort_reports)


def probability(projected, line, errors):
    if len(errors)<20:return None
    cutoff=(line-projected)/max(1.,math.sqrt(projected))
    empirical=(1+sum(error>cutoff for error in errors))/(len(errors)+2)
    return max(.05,min(.95,.5+.8*(empirical-.5)))


def readiness_summary(rows):
    """Count player/game/category groups, not duplicate books or both sides."""
    groups=defaultdict(list)
    for row in rows:groups[row['Game'],row['Player'],row['Category']].append(row)
    counts=defaultdict(int)
    for group in groups.values():
        ready=[r for r in group if r['Decision']!='Pass']
        if ready:
            reason='Conflicting qualifying directions; no pick' if len({r['Selection'] for r in ready})>1 else 'Qualified experimental pick'
        else:
            # A qualifying edge on either side is sufficient; show the most
            # promising evaluated quote, without counting both directions.
            best=max(group,key=lambda r:r.get('Estimated win %') if r.get('Estimated win %') is not None else -999)
            reason=best.get('Reason') or 'No usable forecast'
        counts[reason]+=1
    return [{'Status / reason':reason,'Unique player props':count} for reason,count in sorted(counts.items())]


def nba_availability(injuries, team, player, now):
    try:
        source=datetime.fromisoformat(injuries['source_timestamp'].replace('Z','+00:00'))
        retrieved=datetime.strptime(injuries['retrieved'],'%Y-%m-%d %H:%M UTC').replace(tzinfo=timezone.utc)
        if not -600<=(now-source).total_seconds()<=21600 or not 0<=(now-retrieved).total_seconds()<=900:return None
        if team not in injuries['teams']:return None
        matches=[r for r in injuries['rows'] if r['Team']==team and normalized(r['Player'])==normalized(player)]
        return matches[0]['Status'] if len(matches)==1 else 'Not listed' if not matches else None
    except (ValueError,KeyError,TypeError):return None


def minutes_replacement(history, roster_names, out_names, current_minutes):
    # Distribute half of absent players' observed minutes by current active
    # minute share; no arbitrary starter designation or 36-minute assumption.
    by_player=defaultdict(list)
    for row in history:
        if normalized(row['name']) in roster_names:by_player[normalized(row['name'])].append(row)
    means={name:statistics.mean(r['minutes'] for r in values[-5:]) for name,values in by_player.items() if len(values)>=3}
    absent=sum(v for name,v in means.items() if name in out_names)
    active=sum(v for name,v in means.items() if name not in out_names)
    factor=1+min(.1,.5*absent/active) if active>0 else 1.
    return min(40.,current_minutes*factor),factor


def reviews(events, scoreboard, data, injuries, rosters, now=None, context=None):
    from online_learning import adjust_forecast, adjust_probability
    now=now or datetime.now(timezone.utc)
    output=[]
    research_cache={}
    for event in events:
        start=datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))
        matches=[e for e in scoreboard.get('events',[]) if e.get('name')==event['away_team']+' at '+event['home_team'] and abs((datetime.fromisoformat(e['date'].replace('Z','+00:00'))-start).total_seconds())<3600]
        if len(matches)!=1 or start<=now:continue
        source=matches[0];season=source.get('season',scoreboard.get('season',{}))
        from pick_history import verified_pregame_start
        try:verified_pregame_start(source,event['commence_time'],now)
        except (ValueError,KeyError,TypeError):continue
        if season.get('type')!=2:continue
        # The dataset was loaded for the matching ESPN ending-year season.
        if int(season.get('year',0))!=data['season']:continue
        competitors=source.get('competitions',[{}])[0].get('competitors',[])
        teams={c['team']['displayName']:str(c['team']['id']) for c in competitors}
        game_day=start.astimezone(ZoneInfo('America/Los_Angeles')).date()
        if game_day not in research_cache:research_cache[game_day]=research(data['logs'],game_day)
        model=research_cache[game_day]
        if context is not None and 'matchup_reports'not in model:
            from matchup_homework import validate_nba_context
            model['matchup_reports']=validate_nba_context(data['logs'],context.get('history',[]),game_day,model.get('opportunity_reports',{}))
            model['matchup_facts']={}
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                if market['key'] not in MARKETS:continue
                label,field=MARKETS[market['key']]
                for quote in market.get('outcomes',[]):
                    row=dict(Game=event['away_team']+' at '+event['home_team'],Player=quote.get('description','Unknown'),Category=label,Selection=quote.get('name'),Line=quote.get('point'),Odds=quote.get('price'),Sportsbook=book['title'],Decision='Pass',Reason='',Model=MODEL,**{'Quote updated UTC':market.get('last_update') or book.get('last_update'),'Estimated win %':None})
                    output.append(row)
                    if field=='PRA':row['Model']=MODEL+' / joint PRA v1'
                    line,odds=number(row['Line']),number(row['Odds'])
                    try:age=(now-datetime.fromisoformat(row['Quote updated UTC'].replace('Z','+00:00'))).total_seconds()
                    except (ValueError,TypeError,AttributeError):age=99999
                    if not 0<=age<=900 or line is None or line<0 or line%1!=.5 or odds is None or abs(odds)<100 or row['Selection'] not in ('Over','Under'):
                        row['Reason']='Fresh valid half-unit quote required';continue
                    matched=[(team,p) for team,players in rosters.items() if team in teams for p in players if normalized(p['name'])==normalized(row['Player'])]
                    if len(matched)!=1:row['Reason']='Current game roster match unavailable or ambiguous';continue
                    team,athlete=matched[0]
                    if athlete.get('status','').lower()!='active':row['Reason']='Player roster status is not active';continue
                    status=nba_availability(injuries,team,row['Player'],now)
                    if status is None or status.lower() not in ('active','not listed'):
                        row['Reason']='Availability unverified or uncertain: '+str(status);continue
                    # NBA.com and ESPN athlete IDs differ. Match unique full name
                    # within the verified team, never join those ID namespaces.
                    # ESPN and NBA.com team/player IDs are different namespaces.
                    abbr=next((c['team']['abbreviation'] for c in competitors if c['team']['displayName']==team),None)
                    nba_abbr={'NY':'NYK','GS':'GSW','NO':'NOP','SA':'SAS','UTAH':'UTA','WSH':'WAS'}.get(abbr,abbr)
                    nba_team=teams[team] if data.get('id_namespace')=='ESPN' else data['team_ids'].get(nba_abbr)
                    if not nba_team:row['Reason']='NBA.com/ESPN team mapping unavailable';continue
                    ids={r['player'] for r in data['logs'] if normalized(r['name'])==normalized(row['Player']) and r['date']<game_day.isoformat()}
                    if len(ids)!=1:row['Reason']='Current-team player history unavailable or ambiguous';continue
                    player_history=model['players'].get(next(iter(ids)),[])
                    from nba_player_averages import attach_averages
                    attach_averages(row,player_history,field,data['season'],nba_team,game_day,current_history_verified=next(iter(ids))not in data.get('missing_current',set()))
                    history=[r for r in model['history'].get((next(iter(ids)),nba_team),[]) if (game_day-day(r['date'])).days<=240]
                    detail=season_projection(player_history,field,data['season'],nba_team,game_day)
                    forecast=(detail['projected'],detail['minutes'],detail['baseline']) if detail else projection(history,field)
                    if not forecast:row['Reason']='Need 8 verified last-season appearances or 8 recent current-team appearances; rookies require a separate model';continue
                    projected,minutes,baseline=forecast
                    roster_names={normalized(p['name']) for p in rosters[team]}
                    out_names={normalized(r['Player']) for r in injuries['rows'] if r['Team']==team and str(r['Status']).lower() in ('out','injured reserve','suspended')}
                    team_history=[r for values in model['history'].values() for r in values if r['team']==nba_team and 0<(game_day-day(r['date'])).days<=365]
                    scenario_minutes,factor=minutes_replacement(team_history,roster_names,out_names,minutes)
                    # Historical validation tests the base forecast. An absence
                    # does not prove who inherits minutes; retain redistribution
                    # as a labeled scenario until tested on historical lineups.
                    adjusted_minutes=minutes
                    row.update({'Minutes forecast':round(adjusted_minutes,2),'Injury adjustment %':0.,'Injury adjustment reason':'Fresh availability checked; automatic minutes redistribution is unvalidated and remains a separate scenario','Absence scenario minutes':round(scenario_minutes,2),'Absence scenario projection':round(projected*scenario_minutes/minutes,2),'Absence scenario status':'Research only; not applied to the pick. Quoted-player/reference history may omit teammates.','Availability checked UTC':now.isoformat(),'Injury source updated UTC':injuries.get('source_timestamp'),'Injury retrieved UTC':injuries.get('retrieved'),'Statistics retrieved UTC':data['retrieved'],'Player history through':detail['history_through'] if detail else max(r['date'] for r in history),'Base model':row['Model']})
                    cohort=detail['cohort'] if detail else 'Established season'
                    calibration=model['cohort_errors'][field,cohort] if detail else model['errors'][field]
                    uncertainty=detail['uncertainty'] if detail else 1.
                    calibration=[e*uncertainty for e in calibration]
                    incumbent_calibration=list(calibration)
                    probability_fn=probability;selected_report=None
                    from nba_opportunity import estimate as estimate_opportunity,attach as attach_opportunity,VERSION as OPPORTUNITY_VERSION
                    opportunity_report=model.get('opportunity_reports',{}).get((field,cohort),{})
                    candidate=estimate_opportunity(player_history,data['season'],nba_team,game_day,opportunity_report.get('selected_variant','median-minutes'))
                    attach_opportunity(row,candidate,field,opportunity_report)
                    if opportunity_report.get('passed')and candidate and candidate['values'].get(field)is not None:
                        projected=candidate['values'][field];minutes=adjusted_minutes=candidate['minutes']
                        calibration=opportunity_report['residuals'];selected_report=opportunity_report
                        from forecast_benchmark import probability as tested_probability
                        probability_fn=lambda value,line,errors:tested_probability(value,line,errors,selected_report['temperature'])
                        row.update({'Model':OPPORTUNITY_VERSION,'Base model':OPPORTUNITY_VERSION,'Opportunity model applied':True})
                    if context is not None:
                        from matchup_homework import nba_facts,VERSION as MATCHUP_VERSION
                        game=context.get('games',{}).get(str(source['id']),{})
                        opponent=next((tid for name,tid in game.get('teams',{}).items()if str(tid)!=str(teams[team])),None)
                        fact_key=(str(source['id']),str(teams[team]),field)
                        if fact_key not in model['matchup_facts']:
                            model['matchup_facts'][fact_key]=nba_facts(context.get('history',[]),event['commence_time'],teams[team],opponent,field)
                        facts=model['matchup_facts'][fact_key];row['Matchup homework']=facts
                        matchup_report=model.get('matchup_reports',{}).get((field,cohort),{})
                        row['Matchup benchmark']={k:v for k,v in matchup_report.items()if k!='residuals'}
                        if matchup_report.get('passed')and facts['complete_matchup']:
                            # Match the exact composite candidate used in the historical tests.
                            if candidate and candidate['values'].get(field)is not None:
                                projected=candidate['values'][field];minutes=adjusted_minutes=candidate['minutes']
                            else:projected,minutes,_=forecast;adjusted_minutes=minutes
                            projected*=facts['candidate_factor'];calibration=matchup_report['residuals'];selected_report=matchup_report
                            from forecast_benchmark import probability as tested_probability
                            probability_fn=lambda value,line,errors:tested_probability(value,line,errors,selected_report['temperature'])
                            row.update({'Model':MATCHUP_VERSION+' / '+field,'Base model':MATCHUP_VERSION+' / '+field,'Matchup model applied':True})
                            row['NBA context limitation']='The bounded pace/allowed-stat candidate passed the saved chronological development checks and is applied. Rotation descriptions, teammate absences and unconfirmed lineups are separate evidence; no additional numerical effects are inferred.'
                    if selected_report:
                        row.update({'Minutes forecast':round(minutes,2),'Uncertainty multiplier':1.,'Probability method':'Earlier residual distribution with temperature selected before later historical validation; synthetic-line development evidence only'})
                    from forecast_benchmark import probability as benchmark_probability
                    comparisons=[]
                    incumbent_p=probability(forecast[0],line,incumbent_calibration)
                    for version,cp,report in (
                        (OPPORTUNITY_VERSION,candidate['values'].get(field)if candidate else None,opportunity_report),
                        ('verified-matchup-homework-v1 / '+field,(candidate['values'].get(field)if candidate and candidate['values'].get(field)is not None else forecast[0])*row.get('Matchup homework',{}).get('candidate_factor',1),model.get('matchup_reports',{}).get((field,cohort),{})if row.get('Matchup homework',{}).get('complete_matchup')else {})):
                        if cp is None or not report.get('residuals'):continue
                        candidate_p=benchmark_probability(cp,line,report['residuals'],report.get('temperature',1))
                        if candidate_p is None or incumbent_p is None:continue
                        comparisons.append({'version':version,'incumbent_projection':forecast[0],'candidate_projection':cp,
                            'incumbent_probability':1-incumbent_p if row['Selection']=='Under'else incumbent_p,
                            'candidate_probability':1-candidate_p if row['Selection']=='Under'else candidate_p,
                            'line':line,'selection':row['Selection'],'historical_checks_passed':report.get('passed',False)})
                    row['Research model comparison']=comparisons
                    row.update({'Projection (count)':round(projected,2),'Expected opportunities':round(adjusted_minutes,2),'Opportunity type':'Minutes','History source':data.get('source','NBA.com'),'Season stage':cohort,'Last-season games':detail['prior_games'] if detail else 0,'Current-season appearances':detail['current_games'] if detail else len(history),'Current-season weight %':round(100*detail['current_weight'],1) if detail else 100.,'Role uncertainty':'New team; fewer than 3 current-team games' if detail and detail['role_uncertain'] else 'Historical minutes assumption; lineup changes may differ','Uncertainty multiplier':round(uncertainty,3)})
                    if context is not None:
                        from nba_game_context import attach_context
                        attach_context(row,context,source['id'],team,teams[team],row['Player'],event['commence_time'],field,injuries,now)
                    if detail:
                        from workload_candidates import nba_sample,attach
                        live=dict(player=next(iter(ids)),team=nba_team,date=game_day.isoformat(),season=data['season'])
                        sample=nba_sample(live,player_history,field)
                        absent=[r['Player']for r in injuries['rows']if r['Team']==team and normalized(r['Player']) in out_names]
                        attach(row,sample,model.get('workload_reports',{}).get((field,cohort)),absent)
                    p=probability_fn(projected,line,calibration)
                    if p is None:row['Reason']='Insufficient earlier calibration errors';continue
                    row['Base estimated win %']=100*(1-p if row['Selection']=='Under' else p)
                    projected,adjusted_minutes=adjust_forecast(row,projected,adjusted_minutes,now,sport='NBA')
                    p=probability_fn(projected,line,calibration)
                    if row['Selection']=='Under':p=1-p
                    if row.get('Candidate projection') is not None:
                        candidate_p=probability_fn(row['Candidate projection'],line,calibration)
                        row['Candidate input win %']=100*(1-candidate_p if row['Selection']=='Under' else candidate_p)
                    p=adjust_probability(row,p,now,sport='NBA')
                    from pick_learning import adjust_row as validated_calibration
                    p=validated_calibration(row,p,now=now,sport='NBA')
                    row['Probability calibration status']=row['Feedback status']
                    breakeven=100/(odds+100) if odds>0 else abs(odds)/(abs(odds)+100)
                    selected_validation=dict({k:v for k,v in selected_report.items()if k!='residuals'},forecast_mae=selected_report['candidate_mae'],baseline_mae=selected_report['simple_baseline_mae'])if selected_report else model['cohort_reports'][field,cohort] if detail else model['reports'][field]
                    row.update({'Projection (count)':round(projected,2),'Expected opportunities':round(adjusted_minutes,2),'Opportunity type':'Minutes','Estimated win %':round(100*p,1),'Break-even %':round(100*breakeven,1),'Model edge (pp)':round(100*(p-breakeven),1),'Feedback status':row.get('Online learning status','Collecting prospective per-game evidence')+'; '+row['Probability calibration status'],'Validation':selected_validation})
                    from nba_forecast_quality import attach_quality
                    attach_quality(row,player_history,game_day,nba_team,projected,adjusted_minutes,calibration)
                    if context is not None:
                        from nba_role_usage import attach_role_usage
                        attach_role_usage(row,context,event['commence_time'],teams[team],row['Player'],adjusted_minutes,projected,field)
                    report=row['Validation']
                    row['Validation details']={'mae':report['forecast_mae'],'baseline_mae':report['baseline_mae'],'passed':report['passed'],'validation_games':report['validation_games'],'calibration_examples':report['calibration_examples'],'scope':'NBA '+cohort+'; historical stat error, not sportsbook profitability','empirical_band_validation_coverage':report.get('empirical_band_validation_coverage'),'mean_actual_minus_forecast':report.get('mean_actual_minus_forecast')}
                    if next(iter(ids)) in data.get('missing_current',set()):row['Reason']='Last-season forecast shown; current-season history could not be verified';continue
                    if detail and detail['role_uncertain']:row['Reason']='Last-season starting estimate shown; new-team minutes role unverified until 3 current-team appearances';continue
                    if row.get('Minutes restriction check',{}).get('Review required'):row['Reason']='Current injury report mentions a minutes limit; verify the restriction before use. No numeric cap is invented.';continue
                    if row.get('NBA role review required'):row['Reason']=row['NBA role status'];continue
                    if not report['passed']:row['Reason']='Season-stage model has not beaten the prior-season/recent-average baseline on later games; forecast shown for research';continue
                    if p<=.5:row['Reason']='Selected outcome is not more likely than its alternative';continue
                    row['Decision']='Watch — experimental'
                    row['Reason']='Last-season minutes × production blended with current-season appearances; season-stage stat validation passed. Fresh availability checked; absence-related extra minutes remain a separate research scenario. '+row['Minutes risk']+'. '+row['Minutes sensitivity']+'. '+row.get('Starting lineup check',{}).get('Status','Starting lineup not checked')+'. Probability and actual-price profitability remain unverified.'
                    if selected_report:row['Reason']='Selected opportunity/matchup candidate beat the incumbent and simple baseline on later historical statistics and synthetic-line probability tests. '+row['Reason']
    return output


def reference_players(rosters, limit=12):
    """Small roster-based reference cohort; never selected by model results."""
    teams=[sorted((p for p in players if p.get('id') and p.get('name')),key=lambda p:normalized(p['name'])) for _,players in sorted(rosters.items())]
    result=[];seen=set()
    for depth in range(max((len(players) for players in teams),default=0)):
        for players in teams:
            if depth>=len(players):continue
            p=players[depth];pid=str(p['id'])
            if pid in seen:continue
            result.append((pid,p['name']));seen.add(pid)
            if len(result)>=limit:return tuple(result)
    return tuple(result)


def completed_player_logs(year,pid,name):
    """Completed history including optional paired shooting makes/attempts."""
    return fetch_espn_logs(year,pid,name)


def current_player_logs(year,pid,name):
    """Current history including optional paired shooting makes/attempts."""
    return fetch_espn_logs(year,pid,name)


def load_data(end_year, targets=(), references=()):
    import streamlit as st
    data=st.cache_data(ttl=3600)(_try_load_data)(end_year)
    if data is not None:return data
    if not targets:raise ValueError('NBA.com unavailable and no current roster athlete IDs available for ESPN fallback')
    # Each player/season is cached independently; a single failed request does
    # not discard the other players or a completed prior season.
    from concurrent.futures import ThreadPoolExecutor
    completed=st.cache_data(ttl=86400)(completed_player_logs)
    current=st.cache_data(ttl=1800)(current_player_logs)
    logs=[];issues=[];missing_current=set()
    def fetch(job):
        year,pid,name=job
        return (current if year==end_year else completed)(year,pid,name)
    # A single quoted player's opening games cannot supply 20 distinct heldout
    # games. Add a bounded, roster-selected reference cohort rather than relax
    # sample requirements or wait for this season to accumulate games.
    players={str(pid):name for pid,name in (*references,*targets)}
    jobs=[(year,pid,name) for pid,name in players.items() for year in range(end_year-3,end_year+1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks={job:pool.submit(fetch,job) for job in jobs}
        for job,task in tasks.items():
            try:logs.extend(task.result())
            except Exception:
                issues.append(f'{job[2]}: season ending {job[0]} unavailable')
                if job[0]==end_year:missing_current.add('espn:'+job[1])
    if not logs:raise ValueError('NBA.com and ESPN player game logs unavailable; saved prices are preserved')
    return dict(logs=logs,team_ids={},season=end_year,retrieved=datetime.now(timezone.utc).isoformat(),source='ESPN regular-season game logs (NBA.com unavailable)',id_namespace='ESPN',issues=issues,missing_current=missing_current)


def _try_load_data(end_year):
    # Cache failures too, so reruns do not repeat a slow blocked host request.
    try:return _load_data(end_year)
    except Exception:return None


def _load_data(end_year):
    from nba_tools import nba_request,flat_rows,season_name
    logs=[];team_ids={};issues=[]
    for year in range(end_year-3,end_year+1):
        params=dict(LeagueID='00',Season=season_name(year),SeasonType='Regular Season',PlayerOrTeam='P',Direction='ASC',Sorter='DATE',Counter=1000,DateFrom='',DateTo='')
        try:
            raw=flat_rows(nba_request('leaguegamelog',params))
            for row in raw:
                if row.get('TEAM_ABBREVIATION') and row.get('TEAM_ID'):team_ids[row['TEAM_ABBREVIATION']]=str(row['TEAM_ID'])
            logs.extend(normalize_logs(raw,year))
        except Exception:
            if year==end_year:raise
            else:raise
    if not logs:raise ValueError('No verified NBA player game logs available')
    return dict(logs=logs,team_ids=team_ids,season=end_year,retrieved=datetime.now(timezone.utc).isoformat(),source='NBA.com regular-season game logs',issues=issues)


def render(events, scoreboard, books, auto_analyze=False, key_prefix='nba_props'):
    import streamlit as st
    from nba_tools import load_nba_injuries
    from forecast_tracking import archive
    from pick_history import publish_rows
    from team_emblems import render_team_table
    st.subheader('NBA player forecasts — minutes and production')
    st.caption('Points, rebounds, assists, threes and PRA. PRA calibrates the same-game combined statistic directly. Experimental minutes × production forecasts use last-season minutes and season-long production, then blend new-season appearances with weight n/(n+8). At least 8 prior-season games or 8 recent current-team games are required. Current rosters, fresh injuries and separate early-season baseline tests remain required. New-team roles have greater uncertainty. Preseason stays on Pass. Loading statistics uses no Odds API credits.')
    if auto_analyze or st.button('Analyze saved NBA prop prices',key=key_prefix+'_analyze'):
        try:
            years={e.get('season',scoreboard.get('season',{})).get('year') for e in scoreboard.get('events',[]) if e.get('season',scoreboard.get('season',{})).get('type')==2}
            if len(years)!=1:st.info('No unique regular-season NBA slate to analyze. Preseason does not qualify.');return
            with st.spinner('Loading NBA game logs, rosters and availability…'):
                injuries=load_nba_injuries()
                teams={c['team']['displayName']:c['team']['id'] for e in scoreboard.get('events',[]) for c in e.get('competitions',[{}])[0].get('competitors',[])}
                from concurrent.futures import ThreadPoolExecutor
                roster={}
                with ThreadPoolExecutor(max_workers=6) as pool:
                    tasks={name:pool.submit(current_roster_nba,tid) for name,tid in teams.items()}
                    for name,task in tasks.items():
                        try:roster[name]=task.result()
                        except Exception:roster[name]=[]

                names={normalized(q.get('description','')) for e in events for b in e.get('bookmakers',[]) if b['title'] in books for m in b.get('markets',[]) if m.get('key') in MARKETS for q in m.get('outcomes',[])}
                targets=tuple(sorted({(p['id'],p['name']) for players in roster.values() for p in players if p.get('id') and normalized(p['name']) in names}))
                data=load_data(next(iter(years)),targets,reference_players(roster))
                st.caption('Forecast history source: '+data.get('source','NBA.com'))
                if data.get('issues'):st.info('; '.join(data['issues'][:8]))
                filtered=[dict(e,bookmakers=[b for b in e.get('bookmakers',[]) if b['title'] in books]) for e in events]
                from nba_game_context import load_context
                try:
                    context=load_context(filtered,scoreboard)
                    st.caption('Free ESPN context: '+str(context['history_loaded'])+' verified final game summaries loaded; historical fetch budget '+str(context['history_limit'])+'. Cached summaries use no Odds API credits.')
                    if context['issues']:st.info('Some game context is unavailable: '+'; '.join(context['issues'][:5]))
                except Exception:
                    context={}
                    st.info('Additional lineup, schedule and matchup sources are unavailable. These fields remain unconfirmed; no substitute values are invented.')
                rows=reviews(filtered,scoreboard,data,injuries,roster,context=context)
                from game_day_diagnostics import apply as apply_game_day_diagnostic
                rows=apply_game_day_diagnostic(rows,'NBA')
                st.session_state[key_prefix+'_results']=(rows,datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            st.warning('NBA forecast data unavailable; no substitute statistics or picks invented. '+str(exc)[:180]);return
    saved=st.session_state.get(key_prefix+'_results')
    if not saved:return
    rows,analyzed=saved
    if any(r.get('Selection policy')!='probability-first-v2' for r in rows):
        st.info('Selection rules updated. Analyze saved NBA prop prices again; no new odds request is needed.');return
    # Archive raw usable forecasts first; recommendations are consolidated below.
    archive(rows,events,scoreboard,'NBA')
    current=[];now=datetime.now(timezone.utc)
    for row in rows:
        event=next((e for e in events if e['away_team']+' at '+e['home_team']==row['Game']),None)
        if event is None:continue
        if datetime.fromisoformat(event['commence_time'].replace('Z','+00:00'))<=now or (now-datetime.fromisoformat(analyzed)).total_seconds()>900:
            row=dict(row,Decision='Pass',Reason='Analysis expired or game started; reanalyze before use')
        current.append(row)
    grouped=defaultdict(list)
    for r in current:grouped[r['Game'],r['Player'],r['Category']].append(r)
    picks=[]
    for group in grouped.values():
        qualified=[r for r in group if r['Decision']!='Pass']
        top=max((r['Estimated win %'] for r in qualified),default=-1)
        if len({r['Selection'] for r in qualified if r['Estimated win %']==top})>1:continue
        if qualified:picks.append(max(qualified,key=lambda r:r['Estimated win %']))
    st.write(f'{len(picks)} experimental NBA paper picks; all usable analyzed forecasts are tracked separately.')
    st.caption('Returning players can qualify with zero current-season appearances. There is no requirement to wait 10 games. Last-season history, verified availability, later-season validation and majority outcome probability are checked separately.')
    if current:
        with st.expander('Why NBA props qualify or pass',expanded=not bool(picks)):
            st.dataframe(readiness_summary(current),hide_index=True,use_container_width=True)
            reports={}
            for row in current:
                report=row.get('Validation')
                if report:
                    reports.setdefault((row['Category'],row.get('Season stage')),dict(Category=row['Category'],**{'Season stage':row.get('Season stage'),'Earlier calibration examples':report['calibration_examples'],'Later validation games':report['validation_games'],'Forecast average error':report['forecast_mae'],'Simple baseline average error':report['baseline_mae'],'Baseline passed':report['passed'],'Validation season ending':report.get('validation_season'),'Validation method':report.get('split_method')}))
            if reports:st.dataframe(list(reports.values()),hide_index=True,use_container_width=True)
            st.caption('Validation requires 50 earlier calibration examples and 20 later distinct games for the category and season stage, plus lower forecast error than the simple baseline. These are historical samples, not 20 new games this season. Passing the stat test does not prove profitable odds or calibrated probabilities.')
    else:
        st.info('No supported, matched, upcoming regular-season player quotes were analyzed. Check the selected date, game, sportsbook and supported categories: points, rebounds, assists and three-pointers made. Preseason and started games do not qualify.')
    from selection_policy import render_research
    render_research(current,'NBA')
    if picks:render_team_table(picks,hide_index=True,use_container_width=True,sport='NBA')
    forecasts=[r for r in current if r.get('Projection (count)') is not None]
    if forecasts:
        unique={}
        for r in forecasts:unique.setdefault((r['Game'],r['Player'],r['Category']),r)
        with st.expander('NBA homework — matchups, team tendencies and candidate tests'):
            for r in unique.values():
                st.write('**'+r['Player']+' · '+r['Category']+' · '+r['Game']+'**')
                st.write({'Opportunity model applied':r.get('Opportunity model applied',False),'Matchup model applied':r.get('Matchup model applied',False),'Shot/minutes candidate':r.get('Opportunity candidate'),'Opponent/team facts':r.get('Matchup homework'),'Matchup validation':r.get('Matchup benchmark')})
            st.caption('Existing selection cutoffs are unchanged. Team pace, shot mix and rotation patterns describe observed tendencies. Numerical matchup adjustments require later-game stat, workload and synthetic-probability benchmark passes. Unknown coaching systems or injury redistribution are not invented.')
        with st.expander('NBA projections — last-season starting point and new-season blend',expanded=not bool(picks)):
            st.caption('Stat estimates can be shown before a category qualifies for a recommendation. Role uncertainty and failed or insufficient validation remain explicit. These projections are not a promise of hitting a sportsbook line.')
            fields=('Game','Player','Category','Projection (count)','Minutes forecast','Last-season games','Current-season appearances','Current-season weight %','Role uncertainty','History source')
            render_team_table([{**{k:r.get(k) for k in fields},'Recommendation status':r['Decision'],'Reason':r['Reason']} for r in unique.values()],hide_index=True,use_container_width=True,sport='NBA')
        with st.expander('NBA forecast ranges and minutes risk'):
            st.caption('These are ranges and sensitivity examples, not additional bets. A line inside the range can still qualify; the range shows how much the outcome can vary. Historical coverage is measured on later games, not assumed to be 80%.')
            fields=('Game','Player','Category','Selection','Line','Projection (count)','Historical error range low','Historical error range high','Minutes forecast','Observed minutes low','Observed minutes high','Minutes risk','Minutes sensitivity','Minutes sample basis','Minutes sample games','Absence scenario minutes','Absence scenario projection','Absence scenario status')
            render_team_table([{k:r.get(k) for k in fields}for r in unique.values()],hide_index=True,use_container_width=True,sport='NBA')
            bands=[]
            reports_seen=set()
            for r in unique.values():
                report=r.get('Validation',{});key=(r['Category'],r.get('Season stage'))
                if key in reports_seen:continue
                reports_seen.add(key)
                coverage=report.get('empirical_band_validation_coverage')
                bands.append({'Category':key[0],'Season stage':key[1],'Later validation games':report.get('validation_games'),'Measured range coverage %':round(coverage*100,1) if coverage is not None else None,'Average actual minus forecast':report.get('mean_actual_minus_forecast')})
            st.dataframe(bands,hide_index=True,use_container_width=True)
            st.caption('Positive average actual-minus-forecast means the model underestimated the statistic in those historical games. It is a diagnostic, not an automatically applied correction. Absence-related extra minutes are shown separately and are not applied to picks.')
    average_rows={}
    for row in current:
        if row.get('Player averages'):average_rows.setdefault((row['Game'],row['Player'],row['Category']),row)
    if average_rows:
        with st.expander('NBA player averages and shooting percentages'):
            selected=st.selectbox('Inspect player averages',list(average_rows),format_func=lambda k:' · '.join(k),key=key_prefix+'_averages')
            row=average_rows[selected];profile=row['Player averages']
            st.caption(row['Player averages method'])
            st.write('**'+row['Player']+' · '+row['Category']+' · '+str(row['Selection'])+' '+str(row['Line'])+'**')
            tabs=st.tabs(['Production and minutes','Shooting percentages and attempts','Historical line comparisons'])
            with tabs[0]:
                fields=('Sample','Games','Stat sample games','Average','Median','Stat standard deviation','Minutes average','Stat per minute','Includes prior season','Includes prior team','Latest game date')
                st.dataframe([{k:r.get(k)for k in fields}for r in profile],hide_index=True,use_container_width=True)
                st.caption('The forecast already blends last-season minutes and per-minute production with this-season appearances. Recent averages are supporting evidence; a hot or cold streak does not automatically override the tested forecast.')
            with tabs[1]:
                fields=('Sample','FG %','FG makes/game','FG attempts/game','FG shooting games','3PT %','3PT makes/game','3PT attempts/game','3PT shooting games','FT %','FT makes/game','FT attempts/game','FT shooting games')
                st.dataframe([{k:round(r[k],2)if isinstance(r.get(k),float)else r.get(k)for k in fields}for r in profile],hide_index=True,use_container_width=True)
                st.caption('Percentages = total makes ÷ total attempts × 100 for games with both values available. No attempts means no percentage. Mid-range shooting needs separate verified shot-location data and is not inferred from overall field-goal percentage.')
            with tabs[2]:
                fields=('Sample','Stat sample games','Compared line','Historical overs','Historical unders','Historical pushes','Historical over % (excluding pushes)')
                st.dataframe([{k:r.get(k)for k in fields}for r in profile],hide_index=True,use_container_width=True)
                st.caption('Past results against this line are descriptive. They are not the model’s estimated win chance or proof of future profitability; the offered line and player role may have changed.')
    context_rows={}
    for row in current:
        if row.get('NBA context version'):context_rows.setdefault((row['Game'],row['Player'],row['Category']),row)
    if context_rows:
        with st.expander('NBA lineup, rest and matchup evidence'):
            st.caption('Verified team schedules, reported starting lineups, minutes-limit text flags and observed teammate usage. Statistical associations are research context; they do not automatically change a forecast.')
            selected=st.selectbox('Inspect NBA game context',list(context_rows),format_func=lambda k:' · '.join(k),key=key_prefix+'_game_context')
            row=context_rows[selected]
            for label,field in (('Reported starting lineup','Starting lineup check'),('Minutes-limit report','Minutes restriction check'),('Verified schedule and rest','Verified schedule context'),('Opponent and estimated possessions','Opponent and pace context')):
                st.write('**'+label+'**');st.write(row.get(field,{}))
            st.write('**Observed usage with and without currently unavailable teammates**')
            if row.get('Teammate absence usage'):
                for item in row['Teammate absence usage']:st.write(item)
            else:st.info('No currently unavailable teammates identified in the checked report, or no matched historical comparisons.')
            if row.get('NBA role usage'):
                st.write('**Starter/bench minutes and shot opportunities**')
                st.write(row['NBA role usage'])
                st.caption(row['NBA role status']+'. A role mismatch can require a Pass; a scenario is not automatically turned into an Over or Under pick.')
            st.caption(row.get('NBA context limitation',''))
    scenarios={}
    for row in current:
        if row.get('Workload sensitivity scenarios'):scenarios.setdefault((row['Game'],row['Player'],row['Category']),row)
    if scenarios:
        with st.expander('NBA workload and lineup scenarios — research comparisons'):
            st.caption('Minutes candidates are tested on an earlier season and checked on a later season. They are not applied to recommendations. Low/high scenarios assume unchanged production per minute and are not separate bets.')
            fields=('Game','Player','Category','Minutes forecast','Workload candidate opportunities','Workload candidate projection','Workload candidate status','Confirmed unavailable teammates','Lineup scenario limitation')
            render_team_table([{k:r.get(k) for k in fields}for r in scenarios.values()],hide_index=True,use_container_width=True,sport='NBA')
            chosen=st.selectbox('Inspect NBA minutes sensitivity',list(scenarios),format_func=lambda k:' · '.join(k),key=key_prefix+'_minutes_sensitivity')
            st.dataframe(scenarios[chosen]['Workload sensitivity scenarios'],hide_index=True,use_container_width=True)
            st.write(scenarios[chosen].get('Workload candidate benchmark',{}))
            if scenarios[chosen].get('Schedule and rest context'):st.write(scenarios[chosen]['Schedule and rest context'])
    from saved_pick_explanation import render_current_explanations
    render_current_explanations(current,key_prefix+'_nba_current')
    with st.expander('All NBA forecasts and Pass reasons'):
        if current:render_team_table(current,hide_index=True,use_container_width=True,sport='NBA')
    publish_rows(picks,events,key_prefix=key_prefix+'_publish',sport='NBA')


def current_roster_nba(team_id):
    import requests
    response=requests.get(f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster',timeout=20)
    response.raise_for_status()
    athletes=response.json().get('athletes',[])
    if not isinstance(athletes,list):raise ValueError('NBA roster unavailable')
    # NBA uses a flat athlete list; accept grouped form when explicitly present.
    flattened=[]
    for item in athletes:
        flattened.extend(item.get('items',[]) if 'items' in item else [item])
    rows=[]
    for athlete in flattened:
        status=athlete.get('status',{})
        rows.append(dict(id=str(athlete.get('id','')),name=athlete.get('displayName'),status=status.get('name') if isinstance(status,dict) else str(status)))
    if not rows:raise ValueError('NBA roster empty')
    return rows


