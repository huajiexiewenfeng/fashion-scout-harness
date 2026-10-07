"""Freeze local release inputs and build a paired wheel without downloading anything."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tomllib

_bundle = runpy.run_path(str(Path(__file__).with_name('build_bundle.py')))
BuildError = _bundle['BuildError']
ordinary, require, sha = (_bundle[name] for name in ('ordinary', 'require', 'sha'))
wheel_input, locked = (_bundle[name] for name in ('wheel_input', 'locked'))

ROOT = Path(__file__).resolve().parents[2]
SKILL_RESOURCES = (
    'SKILL.md', 'references/setup.md', 'references/commands.md',
    'references/browser-acquisition.md', 'references/operations.md',
    'scripts/entry.ps1', 'agents/openai.yaml',
)


def inputs():
    files = {}
    for relative in ('pyproject.toml', 'LICENSE', 'requirements-win.lock', 'runtime-win.json'):
        path = ROOT / relative
        ordinary(path)
        require(path.is_file(), 'Required release input missing: ' + relative)
        files[relative] = path.read_bytes()
    for relative in SKILL_RESOURCES:
        path = ROOT / 'skills/fashion-scout' / relative
        ordinary(path)
        require(path.is_file(), 'Required Skill input missing: ' + relative)
        files['skills/fashion-scout/' + relative] = path.read_bytes()
    for directory in ('src/fashion_scout', 'scripts/release'):
        root = ROOT / directory
        ordinary(root)
        require(root.is_dir(), 'Required release directory missing: ' + directory)
        for path in sorted(root.rglob('*')):
            if '__pycache__' in path.parts:
                continue
            ordinary(path)
            if path.is_file():
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    return files


def freeze(output, checkpoint='unreviewed-validation-snapshot'):
    output = Path(output).absolute()
    require(output.parent == ROOT / '.runtime' and output.name.startswith(('t6b-', 't6c-', 't8b-')),
            'Freeze output must be a fresh direct controlled .runtime/t6b-*, t6c-* or t8b-* directory')
    ordinary(output)
    require(not output.exists(), 'Fresh freeze output required; previous inputs are never overwritten')
    selected = inputs()
    project = tomllib.loads(selected['pyproject.toml'].decode('utf-8'))
    require(project['build-system'] == {'requires': ['setuptools==84.0.0'], 'build-backend': 'setuptools.build_meta'},
            'Unsupported build backend; existing pinned setuptools is required')
    require(importlib.metadata.version('setuptools') == '84.0.0', 'Run with the existing pinned build interpreter')
    runtime = ROOT / '.runtime/python.tar.gz'
    ordinary(runtime)
    runtime_digest = json.loads(selected['runtime-win.json'])['sha256']
    require(runtime.is_file() and sha(runtime) == runtime_digest,
            'Existing pinned CPython archive missing or changed')
    cache = ROOT / '.runtime/t6b-dependencies-v1'
    ordinary(cache)
    wheels = {}
    for path in cache.glob('*.whl'):
        ordinary(path)
        wheels[sha(path)] = path
    rows = locked()
    require(all(digest in wheels for _, _, digest in rows), 'Existing locked wheel cache is incomplete')
    output.mkdir()
    for relative, data in selected.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    frozen_runtime = output / '.runtime'
    frozen_runtime.mkdir()
    shutil.copyfile(runtime, frozen_runtime / 'python.tar.gz')
    require(sha(frozen_runtime / 'python.tar.gz') == runtime_digest, 'Runtime changed during freeze')
    frozen_cache = frozen_runtime / 't6b-dependencies-v1'
    frozen_cache.mkdir()
    for _, _, digest in rows:
        source = wheels[digest]
        target = frozen_cache / source.name
        shutil.copyfile(source, target)
        require(sha(target) == digest, 'Dependency changed during freeze: ' + source.name)
    wheel_directory = frozen_runtime / 'app-wheel'
    wheel_directory.mkdir()
    environment = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}}
    environment.update(PYTHONDONTWRITEBYTECODE='1', SOURCE_DATE_EPOCH='1791331200')
    command = [sys.executable, '-I', '-B', '-c',
               'from setuptools.build_meta import build_wheel; build_wheel(".runtime/app-wheel")']
    result = subprocess.run(command, cwd=output, env=environment, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=60)
    (output / 'wheel-build.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    require(result.returncode == 0, 'Local wheel build failed; preserve wheel-build.log')
    built = list(wheel_directory.glob('*.whl'))
    require(len(built) == 1, 'Expected exactly one newly built wheel')
    wheel = built[0]
    digest = sha(wheel)
    paired = wheel_input(wheel, digest, output / 'src', rows)
    require(inputs() == selected, 'Repository inputs changed during freeze; do not use this snapshot')
    require(sha(runtime) == runtime_digest, 'CPython input changed during freeze')
    inventory = {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                 for name, data in sorted(selected.items())}
    receipt = {
        'schema': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'checkpoint': checkpoint, 'approval_inferred': False,
        'root': str(output), 'app_wheel': str(wheel), 'app_sha256': digest,
        'app_version': paired['version'], 'source_root': str(output / 'src'),
        'source_sha256': paired['source_sha256'], 'core_files': len(paired['package']),
        'runtime_sha256': runtime_digest, 'dependency_wheels': len(rows),
        'skill_resources': list(SKILL_RESOURCES), 'input_files': inventory,
        'network_requests': 0, 'services_started': False,
        'build_command': command, 'build_returncode': result.returncode,
    }
    (output / 'freeze-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--checkpoint', default='unreviewed-validation-snapshot',
                        help='Provenance label only; never proof of Manager acceptance')
    arguments = parser.parse_args()
    try:
        receipt = freeze(arguments.output, arguments.checkpoint)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
        return 0
    except (BuildError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print('Freeze refused: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
