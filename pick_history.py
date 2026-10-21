"""Durable published ledger plus completed-game grading. No bets are placed."""
import json, math, hashlib, base64
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.request import urlopen
REPO='pushaman96/EdgeLabSportsAI'
LEDGER='published_picks.json'
SUMMARY='https://site.api.espn.com/apis/site/v2/sports/{sport}/summary?event='

def utc(value):return datetime.fromisoformat(value.replace('Z','+00:00'))

def scoreboard_day(value):return utc(value).astimezone(ZoneInfo('America/Los_Angeles')).strftime('%Y%m%d')

def restore_records(payload):
    imported=payload['records']
    if not isinstance(imported,list) or len(imported)>5000:raise ValueError('Invalid record list.')
    clean=[];seen=set()
    for original in imported:
        r=dict(original)
        if r.get('sport','NFL') not in ('NFL','NBA') or r['category'] not in ('Passing yards','Rushing yards','Receiving yards','Receptions','Passing attempts','Passing interceptions','Passing completions','Passing touchdowns','Rushing attempts','Moneyline','Points','Rebounds','Assists','Three-pointers made','Steals','Blocks'):raise ValueError('Unsupported category/sport.')
        if r['strategy'] not in ('Original','Cushion','Manual'):raise ValueError('Invalid strategy.')
        r['odds']=float(r['odds'])
        if not math.isfinite(r['odds']) or abs(r['odds'])<100:raise ValueError('Invalid price.')
        if r.get('probability') is not None:
            r['probability']=float(r['probability'])
            if not 0<r['probability']<1:raise ValueError('Invalid probability.')
        if r['category']!='Moneyline':
            r['line']=float(r['line'])
            if not math.isfinite(r['line']) or r['line']<0 or r['direction'] not in ('Over','Under'):raise ValueError('Invalid line/direction.')
        if r['evidence']!='Historical import':
            if utc(r['published_utc'])>=utc(r['starts_utc']):raise ValueError('Late record.')
            r['evidence']='Personal paper record'
        for key in ('id','event_id','game','player','model'):
            if not isinstance(r[key],str) or not r[key] or len(r[key])>500:raise ValueError('Invalid identity.')
        if r['id'] in seen:raise ValueError('Duplicate record ID.')
        seen.add(r['id']);r.update(result='Pending',actual=None,profit_per_1=None)
        clean.append(r)
    return clean

