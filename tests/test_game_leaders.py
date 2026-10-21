"""Load only the pure parser: importing app.py would execute the UI."""
import ast
from pathlib import Path
import unittest

tree=ast.parse((Path(__file__).resolve().parents[1]/'app.py').read_text())
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='game_leader_rows')
namespace={}
exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),namespace)
parse=namespace['game_leader_rows']

class GameLeaderTests(unittest.TestCase):
    def category(self,value='24'):
        return {'name':'points','displayName':'Points','leaders':[{'athlete':{'id':'p','displayName':'Player'},'displayValue':value}]}
    def test_per_team_scoreboard_leaders(self):
        competition={'competitors':[{'team':{'id':'1','displayName':'Home'},'leaders':[self.category()]},
                                    {'team':{'id':'2','displayName':'Away'},'leaders':[self.category('18')]}]}
        rows=parse(competition)
        self.assertEqual(len(rows),2)
        self.assertEqual([(r['Team'],r['Game stats']) for r in rows],[('Home','24'),('Away','18')])
    def test_summary_fallback_when_scoreboard_empty(self):
        summary={'leaders':[{'team':{'id':'1','displayName':'Home'},'leaders':[self.category()]}]}
        self.assertEqual(parse({},summary)[0]['Team'],'Home')
    def test_legacy_top_level_and_duplicate_rows(self):
        c=self.category()
        c['leaders'][0]['team']={'id':'1'}
        competition={'leaders':[c],'competitors':[{'team':{'id':'1','displayName':'Home'},'leaders':[c]}]}
        self.assertEqual(len(parse(competition)),1)
        self.assertEqual(parse(competition)[0]['Team'],'Home')
    def test_missing_values_not_zero_but_reported_zero_preserved(self):
        for missing in (None,'','--','—'):
            self.assertEqual(parse({'leaders':[self.category(missing)]}),[])
        self.assertEqual(parse({'leaders':[self.category('0')]})[0]['Game stats'],'0')
    def test_empty_summary_and_unidentified_players(self):
        self.assertEqual(parse({},{}),[])
        c=self.category();c['leaders'][0]['athlete']={}
        self.assertEqual(parse({'leaders':[c]}),[])

if __name__=='__main__':unittest.main()
