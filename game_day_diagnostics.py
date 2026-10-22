"""Daily software health and per-forecast historical evidence audit."""
import hashlib
import io
import json
import math
import sys
import unittest
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
PATH='game_day_diagnostics.json'
def utc(v):return datetime.fromisoformat(str(v).replace('Z','+00:00'))
def pacific_day(now):return now.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
def fingerprint(root='.'):
    root=Path(root);h=hashlib.sha256()
    files=sorted(list(root.glob('*.py'))+list((root/'tests').glob('test_*.py')))
    for p in files:h.update(str(p.relative_to(root)).encode());h.update(p.read_bytes())
    return h.hexdigest()
def load(path=PATH):
    try:return json.loads(Path(path).read_text())
    except (ValueError,OSError):return {}
def software_status(report,now=None,current_hash=None):
    now=now or datetime.now(timezone.utc)
    try:fresh=0<=(now-utc(report['checked_utc'])).total_seconds()<=10800 and report['pacific_date']==pacific_day(now)
    except (KeyError,TypeError,ValueError):fresh=False
    matches=report.get('source_hash')==(current_hash or fingerprint())
    passed=report.get('passed')is True and report.get('tests_run',0)>=200 and fresh and matches
    return {'passed':passed,'tests_run':report.get('tests_run',0),'tests_skipped':report.get('tests_skipped',0),'checked_utc':report.get('checked_utc'),'same_code':matches,'fresh_today':fresh}
def run_tests(path=PATH):
    now=datetime.now(timezone.utc)
    suite=unittest.defaultTestLoader.discover('tests',pattern='test_*.py')
    result=unittest.TextTestRunner(stream=io.StringIO(),verbosity=1).run(suite)
    report={'version':1,'checked_utc':now.isoformat(),'pacific_date':pacific_day(now),'source_hash':fingerprint(),'tests_run':result.testsRun,'tests_skipped':len(result.skipped),'passed':result.wasSuccessful() and result.testsRun>=200,'failed_tests':[str(t)for t,e in result.failures+result.errors],'scope':'Software regression tests. These are not historical games, a pick win rate or proof of profit.'}
    p=Path(path);temp=p.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2)+'\n');temp.replace(p)
    print(json.dumps(report))
    return report
def evidence(row,report=None,now=None,current_hash=None):
    now=now or datetime.now(timezone.utc)
    health=software_status(load()if report is None else report,now,current_hash)
    validation=row.get('Validation')or row.get('Validation details')or {}
    passed=validation.get('passed')is True or validation.get('forecast_passed')is True
    calibration=validation.get('calibration_examples')
    later=validation.get('validation_games',validation.get('test_count',validation.get('validation_examples')))
    try:quote_fresh=0<=(now-utc(row['Quote updated UTC'])).total_seconds()<=900
    except (KeyError,ValueError,TypeError):quote_fresh=False
    p=row.get('Estimated win %',row.get('Model win %'))
    valid_probability=isinstance(p,(int,float))and not isinstance(p,bool)and math.isfinite(p)and 0<p<100
    issues=[]
    if not health['passed']:issues.append('Daily software diagnostic is missing, stale, failed or from different code')
    if not passed:issues.append('Category historical baseline pass is missing or failed')
    if not quote_fresh:issues.append('Quote is older than 15 minutes or its time is unknown')
    if not valid_probability:issues.append('Usable forecast probability is unavailable')
    if row.get('Category'):
        from market_reasoning import analysis
        if not analysis(row)['supported']:issues.append('Exact market category, selection or line is unsupported or invalid')
    ready=not issues and row.get('Decision')!='Pass'
    return {'version':1,'checked_utc':now.isoformat(),'ready':ready,'software':health,'category_baseline_passed':passed,'earlier_calibration_examples':calibration,'later_historical_games_or_examples':later,'historical_scope':validation.get('scope',validation.get('split_method','See frozen model validation')),'quote_fresh':quote_fresh,'model_qualified':row.get('Decision')!='Pass','issues':issues,'interpretation':'Counts are reported as measured; software tests and historical games are different. Correlated props are not independent games. Diagnostics do not guarantee a winning bet.'}
def apply(rows,sport,now=None):
    report=load();source=fingerprint();now=now or datetime.now(timezone.utc);output=[]
    for original in rows:
        from selection_policy import annotate
        from matchup_homework import dossier
        row=annotate(original);row['Homework']=dossier(row,sport)
        row['Selection policy']='probability-first-v2'
        probability=row.get('Estimated win %')
        if row.get('Decision')!='Pass' and (not isinstance(probability,(int,float)) or not math.isfinite(probability) or probability<=50):
            row['Decision']='Pass';row['Reason']='No majority-probability outcome is supported by this forecast.'
        audit=evidence(row,report,now,source);row['Game-day diagnostic']=audit
        if row.get('Decision')!='Pass'and not audit['ready']:
            row['Decision']='Pass';row['Reason']='Game-day diagnostic: '+'; '.join(audit['issues'])
        output.append(annotate(row))
    from market_reasoning import apply as explain_markets
    return explain_markets(output,sport)
def render(sport):
    import streamlit as st
    health=software_status(load())
    with st.expander('Game-day diagnostic — tests and research readiness',expanded=not health['passed']):
        if health['passed']:st.success('Current code passed today’s software checks.')
        else:st.info('Waiting for a current successful background diagnostic before issuing new model recommendations.')
        st.write({'Software tests run':health['tests_run'],'Optional tests skipped':health['tests_skipped'],'Last check UTC':health['checked_utc'],'Same code':health['same_code'],'Fresh today':health['fresh_today']})
        st.caption('Historical calibration and later-game baseline results are checked per forecast and saved with it. These counts appear in the pick explanation. Repeating the same tests does not create independent prediction evidence. Source and quote checks still run when forecasts are issued.')
if __name__=='__main__':
    sys.exit(0 if run_tests()['passed']else 1)


