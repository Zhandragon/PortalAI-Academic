"""Math problems with a boxed final answer: the task plug-in of the MATH experiment (docs/math_design.md) for the LLM
worker (weightenv/lmo/tasks/llm_worker.py, `init(task='math')`). Pure python at import (math-verify / sympy and pyarrow
are imported on demand), so the torch side, the split script and the CPU tests import it without torch / vLLM. The file
is not called math.py: the worker runs as a script with this directory first on sys.path, where a math.py would
shadow the standard library.

What the plug-in fixes (identical for every arm):
- Data: the MATH training split (DigitalLearningGmbH/MATH-lighteval @0530c786, config 'data': 7,500 problems with
  reference solutions; subject = 'type', level 1-5), split by results/math/data/make_split.py into split.json: dev 500
  (stratified by subject x level) and train (the rest, without the rows that resemble a MATH-500 problem and without
  the near-duplicates of dev problems). Items 'train:<i>' / 'dev:<i>'. Training rows carry the reference solution;
  development rows do not (nothing on the tool side needs it).
- Prompt: the problem + '\\nPlease reason step by step, and put your final answer within \\boxed{}.' (the
  instruction the Qwen3.5 model card recommends for math problems) as the user turn of the non-thinking chat template.
- Answer: the content of the LAST \\boxed{...} (or \\fbox{...}) of the response (hendrycks/math last_boxed_only_string
  + remove_boxed: brace matched; a '\\boxed 5' without braces is read up to the next '$' or line end); a stray
  reasoning block is cut off first. No closed box = no answer (an extraction failure; wrong).
- Gold: the same reading of the reference solution (MATH-500: its 'answer' field, harness only).
- Checker (the reward and every accuracy): math-verify 0.9.0, verify(parse('\\boxed{gold}'), parse('\\boxed{pred}'))
  (symbolic / numeric equivalence, sets, intervals, matrices, text answers). The original MATH checker (hendrycks
  is_equiv: equality after string normalisation, stricter) is reported next to it as accuracy_equiv.
- Reward (GRPO): 1.0 if correct else 0.0; a truncated response (finish 'length') gets the call's truncated_reward (0 in
  GRPO: the non-stop penalty of the IFEval / MMLU-Pro experiments).
math-verify is not in the llmrl / repo venvs: it is imported from MATHVERIFY_PKGS (pip --target directory with
math-verify 0.9.0, latex2sympy2_extended 1.11.0, antlr4-python3-runtime 4.13.2; sympy comes from the venv), appended
to the END of sys.path so that nothing the venv already has is shadowed.
"""
import functools
import hashlib
import json
import os
import re
import sys
import threading

try:   # the multiple-choice task's loop signals (its repetitive_end rule is reused below)
    from weightenv.lmo.tasks.mcqa import loop_signals as mcqa_loop_signals
except ImportError:  # run as a script by path (the worker)
    from mcqa import loop_signals as mcqa_loop_signals

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SCRATCH = os.environ.get("MATH_SCRATCH", "<data>/math")
DATA_DIR = os.path.join(SCRATCH, "data")                  # training data (no evaluation problem)
HARNESS_DIR = os.path.join(SCRATCH, "harness")            # harness-only texts (MATH-500 prompts / responses)
DS_REPO, DS_REV = "DigitalLearningGmbH/MATH-lighteval", "0530c78699ea5e8eb5530600900e1f328b48acad"
TRAIN_PARQUET = os.path.join(DATA_DIR, "math_lighteval_train.parquet")   # config 'data', train-00000-of-00001.parquet
TRAIN_SHA256 = "eca6e667f4305dd5e5ba09b4fd55e7f3174a0fbe361cdfd4c44758b593a76933"
SPLIT_PATH = os.path.join(REPO, "results/math/data/split.json")
LOWDATA_PATH = os.path.join(REPO, "results/math/data/lowdata.json")    # the low-data variant (1,000 training items)
MATHVERIFY_PKGS = os.environ.get("MATHVERIFY_PKGS", "<venvs>/mathverify_pkgs")
N_TRAIN, N_DEV = 6700, 500
SUBJECTS = ("Algebra", "Counting & Probability", "Geometry", "Intermediate Algebra", "Number Theory", "Prealgebra",
            "Precalculus")
LEVELS = (1, 2, 3, 4, 5)

