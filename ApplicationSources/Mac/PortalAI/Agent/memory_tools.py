from __future__ import annotations

"""PortableAI read-only chat-history / recall helper.

v15.126 adds a single bounded `recall` route for broad cross-session questions,
raw-session fallback while persistent-memory distillation is still backfilling,
and defensive parsing for legacy/malformed saved messages.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_paths import private_path

VERSION = "15.126a"
STOP = {
    "the","and","for","that","this","with","from","have","has","had","are","was","were",
    "you","your","our","but","not","can","could","would","should","about","into","than",
    "then","what","when","where","which","while","how","why","who","will","just","also",
    "use","using","make","want","need","like","some","more","most","very","all","any",
    "its","they","them","their","there","here","been","being","does","did","doing",
    "remember","recall","memory","conversation","conversations","chat","chats","past","previous",
}


def root_dir(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def tokens(text: str) -> set[str]:
    vals = re.findall(r"[a-z0-9][a-z0-9_+.-]{2,}", str(text or "").lower())
    return {x for x in vals if x not in STOP and not x.isdigit()}


def clip(text, n: int) -> str:
    if isinstance(text, (dict, list, tuple)):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:
            text = str(text)
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= n else s[:max(0,n-1)].rstrip() + "…"


def message_text(m) -> str:
    if isinstance(m, dict):
        return clip(m.get("content") or m.get("text") or "", 100000)
    return clip(m, 100000)


def message_role(m) -> str:
    return str(m.get("role") or "unknown") if isinstance(m, dict) else "unknown"


def safe_messages(session: dict) -> list:
    rows = session.get("messages") if isinstance(session, dict) else []
    return list(rows) if isinstance(rows, list) else []


def sessions(root: Path, *, metadata=False) -> list[dict]:
    d = private_path(root, 'Data/Chat/Sessions')
    from profile_hydration import file_listing
    listing = file_listing(root, 'Data/Chat/Sessions')
    catalog = load_json(private_path(root, 'Data/Chat/session_catalog.json'), {}).get('sessions', {}) if metadata else {}
    rows=[]
    for name in listing['names']:
        if Path(name).parent.as_posix() != 'Data/Chat/Sessions' or Path(name).suffix != '.json': continue
        p = d/Path(name).name
        cached = catalog.get(p.stem)
        if (metadata and isinstance(cached, dict) and cached.get('_sha256') and
                cached['_sha256'] == listing['pending_hashes'].get(name)):
            x = cached
        else: x=load_json(private_path(root, name),None)
        if isinstance(x,dict) and x.get("id"):
            x=dict(x); x["_path"]=p
            rows.append(x)
    rows.sort(key=lambda x: float(x.get("updated") or x.get("created") or 0), reverse=True)
    return rows


def memory_index(root: Path) -> dict:
    x=load_json(private_path(root, 'Data/Memory/memory_index.json'),{})
    return x if isinstance(x,dict) else {}


def memory_state(root: Path, sid: str) -> dict:
    idx=memory_index(root)
    st=(idx.get("chats") or {}).get(str(sid or ""),{})
    if not isinstance(st,dict): st={}
    return {
        "included": bool(st.get("included",True)),
        "recall_enabled": bool(st.get("recall_enabled",True)),
        "distilled_messages": int(st.get("cursor") or 0),
        "capsule": str(st.get("capsule") or ""),
        "tags": list(st.get("tags") or []),
    }


def render_message(m, max_chars: int = 1200) -> str:
    role=message_role(m).upper()
    text=clip(message_text(m),max_chars)
    return f"{role}: {text}" if text else ""


def user_excerpt(session: dict, max_chars: int = 1800) -> str:
    msgs=safe_messages(session)
    user_rows=[message_text(m) for m in msgs if message_role(m).lower()=="user" and message_text(m).strip()]
    if not user_rows:
        # Legacy sessions can lack role labels; bounded fallback still avoids tool/reasoning floods.
        user_rows=[message_text(m) for m in msgs if message_text(m).strip()][:4]
    if not user_rows:
        return ""
    picks=[]
    if len(user_rows)<=4:
        picks=user_rows
    else:
        picks=user_rows[:2]+user_rows[-2:]
    out=[]; used=0
    for row in picks:
        row=clip(row,700)
        if not row: continue
        if used+len(row)+3>max_chars: break
        out.append(row); used+=len(row)+3
    return " | ".join(out)


def session_substance(session: dict) -> tuple[float,int,int]:
    msgs=safe_messages(session)
    users=[message_text(m) for m in msgs if message_role(m).lower()=="user" and message_text(m).strip()]
    user_chars=sum(len(x) for x in users)
    score=len(users)*5.0 + min(35.0,user_chars/450.0) + min(20.0,len(msgs)/2.0)
    return score,len(users),user_chars


def resolve_session(root: Path, selector: str) -> dict | None:
    sel=str(selector or "").strip()
    if not sel: return None
    if re.fullmatch(r'[A-Za-z0-9_-]{1,128}', sel):
        exact = load_json(private_path(root, f'Data/Chat/Sessions/{sel}.json'), None)
        if isinstance(exact, dict) and exact.get('id') == sel: return exact
    rows=sessions(root)
    exact=next((s for s in rows if str(s.get("id") or "")==sel),None)
    if exact: return exact
    pref=[s for s in rows if str(s.get("id") or "").startswith(sel)]
    if len(pref)==1: return pref[0]
    title=[s for s in rows if str(s.get("title") or "").strip().casefold()==sel.casefold()]
    return title[0] if len(title)==1 else None


def _eligible(root: Path, current_sid: str, rows=None) -> list[dict]:
    idx=memory_index(root); chats=idx.get("chats") if isinstance(idx.get("chats"),dict) else {}
    out=[]
    for s in sessions(root) if rows is None else rows:
        sid=str(s.get("id") or "")
        if current_sid and sid==current_sid: continue
        st=chats.get(sid) if isinstance(chats.get(sid),dict) else {}
        if st and not st.get("included",True): continue
        out.append(s)
    return out


def build_recall(root: Path, current_sid: str, limit: int, max_chars: int, query: str = "") -> dict:
    idx=memory_index(root); chats=idx.get("chats") if isinstance(idx.get("chats"),dict) else {}
    facts=idx.get("facts") if isinstance(idx.get("facts"),dict) else {}
    current_state=chats.get(str(current_sid or "")) if isinstance(chats.get(str(current_sid or "")),dict) else {}
    if current_sid and current_state and not current_state.get("recall_enabled",True):
        return {
            "success":True,
            "mode":"bounded_cross_session_recall",
            "current_session_id":current_sid,
            "cross_session_recall_enabled":False,
            "reason":"current_chat_isolated",
            "persistent_index_ready":bool(facts or any(isinstance(x,dict) and str(x.get("capsule") or "").strip() for x in chats.values())),
            "stored_facts":len(facts),
            "stored_capsules":sum(1 for x in chats.values() if isinstance(x,dict) and str(x.get("capsule") or "").strip()),
            "raw_fallback_used":False,
            "sessions_considered":0,
            "returned":0,
            "query":query or None,
            "memories":[],
        }
    q=tokens(query)
    ranked=[]
    rows = sessions(root)
    now=max([float(s.get("updated") or s.get("created") or 0) for s in rows] or [1.0])
    for s in _eligible(root,current_sid,rows):
        sid=str(s.get("id") or ""); st=chats.get(sid) if isinstance(chats.get(sid),dict) else {}
        cap=clip(st.get("capsule") or "",1800) if st else ""
        excerpt=user_excerpt(s,1800)
        substance,user_turns,user_chars=session_substance(s)
        hay=f"{s.get('title') or ''} {cap} {excerpt} {' '.join(st.get('tags') or []) if st else ''}"
        overlap=len(q & tokens(hay)) if q else 0
        updated=float(s.get("updated") or s.get("created") or 0)
        # Recency is deliberately modest: broad recall should favor substantive chats, not just newest tests.
        age=max(0.0, now-updated)
        recency=max(0.0,4.0-math.log2(1.0+age/86400.0)) if updated else 0.0
        score=substance + overlap*18.0 + recency + (8.0 if cap else 0.0)
        ranked.append((score,updated,{
            "session_id":sid,
            "title":s.get("title") or "Untitled",
            "updated":s.get("updated"),
            "message_count":len(safe_messages(s)),
            "user_turns":user_turns,
            "source":"distilled_capsule" if cap else "raw_session_fallback",
            "capsule":cap or None,
            "excerpt":None if cap else excerpt,
            "tags":list(st.get("tags") or [])[:12] if st else [],
        }))
    ranked.sort(key=lambda x:(x[0],x[1]),reverse=True)
    chosen=[]; used=0
    for _score,_updated,row in ranked:
        body=(row.get("capsule") or row.get("excerpt") or "")
        cost=len(str(row.get("title") or ""))+len(body)+180
        if chosen and used+cost>max_chars: break
        chosen.append(row); used+=cost
        if len(chosen)>=limit: break
    capsules=sum(1 for st in chats.values() if isinstance(st,dict) and str(st.get("capsule") or "").strip())
    return {
        "success":True,
        "mode":"bounded_cross_session_recall",
        "current_session_id":current_sid or None,
        "cross_session_recall_enabled":True,
        "persistent_index_ready":bool(capsules or facts),
        "stored_facts":len(facts),
        "stored_capsules":capsules,
        "raw_fallback_used":any(x.get("source")=="raw_session_fallback" for x in chosen),
        "sessions_considered":len(ranked),
        "returned":len(chosen),
        "query":query or None,
        "memories":chosen,
    }


def cmd_status(args, root: Path):
    rows=sessions(root, metadata=True); sid=str(args.session or "")
    target=next((x for x in rows if str(x.get("id"))==sid),None)
    idx=memory_index(root)
    chats=idx.get("chats") if isinstance(idx.get("chats"),dict) else {}
    facts=idx.get("facts") if isinstance(idx.get("facts"),dict) else {}
    capsules=sum(1 for st in chats.values() if isinstance(st,dict) and str(st.get("capsule") or "").strip())
    backlog=0
    for s in rows:
        ssid=str(s.get("id") or ""); st=chats.get(ssid) if isinstance(chats.get(ssid),dict) else {}
        if st and not st.get("included",True): continue
        if int(st.get("cursor") or 0)<int(s.get('message_count', len(safe_messages(s)))): backlog+=1
    out={
        "success":True,"helper_version":VERSION,
        "sessions_directory":str(private_path(root, 'Data/Chat/Sessions')),
        "session_count":len(rows),"current_session_id":sid or None,
        "current_session_exists":bool(target),"current_session_title":(target or {}).get("title"),
        "current_session_file":str(private_path(root, 'Data/Chat/Sessions')/f"{sid}.json") if sid else None,
        "current_session_memory":memory_state(root,sid) if sid else None,
        "memory_enabled":bool((idx.get("config") or {}).get("enabled",True)),
        "stored_facts":len(facts),"stored_capsules":capsules,"sessions_awaiting_distillation":backlog,
    }
    print(json.dumps(out,ensure_ascii=False,indent=2))


def cmd_recall(args, root: Path):
    print(json.dumps(build_recall(root,str(args.session or ""),args.limit,args.max_chars,args.query or ""),ensure_ascii=False,indent=2))


def cmd_list(args, root: Path):
    exclude=str(args.exclude_session or ""); idx=memory_index(root); chats=idx.get("chats") if isinstance(idx.get("chats"),dict) else {}; out=[]
    for s in sessions(root, metadata=True):
        sid=str(s.get("id") or "")
        if exclude and sid==exclude: continue
        st=chats.get(sid) if isinstance(chats.get(sid),dict) else {}
        out.append({"id":sid,"title":s.get("title") or "Untitled","updated":s.get("updated"),"messages":int(s.get('message_count', len(safe_messages(s)))),"distilled_messages":int(st.get("cursor") or 0),"has_capsule":bool(str(st.get("capsule") or "").strip())})
        if len(out)>=args.limit: break
    print(json.dumps({"success":True,"sessions":out},ensure_ascii=False,indent=2))


def cmd_overview(args, root: Path):
    # Backward-compatible route: unlike v15.124, it does not return [] merely because backfill is unfinished.
    data=build_recall(root,str(args.session or ""),args.limit,12000,"")
    compact=[]
    for m in data.get("memories") or []:
        compact.append({"session_id":m.get("session_id"),"title":m.get("title"),"source":m.get("source"),"capsule":m.get("capsule") or m.get("excerpt"),"tags":m.get("tags") or []})
    print(json.dumps({"success":True,"persistent_index_ready":data.get("persistent_index_ready"),"raw_fallback_used":data.get("raw_fallback_used"),"overview":compact},ensure_ascii=False,indent=2))


def cmd_search(args, root: Path):
    q=tokens(args.query); exclude=str(args.exclude_session or ""); hits=[]
    for s in sessions(root):
        sid=str(s.get("id") or "")
        if exclude and sid==exclude: continue
        title=str(s.get("title") or "")
        best_score=len(q & tokens(title))*8; best=""
        for m in safe_messages(s):
            txt=message_text(m); ov=len(q & tokens(txt))
            if ov:
                score=ov*5 + (2 if message_role(m).lower()=="user" else 0)
                if score>best_score:
                    best_score=score; best=render_message(m,900)
        if best_score:
            hits.append((best_score,float(s.get("updated") or 0),{"session_id":sid,"title":title or "Untitled","score":best_score,"snippet":best or clip(title,900)}))
    hits.sort(key=lambda x:(x[0],x[1]),reverse=True)
    print(json.dumps({"success":True,"query":args.query,"matches":[x[2] for x in hits[:args.limit]]},ensure_ascii=False,indent=2))


def cmd_show(args, root: Path):
    s=resolve_session(root,args.session_id)
    if not isinstance(s,dict):
        print(json.dumps({"success":False,"error":"session_not_found_or_ambiguous","selector":args.session_id},ensure_ascii=False,indent=2))
        return 2
    parts=[]; used=0
    for m in safe_messages(s):
        row=render_message(m,2500)
        if not row: continue
        if used+len(row)>args.max_chars: break
        parts.append(row); used += len(row)+2
    total=sum(len(message_text(m)) for m in safe_messages(s))
    print(json.dumps({
        "success":True,"session_id":s.get("id"),"title":s.get("title"),
        "created":s.get("created"),"updated":s.get("updated"),
        "message_count":len(safe_messages(s)),"transcript":"\n\n".join(parts),"truncated":used < total,
    },ensure_ascii=False,indent=2))
    return 0


def _show_parser(sub, name: str, help_text: str):
    p=sub.add_parser(name,help=help_text); p.add_argument("session_id"); p.add_argument("--max-chars",type=int,default=12000)


def main():
    ap=argparse.ArgumentParser(description="PortableAI read-only chat-history helper")
    ap.add_argument("--root",default=None,help=argparse.SUPPRESS)
    sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("status"); p.add_argument("--session",default="")
    p=sub.add_parser("recall",help="Bounded broad recall across prior sessions with raw fallback while memory backfills"); p.add_argument("--session",default=""); p.add_argument("--limit",type=int,default=8); p.add_argument("--max-chars",type=int,default=14000); p.add_argument("--query",default="")
    p=sub.add_parser("overview"); p.add_argument("--session",default=""); p.add_argument("--limit",type=int,default=6)
    p=sub.add_parser("list"); p.add_argument("--exclude-session",default=""); p.add_argument("--limit",type=int,default=12)
    p=sub.add_parser("search"); p.add_argument("query"); p.add_argument("--exclude-session",default=""); p.add_argument("--limit",type=int,default=5)
    for name in ("show","read","display","open"):
        _show_parser(sub,name,"Read one saved session (aliases are accepted defensively)")
    a=ap.parse_args()
    if hasattr(a,"limit"): a.limit=max(1,min(30,a.limit))
    if hasattr(a,"max_chars"): a.max_chars=max(1000,min(50000,a.max_chars))
    root=root_dir(a.root)
    dispatch={"status":cmd_status,"recall":cmd_recall,"overview":cmd_overview,"list":cmd_list,"search":cmd_search,"show":cmd_show,"read":cmd_show,"display":cmd_show,"open":cmd_show}
    try:
        rc=dispatch[a.cmd](a,root)
        return int(rc or 0)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        # Tool callers need structured failure, not a Python traceback that becomes another reasoning detour.
        print(json.dumps({"success":False,"error":type(exc).__name__,"message":str(exc),"command":a.cmd},ensure_ascii=False,indent=2))
        return 1


if __name__=="__main__":
    raise SystemExit(main())