def make_record(row,event_id,start,now=None,strategy='Original'):
    now=now or datetime.now(timezone.utc)
    if now>=utc(start):raise ValueError('Publish before kickoff.')
    if not 0<=(now-utc(row['Quote updated UTC'])).total_seconds()<=900:raise ValueError('Refresh the quote before publishing.')
    category=row['Category']
    if (row['Decision']=='Pass' and strategy!='Analysis') or category not in ('Passing yards','Rushing yards','Receiving yards','Receptions','Passing attempts','Passing interceptions','Passing completions','Passing touchdowns','Rushing attempts','Moneyline','Points','Rebounds','Assists','Three-pointers made','Steals','Blocks'):raise ValueError('Unsupported pick category.')
    line=None if category=='Moneyline' else float(row['Line']);odds=float(row['Odds']);prob=float(row['Estimated win %'])/100 if row.get('Estimated win %') is not None else None
    if not math.isfinite(odds) or abs(odds)<100 or (prob is not None and (not math.isfinite(prob) or not 0<prob<1)):raise ValueError('Invalid price or probability.')
    if prob is None and strategy!='Manual':raise ValueError('Model picks need probabilities.')
    if line is not None and (not math.isfinite(line) or line<0 or (strategy!='Manual' and line%1!=.5)):raise ValueError('Invalid prop line.')
    identity='|'.join([str(event_id),row['Player'],category,strategy,row.get('Base model') or row.get('Model','Experimental')])
    if strategy=='Analysis':identity+='|'+str(line)+'|'+str(row['Selection'])
    record={'id':hashlib.sha256(identity.encode()).hexdigest()[:20],'sport':row.get('Sport','NFL'),'event_id':str(event_id),'game':row['Game'],'player':row['Player'],'category':category,'direction':row['Selection'],'line':line,'odds':odds,'probability':prob,'sportsbook':row['Sportsbook'],'model':row.get('Model','Experimental'),'strategy':strategy,'published_utc':now.isoformat(),'starts_utc':start,'evidence':'Published before kickoff','result':'Pending','actual':None,'profit_per_1':None}
    record['projected_yards']=row.get('Projection (yards)');record['expected_opportunities']=row.get('Expected opportunities');record['reason']=row.get('Reason','')
    record['projected_count']=row.get('Projection (count)')
    record['base_model']=row.get('Base model') or row.get('Model','Experimental')
    record['raw_probability']=float(row['Raw estimated win %'])/100 if row.get('Raw estimated win %') is not None else prob
    record['feedback_version']=row.get('Feedback version')
    record['feedback_status']=row.get('Feedback status')
    for source, destination in (('Base projection','base_projection'),('Base expected opportunities','base_expected_opportunities'),('Online version','online_version'),('Online learning status','online_status'),('Candidate projection','candidate_projection'),('Unadjusted projection','unadjusted_projection')):
        if source in row:record[destination]=row[source]
    for source, destination in (('Base estimated win %','base_probability'),('Online input win %','online_input_probability'),('Candidate win %','candidate_probability')):
        if row.get(source) is not None:record[destination]=float(row[source])/100

    record['forecast_context']={k:row[k] for k in ('Opportunity type','Workload method','Efficiency method','Expected team passing attempts','Catch probability %','Recent snap share %','Recent target share %','Current roster team','Current-team games','Game-script risk','Evidence explanation','Injury adjustment %','Injury adjustment reason','Situation adjustment %','Situation forecast','Minutes forecast','Availability checked UTC','Context validation status','Conversion rate %','QB historical conversion %','Opponent conversion %','Range method','Historical error range low','Historical error range high','Validation details','Probability method','Target breakdown','Player targets forecast','Target share forecast %','Supporting team attempts','Supporting catch probability %','Supporting receptions forecast','Supporting receiving yards forecast','Passing conversion breakdown','Supporting completions forecast','Supporting passing TD forecast','History source','Season stage','Last-season games','Current-season appearances','Current-season weight %','Role uncertainty','Uncertainty multiplier','Workload candidate opportunities','Workload candidate projection','Workload candidate status','Workload candidate benchmark','Workload sensitivity scenarios','Confirmed unavailable teammates','Lineup scenario limitation','Supporting team workload','Supporting player workload share %','Schedule and rest context','Game context scenarios','Workload candidate version','Workload candidate baseline opportunities','Workload candidate baseline projection','Minutes sample games','Minutes sample basis','Observed minutes low','Observed minutes high','Minutes risk','Minutes sensitivity','Minutes sensitivity scenarios','Range calibration examples','Absence scenario minutes','Absence scenario projection','Absence scenario status','NBA context version','NBA context checked UTC','Starting lineup check','Minutes restriction check','Verified schedule context','Teammate absence usage','Opponent and pace context','NBA context limitation','Probability calibration status','Player averages','Player averages method','Last-season average','This-season average','Last-5 average','Last-10 average') if k in row}
    record['source_audit']={k:row[k] for k in ('Quote updated UTC','Statistics retrieved UTC','Injury source updated UTC','Injury retrieved UTC','Roster checked UTC','Player history through','NBA context checked UTC') if row.get(k) is not None}
    return record

