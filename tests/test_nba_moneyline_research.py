import unittest
from datetime import date,timedelta
from nba_moneyline_research import merge_completed,history_ready

class MoneylineHistoryTests(unittest.TestCase):
    def event(self,day='2026-10-20T23:00Z',complete=True,kind=2):
        return {'date':day,'season':{'year':2027,'type':kind},'competitions':[{'status':{'type':{'completed':complete}},'competitors':[{'homeAway':'home','team':{'abbreviation':'NY'},'score':'110'},{'homeAway':'away','team':{'abbreviation':'GS'},'score':'100'}]}]}
    def test_only_verified_completed_prior_regular_games_and_aliases(self):
        today=date(2026,10,22)
        events=[self.event(),self.event(complete=False),self.event(kind=1),self.event(day='2026-10-22T23:00Z')]
        rows=merge_completed([], [{'events':events}],2027,today)
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['home_team'],rows[0]['away_team']),('NYK','GSW'))
        self.assertEqual(merge_completed([], [{'events':events}],2026,today),[])
    def test_missing_scores_are_excluded_and_input_is_not_mutated(self):
        event=self.event();del event['competitions'][0]['competitors'][0]['score']
        base=[dict(date=date(2026,10,20),season=2027,home_team='NYK',away_team='GSW',home_score=99,away_score=98)]
        rows=merge_completed(base,[{'events':[event,self.event()]}],2027,date(2026,10,22))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['home_score'],110)
        self.assertEqual(base[0]['home_score'],99)
    def test_opening_prior_labeled_and_stale_rejected(self):
        today=date(2026,10,22)
        prior=[dict(date=date(2026,4,15)-timedelta(days=i),season=2026)for i in range(100)]
        ready,label=history_ready(prior,2027,today)
        self.assertTrue(ready);self.assertIn('roster changes are not numerically modeled',label)
        self.assertFalse(history_ready(prior,2027,date(2027,2,1))[0])
        self.assertFalse(history_ready(prior[:99],2027,today)[0])

class MoneylineAutoTests(unittest.TestCase):
    def test_loaded_quotes_analyzed_once_without_odds_request(self):
        import ast,sys,types
        from pathlib import Path
        from datetime import datetime,timezone
        from unittest.mock import patch
        class UI:
            def __init__(self):self.session_state={}
            def button(self,*a,**k):return False
            def __getattr__(self,name):return lambda *a,**k:None
        node=next(n for n in ast.parse(Path('sportsbook_tools.py').read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='render_moneyline_shortlist')
        ui=UI();calls=[];archives=[]
        ns=dict(st=ui,datetime=datetime,timezone=timezone,moneyline_reviews=lambda *a,**k:[],render_team_table=lambda *a,**k:None)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'moneyline','exec'),ns)
        diagnostic=types.ModuleType('game_day_diagnostics');diagnostic.apply=lambda rows,sport:rows
        tracking=types.ModuleType('forecast_tracking');tracking.archive=lambda *a:archives.append(a)
        events=[{'id':'e','bookmakers':[{'title':'Book','markets':[{'key':'h2h','last_update':'2026-10-22T00:00Z'}]}]}]
        def model(*a):calls.append(a);return {}
        with patch.dict(sys.modules,{'game_day_diagnostics':diagnostic,'forecast_tracking':tracking}):
            for _ in range(2):ns['render_moneyline_shortlist']('NBA',events,{},model,date(2026,10,22),['Book'])
        self.assertEqual(len(calls),1);self.assertEqual(len(archives),1)
        self.assertEqual(ui.session_state['moneyline_history_candidates'][4],'NBA')
