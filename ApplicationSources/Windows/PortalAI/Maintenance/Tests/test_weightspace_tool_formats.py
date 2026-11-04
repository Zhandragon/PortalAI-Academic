"""Tool-choice scoring accepts native Qwen dialects without executing tool text."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools/WeightSpace'))
import evaluation

def fixture(name='web_read', arguments=None, properties=None):
    arguments=arguments if arguments is not None else {'url':'https://scholar.example/profile?id=123'}
    properties=properties if properties is not None else {'url':{'type':'string'}}
    return {'kind':'tool','calls':[{'name':name,'arguments':arguments}],
            'tools':[{'type':'function','function':{'name':name,'parameters':{
                'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}}]}

def xml(name, params):
    return '<tool_call>\n<function='+name+'>\n'+''.join(
        '<parameter='+key+'>\n'+value+'\n</parameter>\n' for key,value in params)+'</function>\n</tool_call>'

class ToolFormatTests(unittest.TestCase):
    def test_native_xml_photo_lookup_is_correct_without_execution(self):
        text='Reasoning\n</think>\nI will read the linked profile.\n'+xml('web_read',[('url','https://scholar.example/profile?id=123')])+'<|im_end|>'
        with patch.object(evaluation,'bounded_grader',side_effect=AssertionError('Tools must never execute')):
            value=evaluation.grade(fixture(),text)
        self.assertTrue(value['correct']);self.assertFalse(value['tools_executed'])

    def test_json_dialect_keeps_existing_scoring(self):
        case=fixture()
        self.assertTrue(evaluation.grade(case,'<tool_call>'+json.dumps(case['calls'][0])+'</tool_call>')['correct'])

    def test_other_real_qwen_choices(self):
        for name,key,value in [('read_file','path','project/src/search.py'),('operation_status','operation_id','order-123')]:
            with self.subTest(name=name):
                self.assertTrue(evaluation.grade(fixture(name,{key:value},{key:{'type':'string'}}),xml(name,[(key,value)]))['correct'])

    def test_wrong_choice_is_still_wrong(self):
        case=fixture();case['tools'].append(fixture('web_download')['tools'][0])
        self.assertFalse(evaluation.grade(case,xml('web_download',[('url','https://scholar.example/profile?id=123')]))['correct'])

    def test_xml_types_follow_exposed_schema_not_expected_answer(self):
        args={'count':2,'active':True,'items':['a',3],'settings':{'a':1},'text':'123'}
        props={k:{'type':t} for k,t in [('count','integer'),('active','boolean'),('items','array'),('settings','object'),('text','string')]}
        text=xml('choose',[('count','2'),('active','true'),('items','["a",3]'),('settings','{"a":1}'),('text','123')])
        self.assertTrue(evaluation.grade(fixture('choose',args,props),text)['correct'])
        self.assertFalse(evaluation.grade(fixture('choose',{**args,'count':3},props),text)['correct'])

    def test_xml_duplicate_parameter_is_invalid(self):
        self.assertFalse(evaluation.grade(fixture(),xml('web_read',[('url','wrong'),('url','https://scholar.example/profile?id=123')]))['correct'])

    def test_json_duplicate_key_is_invalid(self):
        text='<tool_call>{"name":"wrong","name":"web_read","arguments":{"url":"https://scholar.example/profile?id=123"}}</tool_call>'
        self.assertFalse(evaluation.grade(fixture(),text)['correct'])

    def test_incomplete_or_nested_envelopes_are_invalid(self):
        valid=xml('web_read',[('url','https://scholar.example/profile?id=123')])
        for text in [valid+'<tool_call>',valid+'</tool_call>',valid.replace('</parameter>',''),
                     valid.replace('https://scholar.example/profile?id=123','<parameter=x>value</parameter>')]:
            with self.subTest(text=text):self.assertFalse(evaluation.grade(fixture(),text)['correct'])

    def test_unexpected_extra_call_is_wrong(self):
        valid=xml('web_read',[('url','https://scholar.example/profile?id=123')])
        self.assertFalse(evaluation.grade(fixture(),valid+valid)['correct'])

    def test_numeric_and_boolean_arguments_are_distinct(self):
        case=fixture('count',{'value':1},{'value':{'type':'integer'}})
        for payload in ('<tool_call>{"name":"count","arguments":{"value":true}}</tool_call>',xml('count',[('value','true')])):
            self.assertFalse(evaluation.grade(case,payload)['correct'])

    def test_unknown_xml_schema_does_not_guess_argument_types(self):
        case=fixture();case.pop('tools')
        self.assertFalse(evaluation.grade(case,xml('web_read',[('url','https://scholar.example/profile?id=123')]))['correct'])

    def test_empty_or_nonfinite_tool_output_is_invalid(self):
        for text in ('No tool needed.','<tool_call>{"name":"web_read","arguments":{"url":NaN}}</tool_call>'):
            self.assertFalse(evaluation.grade(fixture(),text)['correct'])

if __name__=='__main__':unittest.main()
