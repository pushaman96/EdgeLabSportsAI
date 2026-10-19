"""Automatic slate-level review of frozen picks. No unvalidated model fitting."""
import json,math
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
PATH='slate_reviews.json'
PACIFIC=ZoneInfo('America/Los_Angeles')
def number(v):
    try:
        n=float(v);return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None

def eligible(r):
    if r.get('strategy')!='Original' or r.get('evidence') not in ('Published before kickoff','Personal paper record') or r.get('season_type')!='Regular season':return False
    try:return datetime.fromisoformat(r['published_utc'].replace('Z','+00:00'))<datetime.fromisoformat(r['starts_utc'].replace('Z','+00:00'))
    except (KeyError,ValueError,TypeError):return False

def metrics(rows):
    settled=[r for r in rows if r.get('result') in ('Win','Loss')];wins=sum(r['result']=='Win' for r in settled)
    probabilities=[(number(r.get('probability')),int(r['result']=='Win')) for r in settled]
    probabilities=[(p,y) for p,y in probabilities if p is not None and 0<p<1]
    profit=[number(r.get('profit_per_1')) for r in settled]
    return {'picks':len(rows),'settled':len(settled),'wins':wins,'losses':len(settled)-wins,'pending':sum(r.get('result')=='Pending' for r in rows),'pushes':sum(r.get('result')=='Push' for r in rows),'distinct_games':len({r['event_id'] for r in rows}),'accuracy':wins/len(settled) if settled else None,'brier':sum((p-y)**2 for p,y in probabilities)/len(probabilities) if probabilities else None,'mean_estimated_probability':sum(p for p,y in probabilities)/len(probabilities) if probabilities else None,'profit_per_1_each':sum(profit) if settled and all(v is not None for v in profit) else None}

def build_reviews(records,usage=None,feedback=None):
    usage=usage or {};feedback=feedback or {};groups=defaultdict(list);seen=set()
    for r in records:
        if not eligible(r) or r.get('id') in seen:continue
        seen.add(r.get('id'))
        day=datetime.fromisoformat(r['starts_utc'].replace('Z','+00:00')).astimezone(PACIFIC).date().isoformat()
        groups[(r.get('sport','NFL'),day)].append(r)
    reports={}
    for (sport,day),rows in sorted(groups.items()):
        result=metrics(rows);categories=[]
        for category in sorted({r['category'] for r in rows}):categories.append({'category':category,**metrics([r for r in rows if r['category']==category])})
        known_final=set()
        for r in rows:
            key=('NBA:' if sport=='NBA' else '')+str(r['event_id'])
            if usage.get('games',{}).get(key,{}).get('completed') or r.get('result') in ('Win','Loss','Push'):known_final.add(str(r['event_id']))
        all_final=len(known_final)==result['distinct_games']
        workload=[];yardage=[];count=[];missing=0
        for r in rows:
            if r.get('result') not in ('Win','Loss','Push'):continue
            expected=number(r.get('expected_opportunities'));actual=number(r.get('actual_opportunities'))
            observed=number(r.get('actual'));projection=number(r.get('projected_yards'));count_projection=number(r.get('projected_count'))
            if expected is not None and actual is not None:workload.append(actual-expected)
            if observed is not None and projection is not None:yardage.append(observed-projection)
            if observed is not None and count_projection is not None:count.append(observed-count_projection)
            if expected is None or actual is None:missing+=1
        calibration=[]
        for low,high in ((0,.5),(.5,.6),(.6,.7),(.7,.8),(.8,1)):
            bucket=[r for r in rows if r.get('result') in ('Win','Loss') and number(r.get('probability')) is not None and low<=float(r['probability'])<high]
            if bucket:calibration.append({'Probability band':f'{low:.0%}–{high:.0%}','Settled picks':len(bucket),'Mean estimate %':round(100*sum(r['probability'] for r in bucket)/len(bucket),1),'Actual win %':round(100*sum(r['result']=='Win' for r in bucket)/len(bucket),1)})
        flow=defaultdict(lambda:{'Passing attempts':0,'Rushing plays':0,'Sacks':0})
        covered=set()
        for eid in {str(r['event_id']) for r in rows}:
            game=usage.get('games',{}).get(('NBA:' if sport=='NBA' else '')+eid,{})
            script=game.get('game_script',{})
            reconciled={r['Team'] for r in script.get('attempt_totals',[]) if r.get('Coverage')=='Reconciled with box score'}
            covered.update((eid,team) for team in reconciled)
            for situation in script.get('score_states',[]):
                if situation.get('Team') not in reconciled:continue
                key=(situation.get('Phase','Unknown'),situation.get('Score before play','Unknown'))
                for field in ('Passing attempts','Rushing plays','Sacks'):flow[key][field]+=number(situation.get(field)) or 0
        flow_rows=[{'Phase':key[0],'Score situation':key[1],**counts} for key,counts in sorted(flow.items())]
        observations=[]
        if workload:observations.append(f'Across {len(workload)} picks with saved workload and observed opportunities, average actual minus expected workload was {sum(workload)/len(workload):+.1f}. Correlated picks are included; this does not prove a cause.')
        if yardage:observations.append(f'Across {len(yardage)} yardage forecasts, mean absolute yardage error was {sum(abs(v) for v in yardage)/len(yardage):.1f}; signed error was {sum(yardage)/len(yardage):+.1f}. A correct betting direction can still have a large yardage miss.')
        if count:observations.append(f'Across {len(count)} count forecasts, mean absolute count error was {sum(abs(v) for v in count)/len(count):.1f}.')
        if missing:observations.append(f'{missing} settled picks lack a complete saved workload comparison; the missing cause is not inferred.')
        if any(r['category']=='Moneyline' for r in rows):observations.append('Moneylines use historical team ratings. Injury effects, replacements and offensive-line changes are not numerically modeled; review availability warnings separately.')
        observations.append('Review run/pass situations and overtime alongside workload errors. Score-state associations do not establish why a forecast missed. Test opportunity and uncertainty changes on older games, then validate later games before promotion.')
        reports[sport+':'+day]={'sport':sport,'date':day,'stage':('All games final — unresolved picks need review' if result['pending'] else 'Completed slate review') if all_final else 'Partial slate — games remain unfinished or unavailable','all_games_final':all_final,'metrics':result,'categories':categories,'calibration':calibration,'game_flow_context':flow_rows,'reconciled_team_games':len(covered),'observations':observations,'active_corrections':feedback.get('active_corrections',0),'learning_status':'Results enter existing outcome-feedback tests. Corrections require at least 100 eligible picks and 30 distinct games per model/category/direction/strategy, plus later-game validation. Workload retraining and causal diagnosis are not automatic.'}
    return {'schema':1,'reports':reports}