def grade_record(record,data):
    r=dict(record)
    if r.get('result')!='Pending':return r
    competitions=data.get('header',{}).get('competitions',[])
    if not competitions or not competitions[0].get('status',{}).get('type',{}).get('completed'):return r
    if str(data.get('header',{}).get('id'))!=str(r['event_id']):raise ValueError('Game identity mismatch.')
    if r['category']=='Moneyline':
        teams=competitions[0].get('competitors',[])
        selected=[t for t in teams if t.get('team',{}).get('displayName')==r['player']]
        if len(teams)!=2 or len(selected)!=1:return r
        scores=[float(t['score']) for t in teams]
        result='Push' if scores[0]==scores[1] else 'Win' if float(selected[0]['score'])==max(scores) else 'Loss'
        odds=r['odds'];profit=odds/100 if odds>0 else 100/abs(odds)
        r.update(result=result,actual={t['team']['displayName']:t['score'] for t in teams},profit_per_1=profit if result=='Win' else -1 if result=='Loss' else 0,graded_utc=datetime.now(timezone.utc).isoformat(),grading_note='Final ESPN score; tied two-way moneyline recorded as Push. Platform rules may differ.')
        return r
    values=[]
    for team in data.get('boxscore',{}).get('players',[]):
        for group in team.get('statistics',[]):
            nba=r.get('sport')=='NBA'
            if not nba and group.get('name')!={'Passing yards':'passing','Rushing yards':'rushing','Receiving yards':'receiving','Receptions':'receiving','Passing attempts':'passing','Passing interceptions':'passing','Passing completions':'passing','Passing touchdowns':'passing','Rushing attempts':'rushing'}.get(r['category']):continue
            labels=group.get('labels',[])
            for entry in group.get('athletes',[]):
                if entry.get('athlete',{}).get('displayName')==r['player']:
                    stats=dict(zip(labels,entry.get('stats',[])))
                    label={'Points':'PTS','Rebounds':'REB','Assists':'AST','Three-pointers made':'3PT','Steals':'STL','Blocks':'BLK'}.get(r['category'],'YDS')
                    if not nba:
                        label={'Receptions':'REC','Passing attempts':'C/ATT','Passing interceptions':'INT','Passing completions':'C/ATT','Passing touchdowns':'TD','Rushing attempts':'CAR'}.get(r['category'],label)
                    if label in stats:
                        value=str(stats[label])
                        if label=='C/ATT':value=value.split('/')[0 if r['category']=='Passing completions' else -1]
                        if label=='3PT':value=value.replace('/','-').split('-')[0]
                        values.append(float(value))
                        if nba and 'MIN' in stats:
                            minute_text=str(stats['MIN'])
                            try:
                                parts=minute_text.split(':')
                                r['actual_opportunities']=float(parts[0])+float(parts[1])/60 if len(parts)==2 else float(minute_text)
                            except (ValueError,TypeError):pass
                        workload_label={'Passing yards':'C/ATT','Rushing yards':'CAR','Receiving yards':'TGTS','Passing attempts':'C/ATT','Passing interceptions':'C/ATT','Passing completions':'C/ATT','Passing touchdowns':'C/ATT','Rushing attempts':'CAR','Receptions':'TGTS'}.get(r['category'])
                        if workload_label in stats:
                            raw=str(stats[workload_label]);r['actual_opportunities']=float(raw.split('/')[-1])
    if len(values)!=1:
        r['grading_note']='Player total not uniquely reported; manual settlement review required.'
        return r
    actual=values[0];line=r['line'];win=actual<line if r['direction']=='Under' else actual>line
    result='Push' if actual==line else 'Win' if win else 'Loss'
    odds=r['odds'];profit=odds/100 if odds>0 else 100/abs(odds)
    r.update(actual=actual,result=result,profit_per_1=profit if result=='Win' else -1 if result=='Loss' else 0,graded_utc=datetime.now(timezone.utc).isoformat(),grading_note='Final ESPN statistic; platform-specific void rules and fees are not modeled.')
    if r.get('projected_count') is not None:r['count_miss']=actual-float(r['projected_count'])
    if r.get('projected_yards') is not None:r['yardage_miss']=actual-float(r['projected_yards'])
    if r.get('expected_opportunities') is not None and r.get('actual_opportunities') is not None:r['opportunity_miss']=r['actual_opportunities']-float(r['expected_opportunities'])
    return r

