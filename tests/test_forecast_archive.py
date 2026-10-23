import unittest
from forecast_archive import partitions,flush

class ForecastArchiveTests(unittest.TestCase):
    def test_small_game_scoped_partitions(self):
        rows=[dict(id=str(i),event_id='123',sport='NBA') for i in range(30)]
        result=partitions(rows)
        self.assertLessEqual(len(result),4)
        self.assertEqual(sum(map(len,result.values())),30)
        self.assertTrue(all(p.startswith('forecast_analysis/NBA_123_') for p in result))
    def test_partial_save_keeps_unconfirmed_pending(self):
        rows=[dict(id=str(i),event_id='123',sport='NBA') for i in range(30)]
        pending={r['id']:r for r in rows};confirmed=set();calls=[]
        def writer(records,*args,**kwargs):
            calls.append(kwargs)
            if len(calls)==2:raise ValueError('test failure')
        with self.assertRaises(ValueError):flush(pending,confirmed,'fixture',None,writer)
        self.assertTrue(confirmed)
        self.assertTrue(pending)
        self.assertEqual(len(pending)+len(confirmed),30)
        self.assertTrue(all(c['allow_create'] for c in calls))
    def test_idempotent_verified_save(self):
        pending={'a':dict(id='a',event_id='123',sport='NFL')};confirmed=set()
        self.assertEqual(flush(pending,confirmed,'fixture',None,lambda *a,**k:0),1)
        self.assertEqual(pending,{})
        self.assertEqual(confirmed,{'a'})
    def test_unsafe_identity_rejected(self):
        with self.assertRaises(ValueError):partitions([dict(id='a',event_id='../bad',sport='NFL')])
