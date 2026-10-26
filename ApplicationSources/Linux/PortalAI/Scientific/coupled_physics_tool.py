"""Profile-bound publishing for the bounded CPU mechanics demo."""
from pathlib import Path
import csv
import io
import json
import os
import time
import uuid


def run(payload, root):
    from profile_paths import capture, private_path, _contained, ProfileLocked
    from media_paths import media_output
    from runtime_policy import require_space, memory_info
    root = Path(root).resolve()
    context = capture(root)
    require_space(root, 32 * 1024**2, for_outputs=True)
    _, available = memory_info()
    if available < 1536 * 1024**2:
        raise RuntimeError('Coupled demo requires at least 1.5 GiB free RAM; close another workload and retry.')
    # Import the already bundled numerical layer only after memory admission.
    from Scientific.coupled_physics import settings, CoupledDemo
    from Scientific.physics_viewer import document
    config = settings(payload)
    last_check = [0.]
    def check(force=False):
        now = time.monotonic()
        if force or now - last_check[0] >= .1:
            if capture(root) != context:
                raise ProfileLocked('The simulation login ended; no result will be published')
            last_check[0] = now
    result = CoupledDemo(config).run(check)
    check(True)
    parent = (media_output(root, payload['output_dir']) if payload.get('output_dir')
              else private_path(root, 'Outputs/Science/CoupledPhysics', context=context))
    # Existing output path semantics are retained, but each run is immutable and
    # unique; no prior science result is overwritten.
    parent = Path(parent).resolve()
    _contained(root, parent)
    destination = parent / ('demo_' + uuid.uuid4().hex)
    staging = parent / (destination.name + '.partial')
    contents = {'trajectory.json': json.dumps(result, separators=(',', ':'), allow_nan=False),
                'viewer.html': document(result)}
    stream = io.StringIO(newline=''); writer = csv.writer(stream)
    writer.writerow(['time_s', 'kinetic_energy_j', *['rigid_' + a + '_m' for a in 'xyz'[:config['dimensions']]]])
    for frame in result['frames']:
        writer.writerow([frame['time_s'], frame['kinetic_energy_j'], *frame['rigid_center']])
    contents['metrics.csv'] = stream.getvalue()
    total = sum(len(value.encode('utf-8')) for value in contents.values())
    if total > 16 * 1024**2:
        raise RuntimeError('Simulation output exceeds the 16 MiB demo limit')
    require_space(root, total, for_outputs=True)
    parent.mkdir(parents=True, exist_ok=True); staging.mkdir()
    identities = {}; published = False
    try:
        for name, value in contents.items():
            check(True)
            target = _contained(root, staging / name)
            with target.open('x', encoding='utf-8', newline='') as handle:
                stat = os.fstat(handle.fileno()); identities[name] = (stat.st_dev, stat.st_ino)
                handle.write(value); handle.flush(); os.fsync(handle.fileno())
        check(True); _contained(root, staging); _contained(root, destination)
        staging.rename(destination)
        published = True
        check(True)
    except BaseException:
        # Only these freshly created, exact files are eligible for cleanup.
        directory = destination if published else staging
        for name in identities:
            target = _contained(root, directory / name)
            if target.is_file():
                stat = target.stat()
                if (stat.st_dev, stat.st_ino) != identities[name]:
                    raise RuntimeError('Simulation cleanup refused a replaced file')
                target.unlink()
        if directory.exists(): directory.rmdir()
        raise
    return {'engine': result['engine'], 'compute': 'cpu', 'config': config,
            'particle_count': result['particle_count'], 'metrics': result['metrics'],
            'files': [str(destination / name) for name in contents],
            'viewer': str(destination / 'viewer.html'), 'output_bytes': total,
            'limitations': result['limitations'], 'validation': result['validation']}
