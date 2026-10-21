"""Observed NFL averages, role/usage evidence, rest and matchup diagnostics.

No missing rows are assigned zero or a DNP. Context scenarios do not silently
alter tested forecasts. Current depth listings are not game-day starter proof.
"""
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime,timezone,date

VERSION='nfl-forecast-evidence-v1'
ALIASES={'LAR':'LA','WSH':'WAS','JAC':'JAX'}
SPECS={'Passing yards':('passing_yards','attempts'),'Passing attempts':('attempts','attempts'),'Passing completions':('completions','attempts'),'Passing touchdowns':('passing_tds','attempts'),'Passing interceptions':('passing_interceptions','attempts'),'Rushing yards':('rushing_yards','carries'),'Rushing attempts':('carries','carries'),'Receiving yards':('receiving_yards','targets'),'Receptions':('receptions','targets')}


def name(value):return re.sub('[^a-z0-9]','',str(value).lower())
def number(value):
    try:
        v=float(value);return v if math.isfinite(v)else None
    except (ValueError,TypeError):return None
def mean(values):return statistics.mean(values)if values else None
def before(r,season,week):return (int(r['season']),int(r['week']))<(season,week)
def prior_rows(rows,season,week):return sorted((r for r in rows if before(r,season,week)and r['season']in (season-1,season)),key=lambda r:(r['season'],r['week'],r['game_id']))


def average_profile(history,teams,snaps,season,week,team,category,line=None):
    field,workload=SPECS[category];history=prior_rows(history,season,week)
    seen=set();unique=[]
    for r in history:
        if r['game_id']in seen:continue
        seen.add(r['game_id']);unique.append(r)
    previous=[r for r in unique if r['season']==season-1];current=[r for r in unique if r['season']==season]
    away=max((r['week']for r in current if r['team']!=team),default=0)
    stint=[r for r in current if r['team']==team and r['week']>away]
    team_index={(r['season'],r['team'],r['game_id']):r for r in teams if before(r,season,week)}
    def summary(label,rows):
        stats=[number(r.get(field))for r in rows];stats=[v for v in stats if v is not None]
        volume=[number(r.get(workload))for r in rows];volume=[v for v in volume if v is not None and v>=0]
        pairs=[(number(r.get(field)),number(r.get(workload)))for r in rows]
        pairs=[(a,b)for a,b in pairs if a is not None and b is not None and b>=0]
        total=sum(b for a,b in pairs)
        result={'Sample':label,'Observed games':len(rows),'Stat sample games':len(stats),'Average':mean(stats),'Median':statistics.median(stats)if stats else None,'Opportunity type':workload,'Opportunities/game':mean(volume),'Opportunity sample games':len(volume),'Stat per opportunity':sum(a for a,b in pairs)/total if total>0 else None,'Includes prior season':any(r['season']==season-1 for r in rows),'Includes prior team':any(r['team']!=team for r in rows)}
        for numerator,denominator,label in (('completions','attempts','Completion %'),('receptions','targets','Catch %'),('passing_tds','attempts','Passing TD/attempt %'),('passing_interceptions','attempts','Interceptions/attempt %')):
            paired=[(number(r.get(numerator)),number(r.get(denominator)))for r in rows]
            paired=[(a,b)for a,b in paired if a is not None and b is not None and 0<=a<=b]
            denominator_total=sum(b for a,b in paired)
            result[label]=100*sum(a for a,b in paired)/denominator_total if denominator_total>0 else None
            result[label+' sample games']=len(paired)
        for numerator,denominator,label in (('passing_yards','attempts','Yards/pass attempt'),('rushing_yards','carries','Yards/carry'),('receiving_yards','targets','Yards/target'),('receiving_yards','receptions','Yards/reception')):
            paired=[(number(r.get(numerator)),number(r.get(denominator)))for r in rows]
            paired=[(a,b)for a,b in paired if a is not None and b is not None and b>=0]
            d=sum(b for a,b in paired);result[label]=sum(a for a,b in paired)/d if d>0 else None
        for numerator,denominator,label in (('targets','targets','Target share %'),('carries','carries','Carry share %'),('attempts','attempts','Pass-attempt share %')):
            paired=[]
            for r in rows:
                t=team_index.get((r['season'],r['team'],r['game_id']))
                a=number(r.get(numerator));b=number(t.get(denominator))if t else None
                if a is not None and b is not None and 0<=a<=b:paired.append((a,b))
            d=sum(b for a,b in paired);result[label]=100*sum(a for a,b in paired)/d if d>0 else None
            result[label+' matched games']=len(paired)
        snap=[]
        for r in rows:
            found=snaps.get((r['season'],r['team'],r['game_id'],name(r['player_display_name'])),[])
            share=number(found[0].get('offense_pct'))if len(found)==1 else None
            if share is not None and 0<=share<=1:snap.append(share)
        result['Mean game offensive snap %']=100*mean(snap)if snap else None
        result['Snap games matched']=len(snap)
        if number(line)is not None:
            line_value=number(line);over=sum(v>line_value for v in stats);under=sum(v<line_value for v in stats)
            result.update({'Compared line':line_value,'Historical overs':over,'Historical unders':under,'Historical pushes':sum(v==line_value for v in stats),'Historical over % (excluding pushes)':100*over/(over+under)if over+under else None})
        return result
    return [summary(label,rows)for label,rows in [('Last season — all teams',previous),('This season — all teams',current),('Current-team current stint',stint),('Last 3 appearances',unique[-3:]),('Last 5 appearances',unique[-5:])]]


