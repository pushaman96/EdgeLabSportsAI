import unittest
from paired_forecasts import capture,summary
class PairedTests(unittest.TestCase):
    def row(self,**kw):
        r=dict(id='a',sport='NFL',strategy='Analysis',evidence='Personal paper record',season_type='Regular season',published_utc='2026-10-18T12:00:00Z',starts_utc='2026-10-18T17:00:00Z',event_id='g',player='P',category='Passing yards',model='m',result='Win',actual=100,actual_opportunities=None,paired_forecast=dict(version=1,base_projection=80,issued_projection=90,base_probability=.6,issued_probability=.7))
        r.update(kw);return r
    def test_actual_issued_not_hypothetical_candidate(self):
        p=capture({'Base projection':80,'Projection (yards)':90,'Candidate projection':120,'Estimated win %':60})
        self.assertEqual(p['issued_projection'],90)
        self.assertIsNone(p['base_probability'])
    def test_passes_paired_missing_and_duplicates(self):
        rows=summary([self.row(),self.row(id='b')],'NFL')
        self.assertEqual(rows[0]['Projection MAE comparisons'],1)
        self.assertEqual(rows[0]['Issued minus base Projection MAE'],-10)
        self.assertEqual(rows[0]['Workload MAE comparisons'],0)
        self.assertEqual(summary([self.row(strategy='Cushion')],'NFL'),[])
    def test_missing_or_late_not_zero(self):
        self.assertEqual(summary([self.row(published_utc='2026-10-18T18:00:00Z')],'NFL'),[])
        row=summary([self.row(actual=None,result='Pending')],'NFL')[0]
        self.assertIsNone(row['Base Projection MAE'])
    def test_push_has_stat_error_not_brier(self):
        row=summary([self.row(result='Push')],'NFL')[0]
        self.assertEqual(row['Projection MAE comparisons'],1)
        self.assertEqual(row['Brier comparisons'],0)
if __name__=='__main__':unittest.main()
