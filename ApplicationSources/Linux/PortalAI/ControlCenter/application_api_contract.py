"""Public v1 request contracts, shared by the OpenAPI document generator."""
STRING={'type':'string'}
ID={'type':'string','pattern':'^[a-f0-9]{32}$'}
TOKENS={'type':'integer','minimum':64,'maximum':4096,'default':1024}
def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
ARTIFACT={'title':{'type':'string','minLength':1,'maxLength':160},'kind':{'type':'string','enum':['html','svg','chart']},'content':{'type':'string','minLength':1,'description':'At most 512 KiB UTF-8'},'expected_revision':ID}
REQUESTS={
 '/v1/chats':obj({'title':{'type':'string','minLength':1,'maxLength':160}}),
 '/v1/chats/{id}/messages':obj({'message':{'type':'string','minLength':1,'maxLength':32000},'max_tokens':TOKENS},['message']),
 '/v1/structured':obj({'question':{'type':'string','minLength':1,'maxLength':16000},'context':{},'schema':{'type':'object','description':'Supported llama.cpp JSON Schema subset; see INTEGRATION.md'},'max_tokens':TOKENS},['question','schema']),
 '/v1/missions':obj({'objective':{'type':'string','minLength':1,'maxLength':16000},'mode':{'type':'string','enum':['observe','full','vm'],'default':'observe'},'max_steps':{'type':'integer','minimum':1,'maximum':100,'default':12},'armed':{'type':'boolean','default':False}},['objective']),
 '/v1/knowledge/collections':obj({'name':STRING,'folder':STRING,'ocr':{'type':'boolean','default':True}},['name','folder']),
 '/v1/knowledge/search':obj({'query':STRING,'collection':ID,'limit':{'type':'integer','minimum':1,'maximum':20,'default':6}},['query']),
 '/v1/artifacts':obj({k:v for k,v in ARTIFACT.items() if k!='expected_revision'},['title','kind','content']),
 '/v1/artifacts/{id}/revisions':obj(ARTIFACT,['title','kind','content','expected_revision']),
 '/v1/artifacts/{id}/restore':obj({'revision':ID,'expected_revision':ID},['revision','expected_revision']),
 '/v1/artifacts/{id}/export':obj({'revision':ID})}
PAGINATION={'offset':{'type':'integer','minimum':0,'default':0},'limit':{'type':'integer','minimum':1,'maximum':200,'default':50}}
QUERIES={**{p:PAGINATION for p in ('/v1/chats','/v1/jobs','/v1/missions','/v1/knowledge/collections','/v1/artifacts','/v1/outputs')},
 '/v1/missions/{id}':{'history_offset':{'type':'integer','minimum':0,'default':0},'history_limit':{'type':'integer','minimum':1,'maximum':100,'default':20}},
 '/v1/knowledge/citation':{'citation':STRING},'/v1/artifacts/{id}':{'revision':ID},
 '/v1/outputs/content':{'path':STRING,'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':1048576},'identity':STRING}}
