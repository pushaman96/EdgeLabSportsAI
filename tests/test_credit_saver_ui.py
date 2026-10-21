"""Exercise request boundaries without contacting any odds provider."""
import ast,types,unittest
import sys
from unittest.mock import patch
from pathlib import Path
from datetime import datetime,timezone,timedelta
from zoneinfo import ZoneInfo
from credit_saver import spending_allowed,choose_targets,balance_record
from odds_changes import estimated_credits
from sportsbook_presets import STANDARD_PRESETS
class Context:
    def __enter__(self):return self
    def __exit__(self,*a):pass
class UI:
    def __init__(self,mode,remaining):
        self.mode=mode;self.remaining=remaining;self.session_state={};self.budget=3
    def radio(self,*a,**k):return self.mode
    def number_input(self,*a,**k):return self.budget
    def button(self,label,**k):return k.get('key')=='sportsbook_props_all_load' and not k.get('disabled')
    def text_input(self,*a,**k):return 'fixture'
    def selectbox(self,label,options,index=0,**k):return options[1] if k.get('key')=='sportsbook_source' else options[index]
    def multiselect(self,label,options,default=None,**k):
        if k.get('key')=='credit_saver_games_NFL':return options[:1]
        return self.session_state.get(k.get('key'),default)
    def checkbox(self,*a,**k):return False
    def expander(self,*a,**k):return Context()
    def spinner(self,*a,**k):return Context()
    def __getattr__(self,name):return lambda *a,**k:None
class SaverUITests(unittest.TestCase):
    def run_ui(self,mode,remaining):
        ui=UI(mode,remaining);requests=[]
        start=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=18).isoformat()
        events=[dict(id=str(i),away_team='Away'+str(i),home_team='Home'+str(i),commence_time=start,bookmakers=[{'title':'Book'}]) for i in range(2)]
        ui.session_state['sportsbook_result']=('NFL','fixture',dict(data=events,remaining=remaining,cost='3',retrieved=datetime.now(timezone.utc).isoformat()))
        ui.session_state['sportsbook_props_categories_NFL']=['Passing yards','Rushing yards']
        def odds(*args,**kw):requests.append('bulk');raise AssertionError('Unexpected bulk request')
        odds.clear=lambda:None
        def batch(key,sport,targets,markets):
            requests.extend(e['id'] for e in targets)
            return dict(results=[dict(data=e) for e in targets],remaining='90',loaded=datetime.now(timezone.utc).isoformat(),failures=[])
        source=Path('saving_new.py')
        if not source.exists():source=Path('sportsbook_tools.py')
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='render_sportsbooks')
        ns=dict(st=ui,SPORT_KEYS={'NFL':'nfl'},PROP_MARKETS={'NFL':{'Passing yards':'pass','Rushing yards':'rush','Anytime touchdown scorer':'td'}},STANDARD_PRESETS=STANDARD_PRESETS,spending_allowed=spending_allowed,choose_targets=choose_targets,balance_record=balance_record,datetime=datetime,timezone=timezone,estimated_credits=estimated_credits,odds_request=odds,load_all_prop_lines=batch,numeric=lambda x:float(x) if x is not None else None,pacific=lambda value:datetime.fromisoformat(value).astimezone(ZoneInfo('America/Los_Angeles')),render_team_table=lambda *a,**k:None,bookmaker_rows=lambda *a:[],render_changes=lambda *a:None,render_prop_market_board=lambda *a:None,render_prop_research=lambda *a,**k:None,OddsSourceError=RuntimeError,requests=types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=RuntimeError)))
        exec(compile(ast.Module(body=[node],type_ignores=[]),'render','exec'),ns)
        ns['render_sportsbooks']('NFL',datetime.fromisoformat(start).astimezone(ZoneInfo('America/Los_Angeles')).date(),{},lambda *a:{})
        return requests
    def test_saved_only_and_zero_balance_never_load_new_odds(self):
        self.assertEqual(self.run_ui('Saved data only — 0 credits','100'),[])
        self.assertEqual(self.run_ui('Credit-saving mode','0'),[])
    def test_saver_requests_only_the_selected_game(self):
        self.assertEqual(self.run_ui('Credit-saving mode','100'),['0'])
    def test_cached_presets_without_session_planner_does_not_crash(self):
        old=types.ModuleType('sportsbook_presets')
        old.STANDARD_PRESETS=STANDARD_PRESETS
        with patch.dict(sys.modules,{'sportsbook_presets':old}):
            self.assertEqual(self.run_ui('Saved data only — 0 credits','100'),[])
            self.assertEqual(self.run_ui('Credit-saving mode','100'),['0'])
