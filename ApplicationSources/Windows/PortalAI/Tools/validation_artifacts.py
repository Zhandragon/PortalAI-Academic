"""Synthetic validation outputs, separate from signed-in user diagnostics."""
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Agent'))
from profile_paths import capture, private_path, _contained, _relative, ProfileLocked

MARKER = '.portalai-synthetic-validation.json'
IDENTITY = {'version': 1, 'purpose': 'PortalAI synthetic offline validation artifacts'}


class ValidationArtifacts:
    def __init__(self, root, explicit=None):
        self.root = Path(root).resolve()
        self.synthetic = explicit is not None
        self.context = None
        if not self.synthetic:
            self.context = capture(self.root)
            self.base = private_path(self.root, 'Data/Maintenance/LinuxValidation')
        else:
            path = Path(explicit)
            if not path.is_absolute():
                raise ValueError('Synthetic artifacts directory must be absolute')
            _contained(Path(path.anchor), path)
            self.base = path.resolve()
            if self.base == Path(self.base.anchor) or self.base == self.root:
                raise ValueError('Choose a dedicated synthetic validation directory')
            if self.base.is_relative_to(self.root):
                approved = self.root/'Maintenance/Validation'
                if self.base == approved or not self.base.is_relative_to(approved):
                    raise ValueError('In-bundle synthetic artifacts belong below Maintenance/Validation')
            marker = self.base/MARKER
            _contained(Path(marker.anchor), marker)
            if marker.exists():
                if marker.stat().st_size > 4096 or json.loads(marker.read_text()) != IDENTITY:
                    raise ValueError('Synthetic artifacts marker does not match')
            elif self.base.exists() and any(self.base.iterdir()):
                raise ValueError('Synthetic artifacts directory must be empty or already marked')
        self.path().mkdir(parents=True, exist_ok=True)
        if self.synthetic and not (self.base/MARKER).exists():
            with (self.base/MARKER).open('x', encoding='utf-8') as output:
                json.dump(IDENTITY, output)

    def path(self, relative=None):
        if not self.synthetic and capture(self.root) != self.context:
            raise ProfileLocked('Validation belongs to a login that has ended')
        _contained(Path(self.base.anchor), self.base)
        path = self.base if relative is None else self.base/_relative(relative)
        return _contained(self.base, path)


def add_artifact_arguments(parser, *, media=False):
    parser.add_argument('--artifacts-dir', help='Absolute empty/marked directory for synthetic test artifacts; default uses the active profile')
    if media:
        parser.add_argument('--media-iso', help='Existing read-only media test ISO (avoids rebuilding duplicate test data)')


def media_iso(root, artifacts, explicit=None):
    path = Path(explicit).resolve() if explicit else artifacts.path('media-science.iso')
    if not explicit and not path.is_file():
        # The old ISO contains only source and distributed fixture assets. Reuse
        # it as immutable test input, never as an unauthenticated output path.
        path = Path(root)/'Cache/LinuxValidation/media-science.iso'
    _contained(Path(path.anchor), path)
    if not path.is_file():
        raise FileNotFoundError('Build the Linux media test ISO or specify --media-iso')
    return path


def require_output_space(root, artifacts, additional_bytes, *, for_outputs=False):
    from runtime_policy import require_space
    require_space(root, additional_bytes, for_outputs=for_outputs)
    usage=shutil.disk_usage(artifacts.path())
    if usage.free < additional_bytes + max(1024**3, int(usage.total*.05)):
        raise RuntimeError('Validation artifacts would cross the destination free-space floor')