def grade_all(records,fetch=None):
    fetch=fetch or (lambda eid,sport:json.load(urlopen(SUMMARY.format(sport='basketball/nba' if sport=='NBA' else 'football/nfl')+eid,timeout=20)))
    cache={};out=[]
    for record in records:
        if record.get('result')!='Pending':out.append(record);continue
        eid=record['event_id'];cache_key=(record.get('sport','NFL'),eid)
        try:
            if cache_key not in cache:cache[cache_key]=fetch(eid,record.get('sport','NFL'))
            out.append(grade_record(record,cache[cache_key]))
        except (OSError,ValueError,KeyError,TypeError):out.append(dict(record,grading_note='Source unavailable or inconsistent; remains Pending. Refresh to retry.'))
    return out

def render_history(sport='NFL'):
    import streamlit as st
    from app_view import is_research
    if not is_research():
        from dashboard_history import render_public_history
        return render_public_history(sport,LEDGER)
    st.divider();st.header('Published pick history and results')
    from research_feeds import render_research_feeds
    render_research_feeds(sport)
    if sport=='NBA':
        from player_usage import render_nba_usage
        render_nba_usage()
    try:records=json.loads(Path(LEDGER).read_text())['records']
    except (OSError,ValueError,KeyError):records=[]
    st.subheader('Personal paper-pick tracking')
    st.caption('Qualifying recommendations save automatically when displayed. Permanent autosave requires PICK_HISTORY_GITHUB_TOKEN in Streamlit Secrets; the shortlist shows whether permanent storage succeeded. Session-only records need a JSON backup until setup is complete.')
    uploaded=st.file_uploader('Restore saved paper-pick JSON',type=['json'],key='personal_history_restore')
    if uploaded is not None and st.button('Restore paper-pick records',key='personal_history_restore_button'):
        try:
            clean=restore_records(json.loads(uploaded.getvalue()))
            merged_restore={r['id']:r for r in st.session_state.get('personal_paper_records',[])}
            for r in clean:merged_restore.setdefault(r['id'],r)
            st.session_state['personal_paper_records']=list(merged_restore.values())
            st.session_state.pop('ledger_live_grades',None)
            st.success('Restored. Refresh completed-game grades to verify results. Imported personal records remain user-editable evidence.')
        except (ValueError,KeyError,TypeError):st.warning('This file could not be restored as a paper-pick ledger.')
    merged={r['id']:r for r in records}
    for r in st.session_state.get('personal_paper_records',[]):merged.setdefault(r['id'],r)
    records=list(merged.values())
    from live_pick_board import render_live_board
    render_live_board(records,sport)
    st.caption('Original and cushion strategies are separate. Historical imports are labeled and excluded from the prospective record. Returns assume $1 straight bets at recorded prices, excluding fees and platform void rules. No guaranteed returns.')
    if st.button('Refresh completed-game grades',key='ledger_refresh'):
        st.session_state['ledger_live_grades']=grade_all(records)
    graded={r['id']:r for r in st.session_state.get('ledger_live_grades',[])}
    records=[graded.get(r['id'],r) for r in records]
    all_records=records
    from pick_learning import render_feedback
    render_feedback(all_records,sport)
    records=[r for r in records if r.get('sport','NFL')==sport]
    season_types=sorted({r.get('season_type','Unknown') for r in records})
    if season_types:
        if 'Regular season' in season_types:season_types.remove('Regular season');season_types.insert(0,'Regular season')
        season_type=st.selectbox('Season type — results kept separate',season_types,key='ledger_season_type_'+sport)
        records=[r for r in records if r.get('season_type','Unknown')==season_type]
    evidence=st.selectbox('Results record',['Personal paper record','Published before kickoff','Historical import'],key='ledger_evidence')
    strategy=st.selectbox('Strategy',['Original','Cushion','Manual'],key='ledger_strategy')
    selected=[r for r in records if r['evidence']==evidence and r['strategy']==strategy]
    model_choice=st.selectbox('Forecast model record',['All']+sorted({r.get('model','Unknown') for r in selected}),key='ledger_model_filter')
    if model_choice!='All':selected=[r for r in selected if r.get('model','Unknown')==model_choice]
    category=st.selectbox('Pick category',['All']+sorted({r['category'] for r in selected}),key='ledger_category')
    if category!='All':selected=[r for r in selected if r['category']==category]
    settled=[r for r in selected if r['result'] in ('Win','Loss')]
    if settled:
        wins=sum(r['result']=='Win' for r in settled);profit=sum(r['profit_per_1'] for r in settled)
        st.write(f"{wins} wins / {len(settled)-wins} losses · Net per $1 per pick: ${profit:.2f} · ROI: {profit/len(settled):.1%}")
        estimated=[r for r in settled if r.get('probability') is not None]
        if estimated:
            brier=sum((r['probability']-(r['result']=='Win'))**2 for r in estimated)/len(estimated)
            st.write(f"Probability accuracy (Brier, lower is better): {brier:.4f}")
        bins=[]
        for lo in range(0,100,10):
            group=[r for r in estimated if lo<=r['probability']*100<lo+10]
            if group:bins.append({'Probability range':f'{lo}–{lo+10}%','Picks':len(group),'Average estimate %':round(100*sum(r['probability'] for r in group)/len(group),1),'Actual win %':round(100*sum(r['result']=='Win' for r in group)/len(group),1)})
        st.dataframe(bins,hide_index=True,use_container_width=True)
    else:st.info('No settled picks in this record yet.')
    if selected:st.dataframe(selected,hide_index=True,use_container_width=True)
    with st.expander('Review forecast misses and improvement process'):
        reviewed=[r for r in settled if r.get('yardage_miss') is not None]
        if reviewed:
            st.dataframe([{'Player':r['player'],'Model':r['model'],'Result':r['result'],
                'Predicted yards':r.get('projected_yards'),'Actual yards':r['actual'],
                'Yards above/below forecast':r['yardage_miss'],'Expected opportunities':r.get('expected_opportunities'),
                'Actual opportunities':r.get('actual_opportunities'),'Opportunity miss':r.get('opportunity_miss')} for r in reviewed],hide_index=True,use_container_width=True)
        else:st.info('No graded records with saved forecast inputs yet. New saves include yardage and workload estimates; older files may lack them.')
        st.write('1. Freeze every selection before kickoff and grade wins, losses and unresolved records.\n2. Review workload, efficiency and availability errors across multiple games.\n3. Fit candidate changes on older data and evaluate later games separately.\n4. Promote only after prospective accuracy, calibration and actual-price returns support the change. Per-game feedback now updates bounded forecast and probability adjustments after grading. The original forecasts remain saved for comparison; full model retraining remains separate.')
    None

