"""Automatic durable copies of report data; frozen betting picks stay in their ledger."""
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

REPO='pushaman96/EdgeLabSportsAI'

def report_path(file_name):
    if Path(file_name).name!=file_name:raise ValueError('Invalid report name')
    return 'app_archives/'+file_name+'.json'

def load_report(file_name):
    """Restore the most recent report installed with the app's repository."""
    try:return json.loads(Path(report_path(file_name)).read_text())['data']
    except (OSError,ValueError,KeyError):return None

def save_report(data,file_name,mime,token,client):
    path=report_path(file_name)
    digest=hashlib.sha256(data.encode()).hexdigest()
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'}
    url=f'https://api.github.com/repos/{REPO}/contents/{path}'
    for attempt in range(3):
        response=client.get(url,headers=headers,params={'ref':'main'},timeout=15)
        sha=None
        if response.status_code!=404:
            response.raise_for_status();payload=response.json();sha=payload['sha']
            prior=json.loads(base64.b64decode(payload['content']))
            if prior.get('digest')==digest:return digest
        document={'schema':1,'file_name':file_name,'mime':mime,'digest':digest,'saved_utc':datetime.now(timezone.utc).isoformat(),'data':data,'purpose':'Latest report snapshot; not independently verified training evidence. Frozen selections remain in published_picks.json.'}
        body={'message':'Automatically save app report','branch':'main','content':base64.b64encode(json.dumps(document).encode()).decode()}
        if sha:body['sha']=sha
        response=client.put(url,headers=headers,json=body,timeout=20)
        if response.status_code in (409,422):continue
        response.raise_for_status()
        local=Path(path);local.parent.mkdir(parents=True,exist_ok=True);local.write_text(json.dumps(document))
        return digest
    raise ValueError('Concurrent report update; retry required')

def autosave_report(label,data,file_name,mime='text/plain',key=None,**kwargs):
    import streamlit as st
    import requests
    if isinstance(data,bytes):data=data.decode('utf-8')
    digest=hashlib.sha256(data.encode()).hexdigest()
    confirmed=st.session_state.setdefault('automatic_report_digests',{})
    if confirmed.get(file_name)==digest:return
    try:
        token=st.secrets.get('PICK_HISTORY_GITHUB_TOKEN','')
        if not isinstance(token,str) or not token.strip():
            st.warning('Automatic report saving needs PICK_HISTORY_GITHUB_TOKEN in this app’s Secrets. This report is not permanently saved yet.');return
        confirmed[file_name]=save_report(data,file_name,mime,token.strip(),requests)
    except Exception:
        st.warning('Automatic report save has not succeeded. The app will retry when this section runs again. Check permanent-storage settings; do not share your token.')
        return
    st.caption('Report saved automatically. Original recommended picks remain frozen in pick history.')