# ---------------------------------------------------------------- prompt
INSTRUCTION = "Please reason step by step, and put your final answer within \\boxed{}."
TEMPLATE = "math_qwen_boxed_v1"


def build_prompt(problem):
    """The user turn: the problem, a newline, Qwen's math instruction."""
    return problem + "\n" + INSTRUCTION


# ---------------------------------------------------------------- the original MATH code (hendrycks/math @985bdc16,
# modeling/dataset/util.py last_boxed_only_string, modeling/eval_math_gpt.py remove_boxed, modeling/math_equivalence.py
# is_equiv; MIT licence). Verbatim apart from the bare `except:` -> `except Exception:`.
def last_boxed_only_string(string):
    idx = string.rfind("\\boxed")
    if idx < 0:
        idx = string.rfind("\\fbox")
        if idx < 0:
            return None
    i = idx
    right_brace_idx = None
    num_left_braces_open = 0
    while i < len(string):
        if string[i] == "{":
            num_left_braces_open += 1
        if string[i] == "}":
            num_left_braces_open -= 1
            if num_left_braces_open == 0:
                right_brace_idx = i
                break
        i += 1
    if right_brace_idx is None:
        retval = None
    else:
        retval = string[idx:right_brace_idx + 1]
    return retval


def remove_boxed(s):
    left = "\\boxed{"
    try:
        assert s[:len(left)] == left
        assert s[-1] == "}"
        return s[len(left):-1]
    except Exception:  # noqa: BLE001
        return None


def _fix_fracs(string):
    substrs = string.split("\\frac")
    new_str = substrs[0]
    if len(substrs) > 1:
        substrs = substrs[1:]
        for substr in substrs:
            new_str += "\\frac"
            if substr[0] == "{":
                new_str += substr
            else:
                try:
                    assert len(substr) >= 2
                except Exception:  # noqa: BLE001
                    return string
                a = substr[0]
                b = substr[1]
                if b != "{":
                    if len(substr) > 2:
                        post_substr = substr[2:]
                        new_str += "{" + a + "}{" + b + "}" + post_substr
                    else:
                        new_str += "{" + a + "}{" + b + "}"
                else:
                    if len(substr) > 2:
                        post_substr = substr[2:]
                        new_str += "{" + a + "}" + b + post_substr
                    else:
                        new_str += "{" + a + "}" + b
    string = new_str
    return string


def _fix_a_slash_b(string):
    if len(string.split("/")) != 2:
        return string
    a = string.split("/")[0]
    b = string.split("/")[1]
    try:
        a = int(a)
        b = int(b)
        assert string == "{}/{}".format(a, b)
        new_string = "\\frac{" + str(a) + "}{" + str(b) + "}"
        return new_string
    except Exception:  # noqa: BLE001
        return string


def _remove_right_units(string):
    # "\\text{ " only ever occurs (at least in the val set) when describing units
    if "\\text{ " in string:
        splits = string.split("\\text{ ")
        assert len(splits) == 2
        return splits[0]
    else:
        return string


def _fix_sqrt(string):
    if "\\sqrt" not in string:
        return string
    splits = string.split("\\sqrt")
    new_string = splits[0]
    for split in splits[1:]:
        if split[0] != "{":
            a = split[0]
            new_substr = "\\sqrt{" + a + "}" + split[1:]
        else:
            new_substr = "\\sqrt" + split
        new_string += new_substr
    return new_string


def _strip_string(string):
    string = string.replace("\n", "")
    string = string.replace("\\!", "")
    string = string.replace("\\\\", "\\")
    string = string.replace("tfrac", "frac")
    string = string.replace("dfrac", "frac")
    string = string.replace("\\left", "")
    string = string.replace("\\right", "")
    string = string.replace("^{\\circ}", "")
    string = string.replace("^\\circ", "")
    string = string.replace("\\$", "")
    string = _remove_right_units(string)
    string = string.replace("\\%", "")
    string = string.replace("\\%", "")   # the original's second line is "\%" (the same two characters)
    string = string.replace(" .", " 0.")
    string = string.replace("{.", "{0.")
    if len(string) == 0:
        return string
    if string[0] == ".":
        string = "0" + string
    if len(string.split("=")) == 2:
        if len(string.split("=")[0]) <= 2:
            string = string.split("=")[1]
    string = _fix_sqrt(string)
    string = string.replace(" ", "")
    string = _fix_fracs(string)
    if string == "0.5":
        string = "\\frac{1}{2}"
    string = _fix_a_slash_b(string)
    return string