def schedule_context(schedule,team,opponent,cutoff):
    day=date.fromisoformat(str(cutoff))
    def own(code):
        games=[]
        for r in schedule:
            if code not in (r.get('home_team'),r.get('away_team'))or not r.get('gameday'):continue
            try:when=date.fromisoformat(r['gameday'])
            except ValueError:continue
            if when>=day or (day-when).days>400:continue
            if number(r.get('home_score'))is None or number(r.get('away_score'))is None:continue
            games.append(r)
        if not games:return {'Status':'Earlier completed schedule entry unavailable','Short week':None}
        last=max(games,key=lambda r:r['gameday']);gap=(day-date.fromisoformat(last['gameday'])).days
        return {'Status':'Verified completed NFL schedule','Previous game':last.get('game_id'),'Previous game date':last['gameday'],'Calendar days between games':gap,'Scheduled off days':max(0,gap-1),'Short week':gap<=4,'Extended schedule gap':gap>=12,'Method':'Schedule gaps, not verified physical rest; no automatic rest penalty'}
    return {'Team':own(team),'Opponent':own(opponent)}


def opponent_context(teams,season,week,team,opponent):
    output=[]
    for year in (season-1,season):
        own=[r for r in teams if r['season']==year and before(r,season,week)and r['team']==team][-8:]
        defense=[r for r in teams if r['season']==year and before(r,season,week)and r['opponent_team']==opponent][-8:]
        result={'Season':year,'Team sample games':len(own),'Opponent sample games':len(defense)}
        plays=[r['attempts']+r['carries']for r in own if number(r.get('attempts'))is not None and number(r.get('carries'))is not None]
        result['Team attempts + carries/game']=mean(plays)
        result['Team pass-attempt % of attempts + carries']=100*sum(r['attempts']for r in own if number(r.get('attempts'))is not None and number(r.get('carries'))is not None)/sum(plays)if sum(plays)>0 else None
        for field in ('passing_yards','rushing_yards','receiving_yards','attempts','carries','targets','receptions'):
            values=[number(r.get(field))for r in defense];values=[v for v in values if v is not None]
            result['Opponent allowed '+field+'/game']=mean(values);result[field+' sample games']=len(values)
        result['Limitation']='Team-level context, not position-specific. Attempts + carries exclude sacks and are not a full pace metric. No extra multiplier applied.'
        output.append(result)
    return output


