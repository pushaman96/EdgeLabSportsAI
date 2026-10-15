"""Participation-aware role forecast research. No missing values are imputed as zero."""
from collections import defaultdict
from datetime import datetime,timezone
import statistics
import streamlit as st
from nfl_prop_model import MARKETS,ALIASES,name_key,num,load_prop_research,load_season_stats,indexes
from player_usage import load_snap_usage

def avg(values):return statistics.mean(values) if values else None

def snap_lookup(rows):
    result=defaultdict(list)
    for r in rows:
        if r.get('game_type')!='REG':continue
        result[(int(r['season']),ALIASES.get(r['team'],r['team']),r['game_id'],name_key(r['player']))].append(r)
    return result

def participation_history(player,team,season,before_week,idx,snaps):
    history=idx[0].get((season,player),[])
    own=[r for r in history if r['team']==team and r['week']<before_week]
    if not own:return []
    names={name_key(r['player_display_name']) for r in own}
    output=[]
    for game in idx[1].get((season,team),[]):
        if game['week']>=before_week:continue
        reported=[r for r in own if r['game_id']==game['game_id']]
        found=[s for name in names for s in snaps.get((season,team,game['game_id'],name),[])]
        snap=found[0] if len(found)==1 else None
        count=num(snap.get('offense_snaps')) if snap else None
        status='Stats reported' if len(reported)==1 else 'Played offensive snaps; player stats missing' if count is not None and count>0 else 'No offensive snaps recorded; participation unresolved' if count==0 else 'Participation unresolved; stats missing'
        output.append({'Player':own[-1]['player_display_name'],'Team':team,'Week':game['week'],'Game ID':game['game_id'],'Status':status,'Reported attempts':reported[0].get('attempts') if len(reported)==1 else None,'Reported carries':reported[0].get('carries') if len(reported)==1 else None,'Reported targets':reported[0].get('targets') if len(reported)==1 else None,'Offensive snaps':count,'Snap share %':100*num(snap['offense_pct']) if snap and num(snap.get('offense_pct')) is not None else None})
    return output

def role_inputs(row,market,idx,snaps):
    _,stat,workload,positions,minimum=MARKETS[market]
    if row['position'] not in positions:return None
    history=[r for r in idx[0].get((row['season'],row['player_id']),[]) if r['week']<row['week'] and r['team']==row['team'] and r.get(stat) is not None and r.get(workload) is not None][-8:]
    team=[r for r in idx[1].get((row['season'],row['team']),[]) if r['week']<row['week'] and r.get(workload) is not None][-4:]
    if len(history)<2 or len(team)<4:return None
    # Latest observed role must include the team's latest completed game.
    if history[-1]['game_id']!=team[-1]['game_id']:return None
    by_game={r['game_id']:r for r in team};joined=[]
    for r in history[-4:]:
        matches=snaps.get((r['season'],r['team'],r['game_id'],name_key(r['player_display_name'])),[])
        t=by_game.get(r['game_id'])
        if len(matches)!=1 or not t or not t[workload]:continue
        share=num(matches[0].get('offense_pct'))
        if share is None or not 0<share<=1:continue
        joined.append((r,t,share))
    if len(joined)<2 or joined[-1][0]['game_id']!=team[-1]['game_id']:return None
    recent=joined[-2:];recent_work=avg([r[workload] for r,_,_ in recent])
    if recent_work<minimum:return None
    previous=joined[:-2]
    latest_share=avg([s for _,_,s in recent]);previous_share=avg([s for _,_,s in previous])
    shift=latest_share-previous_share if previous_share is not None else None
    team_volume=.6*avg([t[workload] for t in team[-2:]])+.4*avg([t[workload] for t in team])
    recent_fraction=avg([r[workload]/t[workload] for r,t,_ in recent])
    all_fraction=avg([r[workload]/t[workload] for r,t,_ in joined])
    intensity=avg([r[workload]/t[workload]/s for r,t,s in joined])
    volumes={'Recent opportunity share':team_volume*min(1,recent_fraction),'Four-game opportunity share':team_volume*min(1,all_fraction),'Snap-adjusted opportunity share':team_volume*min(1,intensity*latest_share)}
    total=sum(r[workload] for r in history)
    if total<=0:return None
    efficiency=sum(r[stat] for r in history)/total
    # Previous-year performance supplies efficiency only, never a claimed current role.
    prior=[r for r in idx[0].get((row['season']-1,row['player_id']),[]) if r['team']==row['team'] and r['position'] in positions and r.get(stat) is not None and r.get(workload) is not None][-8:]
    prior_total=sum(r[workload] for r in prior)
    stabilized=(sum(r[stat] for r in history)+40*sum(r[stat] for r in prior)/prior_total)/(total+40) if len(prior)>=8 and prior_total>0 else efficiency
    return {'volumes':volumes,'efficiency':efficiency,'stabilized':stabilized,'baseline':avg([r[stat] for r in history[-4:]]),'snap_shift':shift,'role_change':shift is not None and abs(shift)>=.2,'missing_recent':len({t['game_id'] for t in team}-{r['game_id'] for r in history}),'row':row}

