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


def post(path, value):
    req = urllib.request.Request(_instance_url('qwen', '')+path, encoded(value).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read(8*1024**2+1)
    if len(raw) > 8*1024**2: raise ValueError("Context endpoint response exceeds limit")
    return json.loads(raw)


class Budget:
    def __init__(self, context_tokens, api=post):
        self.limit = int(context_tokens)-OUTPUT_TOKENS-HEADROOM
        self.api = api
        self.method = "rendered-template-tokenizer"
        self.cache = {}

    def count(self, messages):
        key = encoded(messages)
        if key in self.cache: return self.cache[key]
        if self.method == "rendered-template-tokenizer":
            try:
                prompt = self.api("/apply-template", {"messages": messages,
                    "chat_template_kwargs": {"enable_thinking": False}})["prompt"]
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


def build_messages(store, mission, instruction, children, notes, context_tokens, api=post):
    from mission_runner import MissionContextError
    budget = Budget(context_tokens, api)
    index = rolling_index(store, mission)
    # Critical state is never sourced from a summary or shortened to fit.
    base = {"objective": mission["objective"], "mode": mission["mode"],
            "steps_remaining": mission["max_steps"]-mission["steps"],
            "pending_action": mission.get("pending_action"),
            "subtasks": [{"id": c["id"], "status": c["status"], "objective": c["objective"]} for c in children],
            "completed_records": len(mission["history"]),
            "history_rule": "Records 1..completed_records already ran. Use history(start,count) for evidence before repeating an older action."}
    from academic_policy import instruction_suffix
    instruction += instruction_suffix(store.root)
    def messages(value):
        return [{"role": "system", "content": instruction}, {"role": "user", "content": encoded(value)}]
    if budget.count(messages(base)) > budget.limit:
        raise MissionContextError("The complete objective, access mode and child state do not fit this model's context. No action was executed; choose a larger context or shorten the objective.")
    full = {**base, "recent_history": [{"step": i+1, **row} for i, row in enumerate(mission["history"])],
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
            card = {"step": i+1, "action": clip(row["action"], 500), "result": clip(row.get("result", ""), 900)}
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
        "output_tokens_reserved": OUTPUT_TOKENS, "headroom_tokens": HEADROOM,
        "full_history_preserved": True, "updated_at": time.time()})
    return result
