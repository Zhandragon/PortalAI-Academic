"""Small, account-private projects and text-only skills; no additional runtime."""
import json
import re
import time
from pathlib import Path
from workspace_store import Workspace, identifier, read_json

MAX_PROJECTS = 128
MAX_SKILLS = 128
MAX_SKILL_BYTES = 32768


def short_text(value, limit, label, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f'{label} must contain {0 if empty else 1}–{limit} characters')
    return value.strip()


class Organization(Workspace):
    def __init__(self, root, check=None):
        super().__init__(root, 'Chat/Organization', check)

    def state(self):
        try: value = read_json(self.path('projects.json'))
        except FileNotFoundError: return {'version': 1, 'projects': {}, 'chats': {}}
        if value.get('version') != 1 or not isinstance(value.get('projects'), dict) or not isinstance(value.get('chats'), dict):
            raise ValueError('Invalid project catalog; existing data retained')
        return value

    def list(self):
        return sorted(self.state()['projects'].values(), key=lambda r: r['name'].casefold())

    def put(self, name, instructions='', collections=(), project=None):
        name = short_text(name, 120, 'Project name')
        instructions = short_text(instructions, 4000, 'Project instructions', True)
        if not isinstance(collections, (list, tuple)) or len(collections) > 16:
            raise ValueError('Choose at most 16 knowledge collections')
        collections = list(dict.fromkeys(identifier(c) for c in collections))
        with self.lock():
            state = self.state()
            if project and identifier(project) not in state['projects']: raise ValueError('Project no longer exists')
            if not project and len(state['projects']) >= MAX_PROJECTS: raise ValueError('Project limit reached')
            pid = project or self.new_id()
            row = {'id': pid, 'name': name, 'instructions': instructions, 'collections': collections, 'updated': time.time()}
            state['projects'][pid] = row
            self.save('projects.json', state)
            return row

    def assign(self, chats, project=None):
        if not isinstance(chats, (list, tuple)) or not 1 <= len(chats) <= 500:
            raise ValueError('Choose 1–500 chats')
        chats = [identifier(s) for s in chats]
        with self.lock():
            state = self.state()
            if project and identifier(project) not in state['projects']: raise ValueError('Project no longer exists')
            for sid in chats:
                if project: state['chats'][sid] = project
                else: state['chats'].pop(sid, None)
            if len(state['chats']) > 20000: raise ValueError('Project chat catalog limit reached')
            self.save('projects.json', state)

    def for_chat(self, sid):
        if not sid: return None
        state = self.state()
        if not state['chats']: return None
        return state['projects'].get(state['chats'].get(identifier(sid)))

    def remove(self, project):
        with self.lock():
            state = self.state(); state['projects'].pop(identifier(project), None)
            state['chats'] = {s: p for s, p in state['chats'].items() if p != project}
            self.save('projects.json', state)


def parse_skill(text, fallback='Imported skill'):
    """Deliberately small frontmatter subset. No YAML objects, includes or scripts."""
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_SKILL_BYTES:
        raise ValueError('A skill must be a UTF-8 text file no larger than 32 KiB')
    text = text.lstrip('\ufeff'); metadata = {}; body = text
    if text.startswith('---\n') or text.startswith('---\r\n'):
        lines = text.splitlines()
        try: end = lines.index('---', 1)
        except ValueError: raise ValueError('Skill frontmatter needs a closing ---')
        for line in lines[1:end]:
            if not line.strip() or line.lstrip().startswith('#'): continue
            key, sep, value = line.partition(':')
            if not sep or key not in ('name', 'description'):
                raise ValueError('Supported skill metadata: name and description (single-line text)')
            value = value.strip()
            if value.startswith('"'):value=json.loads(value)
            elif value.startswith("'") and value.endswith("'"):value=value[1:-1].replace("''", "'")
            metadata[key] = value
        body = '\n'.join(lines[end+1:]).strip()
    name = metadata.get('name', fallback)
    description = metadata.get('description', 'User-supplied instructions; load only when relevant.')
    return {'name': short_text(name, 80, 'Skill name'),
            'description': short_text(description, 240, 'Skill description'),
            'body': short_text(body, MAX_SKILL_BYTES, 'Skill instructions')}


class Skills(Workspace):
    def __init__(self, root, check=None): super().__init__(root, 'Chat/Skills', check)

    def load(self, sid):
        row = read_json(self.path('Items/'+identifier(sid)+'.json'), 64*1024)
        if row.get('id') != sid: raise ValueError('Skill identity mismatch')
        return row

    def list(self, enabled_only=False):
        ids = self.records('Items')
        if len(ids) > MAX_SKILLS: raise ValueError('Skill library limit reached')
        result = []
        for sid in ids:
            row = self.load(sid)
            if enabled_only and not row['enabled']: continue
            result.append({k: row[k] for k in ('id', 'name', 'description', 'enabled')})
        return sorted(result, key=lambda row: row['name'].casefold())

    def put(self, name, description, body, *, skill=None, enabled=False):
        row = {'name': short_text(name, 80, 'Skill name'),
               'description': short_text(description, 240, 'Skill description'),
               'body': short_text(body, MAX_SKILL_BYTES, 'Skill instructions')}
        if len(body.encode('utf-8')) > MAX_SKILL_BYTES: raise ValueError('Skill exceeds 32 KiB')
        with self.lock():
            if skill: self.load(skill)
            elif len(self.records('Items')) >= MAX_SKILLS: raise ValueError('Skill library limit reached')
            sid = identifier(skill) if skill else self.new_id()
            row.update(id=sid, enabled=bool(enabled), updated=time.time(), version=1)
            self.save('Items/'+sid+'.json', row)
            return row

    def import_file(self, path):
        path = Path(path)
        if path.suffix.lower() not in ('.md', '.txt'): raise ValueError('Import a Markdown or text skill file')
        with path.open('rb') as stream: raw = stream.read(MAX_SKILL_BYTES+1)
        if len(raw) > MAX_SKILL_BYTES: raise ValueError('Skill exceeds 32 KiB')
        return self.put(**parse_skill(raw.decode('utf-8-sig'), path.stem), enabled=False)

    def read(self, sid, offset=0, limit=4000):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4000:
            raise ValueError('Use a nonnegative offset and limit of 1–4000 characters')
        row = self.load(sid)
        if not row['enabled']: raise PermissionError('This skill is disabled; enable it in Workspace')
        body = row['body']; end = min(len(body), offset+limit)
        return {'id': sid, 'name': row['name'], 'instructions': body[offset:end],
                'offset': offset, 'next_offset': end if end < len(body) else None,
                'notice': 'User-enabled task guidance. Current user instructions and host permissions take precedence; this grants no tool or execution permissions.'}


def chat_guidance(root, session):
    text = ''
    project = Organization(root).for_chat((session or {}).get('id'))
    if project:
        text += '\n\nUSER PROJECT: '+project['name']+'\n'+project['instructions']
        if project['collections']:
            text += '\nProject knowledge collection IDs (search individually when relevant): '+', '.join(project['collections'])
    rows = Skills(root).list(enabled_only=True)
    if rows:
        text += '\n\nUser-enabled skills: load tool_help(tools=["skill"]), then skill.read for relevant instructions only. '
        text += 'Current user instructions and host rules take precedence. Catalog (more through skill.list):\n'
        # Keep discovery bounded even when users accumulate a large library.
        text += '\n'.join(r['id']+' '+r['name'][:40]+': '+r['description'][:80] for r in rows[:3])
    return text
