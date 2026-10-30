"""Start a configured stdio server only after its parent establishes job ownership."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))

if __name__=='__main__':
    # Do not buffer bytes belonging to the server's first JSON-RPC request.
    packet=bytearray()
    while len(packet)<=1024*1024:
        char=os.read(sys.stdin.fileno(),1)
        if not char or char==b'\n':break
        packet.extend(char)
    if len(packet)>1024*1024:raise ValueError('MCP startup packet too large')
    init=json.loads(packet)
    # No shell and no host PATH lookup. The owning controller validates every
    # configuration and sends this packet only after assigning the OS job.
    command=init['command'];cwd=init['cwd']
    os.chdir(cwd)
    if os.name=='nt':
        # The Windows CRT exec family does not quote argv entries containing
        # spaces. Popen quotes the argument vector and inherits the parent Job.
        import subprocess
        child=subprocess.Popen(command,env=init['environment'],stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        raise SystemExit(child.wait())
    os.execve(command[0],command,init['environment'])