class StorageError(ValueError):
    """Safe storage diagnosis: never include response bodies, headers or tokens."""


def storage_status(response,operation):
    code=response.status_code
    if 200<=code<300:return
    if code==401:reason='GitHub rejected the token (HTTP 401). Check that the saved value is the current GitHub token, not an Odds API key, and that it has not been revoked.'
    elif code==403:
        limited=response.headers.get('x-ratelimit-remaining')=='0'
        reason='GitHub API rate limit reached (HTTP 403). Wait and retry.' if limited else 'GitHub denied access (HTTP 403). Check Contents: Read and write, repository access, and any organization approval requirements.'
    elif code==404:reason='GitHub could not access the repository or pick-history file (HTTP 404). Check that the token can access pushaman96/EdgeLabSportsAI and that published_picks.json exists on main.'
    elif code in (409,422):reason='GitHub rejected the update (HTTP '+str(code)+'). The file changed concurrently, or repository rules prevent direct writes to main.'
    elif code==429:reason='GitHub is rate limiting requests (HTTP 429). Wait and retry.'
    elif code>=500:reason='GitHub is temporarily unavailable (HTTP '+str(code)+'). Retry later.'
    else:reason='GitHub storage request failed (HTTP '+str(code)+').'
    raise StorageError(operation+': '+reason)


