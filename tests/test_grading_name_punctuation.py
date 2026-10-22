import copy
import unittest
from pick_history import grade_record


class GradingNames(unittest.TestCase):
    def record(self):
        return dict(event_id='game',sport='NBA',player='Wendell Carter Jr',
                    category='Three-pointers made',direction='Over',line=.5,
                    odds=-130,result='Pending',projected_count=.92)

    def summary(self, entries):
        return {'header':{'id':'game','competitions':[{'status':{'type':{'completed':True}}}]},
                'boxscore':{'players':[{'statistics':[{'labels':['MIN','3PT'], 'athletes':entries}]}]}}

    def athlete(self, name='Wendell Carter Jr.'):
        return {'athlete':{'displayName':name},'stats':['31','1-3']}

    def test_suffix_punctuation_grades_win_without_changing_frozen_pick(self):
        r=self.record();before=copy.deepcopy(r)
        graded=grade_record(r,self.summary([self.athlete()]))
        self.assertEqual(graded['result'],'Win')
        self.assertEqual(graded['actual'],1)
        self.assertEqual(graded['actual_opportunities'],31)
        self.assertEqual(r,before)
        self.assertEqual(graded['player'],r['player'])

    def test_ambiguous_match_stays_pending(self):
        graded=grade_record(self.record(),self.summary([self.athlete(),self.athlete('Wendell Carter Jr')]))
        self.assertEqual(graded['result'],'Pending')

    def test_different_player_and_missing_statistics_stay_pending(self):
        for entries in ([self.athlete('Jevon Carter')],[dict(self.athlete(),stats=[])],[]):
            self.assertEqual(grade_record(self.record(),self.summary(entries))['result'],'Pending')

    def test_unfinished_game_stays_pending(self):
        data=self.summary([self.athlete()])
        data['header']['competitions'][0]['status']['type']['completed']=False
        self.assertEqual(grade_record(self.record(),data)['result'],'Pending')