def test_roles(research,snap_rows):
    idx=indexes(research['players'],research['teams']);snaps=snap_lookup(snap_rows);samples=defaultdict(list)
    for row in research['players']:
        if row['season']<2024:continue
        for market,(_,stat,_,positions,_) in MARKETS.items():
            if row['position'] not in positions or row.get(stat) is None:continue
            f=role_inputs(row,market,idx,snaps)
            if f:samples[market,row['season']].append((f,row[stat]))
    reports=[];choices={}
    def predict(f,p):return f['volumes'][p[0]]*f[p[1]]
    for market,(label,*_) in MARKETS.items():
        training=samples[market,2024]
        if len(training)<100:continue
        params=min(((v,e) for v in training[0][0]['volumes'] for e in ('efficiency','stabilized')),key=lambda p:avg([abs(predict(f,p)-y) for f,y in training]))
        choices[market]=params
        for season in sorted({2025,research['season']}):
            all_test=samples[market,season]
            for cohort in ('All eligible','Role change or recent stat gap'):
                tested=all_test if cohort=='All eligible' else [(f,y) for f,y in all_test if f['role_change'] or f['missing_recent']]
                if not tested:continue
                error=avg([abs(predict(f,params)-y) for f,y in tested]);baseline=avg([abs(f['baseline']-y) for f,y in tested])
                reports.append({'Category':label,'Season':season,'Cohort':cohort,'Forecasts':len(tested),'2024 training examples':len(training),'Workload method':params[0],'Efficiency method':params[1],'Role forecast error':round(error,3),'Recent-average error':round(baseline,3),'Improvement':round(baseline-error,3),'Status':'Research only — no automatic promotion'})
    evidence=[]
    for (season,pid),rows in idx[0].items():
        if season!=research['season']:continue
        for team in {r['team'] for r in rows}:
            evidence.extend(participation_history(pid,team,season,23,idx,snaps))
    previews=[]
    for (season,pid),rows in idx[0].items():
        if season!=research['season']:continue
        for team in {r['team'] for r in rows}:
            own=[r for r in rows if r['team']==team]
            team_rows=idx[1].get((season,team),[])
            if not own or not team_rows:continue
            before=max(r['week'] for r in team_rows)+1
            probe=dict(own[-1],week=before)
            for market,params in choices.items():
                f=role_inputs(probe,market,idx,snaps)
                if not f:continue
                previews.append({'Player':probe['player_display_name'],'Team':team,'Category':MARKETS[market][0],'Stats through week':before-1,'Expected opportunities':round(f['volumes'][params[0]],2),'Research projection':round(predict(f,params),2),'Recent snap share change (pp)':round(100*f['snap_shift'],1) if f['snap_shift'] is not None else None,'Missing recent stat games':f['missing_recent'],'Status':'Research estimate — no bet probability or recommendation'})
    return {'reports':reports,'choices':choices,'participation':evidence,'previews':previews}

def render_role_forecast_lab():
    with st.expander('Participation and role-change forecast test'):
        st.caption('Tests team volume × player opportunity share, snap-adjusted usage and same-team prior-season efficiency. Missing stats remain unknown; no DNP or zero is inferred. Uses earlier weeks only, chooses methods on 2024, and reports later years separately. The 2025 results are development evidence, not a fresh independent test. Observed role changes are not confirmed injury news or future starting assignments. No live picks change.')
        if st.button('Run participation and role-change test',key='role_forecast_test'):
            try:
                season=datetime.now(timezone.utc).year
                with st.spinner('Testing role forecasts and participation coverage…'):
                    research=load_prop_research(season)
                    research=dict(research,players=load_season_stats('player',2023)+research['players'])
                    snaps=[r for year in sorted({2024,2025,season}) for r in load_snap_usage(year)]
                    st.session_state['role_forecast_lab']=test_roles(research,snaps)
            except Exception:st.warning('Role test unavailable; existing picks are unchanged.')
        saved=st.session_state.get('role_forecast_lab')
        if not saved:return
        st.dataframe(saved['reports'],hide_index=True,use_container_width=True)
        names=sorted({r['Player'] for r in saved['participation']})
        if names:
            selected=st.selectbox('Inspect player participation',names,key='role_participation_player')
            st.dataframe([r for r in saved['participation'] if r['Player']==selected],hide_index=True,use_container_width=True)
            st.write('Current role estimates — research only')
            st.dataframe([r for r in saved.get('previews',[]) if r['Player']==selected],hide_index=True,use_container_width=True)
