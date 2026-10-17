import base64
import json
import tempfile
import unittest
from unittest.mock import patch
from automatic_reports import save_report, report_path
class Response:
    def __init__(self,status,payload=None):self.status_code=status;self.payload=payload
    def raise_for_status(self):
        if self.status_code>=400:raise ValueError('HTTP failure')
    def json(self):return self.payload
class Client:
    def __init__(self):self.doc=None;self.writes=0
    def get(self,*a,**kw):return Response(404) if self.doc is None else Response(200,dict(sha='current',content=base64.b64encode(json.dumps(self.doc).encode()).decode()))
    def put(self,*a,**kw):
        self.doc=json.loads(base64.b64decode(kw['json']['content']));self.writes+=1
        return Response(200)
class AutomaticReportTests(unittest.TestCase):
    def test_persists_changed_reports_and_skips_identical_refresh(self):
        client=Client()
        with tempfile.TemporaryDirectory() as directory,patch('automatic_reports.report_path',return_value=directory+'/report.json'):
            first=save_report('frozen projection','picks.csv','text/csv','private-test-token',client)
            self.assertEqual(save_report('frozen projection','picks.csv','text/csv','private-test-token',client),first)
            self.assertEqual(client.writes,1)
            save_report('updated report','picks.csv','text/csv','private-test-token',client)
            self.assertEqual(client.writes,2)
            self.assertNotIn('private-test-token',json.dumps(client.doc))
    def test_rejects_paths(self):
        with self.assertRaises(ValueError):report_path('../secrets')