def depth_listing(data,athlete_id,player):
    matches=[]
    for group in data.get('depthchart',[]):
        for slot,p in group.get('positions',{}).items():
            position=p.get('position',{}).get('abbreviation','').upper()
            parent=p.get('position',{}).get('parent',{}).get('abbreviation','').upper()
            if position not in ('QB','RB','HB','FB','WR','TE')and parent not in ('QB','RB','HB','FB','WR','TE'):continue
            athletes=p.get('athletes',[])
            for rank,a in enumerate(athletes,1):
                if (athlete_id and str(a.get('id'))==str(athlete_id))or(not athlete_id and name(a.get('displayName'))==name(player)):
                    matches.append({'Position slot':slot,'Position':position,'Listed rank':rank,'First-listed player':athletes[0].get('displayName')if athletes else None})
    return {'Listings':matches,'Status':'ESPN depth listing; game-day starting role and workload are unconfirmed'if matches else'Depth listing unavailable or player not uniquely identified','Confirmed game-day starter':None}


def restriction(injuries,team,player,now):
    for row in injuries.get('rows',[]):
        if row.get('Team')!=team or name(row.get('Player'))!=name(player):continue
        try:fresh=0<=(now-datetime.fromisoformat(row['Report updated UTC'].replace('Z','+00:00'))).total_seconds()<=86400
        except (ValueError,KeyError,TypeError):fresh=False
        text=str(row.get('Short comment')or'')
        mention=bool(re.search(r'(?:on a |under a |with a )(?:snap|pitch|touches?) (?:count|limit)|limited (?:workload|snaps|touches)|workload (?:restriction|limit)|limited to \d+ (?:snaps|touches)',text,re.I))
        practice_only=bool(re.search(r'(?:in|during|at) practice|practice workload',text,re.I))and not bool(re.search(r'(?:in|during) (?:the )?game|on a (?:snap|pitch) count|game workload',text,re.I))
        clear=bool(re.search(r'\b(?:no|without|not (?:be )?(?:on|under)|no longer (?:on|under))(?: a)? (?:snap|pitch|touches?) (?:count|limit)|(?:restriction|limit) (?:has been|was|is) (?:lifted|removed)',text,re.I))
        if fresh and mention and not clear and not practice_only:return {'Review required':True,'Status':'Current report mentions limited game workload; verify before use','Report text':text,'Report updated UTC':row['Report updated UTC']}
    return {'Review required':False,'Status':'No explicit current game-workload limit found in checked report; unrestricted usage is not confirmed'}


def request_depth(team_id):
    import json
    from urllib.request import urlopen
    with urlopen('https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/'+str(team_id)+'/depthcharts',timeout=12)as response:return json.load(response)


def load_depths(team_ids):
    import streamlit as st
    from concurrent.futures import ThreadPoolExecutor
    cached=st.cache_data(ttl=300)(request_depth);result={};issues=[]
    with ThreadPoolExecutor(max_workers=6)as pool:
        jobs={str(tid):pool.submit(cached,str(tid))for tid in set(team_ids)}
        for tid,job in jobs.items():
            try:result[tid]=job.result()
            except Exception:issues.append('NFL depth listing unavailable for team '+tid)
    return {'teams':result,'issues':issues,'retrieved':datetime.now(timezone.utc).isoformat()}


