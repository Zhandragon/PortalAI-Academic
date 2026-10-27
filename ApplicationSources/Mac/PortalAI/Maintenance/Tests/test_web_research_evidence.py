import copy,json
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ControlCenter'))
from chat_evidence import project,web_evidence

class ResearchEvidenceTests(unittest.TestCase):
    def message(self,row):return {'role':'tool','name':'web','tool_call_id':'fixture','content':json.dumps({'ok':True,'result':row})}
    def test_compacted_data_cannot_skip_unseen_records(self):
        rows=[{'index':i,'value':'record '*20} for i in range(100)]
        m=self.message({'kind':'data_preview','document':'cached','url':'https://example.com/data','format':'json','offset':200,'items':rows,'next_offset':300,'total_items':1000,'source':'Parsed data preview'})
        before=copy.deepcopy(m);result=json.loads(project(m,4,1800))
        self.assertGreater(len(result['items']),0);self.assertLess(len(result['items']),100)
        self.assertEqual(result['items'],rows[:len(result['items'])])
        self.assertEqual(result['next_offset'],200+len(result['items']))
        self.assertEqual(result['source_next_offset'],300);self.assertEqual(m,before)
    def test_oversize_first_record_requires_exact_history(self):
        m=self.message({'kind':'data_preview','document':'cached','offset':0,'items':[{'large':'x'*5000}], 'next_offset':1,'total_items':2})
        result=json.loads(project(m,5,900))
        self.assertEqual(result['items'],[]);self.assertIsNone(result['next_offset'])
        self.assertTrue(result['read_exact_history_first']);self.assertEqual(result['message_id'],5)
    def test_catalog_retains_identifier_and_metadata_source(self):
        item={'title':'A paper','identifier':'10.123/x','url':'https://doi.org/10.123/x','type':'dataset'}
        m=self.message({'kind':'catalog_results','provider':'datacite','query':'science','source':'Public database metadata; papers have not been fetched.','results':[item]*20})
        result=json.loads(project(m,6,1200))
        self.assertEqual(result['kind'],'catalog_results');self.assertIn('not been fetched',result['source'])
        self.assertEqual(result['results'][0],item);self.assertGreater(result['omitted_items'],0)
    def test_discovery_preserves_filter_cursor_and_unfetched_status(self):
        records=[{'url':'https://example.com/video'+str(i)+'.mp4','content_fetched':False,'label':'clip '*20} for i in range(50)]
        m=self.message({'kind':'resource_discovery','document':'cached','query':'clip','resource_kind':'video','offset':10,'resources':records,'next_offset':60,'total_resources':80})
        result=json.loads(project(m,7,1400))
        self.assertEqual(result['next_offset'],10+len(result['resources']));self.assertEqual(result['resource_kind'],'video')
        self.assertFalse(result['resources'][0]['content_fetched'])
    def test_error_envelopes_are_never_projected_as_successful_data(self):
        m={'name':'web','content':json.dumps({'ok':False,'result':{'kind':'data_preview','items':[1]}})}
        self.assertIsNone(web_evidence(m,1,1000))

if __name__=='__main__':unittest.main()
