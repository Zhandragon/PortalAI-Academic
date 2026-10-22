"""Foreground Linux LLM entrypoint; media/GUI portability remains separate."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import build_plan, portable_env

parser = argparse.ArgumentParser()
parser.add_argument("--preflight", action="store_true")
args = parser.parse_args()
plan = build_plan(ROOT)
if args.preflight:
    print(json.dumps(plan, indent=2))
else:
    env = portable_env(ROOT)
    from platform_runtime import linux_elf_command
    command, cwd = linux_elf_command(ROOT, plan['command'])
    os.chdir(cwd or ROOT)
    os.execve(command[0], command, env)
