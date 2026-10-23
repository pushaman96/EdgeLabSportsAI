import unittest
from secondary_settlement import archive_summary
from pick_history import grade_record

def record(**kw):
    return dict(dict(id='p',event_id='123',sport='NBA',game='Cleveland Cavaliers at Philadelphia 76ers',starts_utc='2026-10-22T23:00:00Z',player='Player',category='Points',line=10.5,direction='Over',odds=-110,result='Pending'),**kw)
def rows():
    return [
        dict(game_id='123',game_date='2026-10-22',season_type='2',team_display_name='Philadelphia 76ers',opponent_team_display_name='Cleveland Cavaliers',team_score='114',opponent_team_score='106',athlete_display_name='Player',did_not_play='false',minutes='24',points='16'),
        dict(game_id='123',game_date='2026-10-22',season_type='2',team_display_name='Cleveland Cavaliers',opponent_team_display_name='Philadelphia 76ers',team_score='106',opponent_team_score='114',athlete_display_name='Other',did_not_play='false',minutes='20',points='9')]
def final():
    return {'header':{'id':'123','competitions':[{'status':{'type':{'completed':True}}}]}}
class ArchiveFallbackTests(unittest.TestCase):
    def test_exact_final_archive_grades(self):
        self.assertEqual(grade_record(record(),archive_summary(record(),rows(),final()))['result'],'Win')
    def test_missing_final_evidence_rejected(self):
        with self.assertRaises(ValueError):archive_summary(record(),rows(),{})
    def test_wrong_event_date_and_duplicate_player_rejected(self):
        for data in (rows()+[rows()[0]],[dict(r,game_date='2026-10-21') for r in rows()]):
            with self.assertRaises(ValueError):archive_summary(record(),data,final())
    def test_dnp_and_blank_stat_never_zero(self):
        for change in ({'did_not_play':'true'},{'points':''},{'minutes':'0'}):
            data=rows();data[0].update(change)
            with self.assertRaises(ValueError):archive_summary(record(),data,final())
    def test_conflicting_archive_scores_rejected(self):
        data=rows();data[0]['opponent_team_score']='105'
        with self.assertRaises(ValueError):archive_summary(record(),data,final())

class DownloadFormatTests(unittest.TestCase):
    def test_json_query_url_is_not_parsed_as_csv(self):
        from unittest.mock import patch,MagicMock
        from secondary_settlement import download
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"events": []}'
        with patch('secondary_settlement.urlopen',return_value=response):
            self.assertEqual(download('https://example.test/scoreboard?dates=20261022',999),{'events':[]})