def persist_records(records,token,client=None,ledger=LEDGER):
    """Append frozen records; verify durable IDs without overwriting old picks."""
    if client is None:
        import requests as client
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'}
    url=f'https://api.github.com/repos/{REPO}/contents/{ledger}'
    def read():
        response=client.get(url,headers=headers,params={'ref':'main'},timeout=15)
        storage_status(response,'Reading pick history')
        payload=response.json()
        if payload.get('encoding')=='none':
            # Contents API omits base64 for larger ledgers; raw media is authenticated.
            raw=client.get(url,headers=dict(headers,Accept='application/vnd.github.raw+json'),params={'ref':'main'},timeout=15)
            storage_status(raw,'Reading large pick history');data=raw.json()
        else:data=json.loads(base64.b64decode(payload['content']))
        if not isinstance(data.get('records'),list):raise StorageError('Saved history format is invalid; existing history was not replaced.')
        return payload,data
    for attempt in range(3):
        payload,data=read()
        existing={r['id'] for r in data['records']}
        new=[];seen=set(existing)
        for record in records:
            if record['id'] not in seen:new.append(record);seen.add(record['id'])
        if not new:return 0
        data['records'].extend(new)
        response=client.put(url,headers=headers,json={'message':'Automatically save frozen pregame paper picks','branch':'main','sha':payload['sha'],'content':base64.b64encode(json.dumps(data,indent=2).encode()).decode()},timeout=20)
        if response.status_code in (409,422) and attempt<2:continue
        storage_status(response,'Writing pick history')
        _,verified=read()
        ids={r['id'] for r in verified['records']}
        if all(r['id'] in ids for r in records):return len(new)
    raise StorageError('Permanent save could not be verified after concurrent updates. Picks remain queued; retry saving.')


def sync_session_records(key_prefix='history_storage',show_success=True):
    """Retry frozen session records without new odds, analysis or publication times."""
    import streamlit as st
    import requests
    saved=st.session_state.get('personal_paper_records',[])
    if not saved:return
    confirmed=st.session_state.setdefault('autosave_permanent_ids',set())
    pending=[r for r in saved if r['id'] not in confirmed]
    if not pending:
        if show_success:st.success('Automatic permanent save confirmed for this session. Original picks stay frozen.')
        return
    try:token=st.secrets.get('PICK_HISTORY_GITHUB_TOKEN','')
    except Exception:token=''
    if not isinstance(token,str) or not token.strip():
        st.warning('Session-only save: missing top-level PICK_HISTORY_GITHUB_TOKEN in Streamlit Secrets. Keep this session open until permanent saving is confirmed.')
        return
    retry=st.button('Retry saving existing picks — 0 odds credits',key=key_prefix+'_retry')
    # Back off failed retries on ordinary reruns; the explicit button retries immediately.
    import time
    last=st.session_state.get('_pick_save_last_attempt',0)
    if not retry and time.time()-last<60:
        message=st.session_state.get('_pick_save_error')
        if message:st.warning(message)
        return
    st.session_state['_pick_save_last_attempt']=time.time()
    try:
        persist_records(pending,token.strip(),requests)
    except StorageError as exc:reason=str(exc)
    except requests.exceptions.Timeout:reason='GitHub storage request timed out. Retry; already-frozen picks will not be duplicated.'
    except requests.exceptions.RequestException:reason='Network connection to GitHub failed. Retry when the connection recovers.'
    except (ValueError,KeyError,TypeError):reason='GitHub returned an unexpected history response. Existing history was not replaced.'
    else:
        confirmed.update(r['id'] for r in pending)
        st.session_state.pop('_pick_save_error',None)
        st.session_state['_pick_save_last_attempt']=0
        st.success('Automatic permanent save confirmed. GitHub was read back to verify the saved pick IDs. Original picks remain frozen.')
        return
    message='Permanent autosave failed. '+reason+' Keep this session open; '+str(len(pending))+' frozen picks remain queued.'
    st.session_state['_pick_save_error']=message
    st.warning(message)


