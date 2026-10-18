import unittest
from pick_presentation import result_indicator
class ResultIndicatorTests(unittest.TestCase):
    def test_final_win_loss_and_push_marks(self):
        self.assertEqual(result_indicator({'Final result':'Win'}),'✅ Win')
        self.assertEqual(result_indicator({'Final result':'Loss'}),'❌ Loss')
        self.assertEqual(result_indicator({'Final result':'Push'}),'➖ Push')
    def test_live_under_and_missing_stat_never_marked_win(self):
        self.assertEqual(result_indicator({'Final result':'Pending','Live position':'Below line — game ongoing'}),'⏳ Pending')
        self.assertEqual(result_indicator({'Final result':'Pending','Live position':'Final — stat missing; settlement review needed'}),'⏳ Pending')
