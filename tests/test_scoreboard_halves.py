import unittest
from half_possession import scoreboard_halves
class ScoreboardHalfTests(unittest.TestCase):
    def test_started_games_only_shared_fetch_and_identity_validation(self):
        board={'events':[{'id':'live','status':{'type':{'state':'in'}}},{'id':'live','status':{'type':{'state':'in'}}},{'id':'future','status':{'type':{'state':'pre'}}}]}
        calls=[]
        def fetch(eid):calls.append(eid);return {'data':{'header':{'id':'wrong'}}}
        results=scoreboard_halves(board,fetch)
        self.assertEqual(calls,['live'])
        self.assertEqual(results['live']['Opening kickoff by'],'Not reported')
    def test_source_failure_is_unknown(self):
        def fail(eid):raise OSError('Fixture failure')
        result=scoreboard_halves({'events':[{'id':'g','status':{'type':{'state':'post'}}}]},fail)
        self.assertEqual(result['g']['Second-half start'],'Not confirmed')