def publish_rows(rows,events,cushions=(),key_prefix='ledger',sport='NFL',manual=False):
    import streamlit as st
    import requests
    saved=st.session_state.setdefault('personal_paper_records',[])
    existing={r['id'] for r in saved}
    to_save=[(dict(r,Sport=sport),'Manual' if manual else 'Original') for r in rows if r.get('Decision')!='Pass']
    for c in cushions:
        if c['Cushion decision']=='Pass':continue
        original=next((r for r in rows if r['Player']==c['Player'] and r['Game']==c['Game'] and r.get('Category')==c.get('Category',r.get('Category'))),None)
        if original is None:continue
        alternate=dict(original,Decision=c['Cushion decision'],Selection=c.get('Direction',original['Selection']),Line=c['Available line'],Odds=c['Actual odds'],Sportsbook=c['Sportsbook'])
        alternate['Estimated win %']=c['Recalculated win %'];alternate['Quote updated UTC']=c['Quote updated UTC']
        alternate['Reason']=c['Reason']+' Original decision: '+original['Decision']
        alternate['Model']=original.get('Base model') or original.get('Model','Experimental')
        alternate['Base model']=alternate['Model']
        alternate['Raw estimated win %']=c['Recalculated win %']
        alternate['Feedback version']=None
        alternate['Feedback status']='Cushion strategy tracked separately; original correction not inherited'
        to_save.append((alternate,'Cushion'))
    boards={};failed=0
    for row,strategy in to_save:
        try:
            match=next((e for e in events if e['away_team']+' at '+e['home_team']==row['Game']),None)
            if not match:failed+=1;continue
            # Skip records frozen earlier in this session, including after kickoff.
            identity='|'.join([sport,match['id'],row['Player'],row['Category'],strategy,row.get('Base model') or row.get('Model','Experimental')])
            seen=st.session_state.setdefault('autosave_seen',set())
            if identity in seen:continue
            day=scoreboard_day(match['commence_time'])
            if day not in boards:
                path='basketball/nba' if sport=='NBA' else 'football/nfl'
                response=requests.get('https://site.api.espn.com/apis/site/v2/sports/'+path+'/scoreboard',params={'dates':day},timeout=15)
                response.raise_for_status();boards[day]=response.json()
            espn=next((e for e in boards[day].get('events',[]) if e.get('name')==row['Game'] and abs((utc(e['date'])-utc(match['commence_time'])).total_seconds())<3600),None)
            if not espn:failed+=1;continue
            record=make_record(row,espn['id'],match['commence_time'],strategy=strategy)
            record['season_type']='Preseason' if espn.get('season',{}).get('type')==1 else 'Regular season' if espn.get('season',{}).get('type')==2 else 'Other/unknown'
            record['evidence']='Personal paper record'
            if record['id'] not in existing:saved.append(record);existing.add(record['id'])
            seen.add(identity)
        except (requests.exceptions.RequestException,ValueError,KeyError,TypeError):failed+=1
    if failed:st.warning(f'{failed} recommendations could not be frozen. Refresh prices and analysis; no late or unverifiable pick is recorded.')
    from pick_explanations import render_explanations
    render_explanations(rows,key_prefix)
    sync_session_records(key_prefix=key_prefix+'_storage')

if __name__=='__main__':
    path=Path(LEDGER);data=json.loads(path.read_text());data['records']=grade_all(data['records']);path.write_text(json.dumps(data,indent=2)+'\n')
    from pick_learning import write_feedback
    write_feedback(data['records'])
    from forecast_tracking import grade as grade_forecasts
    forecasts=grade_forecasts()
    from workload_candidates import write_saved_reviews
    write_saved_reviews(data['records']+forecasts)
    from online_learning import write_state
    write_state(data['records']+forecasts)
    from live_usage import archive_completed_usage
    archive_completed_usage(data['records'])
    from slate_review import write_reviews
    write_reviews(data['records'])







