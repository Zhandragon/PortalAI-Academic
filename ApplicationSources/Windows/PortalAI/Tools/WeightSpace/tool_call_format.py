"""Parse native Qwen tool dialects for offline grading only; never dispatch calls."""
import json
import re

NAME=r'[A-Za-z_][A-Za-z0-9_-]{0,127}'
FUNCTION=re.compile(r'<function=('+NAME+r')>\s*(.*?)\s*</function>',re.S)
PARAMETER=re.compile(r'<parameter=('+NAME+r')>(.*?)</parameter>',re.S)

def strict_json(text):
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('Duplicate JSON key')
            value[key]=item
        return value
    def invalid(_):raise ValueError('Non-JSON constant')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=invalid)

def same_value(left,right):
    """JSON booleans must not compare equal to numeric arguments."""
    if isinstance(left,bool) or isinstance(right,bool):return type(left) is type(right) and left==right
    if isinstance(left,dict) and isinstance(right,dict):
        return left.keys()==right.keys() and all(same_value(left[k],right[k]) for k in left)
    if isinstance(left,list) and isinstance(right,list):
        return len(left)==len(right) and all(same_value(a,b) for a,b in zip(left,right))
    return left==right

def typed(value,kind):
    if isinstance(kind,list):return any(typed(value,k) for k in kind)
    return {'string':isinstance(value,str),'integer':type(value) is int,
            'number':type(value) in (int,float),'boolean':type(value) is bool,
            'object':isinstance(value,dict),'array':isinstance(value,list),'null':value is None}.get(kind,False)

def parse_tool_calls(content,tools=()):
    if not isinstance(content,str) or len(content.encode('utf-8'))>65536:raise ValueError('Tool envelope exceeds bound')
    if any(marker in content.upper() for marker in ('<!DOCTYPE','<!ENTITY','<?XML')):raise ValueError('Unsupported declaration')
    matches=list(re.finditer(r'<tool_call>\s*(.*?)\s*</tool_call>',content,re.S))
    if not 1<=len(matches)<=32 or content.count('<tool_call>')!=len(matches) or content.count('</tool_call>')!=len(matches):
        raise ValueError('Missing, nested or incomplete tool envelope')
    schemas={}
    for tool in tools:
        function=tool.get('function',{})
        if isinstance(function,dict) and isinstance(function.get('name'),str):
            schemas[function['name']]=function.get('parameters',{})
    calls=[]
    for match in matches:
        body=match.group(1)
        if body.startswith('<function='):
            function=FUNCTION.fullmatch(body)
            if not function or function[1] not in schemas:raise ValueError('XML function requires its exposed schema')
            name=function[1];schema=schemas[name];properties=schema.get('properties',{})
            rest=function[2].strip();arguments={}
            while rest:
                part=PARAMETER.match(rest)
                if not part or part[1] in arguments or len(arguments)>=32:raise ValueError('Malformed or duplicate parameter')
                key,raw=part[1],part[2].strip()
                if key not in properties or re.search(r'</?(?:tool_call|function|parameter)(?:[=>\s])',raw):
                    raise ValueError('Unknown or nested parameter')
                kind=properties[key].get('type')
                value=raw if kind=='string' else strict_json(raw)
                if not typed(value,kind):raise ValueError('Parameter type differs from exposed schema')
                arguments[key]=value
                rest=rest[part.end():].strip()
            call={'name':name,'arguments':arguments}
        else:
            call=strict_json(body)
        if not isinstance(call,dict) or set(call)!={'name','arguments'} or not isinstance(call['name'],str) or not re.fullmatch(NAME,call['name']) or not isinstance(call['arguments'],dict):
            raise ValueError('Malformed tool call')
        schema=schemas.get(call['name'])
        if schema:
            arguments=call['arguments'];properties=schema.get('properties',{})
            if not set(schema.get('required',[]))<=arguments.keys():raise ValueError('Missing required argument')
            if schema.get('additionalProperties') is False and not arguments.keys()<=properties.keys():raise ValueError('Extra argument')
            for key,value in arguments.items():
                kind=properties.get(key,{}).get('type')
                if kind is not None and not typed(value,kind):raise ValueError('Incorrect argument type')
        calls.append(call)
    return calls
