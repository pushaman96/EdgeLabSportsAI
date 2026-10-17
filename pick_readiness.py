"""Read-only audits and freshness labels. These never alter saved predictions."""
import json,math,re
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
PACIFIC=ZoneInfo('America/Los_Angeles')
def utc(value):return datetime.fromisoformat(str(value).replace('Z','+00:00'))
def age_label(value,limit,now=None):
    now=now or datetime.now(timezone.utc)
    try:seconds=(now-utc(value)).total_seconds()
    except (ValueError,TypeError):return 'Unknown'
    if seconds< -600:return 'Clock mismatch'
    return ('Fresh' if seconds<=limit else 'Stale')+' · '+(f'{max(0,seconds)/60:.0f} min ago' if seconds<3600 else f'{seconds/3600:.1f} h ago')
def records_for_day(records,sport,day):
    selected=[]
    for r in records:
        try:matches=utc(r['starts_utc']).astimezone(PACIFIC).date()==day
        except (ValueError,KeyError):continue
        if matches and r.get('sport','NFL')==sport:selected.append(r)
    return selected

def audit_records(records):
    result=[];ids=set();directions={}
    for r in records:
        notes=[]
        if r.get('id') in ids:notes.append('Duplicate saved ID')
        ids.add(r.get('id'))
        try:
            if utc(r['published_utc'])>=utc(r['starts_utc']):notes.append('Not frozen before kickoff')
        except (ValueError,KeyError):notes.append('Publish/kickoff timestamp unavailable')
        p=r.get('probability')
        if r.get('strategy')!='Manual' and (not isinstance(p,(int,float)) or not math.isfinite(p) or not 0<p<1):notes.append('Model probability unavailable/invalid')
        if r.get('category')!='Moneyline' and (r.get('line') is None or r.get('direction') not in ('Over','Under')):notes.append('Line or direction unavailable')
        result.append({'Pick ID':r.get('id'),'Player/team':r.get('player'),'Game':r.get('game'),'Audit':'Review needed' if notes else 'Frozen-record checks passed','Notes':'; '.join(notes) or 'Identity, saved probability and pregame timestamp checked; current availability is a separate check.'})
        key=(r.get('sport','NFL'),r.get('event_id'),r.get('player'),r.get('category'),r.get('strategy'))
        directions.setdefault(key,set()).add(r.get('direction'))
    for row,r in zip(result,records):
        key=(r.get('sport','NFL'),r.get('event_id'),r.get('player'),r.get('category'),r.get('strategy'))
        if len(directions[key])>1:row.update(Audit='Review needed',Notes=row['Notes']+' Conflicting saved directions across models; review before treating them as separate picks.')
    return result

def risk_notes(record):
    category=record.get('category','');context=record.get('forecast_context') or {};notes=[]
    if category in ('Passing yards','Passing attempts','Receiving yards','Receptions'):notes.append('Trailing can increase passing volume; a lead can reduce it. The model does not assign probabilities to those game scripts.')
    elif category in ('Rushing yards','Rushing attempts'):notes.append('Trailing can reduce rushing volume; a lead can increase it. Carries also depend on role and availability.')
    elif category=='Moneyline':notes.append('Historical Elo does not numerically adjust for injuries, replacement players or offensive-line changes.')
    if context.get('Current-team games') is not None:notes.append(f"Saved current-team sample: {context['Current-team games']} games.")
    notes.append('Picks involving the same player or game can be correlated; they are not independent evidence.')
    return ' '.join(notes)

def render_source_status(saved):
    import streamlit as st
    now=datetime.now(timezone.utc)
    rows=[]
    for label,key,limit in [('Analysis','analyzed',900),('Statistics downloaded','retrieved',21600),('Injury feed retrieved','injury_retrieved',900),('Injury feed source update','injury_source_updated',21600),('Roster checked (may use 5-minute cache)','roster_checked',900)]:
        rows.append({'Input':label,'Status':age_label(saved.get(key),limit,now),'Timestamp UTC':saved.get(key) or 'Not recorded'})
    with st.expander('Input freshness and forecast coverage'):
        st.dataframe(rows,hide_index=True,use_container_width=True)
        st.caption('A recent download does not mean the underlying weekly statistics are current. Player history dates appear beside analyzed picks. Injury checks verify reported status, not a quantified injury impact.')

