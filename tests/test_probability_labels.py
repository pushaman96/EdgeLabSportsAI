import unittest
from probability_labels import indicator, decorate, grouped

class ProbabilityLabelsTests(unittest.TestCase):
    def test_threshold_and_units(self):
        self.assertEqual(indicator(.60)['group'], 'High probability')
        self.assertEqual(indicator(59.9, percent=True)['group'], 'Low probability')
        self.assertIn('65.0%', indicator(.65)['label'])
        self.assertEqual(indicator(0)['group'], 'Low probability')
        self.assertEqual(indicator(1)['group'], 'High probability')
    def test_invalid_not_low(self):
        for value in (None, True, float('nan'), float('inf'), -1, 65):
            self.assertEqual(indicator(value)['group'], 'Probability unavailable')
    def test_display_copies_do_not_mutate(self):
        row={'Estimated win %':65, 'Decision':'Pass'}
        copy=decorate(row)
        self.assertEqual(row, {'Estimated win %':65, 'Decision':'Pass'})
        self.assertEqual(copy['Decision'], 'Pass')
        self.assertIn('High probability',copy['Probability indicator'])
    def test_grouping_and_order(self):
        rows=[{'Frozen model probability %':55},{'Frozen model probability %':70},{'Frozen model probability %':None},{'Frozen model probability %':80}]
        result=grouped(rows)
        self.assertEqual([r['Frozen model probability %'] for r in result['High probability']],[80,70])
        self.assertEqual(len(result['Low probability']),1)
        self.assertEqual(len(result['Probability unavailable']),1)
        self.assertNotIn('Probability indicator',rows[0])
