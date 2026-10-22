"""Reproducible free-data historical tests; never calls a sportsbook or an LLM."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PATH='prediction_research_validation.json'


def clean_reports(reports):
    return [{'category':key[0],'season_stage':key[1],**{k:v for k,v in report.items()if k!='residuals'}}
            for key,report in sorted(reports.items())]


def run(path=PATH):
    from background_research import cached,get
    from game_day_diagnostics import fingerprint
    now=datetime.now(timezone.utc);cutoff=now.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
    source=fingerprint();target=Path(path)
    prior={}
    try:
        prior=json.loads(target.read_text())
        if prior.get('source_hash')==source and prior.get('pacific_date')==cutoff:return prior
    except (OSError,ValueError):pass
    report={'schema':1,'generated_utc':now.isoformat(),'pacific_date':cutoff,'source_hash':source,
            'status':'Historical development checks; no sportsbook historical prices, profit test or accuracy guarantee',
            'NBA':{},'NFL':{}}
    try:
        from nba_prop_model import current_roster_nba,reference_players,research
        from nba_season_prior import fetch_espn_logs
        from nba_game_context import schedule_rows,completed_game
        from matchup_homework import validate_nba_context
        team_ids=(2,6,9,13,14,24,1,4,7,11,19,23)
        rosters={str(t):cached('validation_roster_'+str(t),86400,lambda t=t:current_roster_nba(t))for t in team_ids}
        refs=reference_players(rosters,48);year=now.year+int(now.month>=7);logs=[];issues=[]
        # Completed historical seasons do not change within a rerun. Retain
        # explicit failed-source labels until the next daily attempt rather
        # than repeatedly request a rookie's nonexistent older game logs.
        unavailable={(r.get('player'),r.get('season'))for r in prior.get('NBA',{}).get('missing_sources',[])if r.get('player')and r.get('season')}if prior.get('pacific_date')==cutoff else set()
        issues.extend(r for r in prior.get('NBA',{}).get('missing_sources',[])if (r.get('player'),r.get('season'))in unavailable)
        with ThreadPoolExecutor(max_workers=6)as pool:
            jobs={(y,pid,name):pool.submit(cached,'validation_logs_'+str(y)+'_'+pid,86400,lambda y=y,pid=pid,name=name:fetch_espn_logs(y,pid,name))for y in range(year-3,year)for pid,name in refs if (name,y)not in unavailable}
            for (y,pid,name),task in jobs.items():
                try:logs.extend(task.result())
                except Exception:issues.append({'player':name,'season':y,'status':'Historical source unavailable'})
        model=research(logs,cutoff)
        pools={}
        for y in (year-2,year-1):
            for tid in team_ids:
                try:
                    url=f'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{tid}/schedule?season={y}&seasontype=2'
                    payload=cached('validation_schedule_'+str(y)+'_'+str(tid),86400,lambda url=url:get(url))
                    rows=[r for r in schedule_rows(payload,tid,y)if r['completed']and r['date'][:10]<cutoff]
                    # Distributed predetermined sample, never selected by outcome.
                    pools[y,tid]=list({r['id']:r for r in rows[:12]+rows[30:36]+rows[-6:]}.values())
                except Exception:issues.append({'team':tid,'season':y,'status':'Schedule unavailable'})
        eids=[];seen=set()
        for depth in range(24):
            for key,rows in sorted(pools.items()):
                if depth<len(rows)and rows[depth]['id']not in seen:
                    seen.add(rows[depth]['id']);eids.append(rows[depth]['id'])
        summaries=[]
        with ThreadPoolExecutor(max_workers=6)as pool:
            jobs={eid:pool.submit(cached,'validation_summary_'+eid,86400,lambda eid=eid:get('https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event='+eid))for eid in eids}
            for eid,task in jobs.items():
                try:
                    data=task.result()
                    if str(data.get('header',{}).get('id'))!=eid or not completed_game(data,cutoff+'T00:00:00+00:00'):raise ValueError('Unverified final')
                    summaries.append(data)
                except Exception:issues.append({'event':eid,'status':'Final summary unavailable'})
        context_reports=validate_nba_context(logs,summaries,cutoff,model['opportunity_reports'])
        report['NBA']={'history_rows':len(logs),'reference_players':[name for pid,name in refs],
            'verified_context_games':len(summaries),'opportunity_reports':clean_reports(model['opportunity_reports']),
            'matchup_reports':clean_reports(context_reports),'missing_sources':issues,
            'scope':'Expanded current-roster-selected 48-player development cohort across twelve fixed teams; limited and subject to survivorship/selection bias. Previously reviewed seasons remain development evidence. Context samples include opening, middle and late-season games. Production reviews test their own loaded history; later frozen picks provide independent comparison. Not whole-league or sportsbook validation.'}
    except Exception as exc:report['NBA']={'status':'Historical validation incomplete; no pass invented','error_type':type(exc).__name__}
    try:
        from nfl_prop_model import load_season_stats
        from nfl_opportunity import validate
        players=[];teams=[]
        for y in (2023,2024,2025):
            for kind,rows in (('player',players),('team',teams)):
                rows.extend(cached('validation_nfl_'+kind+'_'+str(y),86400,lambda kind=kind,y=y:load_season_stats(kind,y)))
        report['NFL']={'player_rows':len(players),'team_rows':len(teams),'opportunity_reports':clean_reports(validate(players,teams)),
                       'scope':'nflverse regular-season weekly statistics; 2024 residual/temperature windows, 2025 later-game validation; no historical sportsbook prices'}
    except Exception as exc:report['NFL']={'status':'Historical validation incomplete; no pass invented','error_type':type(exc).__name__}
    temp=target.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2)+'\n');temp.replace(target)
    return report


def render(sport):
    import streamlit as st
    with st.expander('Prediction research — opportunity and matchup benchmarks'):
        try:report=json.loads(Path(PATH).read_text())
        except (OSError,ValueError):st.info('Free-source historical comparisons are prepared by the background research job.');return
        data=report.get(sport,{})
        st.caption(report.get('status',''))
        st.caption('Historical report updated UTC: '+report.get('generated_utc','Unknown'))
        from game_day_diagnostics import fingerprint
        if report.get('source_hash')!=fingerprint():st.caption('This report predates the current code; a fresh comparison is pending.')
        st.write(data.get('scope',data.get('status','No completed comparison')))
        for key in ('opportunity_reports','matchup_reports'):
            if data.get(key):st.dataframe(data[key],hide_index=True,use_container_width=True)
        if data.get('missing_sources'):st.caption(str(len(data['missing_sources']))+' source requests were incomplete. Missing evidence is not a pass.')


if __name__=='__main__':
    result=run()
    print(json.dumps({sport:{k:v for k,v in result[sport].items()if k not in ('opportunity_reports','matchup_reports','reference_players','missing_sources')}for sport in ('NBA','NFL')}))
