"""Real NativeChat tool loop: model call -> media handoff -> model summary.

Uses the actual GUI worker, streaming client, message conversion and ToolRuntime
without opening a GUI. The isolated test transcript never enters user chat memory.
Only the single declared test command may execute.
"""
import argparse
import atexit
import getpass
import http.client
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"ControlCenter"), str(ROOT/"Agent"), str(ROOT/"Tools")]
import native_chat as chat
from instance_runtime import port as instance_port
from runtime_policy import require_space
from service_manager import _listener_identity, _wait_qwen_ready
from chat_model_switch import _guard
from chat_effort_ui import ChatEffortControls
from smoke_profile import SmokeProfile


def headless_effort(panel, level, started_at):
    """Use the real GUI request preparation/options without creating Tk widgets."""
    controls = ChatEffortControls.__new__(ChatEffortControls)
    controls.panel = panel
    controls.profile = level
    controls.tools_profile = 'balanced'
    controls.active_tools_profile = 'balanced'
    controls.session_unlocked = False
    controls.active_options = {}
    controls.active_plan = None
    # Keep the enclosing lifecycle smoke's original Stop fence, including while
    # the GUI helper prepares the selected profile. Never re-arm after Stop.
    real_module = controls._module
    def module(name):
        value = real_module(name)
        if name != 'chat_model_switch':
            return value
        def prepare(*args, **kwargs):
            kwargs['requested_at'] = started_at
            return value.prepare_chat(*args, **kwargs)
        return SimpleNamespace(prepare_chat=prepare)
    controls._module = module
    return controls


