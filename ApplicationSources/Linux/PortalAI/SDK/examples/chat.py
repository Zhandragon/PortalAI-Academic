"""Run with bundled Python: chat.py URL. A local chat model must be running."""
import getpass
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from portalai import Client
client=Client(sys.argv[1],getpass.getpass('API token: '))
chat_key=client.new_key();print('Create key:',chat_key,flush=True)
chat=client.create_chat('SDK example',key=chat_key)
message_key=client.new_key();print('Message key:',message_key,flush=True)
job=client.message(chat['id'],'Explain portable applications in one sentence.',key=message_key)
print('Job:',job['job_id'],flush=True)
print(client.wait(job['job_id']))