def teammate_involvement(history,research,snaps,season,week,team,team_name,injuries,field,work):
    """Compare explicitly positive/zero offensive snaps, never absent rows."""
    absent={n for (t,n),status in injuries.get('statuses',{}).items()if t==team_name and str(status).lower()in ('out','ir','injured reserve','suspended','inactive')}
    names={name(r['player_display_name']):r['player_display_name']for r in research['players']if r['team']==team and before(r,season,week)and r['position']in ('QB','RB','HB','FB','WR','TE')}
    target=[r for r in prior_rows(history,season,week)if r['team']==team][-16:]
    results=[]
    for n in sorted(absent&names.keys()):
        if target and n==name(target[-1]['player_display_name']):continue
        groups={True:[],False:[]}
        for r in target:
            found=snaps.get((r['season'],team,r['game_id'],n),[])
            count=number(found[0].get('offense_snaps'))if len(found)==1 else None
            actual=number(r.get(field));volume=number(r.get(work))
            if count is None or count<0 or actual is None or volume is None:continue
            groups[count>0].append((actual,volume))
        enough=min(len(v)for v in groups.values())>=3
        def summarize(values):return {'Games':len(values),'Stat average':mean([v[0]for v in values]),'Opportunities/game':mean([v[1]for v in values])}
        positive,zero=summarize(groups[True]),summarize(groups[False])
        results.append({'Currently unavailable teammate':names[n],'Recorded positive offensive snaps':positive,'Recorded zero offensive snaps':zero,'Observed stat difference':zero['Stat average']-positive['Stat average']if enough else None,'Status':'Descriptive matched comparison only'if enough else'Insufficient matched evidence (need 3 games in each group)','Limitation':'A missing snap row is unknown, not zero or DNP. Recorded zero offensive snaps does not prove injury or total game absence. No causal effect or automatic redistribution is inferred.'})
    return results


def attach(row,history,research,season,week,team,opponent,team_name,team_id,athlete_id,injuries,now,cutoff):
    if row['Category']not in SPECS:return row
    snaps=research.get('parity_snaps',{})
    profile=average_profile(history,research['teams'],snaps,season,week,team,row['Category'],row.get('Line'))
    row['NFL player averages']=profile;row['NFL evidence version']=VERSION
    row['NFL averages method']='Completed regular-season observed games only. Rates use paired totals. Recent samples may span seasons/teams as labeled; missing rows are not zero or DNP. Historical line percentages are not predicted win chances.'
    row['NFL verified schedule context']=schedule_context(research['schedule'],team,opponent,cutoff)
    row['NFL opponent workload context']=opponent_context(research['teams'],season,week,team,opponent)
    depths=research.get('parity_depths',{})
    row['NFL depth check']=depth_listing(depths.get('teams',{}).get(str(team_id),{}),athlete_id,row['Player'])
    row['NFL depth checked UTC']=depths.get('retrieved')
    row['NFL restriction check']=restriction(injuries,team_name,row['Player'],now)
    field,work=SPECS[row['Category']];ordered=prior_rows(history,season,week)
    current=[r for r in ordered if r['season']==season]
    away=max((r['week']for r in current if r['team']!=team),default=0)
    stint=[r for r in current if r['team']==team and r['week']>away]
    relevant=stint or [r for r in ordered if r['season']==season-1 and r['team']==team]
    snap_values=[]
    for r in relevant[-8:]:
        matched=snaps.get((r['season'],r['team'],r['game_id'],name(r['player_display_name'])),[])
        share=number(matched[0].get('offense_pct'))if len(matched)==1 else None
        snap_values.append(share if share is not None and 0<=share<=1 else None)
    complete=len(snap_values)>=4 and all(v is not None for v in snap_values)
    recent_snap=mean(snap_values[-2:])if complete else None
    earlier_snap=mean(snap_values[:-2])if complete else None
    row['NFL snap trend']={'Sample games':len(snap_values),'Matched games':sum(v is not None for v in snap_values),'Recent two-game snap %':100*recent_snap if recent_snap is not None else None,'Earlier snap %':100*earlier_snap if earlier_snap is not None else None,'Role change flag':abs(recent_snap-earlier_snap)>=.15 if complete else None,'Limitation':'Observed snap-share change, not routes, a confirmed new starting role or a causal explanation; no snap penalty/boost automatically applied'}
    expected=number(row.get('Expected opportunities'));projected=number(row.get('Projection (yards)'))
    if projected is None:projected=number(row.get('Projection (count)'))
    opportunities=[number(r.get(work))for r in relevant[-8:]]
    opportunities=[v for v in opportunities if v is not None and v>=0]
    scenarios=[];candidate=None
    if expected is not None and expected>0 and projected is not None and len(opportunities)>=3:
        values=sorted(opportunities);low=values[int(.1*(len(values)-1))];high=values[math.ceil(.9*(len(values)-1))]
        scenarios=[{'Scenario':label,'Opportunities':v,'Stat if production per opportunity stays unchanged':projected*v/expected}for label,v in [('Observed lower workload',low),('Base workload forecast',expected),('Observed higher workload',high)]]
        if len(stint)>=2 and all(number(r.get(work))is not None for r in stint[-2:]):candidate=mean([r[work]for r in stint[-2:]])
    row['NFL workload sensitivity']=scenarios
    row['NFL recent-role candidate']={'Version':VERSION,'Opportunities':candidate,'Projection':projected*candidate/expected if candidate is not None and expected and projected is not None else None,'Base opportunities':expected,'Base projection':projected,'Sample games':2 if candidate is not None else 0,'Status':'Recent observed opportunities only; research scenario, not a validated replacement or automatic pick'}
    row['NFL teammate involvement']=teammate_involvement(history,research,snaps,season,week,team,team_name,injuries,field,work)
    if projected is not None and row.get('Historical error range low')is None:
        markets={'Passing yards':'player_pass_yds','Passing attempts':'player_pass_attempts','Passing completions':'player_pass_completions','Passing touchdowns':'player_pass_tds','Passing interceptions':'player_pass_interceptions','Rushing yards':'player_rush_yds','Rushing attempts':'player_rush_attempts','Receiving yards':'player_reception_yds','Receptions':'player_receptions'}
        prior_model=str(row.get('Model','')).startswith('NFL season-prior')
        report=research.get('season_prior_reports',{}).get((markets[row['Category']],row.get('Season stage')),{})if prior_model else research.get('models',{}).get(markets[row['Category']],{})
        residuals=sorted(v for v in report.get('residuals',[])if number(v)is not None)
        if len(residuals)>=50:
            scale=max(1.,math.sqrt(max(0.,projected)))*float(row.get('Uncertainty multiplier',1))if prior_model else max(15.,.35*projected)
            low=projected+residuals[int(.1*(len(residuals)-1))]*scale;high=projected+residuals[math.ceil(.9*(len(residuals)-1))]*scale
            if 'yards'not in row['Category'].lower():low=max(0.,low);high=max(0.,high)
            row.update({'Historical error range low':low,'Historical error range high':high,'Range method':'Earlier model residual 10th–90th percentiles; empirical range, not guaranteed future coverage'})
            if prior_model:row['Validation details']={'mae':report.get('forecast_mae'),'baseline_mae':report.get('baseline_mae'),'passed':report.get('passed'),'validation_games':report.get('validation_games'),'empirical_band_validation_coverage':report.get('empirical_band_validation_coverage'),'scope':'NFL season-stage historical stat development comparison; not historical sportsbook returns'}
    if row['NFL restriction check']['Review required']:
        row['Decision']='Pass';row['Reason']=row['NFL restriction check']['Status']
    return row


