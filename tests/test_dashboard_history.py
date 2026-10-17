import json
import tempfile
import unittest
from pathlib import Path
from dashboard_history import accuracy_summary, tracked_records

class DashboardHistoryTests(unittest.TestCase):
    def test_accuracy_keeps_sports_strategies_and_unsettled_separate(self):
        base=dict(sport='NFL',evidence='Published before kickoff',strategy='Original',season_type='Regular season',probability=.7,result='Win')
        rows=[base,dict(base,result='Loss',probability=.6)]
        rows += [dict(base,**change) for change in [dict(sport='NBA'),dict(strategy='Cushion'),dict(result='Pending'),dict(evidence='Historical import'),dict(season_type='Preseason')]]
        result=accuracy_summary(rows,'NFL')
        self.assertEqual(result['settled'],2)
        self.assertEqual(result['accuracy'],.5)
        self.assertAlmostEqual(result['brier'],.225)
    def test_merge_preserves_frozen_picks_and_applies_live_grades(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'picks.json'
            original=dict(id='one',line=90.5,result='Pending')
            path.write_text(json.dumps(dict(records=[original])))
            rows=tracked_records(path,[dict(original,line=89.5),dict(id='two')],[dict(original,result='Win')])
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['line'],90.5)
            self.assertEqual(rows[0]['result'],'Win')
            self.assertEqual(json.loads(path.read_text())['records'][0],original)
    def test_empty_accuracy_has_no_fabricated_zero(self):
        result=accuracy_summary([],'NBA')
        self.assertIsNone(result['accuracy'])
        self.assertIsNone(result['brier'])

if __name__=='__main__':unittest.main()