def render_overview(sport,day,path='published_picks.json'):
    import streamlit as st
    from dashboard_history import tracked_records
    records=tracked_records(path,st.session_state.get('personal_paper_records',[]))
    selected=records_for_day(records,sport,day)
    try:persisted=json.loads(Path(path).read_text())['records'];permanent={r['id'] for r in persisted}
    except (OSError,ValueError,KeyError):persisted=[];permanent=set()
    audit_input=records_for_day(persisted+[r for r in st.session_state.get('personal_paper_records',[]) if r['id'] not in permanent],sport,day)
    permanent|=set(st.session_state.get('autosave_permanent_ids',set()))
    waiting=sum(r['id'] not in permanent for r in selected)
    st.caption(f'{sport} · {day.strftime("%A, %B %d")} · Saved recommendations and source status')
    cols=st.columns(3)
    cols[0].metric('Saved picks for this date',len(selected))
    cols[1].metric('Awaiting final results',sum(r.get('result')=='Pending' for r in selected))
    cols[2].metric('Permanent storage','Confirmed' if selected and not waiting else f'{waiting} awaiting confirmation' if waiting else 'No picks for this date')
    with st.expander('Data freshness and saved-pick audit'):
        audit=audit_records(audit_input)
        issues=sum(r['Audit']=='Review needed' for r in audit)
        if audit:st.write(f'{len(audit)-issues}/{len(audit)} saved records passed structural checks.');st.dataframe(audit,hide_index=True,use_container_width=True)
        else:st.info('Select the game date containing your saved picks to review them.')
        st.caption('These checks do not independently validate model accuracy or current lineups. No sportsbook request is made here.')
        odds=st.session_state.get('sportsbook_result')
        if odds and odds[0]==sport:st.write('Loaded game prices: '+age_label(odds[2].get('retrieved'),900))
        analysis=st.session_state.get('nfl_prop_analysis') if sport=='NFL' else None
        if analysis:render_source_status(analysis)
        if sport=='NFL' and selected:
            if st.button('Verify saved players against current rosters & injuries — 0 odds credits',key='verify_saved_rosters'):
                st.session_state['saved_pick_availability']=verify_current_players(selected)
            verification=st.session_state.get('saved_pick_availability')
            if verification and verification.get('ids')==sorted(r['id'] for r in selected):
                st.caption('Availability check: '+age_label(verification['checked'],900))
                st.dataframe(verification['rows'],hide_index=True,use_container_width=True)

def verify_current_players(records):
    """Free ESPN availability check, separate from frozen records and decisions."""
    from concurrent.futures import ThreadPoolExecutor
    from nfl_prop_model import current_roster,injury_context,name_key
    from team_emblems import directory_index
    now=datetime.now(timezone.utc);index=directory_index('NFL');rows=[]
    try:injuries=injury_context()
    except Exception:injuries={}
    codes={(r.get('forecast_context') or {}).get('Current roster team') for r in records if r.get('category')!='Moneyline'}-{None}
    teams={code:index.get('NFL:'+code) for code in codes}
    def fetch(pair):
        code,team=pair
        try:return code,current_roster(team['id']) if team else []
        except Exception:return code,[]
    with ThreadPoolExecutor(max_workers=4) as pool:rosters=dict(pool.map(fetch,teams.items()))
    for r in records:
        if r.get('category')=='Moneyline':
            rows.append({'Player/team':r['player'],'Status':'Historical team model — inspect matchup injury warnings; no injury-adjusted probability'});continue
        code=(r.get('forecast_context') or {}).get('Current roster team');team=teams.get(code)
        matches=[p for p in rosters.get(code,[]) if name_key(p['name'])==name_key(r['player']) and p.get('position') in ('QB','RB','HB','FB','WR','TE')]
        if len(matches)!=1:status='Roster unavailable or no unique offensive player match'
        else:
            reported=injuries.get('statuses',{}).get((team['name'],name_key(r['player'])),'Not listed')
            covered=team['name'] in injuries.get('teams',set())
            source=age_label(injuries.get('source_updated'),21600,now)
            retrieved=age_label(injuries.get('retrieved'),900,now)
            if not covered or int(injuries.get('season') or 0)!=utc(r['starts_utc']).year or not source.startswith('Fresh') or not retrieved.startswith('Fresh'):status='Roster matched; injury coverage stale or unavailable'
            else:status=f"Roster: {matches[0].get('status','Unknown')} · Injury report: {reported}"
        note=''
        text=r.get('reason','')
        if 'New teammates with limited team history:' in text:
            fragment=text.split('New teammates with limited team history:',1)[1].split('Target/carry redistribution',1)[0].strip().rstrip('.')
            named=[n.strip() for n in fragment.split(',') if n.strip()]
            offensive={name_key(p['name']) for p in rosters.get(code,[]) if p.get('position') in ('QB','RB','HB','FB','WR','TE')}
            unsupported=[n for n in named if name_key(n) not in offensive]
            if rosters.get(code) and unsupported:note='Older saved teammate warning needs review: '+', '.join(unsupported)+' is not a matched current offensive teammate. The frozen pick is unchanged.'
        rows.append({'Pick ID':r['id'],'Player/team':r['player'],'Saved team':code,'Status':status,'Saved explanation note':note})
    return {'ids':sorted(r['id'] for r in records),'checked':now.isoformat(),'rows':rows}