def render_evidence(rows):
    import streamlit as st
    choices={}
    for row in rows:
        if row.get('NFL evidence version'):choices.setdefault((row['Game'],row['Player'],row['Category']),row)
    if not choices:return
    with st.expander('NFL player averages, conversion rates and usage evidence'):
        chosen=st.selectbox('Inspect NFL player evidence',list(choices),format_func=lambda k:' · '.join(k),key='nfl_parity_evidence')
        row=choices[chosen];profile=row['NFL player averages']
        tabs=st.tabs(['Averages and conversion','Shares and snap role','Matchup, rest and availability'])
        with tabs[0]:
            fields=('Sample','Observed games','Average','Median','Opportunities/game','Opportunity type','Stat per opportunity','Completion %','Catch %','Passing TD/attempt %','Interceptions/attempt %','Yards/pass attempt','Yards/carry','Yards/target','Yards/reception','Includes prior season','Includes prior team')
            st.dataframe([{k:r.get(k)for k in fields}for r in profile],hide_index=True,use_container_width=True)
            st.caption(row['NFL averages method'])
            with st.expander('Historical results against this line'):
                fields=('Sample','Stat sample games','Compared line','Historical overs','Historical unders','Historical pushes','Historical over % (excluding pushes)')
                st.dataframe([{k:r.get(k)for k in fields}for r in profile],hide_index=True,use_container_width=True)
                st.caption('Historical line results are not forecast win probabilities. Rates use paired total completions/attempts, receptions/targets and other matching observations; missing values are not zero.')
        with tabs[1]:
            fields=('Sample','Target share %','Target share % matched games','Carry share %','Carry share % matched games','Pass-attempt share %','Mean game offensive snap %','Snap games matched')
            st.dataframe([{k:r.get(k)for k in fields}for r in profile],hide_index=True,use_container_width=True)
            st.write(row.get('NFL snap trend',{}));st.write(row.get('NFL recent-role candidate',{}))
            if row.get('NFL workload sensitivity'):st.dataframe(row['NFL workload sensitivity'],hide_index=True,use_container_width=True)
            st.caption('Workload scenarios are not separate bets. Snap share is not routes run or confirmed starting status. Candidate workload changes are saved for prospective comparison, not automatically applied.')
        with tabs[2]:
            for label,field in (('Depth listing','NFL depth check'),('Reported workload limits','NFL restriction check'),('Verified schedule/rest','NFL verified schedule context'),('Opponent and play-volume context','NFL opponent workload context'),('Teammate involvement comparisons','NFL teammate involvement'),('Unvalidated absence/game-flow scenario','NFL context scenario')):
                st.write('**'+label+'**');st.write(row.get(field)or'No verified comparison available')