def is_equiv(str1, str2):
    """hendrycks/math is_equiv (the original MATH checker): equality after _strip_string."""
    if str1 is None and str2 is None:
        return True
    if str1 is None or str2 is None:
        return False
    try:
        ss1 = _strip_string(str1)
        ss2 = _strip_string(str2)
        return ss1 == ss2
    except Exception:  # noqa: BLE001
        return str1 == str2


# ---------------------------------------------------------------- answer extraction
def answer_text(text):
    """The text the extraction reads: a stray reasoning block cut off (up to the last '</think>')."""
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()
    return text


_BOX_FORMS = re.compile(r"\\boxed|\\fbox")


def _box_at(text, idx):
    """the content of the box that starts at text[idx] ('\\boxed' or '\\fbox'), or None."""
    key = "\\boxed" if text.startswith("\\boxed", idx) else "\\fbox"
    rest = text[idx + len(key):]
    r = rest.lstrip()
    if r.startswith("{"):   # brace matched, as last_boxed_only_string
        depth = 0
        for k, ch in enumerate(r):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out = r[1:k].strip()
                    return out or None
        return None          # not closed (e.g. a response cut inside the box)
    if key == "\\boxed" and rest.startswith(" "):   # '\\boxed 5': up to the next '$' or line end (Qwen's reading)
        out = rest.strip().split("$")[0].split("\n")[0].strip()
        return out or None
    return None


def last_boxed(text):
    """The content of the last box of a text, or None: hendrycks last_boxed_only_string + remove_boxed (the last
    '\\boxed', else the last '\\fbox'; brace matched; an unclosed last box = None), extended to '\\fbox{..}',
    '\\boxed {..}' and '\\boxed 5' (no braces: read up to the next '$' or line end, as Qwen's evaluation reads it).
    An empty box = None."""
    idx = text.rfind("\\boxed")
    if idx < 0:
        idx = text.rfind("\\fbox")
        if idx < 0:
            return None
    return _box_at(text, idx)


def boxed_values(text):
    """the distinct contents of every box in a text."""
    return {b for b in (_box_at(text, m.start()) for m in _BOX_FORMS.finditer(text)) if b is not None}


def extract(text):
    """(answer or None, number of boxes in the text)."""
    t = answer_text(text)
    return last_boxed(t), len(_BOX_FORMS.findall(t))


def gold_of_solution(solution):
    """The gold answer of a reference solution (the last box)."""
    return last_boxed(solution)


# ---------------------------------------------------------------- loop signals
LOOP_MAX_PERIOD, LOOP_MIN_REPEATS, LOOP_MIN_SPAN = 200, 3, 40


