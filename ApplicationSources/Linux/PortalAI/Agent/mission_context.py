"""Rolling, evidence-based mission context; full checkpoints remain authoritative.

Compaction never edits history, objectives, access modes or pending effects. The
persisted index is a disposable view tied to the exact history digest. No model
is allowed to invent a replacement for the execution ledger.
"""
from instance_runtime import port as _instance_port, url as _instance_url
import hashlib
import json
import re
import time
import urllib.request

from runtime_policy import atomic_json, require_space

OUTPUT_TOKENS = 768
HEADROOM = 256


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def clip(value, size):
    text = value if isinstance(value, str) else encoded(value)
    raw = text.encode("utf-8")
    if len(raw) <= size: return text
    # Keep both ends: exit codes/errors and output paths often occur at the end.
    half = max(0, (size-24)//2)
    return raw[:half].decode("utf-8", "ignore") + " [excerpt; use history] " + raw[-half:].decode("utf-8", "ignore")


def digest(value):
    return hashlib.sha256(encoded(value).encode("utf-8")).hexdigest()


def result_value(value):
    """Render JSON tool evidence as data, without double-encoding it as text."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, (dict, list)):
                return parsed
        except (ValueError, TypeError):
            pass
    return value


def post(path, value):
    req = urllib.request.Request(_instance_url('qwen', '')+path, encoded(value).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read(8*1024**2+1)
    if len(raw) > 8*1024**2: raise ValueError("Context endpoint response exceeds limit")
    return json.loads(raw)


class Budget:
    def __init__(self, context_tokens, api=post, output_tokens=OUTPUT_TOKENS):
        self.limit = int(context_tokens)-output_tokens-HEADROOM
        self.api = api
        self.method = "rendered-template-tokenizer"
        self.cache = {}

    def count(self, messages):
        key = encoded(messages)
        if key in self.cache: return self.cache[key]
        if self.method == "rendered-template-tokenizer":
            try:
                prompt = self.api("/apply-template", {"messages": messages,
                    "chat_template_kwargs": {"enable_thinking": True}})["prompt"]
                if not isinstance(prompt, str): raise ValueError("Invalid rendered prompt")
                tokens = self.api("/tokenize", {"content": prompt, "add_special": True})["tokens"]
                if not isinstance(tokens, list) or not all(type(t) is int for t in tokens):
                    raise ValueError("Invalid tokenizer response")
                self.cache[key] = len(tokens)
                return len(tokens)
            except (OSError, ValueError, KeyError, TypeError):
                # Older servers may lack these routes. One token per UTF-8 byte
                # plus template allowance is conservative for bundled tokenizers.
                self.method = "conservative-utf8-bytes"
        count = len(key.encode("utf-8"))+128
        self.cache[key] = count
        return count


def rolling_index(store, mission):
    history = mission["history"]
    through = max(0, len(history)-4)
    path = store.folder(mission["id"])/"context.json"
    source = digest(history[:through])
    if path.is_file():
        try:
            if path.stat().st_size <= 256*1024:
                old = json.loads(path.read_text(encoding="utf-8"))
                if (old.get("version") == 1 and old.get("mission") == mission["id"] and
                    old.get("mode") == mission["mode"] and old.get("through") == through and
                    old.get("source_sha256") == source and old.get("index_sha256") == digest(old["records"])):
                    return old
        except (OSError, ValueError, KeyError, TypeError): pass
    records = []
    for step, row in enumerate(history[:through], 1):
        records.append({"step": step, "action": clip(row["action"], 320),
                        "result": clip(row.get("result", ""), 480), "sha256": digest(row)})
    value = {"version": 1, "mission": mission["id"], "mode": mission["mode"], "through": through,
             "source_sha256": source, "records": records, "index_sha256": digest(records),
             "method": "extractive evidence; not a model-generated claim", "updated_at": time.time()}
    if through:
        require_space(store.root, 256*1024, for_outputs=True)
        atomic_json(path, value)
    return value


def history_page(mission, start=1, count=1):
    """Only the current mission's records; no path or cross-mode lookup."""
    if type(start) is not int or type(count) is not int or start < 1 or not 1 <= count <= 4:
        raise ValueError("history requires start >= 1 and count between 1 and 4")
    rows = mission["history"][start-1:start-1+count]
    # A single source/tool result is bounded by the executor; further trim only
    # this response, never the disk history. Exact step IDs survive compaction.
    return encoded({"total": len(mission["history"]), "records": [
        {"step": start+i, "action": row["action"], "result": clip(row.get("result", ""), 6000//count)}
        for i, row in enumerate(rows)]})


def build_messages(store, mission, instruction, children, notes, context_tokens, api=post, *, rejected_action=None, rejection_reason=None, output_tokens=OUTPUT_TOKENS):
    from mission_runner import MissionContextError
    budget = Budget(context_tokens, api, output_tokens)
    index = rolling_index(store, mission)
    # Critical state is never sourced from a summary or shortened to fit.
    base = {"objective": mission["objective"], "mode": mission["mode"],
            "steps_remaining": mission["max_steps"]-mission["steps"],
            "pending_action": mission.get("pending_action"),
            "subtasks": [{"id": c["id"], "status": c["status"], "objective": c["objective"]} for c in children],
            "completed_records": len(mission["history"]),
            "history_rule": "Records 1..completed_records already ran. Use history(start,count) for evidence before repeating an older action."}
    if mission.get('schedule_id'):
        from mission_schedule import Schedules
        schedule = Schedules(store.root).load(mission['schedule_id'])
        if schedule.get('active_run') != mission['id'] or schedule['mode'] != mission['mode']:
            raise MissionContextError('This mission is not the current scheduled run; review its schedule before planning.')
        base['scheduled_run'] = {
            'autonomous_recovery': schedule.get('autonomous_recovery',False),
            'previous_run_outcome': result_value(clip(schedule.get('history',[])[-1:],1800)),
            'occurrence': schedule['runs_started'],
            'previous_runs_completed': schedule['runs_completed'],
            'run_limit': schedule['max_runs'] or 'until stopped',
            'rule': ('This is a later occurrence; inspect the previous outcome and continue unfinished work. An ended run may have exhausted its budget without completing. If the objective distinguishes first-run work from next-run or recurring work, perform the next-run or recurring work NOW. Do not defer it merely because the objective is repeated. '
                     if schedule['runs_started']>1 else 'This is the first occurrence. If the objective distinguishes first-run work from later work, perform the first-run work now. ')+
                    'Saved memory may describe previous occurrences. Current history contains only actions in this occurrence; a previous run completing does not finish this run. Use previous_run(start,count) to inspect the preceding run before repeating effects, especially after budget exhaustion.'}
    if mission.get('recovery_history'):
        base['autonomous_recovery']={
            'recent_failures':[{'action':result_value(clip(row.get('action'),500)),
                                'error':clip(row.get('error',''),1200),'outcome':row.get('outcome')}
                               for row in mission['recovery_history'][-2:]],
            'rule':'These attempts failed; they are not completed actions. Change strategy using the error and saved access. Use pause(text) if you cannot proceed. Do not repeat uncertain external effects.'}
    if mission['history']:
        row = mission['history'][-1]
        base['last_completed_step'] = {
            'step': len(mission['history']), 'execution': 'already completed',
            'action': result_value(clip(row['action'], 500)),
            'result': result_value(clip(row.get('result', ''), 900)),
            'next_step': 'Use this result to choose the next unfinished action. Do not repeat this action just to obtain the same result.'}
    if rejected_action is not None:
        base['planning_feedback'] = {
            'rejected_proposal': rejected_action,
            'execution': 'not executed; no action budget was consumed',
            'reason': rejection_reason or 'This repeats the last completed action. Its result is already available above.',
            'required': 'Return the next valid action using the objective and completed evidence. Complete only if all required work for THIS occurrence is verified. If waiting for a real external change, wait. Do not fabricate success.'}
    if mission.get('review_instructions'):
        # Current user guidance is critical state, never an optional memory hit
        # or a clipped excerpt. Older versions remain in the saved review log.
        base['review_instructions']=mission['review_instructions']
        last=mission.get('review_history',[])[-1:]
        if last:
            base['reviewed_problem']={'reported_error':clip(last[0].get('previous_error') or '',1200),
                'action_under_review':clip(last[0].get('pending_action'),1200),
                'resolution':last[0].get('resolution'),
                'rule':'User review is guidance, not proof that an external action succeeded.'}
    from academic_policy import instruction_suffix
    instruction += instruction_suffix(store.root)
    def messages(value):
        # Present actual actions and their results as exchanges, as in chat.
        # The ledger remains immutable; these are evidence, not replay requests.
        state = dict(value)
        last = state.pop('last_completed_step', None)
        feedback = state.pop('planning_feedback', None)
        result = [{"role": "system", "content": instruction}, {"role": "user", "content": encoded(state)}]
        if last:
            result.append({'role':'assistant','content':encoded(last['action'])})
            evidence={'last_completed_step':last}
            if 'scheduled_run' in state:evidence['scheduled_run']=state['scheduled_run']
            result.append({'role':'user','content':encoded(evidence)})
        if feedback:
            result.append({'role':'assistant','content':encoded(feedback['rejected_proposal'])})
            result.append({'role':'user','content':encoded({'planning_feedback':feedback})})
        return result
    if budget.count(messages(base)) > budget.limit:
        raise MissionContextError("The complete objective, review instructions, access mode and child state do not fit this model's context. No action was executed; choose a larger context or shorten the objective/review instructions.")
    full = {**base, "recent_history": [{"step": i+1, **row, "result": result_value(row.get('result', ''))} for i, row in enumerate(mission["history"])],
            "recent_notes": notes}
    compacted = budget.count(messages(full)) > int(budget.limit*.78) or len(mission["history"]) > 8
    chosen = dict(base)
    if not compacted:
        chosen = full
    else:
        chosen["context_compacted"] = True
        # Soft threshold leaves room for the next tool result and output tokens.
        soft = max(budget.count(messages(chosen)), int(budget.limit*.78))
        def add(key, value):
            candidate = {**chosen, key: value}
            if budget.count(messages(candidate)) <= soft:
                chosen[key] = value
                return True
            return False
        # Preserve the most recent outcomes first; huge tool logs get excerpts.
        recent = []
        for i in range(len(mission["history"])-1, max(-1, len(mission["history"])-5), -1):
            row = mission["history"][i]
            card = {"step": i+1, "action": result_value(clip(row["action"], 500)), "result": result_value(clip(row.get("result", ""), 900))}
            if add("recent_history", [card]+recent): recent.insert(0, card)
        add("recent_notes", clip(notes, 1000))
        words = set(re.findall(r"\w+", mission["objective"].lower()))
        def relevance(card):
            # Stable evidence selection; note/remember decisions and matching
            # objective terms outrank repetitive diagnostic/log noise.
            text = card["action"]+" "+card["result"]
            return (len(words & set(re.findall(r"\w+", text.lower()))), card["step"])
        selected = []
        for card in sorted(index["records"], key=relevance, reverse=True):
            item = {k: card[k] for k in ("step", "action", "result")}
            if add("earlier_evidence", sorted(selected+[item], key=lambda c: c["step"])): selected.append(item)
    result = messages(chosen)
    count = budget.count(result)
    if count > budget.limit: raise MissionContextError("Mission context exceeds its input budget; no action executed")
    require_space(store.root, 32768, for_outputs=True)
    atomic_json(store.folder(mission["id"])/"context-status.json", {
        "compacted": compacted, "through": index["through"], "history_records": len(mission["history"]),
        "input_tokens_or_upper_bound": count, "count_method": budget.method, "context_tokens": context_tokens,
        "output_tokens_reserved": output_tokens, "headroom_tokens": HEADROOM,
        "full_history_preserved": True, "updated_at": time.time()})
    return result