def saved_role_reviews(records):
    """Game-weighted frozen prospective workload/range comparisons."""
    groups=defaultdict(list);seen=set()
    for r in sorted(records,key=lambda r:r.get('published_utc')or'9999'):
        if r.get('sport','NFL')!='NFL'or r.get('strategy')not in ('Original','Analysis')or r.get('season_type')!='Regular season'or r.get('evidence')not in ('Published before kickoff','Personal paper record'):continue
        try:
            if datetime.fromisoformat(r['published_utc'].replace('Z','+00:00'))>=datetime.fromisoformat(r['starts_utc'].replace('Z','+00:00')):continue
        except (ValueError,TypeError,KeyError):continue
        context=r.get('forecast_context')or{}
        if context.get('NFL evidence version')!=VERSION:continue
        identity=(r.get('event_id'),r.get('player'),r.get('category'))
        if identity in seen:continue
        seen.add(identity)
        if r.get('result')not in ('Win','Loss','Push'):continue
        candidate=context.get('NFL recent-role candidate')or{}
        actual=number(r.get('actual'));work=number(r.get('actual_opportunities'))
        cw,bw=number(candidate.get('Opportunities')),number(candidate.get('Base opportunities'))
        cp,bp=number(candidate.get('Projection')),number(candidate.get('Base projection'))
        low,high=number(context.get('Historical error range low')),number(context.get('Historical error range high'))
        values=(abs(work-cw)if work is not None and cw is not None else None,abs(work-bw)if work is not None and bw is not None else None,abs(actual-cp)if actual is not None and cp is not None else None,abs(actual-bp)if actual is not None and bp is not None else None,low<=actual<=high if actual is not None and low is not None and high is not None else None)
        groups[r['category']].append((r['event_id'],values))
    output=[]
    for category,rows in sorted(groups.items()):
        def metric(index):
            games=defaultdict(list)
            for eid,values in rows:
                if values[index]is not None:games[eid].append(values[index])
            return mean([mean(v)for v in games.values()])
        coverage=metric(4)
        output.append({'sport':'NFL','category':category,'forecasts':len(rows),'distinct_games':len({eid for eid,v in rows}),'role_workload_mae':metric(0),'base_workload_mae':metric(1),'role_stat_mae':metric(2),'base_stat_mae':metric(3),'range_comparisons':sum(v[4]is not None for eid,v in rows),'range_coverage_pct':100*coverage if coverage is not None else None,'status':'Prospective research comparison only; no automatic promotion'})
    return output
