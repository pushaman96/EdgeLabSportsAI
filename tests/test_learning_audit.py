import unittest
from learning_audit import audit_rows

class LearningAuditTests(unittest.TestCase):
    def test_unmeasured_update_is_not_improvement(self):
        state={'groups':{'["NFL","model","Passing yards","Regular season"]':{'games':7,'bias':.01,'workload_bias':.04,'issued_comparisons':0}}}
        row=audit_rows(state,'NFL')[0]
        self.assertEqual(row['Workload adjustment %'],4)
        self.assertIsNone(row['Adjusted minus base Brier'])
        self.assertIn('No completed',row['Evidence status'])
        self.assertEqual(audit_rows(state,'NBA'),[])
    def test_actual_frozen_comparison_and_damping_visible(self):
        state={'groups':{'["NFL","model","Passing yards","Regular season"]':{'issued_comparisons':2,'base_brier_sum':.6,'issued_brier_sum':.4,'application_weight':.5}}}
        row=audit_rows(state,'NFL')[0]
        self.assertAlmostEqual(row['Adjusted minus base Brier'],-.1)
        self.assertEqual(row['Application weight'],.5)
        self.assertIn('not proof',row['Evidence status'])

if __name__=='__main__':unittest.main()
