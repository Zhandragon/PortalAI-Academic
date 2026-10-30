"""Synthetic stdio MCP server used by smoke_workspace; no production services."""
import json,sys,time
from pathlib import Path
for line in sys.stdin:
    msg=json.loads(line)
    if 'id' not in msg:continue
    method=msg['method'];params=msg.get('params',{})
    if method=='initialize':result={'protocolVersion':params['protocolVersion'],'capabilities':{'tools':{}},'serverInfo':{'name':'PortalAI fixture','version':'1'}}
    elif method=='tools/list':result={'tools':[{'name':'echo','description':'Fixture echo','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}
    elif method=='tools/call':
        text=params['arguments']['text']
        if text=='wait':time.sleep(30)
        result={'content':[{'type':'text','text':text}]}
    else:result={}
    print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}),flush=True)
