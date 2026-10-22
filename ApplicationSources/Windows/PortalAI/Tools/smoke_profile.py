"""Private, epoch-bound paths for bounded live smoke tests."""
from pathlib import Path
import json
import os
import uuid

from profile_paths import capture, private_path, ProfileLocked, _relative, _contained


class SmokeProfile:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.context = capture(self.root)
        self.relative = 'Data/Maintenance/Smoke/' + uuid.uuid4().hex

    def check(self):
        if capture(self.root) != self.context:
            raise ProfileLocked('The smoke-test login ended')

    def path(self, relative):
        self.check()
        return private_path(self.root, self.relative + '/' + _relative(relative), context=self.context)

    def outputs(self, folder):
        self.check()
        return private_path(self.root, 'Outputs/' + _relative(folder), context=self.context)

    def save(self, relative, data):
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        identity = None
        published = False
        try:
            with temporary.open('x', encoding='utf-8') as output:
                json.dump(data, output, indent=2)
                output.flush(); os.fsync(output.fileno())
                stat = os.fstat(output.fileno())
                identity = (stat.st_dev, stat.st_ino)
            self.check()
            _contained(self.root, path)
            temporary.replace(path)
            published = True
            self.check()
            return path
        except BaseException:
            if published:
                _contained(self.root, path)
                if path.is_file() and not path.is_symlink():
                    stat = path.lstat()
                    if (stat.st_dev, stat.st_ino) == identity:
                        path.unlink()
            raise
        finally:
            _contained(self.root, temporary)
            temporary.unlink(missing_ok=True)