def write_reviews(records,path=PATH,usage_path='game_usage_history.json',feedback_path='pick_learning_state.json'):
    def read(p):
        try:return json.loads(Path(p).read_text())
        except (OSError,ValueError):return {}
    result=build_reviews(records,read(usage_path),read(feedback_path));target=Path(path)
    previous=read(path);comparable={k:v for k,v in previous.items() if k!='updated_utc'}
    if comparable==result:return previous
    result['updated_utc']=datetime.now(timezone.utc).isoformat()
    temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(result,indent=2)+'\n');temporary.replace(target)
    return result

def render_review(sport,records):
    import streamlit as st
    from pick_learning import diagnostics
    try:saved=json.loads(Path(PATH).read_text());reports=[r for r in saved.get('reports',{}).values() if r['sport']==sport]
    except (OSError,ValueError,KeyError):reports=[];saved={}
    with st.expander('Postgame review — results, misses and learning'):
        if not reports:st.info('The scheduled review appears after the next grading run. It requires no Odds API credits.');return
        report=st.selectbox('Review game date',sorted(reports,key=lambda r:r['date'],reverse=True),format_func=lambda r:r['date'],key='slate_review_date_'+sport)
        st.write('**'+report['stage']+'**');m=report['metrics']
        st.write(f"{m['wins']} wins · {m['losses']} losses · {m['pending']} pending · {m['distinct_games']} games")
        st.caption('Original pregame regular-season records only. Cushions, manual picks and retrospective imports are excluded. Same-game/player picks are correlated.')
        st.dataframe(report['categories'],hide_index=True,use_container_width=True)
        if report['calibration']:st.dataframe(report['calibration'],hide_index=True,use_container_width=True)
        for note in report['observations']:st.write(note)
        if report.get('game_flow_context'):
            st.write('**Game-flow context from reconciled play feeds**')
            st.dataframe(report['game_flow_context'],hide_index=True,use_container_width=True)
            st.caption(f"Available plays across {report.get('reconciled_team_games',0)} team-games whose passing attempts reconcile with the box score. Descriptive context, not proof of a forecast cause.")
        matching=[r for r in records if eligible(r) and r.get('sport','NFL')==sport and datetime.fromisoformat(r['starts_utc'].replace('Z','+00:00')).astimezone(PACIFIC).date().isoformat()==report['date']]
        reviewed=diagnostics(matching)
        if reviewed:st.dataframe(reviewed,hide_index=True,use_container_width=True)
        st.caption(report['learning_status'])
        st.caption('Review updated UTC: '+saved.get('updated_utc','Unknown'))