def http_status(path):
    c = http.client.HTTPConnection("127.0.0.1", instance_port('qwen', ROOT), timeout=1)
    try:
        c.request("GET", path); r = c.getresponse(); r.read(256000); return r.status
    except Exception as exc: return type(exc).__name__
    finally: c.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["image", "native-image", "native-klein4", "cpu-music", "cpu-transcribe", "voice", "error", "musetalk"], default="image")
    parser.add_argument('--native-engine', choices=['sdcpp-cpu','sdcpp-vulkan'], default='sdcpp-vulkan',
                        help='Backend for the native-klein4 case; still uses the real lease and healthy chat restoration')
    parser.add_argument("--report", default="chat-handoff.json")
    parser.add_argument("--effort", choices=['fast', 'balanced', 'deep'],
                        help='Prepare this real GUI chat effort profile before the tool handoff')
    parser.add_argument("--username", help="Current administrator for an account-enabled bundle; password is read with a hidden prompt")
    args = parser.parse_args()
    profile = SmokeProfile(ROOT)
    account_session = None
    if profile.context is not None:
        if not args.username:
            parser.error("Account-enabled handoff testing requires --username and the active administrator login")
        from local_accounts import LocalAccounts
        account_store = LocalAccounts(ROOT)
        account_session = account_store.login(args.username, getpass.getpass("Administrator password (hidden): "))
        atexit.register(account_store.logout, account_session)
        if account_session.role != "admin" or account_session.user_id != profile.context[0]:
            raise PermissionError("The handoff test requires the current profile administrator")
    profile.check()
    started_at = float(os.environ.get('PORTALAI_SMOKE_STARTED_AT') or time.time())
    _guard(ROOT, started_at)
    if Path(args.report).name != args.report: raise ValueError("Report must be a filename")
    report_path = profile.path(args.report)
    require_space(ROOT, 64*1024**2, for_outputs=True)
    before = _listener_identity()
    initial = before
    if not before["portable_qwen"]: raise RuntimeError("Start the owned PortalAI chat server first")
    _wait_qwen_ready(300)
    marker = "REMEMBER_"+uuid.uuid4().hex[:10]
    if args.case in ("musetalk", "cpu-transcribe"):
        # Use the bundled demo, never user media. Spaced paths exercise the CLI.
        fixture = profile.path("MuseTalk smoke")
        fixture.mkdir(parents=True, exist_ok=True)
        ffmpeg = str(ROOT/"Tools/ffmpeg/bin/ffmpeg.exe")
        for source, dest, flags in (
            ("video/sun.mp4", "input video.mp4", ["-an", "-vf", "scale=512:-2,fps=12"]),
            ("audio/sun.wav", "input audio.wav", ["-ac", "1", "-ar", "16000"]),
        ):
            subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(ROOT/"Video/MuseTalk/data"/source),
                            "-t", "2", *flags, str(fixture/dest)], check=True, timeout=30,
                           creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    fixture_relative = (fixture.relative_to(ROOT).as_posix() if args.case in ("musetalk", "cpu-transcribe") else "")
    commands = {
        "cpu-music": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py music "A gentle acoustic guitar instrumental" --engine musicgen-cpu --instrumental --duration 3',
        "native-klein4": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py image "A blue cube on a plain white table" --profile klein4 --uncensored --engine '+args.native_engine+' --width 128 --height 128 --steps 4 --seed 52',
        "native-image": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py image "A blue cube on a plain white table" --profile sd15 --engine sdcpp-vulkan --width 128 --height 128 --seed 52',
        "cpu-transcribe": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py transcribe "Maintenance/Reports/MuseTalk smoke/input audio.wav" --device cpu --model base --no-vad --beam-size 1',
        "image": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py image "A blue cube on a plain white table" --profile sd15 --width 128 --height 128 --seed 52',
        "voice": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py voice-say "Portal AI has restored the conversation after this voice task." --engine qwen',
        "error": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py image "A blue cube" --profile sd15 --width 65 --height 64',
        "musetalk": '.\\Tools\\portable_python.cmd Agent\\ai_tools.py lip-sync "Maintenance/Reports/MuseTalk smoke/input video.mp4" "Maintenance/Reports/MuseTalk smoke/input audio.wav" --output "Outputs/Tests/MuseTalk smoke/lip sync.mp4"',
    }
    command = commands[args.case]
    if fixture_relative:
        command = command.replace("Maintenance/Reports/MuseTalk smoke", fixture_relative)
    started = time.monotonic(); events = []; executed = []; blocked = []; at_return = []
    class Events(queue.Queue):
        def put(self, item, *a, **kw):
            nonlocal before, old_states
            kind, data = item
            if kind == 'effort_applied':
                _guard(ROOT, started_at)
                # The media tool must stop and restore the prepared profile,
                # not the different model that preceded effort selection.
                before = _listener_identity()
                old_states = set((ROOT/'Agent/.runtime').glob('qwen_handoff_*.json'))
            if kind not in {"content", "reasoning"}:
                events.append({"seconds": round(time.monotonic()-started, 2), "kind": kind,
                               "detail": data if kind in {"error", "connection_status"} else None})
                print(json.dumps(events[-1]), flush=True)
            return super().put(item, *a, **kw)
    class TestTools(chat.ToolRuntime):
        def execute(self, name, tool_args):
            _guard(ROOT, started_at)
            if name != "shell" or tool_args.get("command", "").strip() != command or executed:
                blocked.append({"name": name, "args": tool_args})
                raise RuntimeError("Compatibility test permits its exact command once only")
            executed.append(command)
            result = super().execute(name, tool_args)
            at_return.append({"seconds": round(time.monotonic()-started, 2), "health": http_status("/health"), "models": http_status("/v1/models")})
            return result
    class Store:
        def __init__(self): self.profile = chat.CapturedProfile(ROOT)
        def save_session(self, session): profile.save(Path(args.report).with_suffix(".session.json").name, session)
    panel = chat.NativeChat.__new__(chat.NativeChat)
    panel.root = ROOT; panel.settings = {**chat.DEFAULT_SETTINGS, "max_output_tokens": 700, "temperature": 0, "tool_step_limit": 3}
    panel.cancel_event = threading.Event(); panel.active_http = chat.ActiveHTTP(); panel.ev = Events()
    panel.store = Store(); panel.tool_runtime = TestTools(ROOT, panel.settings)
    if account_session is not None: panel.tool_runtime.bind_account(account_session)
    panel.session = {"id": uuid.uuid4().hex, "title": "Isolated handoff compatibility test", "messages": [
        {"role": "user", "content": f"Remember {marker}. Call shell exactly once with this exact command: {command}\nAfter the tool result, summarize its actual success or error and include {marker}. On success include the actual output filename. Do not retry or call other tools.", "attachments": []}]}
    if args.effort:
        panel.effort = headless_effort(panel, args.effort, started_at)
    panel.compact_context_if_needed = lambda: False
    panel.make_thumbnail = lambda p: None
    def messages():
        rows = [{"role": "system", "content": "You are executing a bounded PortalAI compatibility test. Follow the single user-authorized tool command exactly; then summarize its actual result. Never retry the command. Preserve the user's marker in your final response."}]
        rows.extend(row for m in panel.session["messages"] if (row := panel._api_row(m)) is not None)
        return rows, 0
    panel.api_messages = messages
    old_states = set((ROOT/"Agent/.runtime").glob("qwen_handoff_*.json"))
    timer = threading.Timer(900, lambda: (panel.cancel_event.set(), panel.cancel_http(), panel.tool_runtime.cancel()))
    timer.daemon = True; timer.start()
    try: panel.agent_worker(panel.session["id"])
    finally: timer.cancel()
    tool_rows = [m for m in panel.session["messages"] if m["role"] == "tool"]
    final = panel.session["messages"][-1]
    errors = [e for e in events if e["kind"] == "error"]
    # Preserve the immediate chat outcome BEFORE waiting for any eventual backend
    # recovery. This is the race earlier backend-only smoke tests could conceal.
    report = {"passed": False, "case": args.case, "before": before, "initial": initial, "events": events,
              "effort": args.effort, "completion_options": getattr(getattr(panel, 'effort', None), 'active_options', {}),
              "executed_commands": executed, "blocked_calls": blocked, "tool_return_http": at_return,
              "tool_results": tool_rows, "final": final, "marker": marker, "errors": errors,
              "scope": "Actual NativeChat worker/stream/tool runtime with an isolated prompt; no GUI rendering, history compaction or persistent-memory retrieval"}
    profile.save(args.report, report)
    _wait_qwen_ready(300)
    after = _listener_identity()
    states = set((ROOT/"Agent/.runtime").glob("qwen_handoff_*.json"))-old_states
    handoffs = [json.loads(p.read_text()) for p in states]
    stopped = any(before["listeners"][0]["pid"] in h.get("killed_pids", []) for h in handoffs)
    restored = bool(after["listeners"]) and before["listeners"][0]["command_line"] == after["listeners"][0]["command_line"]
    payload = json.JSONDecoder().raw_decode(tool_rows[0]["content"].lstrip())[0] if tool_rows else {}
    tool_expected = payload.get("success") is (args.case != "error")
    summary = final.get("content", "") if final.get("role") == "assistant" and not final.get("tool_calls") else ""
    files = payload.get("files", [])
    evidence_in_summary = all(Path(p).name in summary for p in files) if args.case != "error" else bool(summary)
    report.update(after=after, llm_was_stopped=stopped, exact_command_restored=restored,
                  elapsed_seconds=round(time.monotonic()-started, 2), summary=summary)
    report["passed"] = len(executed) == 1 and not blocked and len(tool_rows) == 1 and not errors and stopped and restored and tool_expected and marker in summary and evidence_in_summary
    profile.save(args.report, report)
    print(json.dumps({k:report[k] for k in ("passed", "case", "llm_was_stopped", "exact_command_restored", "tool_return_http", "summary", "errors", "elapsed_seconds")}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