def loop_signals(text):
    """Two signals of a response's END (2026-10-04):
    - verbatim_loop_end: without its last word (a response cut at the token cap usually stops inside a word, which broke
      mcqa.loop_signals' test: it found 12 of the base model's 175 cut dev answers), the text ends with one block of
      1..200 words repeated in a row at least 3 times and over at least 40 words (period test: the phase does not
      matter). Math loops are longer than the multiple-choice ones (a re-derivation of several lines); base model, dev
      greedy at 4,096 tokens: 43 of 175 cut answers, 0 of 325 finished ones;
    - repetitive_end: mcqa.loop_signals' rule (in the last 200 words, the 4-word positions whose phrase occurs 3+ times
      there are at least half of all positions: circling with small variations)."""
    w = text.split()[:-1]
    n = len(w)
    verbatim = False
    for p in range(1, LOOP_MAX_PERIOD + 1):
        reps = max(LOOP_MIN_REPEATS, -(-LOOP_MIN_SPAN // p))
        if reps * p > n:
            break
        blk = w[n - p:]
        if all(w[n - (j + 1) * p:n - j * p] == blk for j in range(1, reps)):
            verbatim = True
            break
    return {"verbatim_loop_end": verbatim, "repetitive_end": mcqa_loop_signals(text)["repetitive_end"]}


# ---------------------------------------------------------------- the checker (math-verify)
_MV = []


def mv():
    """the math_verify module (from MATHVERIFY_PKGS when the venv does not have it)."""
    if not _MV:
        try:
            import math_verify  # noqa: PLC0415
        except ImportError:
            if MATHVERIFY_PKGS not in sys.path:
                sys.path.append(MATHVERIFY_PKGS)
            import math_verify  # noqa: PLC0415
        _MV.append(math_verify)
    return _MV[0]


def _timeouts():
    """math-verify's timeouts use signal.alarm, which works only in the main thread; elsewhere they raise and the
    library would silently return 'not equal'. Off the main thread the checks run without its timeouts."""
    return 5 if threading.current_thread() is threading.main_thread() else None


@functools.lru_cache(maxsize=1 << 16)
def _parsed(s, to):
    return mv().parse("\\boxed{" + s + "}", parsing_timeout=to)


def is_correct(pred, gold):
    """math-verify equivalence of a boxed answer and the gold answer (False for no answer / unparseable gold)."""
    if pred is None or gold is None:
        return False
    to = _timeouts()
    g, p = _parsed(gold, to), _parsed(pred, to)
    if not g or not p:
        return False
    try:
        return bool(mv().verify(g, p, timeout_seconds=to))
    except Exception:  # noqa: BLE001
        return False


def score(row, text, finish="stop", truncated_reward=None):
    """record of one response: pred (<= 200 characters shown), boxed, boxes, correct (math-verify), equiv (the
    original MATH checker), reward."""
    pred, nbox = extract(text)
    ok = is_correct(pred, row["gold"])
    rec = {"pred": pred if pred is None or len(pred) <= 200 else pred[:200] + "...", "boxed": pred is not None,
           "boxes": nbox, "correct": bool(ok), "equiv": bool(pred is not None and is_equiv(pred, row["gold"])),
           "reward": 1.0 if ok else 0.0}
    if truncated_reward is not None and finish == "length":
        rec["reward"] = float(truncated_reward)
    return rec


def metrics(records):
    """accuracy (math-verify), accuracy_equiv (the original MATH checker), no_boxed (no closed box = extraction
    failure), mean reward."""
    n = len(records)
    if n == 0:
        return {}
    return {"n_problems": n, "accuracy": sum(r["correct"] for r in records) / n,
            "accuracy_equiv": sum(r["equiv"] for r in records) / n,
            "no_boxed": sum(not r["boxed"] for r in records) / n,
            "mean_reward": sum(r["reward"] for r in records) / n}


def _cell():
    return {"n": 0, "correct": 0, "truncated": 0, "no_boxed": 0, "wrong_answer": 0, "_tok": []}


def _close(c):
    tok = sorted(c.pop("_tok"))
    c["tokens_p50"] = tok[len(tok) // 2] if tok else None
    return c


def diagnostics(records, rows, languages=True):  # noqa: ARG001 - same signature as the IFEval task
    """Aggregate behaviour of scored responses: lengths, truncation, answers without a closed box (cut / finished),
    several different boxes, loop signals at the end (loop_signals), accuracy of finished / cut responses, the
    checkers' disagreements, per subject and per level (n, correct, truncated, no box, wrong_answer = finished with a box
    but wrong, median length). The outcome of a response is one of: correct (a box with the right answer; a cut response
    can be correct when its box came before the cap), wrong_answer (finished, boxed, wrong), no box although finished,
    cut without a right box (outcomes)."""
    n = len(records)
    if n == 0:
        return {}
    lens = sorted(r["n_tokens"] for r in records)
    by_s, by_l = {}, {}
    empty = think = verbatim = rep = several = nobox_fin = nobox_cut = 0
    fin_ok = fin_n = cut_ok = cut_n = mv_only = eq_only = wrong_ans = 0
    loop_cut = 0
    tok_ok, tok_bad = [], []
    for r, row in zip(records, rows):
        t = answer_text(r["response"])
        think += int("<think>" in r["response"] or "</think>" in r["response"])
        empty += int(not t.strip())
        ls = loop_signals(t)
        verbatim += int(ls["verbatim_loop_end"])
        rep += int(ls["repetitive_end"])
        several += int(len(boxed_values(t)) > 1)
        cut = r["finish"] == "length"
        wrong = int(not cut and r["boxed"] and not r["correct"])
        wrong_ans += wrong
        if cut:
            cut_n += 1
            cut_ok += int(r["correct"])
            nobox_cut += int(not r["boxed"])
            loop_cut += int(ls["verbatim_loop_end"] or ls["repetitive_end"])
        else:
            fin_n += 1
            fin_ok += int(r["correct"])
            nobox_fin += int(not r["boxed"])
        mv_only += int(r["correct"] and not r["equiv"])
        eq_only += int(r["equiv"] and not r["correct"])
        (tok_ok if r["correct"] else tok_bad).append(r["n_tokens"])
        for key, d in ((row.get("subject", "?"), by_s), (str(row.get("level", "?")), by_l)):
            c = d.setdefault(key, _cell())
            c["n"] += 1
            c["correct"] += int(r["correct"])
            c["truncated"] += int(cut)
            c["no_boxed"] += int(not r["boxed"])
            c["wrong_answer"] += wrong
            c["_tok"].append(r["n_tokens"])
    tok_ok.sort()
    tok_bad.sort()
    return {"n": n, "tokens_p50": lens[n // 2], "tokens_p95": lens[min(n - 1, int(0.95 * n))],
            "tokens_mean": sum(lens) / n, "truncated": cut_n / n, "empty": empty / n, "think_tags": think,
            "no_boxed": (nobox_fin + nobox_cut) / n, "no_boxed_finished": nobox_fin / n, "no_boxed_cut": nobox_cut / n,
            "several_boxed_answers": several / n, "verbatim_loop_end": verbatim / n, "repetitive_end": rep / n,
            "outcomes": {"correct": sum(r["correct"] for r in records) / n, "wrong_answer": wrong_ans / n,
                         "no_boxed_finished": nobox_fin / n,
                         "cut_not_correct": (cut_n - cut_ok) / n},
            "cut_with_loop_signal": loop_cut / cut_n if cut_n else None,
            "accuracy_finished": fin_ok / fin_n if fin_n else None,
            "accuracy_truncated": cut_ok / cut_n if cut_n else None,
            "checkers": {"math_verify_only": mv_only, "equiv_only": eq_only},
            "tokens_p50_correct": tok_ok[len(tok_ok) // 2] if tok_ok else None,
            "tokens_p50_wrong": tok_bad[len(tok_bad) // 2] if tok_bad else None,
            "by_subject": {k: _close(by_s[k]) for k in sorted(by_s)}, "by_level": {k: _close(by_l[k]) for k in sorted(by_l)}}


# ---------------------------------------------------------------- data
def norm_problem(s):
    import unicodedata  # noqa: PLC0415
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s).lower()).strip()


def phash(problem, solution=""):
    return hashlib.sha256(json.dumps([problem, solution]).encode()).hexdigest()[:16]


def read_parquet_columns(path, columns):
    """{column: list} of a parquet file by pyarrow (the llmrl venv has it; the repo venv gets it from MATHVERIFY_PKGS,
    appended to the end of sys.path like math-verify)."""
    try:
        import pyarrow.parquet as pq  # noqa: PLC0415
    except ImportError:
        if MATHVERIFY_PKGS not in sys.path:
            sys.path.append(MATHVERIFY_PKGS)
        import pyarrow.parquet as pq  # noqa: PLC0415
    t = pq.read_table(path, columns=list(columns))
    return {c: t.column(c).to_pylist() for c in columns}


def load_split(split_path=SPLIT_PATH, parquet=TRAIN_PARQUET):
    """{'train': [row dicts], 'dev': [row dicts]}: id, row (parquet index), subject, level, group, problem, gold, prompt
    (the user turn); training rows also carry the reference solution."""
    sp = json.load(open(split_path))
    if sp["revision"] != DS_REV:
        raise RuntimeError(f"split.json revision {sp['revision']} != {DS_REV}")
    if (len(sp["train_rows"]), len(sp["dev_rows"])) != (N_TRAIN, N_DEV):
        raise RuntimeError(f"split.json sizes {len(sp['train_rows'])} / {len(sp['dev_rows'])} != {N_TRAIN} / {N_DEV}")
    df = read_parquet_columns(parquet, ("problem", "solution", "type", "level"))
    out = {}
    for split in ("train", "dev"):
        rows = []
        for i, (r, h) in enumerate(zip(sp[f"{split}_rows"], sp[f"{split}_hashes"])):
            x = {k: v[r] for k, v in df.items()}
            prob, sol = str(x["problem"]), str(x["solution"])
            if phash(prob, sol) != h:
                raise RuntimeError(f"split.json hash mismatch at {split}:{i} (row {r})")
            row = {"id": f"{split}:{i}", "row": int(r), "subject": str(x["type"]), "level": int(x["level"][-1]),
                   "group": int(sp[f"{split}_groups"][i]), "problem": prob, "gold": gold_of_solution(sol),
                   "prompt": build_prompt(prob)}
            if split == "train":
                row["solution"] = sol
            rows.append(row)
        out[split] = rows
    return out


def lowdata_items(path=LOWDATA_PATH):
    """the training items of the LOW-DATA variant (results/math/data/make_lowdata.py: 1,000 of the 6,700 training
    problems, stratified by subject x level, one per near-duplicate group), as 'train:<k>' ids. Same dev split and final
    evaluation as the main setting; an arm of this variant trains on these items only."""
    low = json.load(open(path))
    items = list(low["items"])
    if len(items) != low["n"] or len(set(items)) != len(items):
        raise RuntimeError(f"{path}: {len(items)} items, expected {low['n']} distinct")
    for it in items:
        if not it.startswith("train:") or not 0 <= int(it.split(":")[1]) < N_TRAIN:
            raise RuntimeError(f"{path}: bad item {it!r}")
    return items


# ---------------------------------------------------------------- the worker plug-in
def _tool_max_new_tokens():
    """the tool worker's limit on new tokens: 4,096 (every arm, the LMO's tools and the dev evaluation). The environment
    variable MATH_MAX_NEW_TOKENS (4,096..16,384) raises it for a researcher check only (e.g. how many GRPO rollouts a
    longer cap would finish: scripts/math_base_eval.py tool --sample-max-tokens 8192); runs of the arms and the LMO
    leave it unset, and info() reports the value in force."""
    v = int(os.environ.get("MATH_MAX_NEW_TOKENS", "4096"))
    if not 4096 <= v <= 16384:
        raise ValueError(f"MATH_MAX_NEW_TOKENS={v}: must be 4096..16384")
    return v


TOOL_MAX_NEW_TOKENS = _tool_max_new_tokens()

FAKE_CANNED = ("We add the numbers, so the answer is $\\boxed{1}$.", "Thus the result is \\boxed{\\frac{1}{2}}.",
               "I am not sure how to solve this.", "Let x = 3. Checking: 3 + 3 = 6, so \\boxed{3}",
               "The answer is 2, or maybe \\boxed{4} ... wait, \\boxed{2}")


class MathTask:
    """Task plug-in of llm_worker.Worker (see IFEvalTask there for the interface)."""
    name = "math"
    sizes = {"train": N_TRAIN, "dev": N_DEV}
    max_new_tokens = TOOL_MAX_NEW_TOKENS     # 4,096 (prompts <= 2,048 tokens by the split filter + 4,096 new
    max_model_len = 2048 + TOOL_MAX_NEW_TOKENS   # = max_model_len 6,144); researcher checks only: MATH_MAX_NEW_TOKENS
    final_max_model_len = 40960              # harness engine: Qwen's sampling settings up to 32,768 new tokens
    eval_max_tokens = 4096
    fake_canned = FAKE_CANNED
    metric = "accuracy"

    def load(self, split_path=None, parquet=None):
        return load_split(split_path or SPLIT_PATH, parquet or TRAIN_PARQUET)

    def score(self, row, text, finish, loose=True, truncated_reward=None):  # noqa: ARG002 - no loose variant
        return score(row, text, finish, truncated_reward)

    def metrics(self, records):
        return metrics(records)

    def diagnostics(self, records, rows, languages=True):
        return diagnostics(records, rows, languages)

    def full(self, rec):
        return bool(rec["correct"])

    def groups(self, row, rec):
        return [(row["subject"], bool(rec["correct"])), (f"level {row['level']}", bool(rec["correct"]))]

    def info(self):
        return {"data": {"repo": DS_REPO, "revision": DS_REV, "config": "data (train split)",
                         "split": os.path.relpath(SPLIT_PATH, REPO), "n_train": N_TRAIN, "n_dev": N_DEV,
                         "template": TEMPLATE, "max_new_tokens": self.max_new_tokens},
                "reward": "1 if the last \\boxed{} answer is equivalent to the reference answer (math-verify), else 0; "
                          "a truncated response scores truncated_reward (0 in GRPO)"}

    def final_eval(self, worker, tag, sets=None, settings=None, harness_dir=None, options=None):
        """HARNESS ONLY (the caller checked the role): MATH-500 (and the dev split) with the harness settings."""
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        import math_harness as H  # noqa: PLC0415 - harness-only module (evaluation problems)
        return H.final_eval(worker, tag, sets=sets, settings=settings, harness_dir=harness_dir, options=options)
