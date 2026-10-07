"""Repeat wheel and ZIP builds from the same unreviewed, frozen validation inputs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
frozen = Path(sys.argv[1]).resolve()
assert frozen.parent == root / '.runtime' and frozen.name.startswith('t8b-inputs-')
pair = json.loads((frozen / 'freeze-receipt.json').read_text('utf-8'))
original = json.loads((frozen / '.runtime/t8b-candidate/build-receipt.json').read_text('utf-8'))
assert pair['checkpoint'] == 'unreviewed-validation-snapshot' and not pair['approval_inferred']
environment = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}}
environment.update(PYTHONDONTWRITEBYTECODE='1', SOURCE_DATE_EPOCH='1791331200')
destination = frozen / '.runtime/repro-wheel'
destination.mkdir()
commands = []


def run(arguments):
    result = subprocess.run(arguments, cwd=frozen, env=environment, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=60)
    commands.append({'argv': arguments, 'returncode': result.returncode,
                     'stdout': result.stdout, 'stderr': result.stderr})
    (frozen / 'repro-commands.json').write_text(json.dumps(commands, ensure_ascii=False, indent=2), encoding='utf-8')
    assert result.returncode == 0, commands[-1]


run([sys.executable, '-I', '-B', '-c',
     'from setuptools.build_meta import build_wheel; build_wheel(".runtime/repro-wheel")'])
wheels = list(destination.glob('*.whl'))
assert len(wheels) == 1
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
assert sha(wheels[0]) == pair['app_sha256']
output = frozen / '.runtime/t8b-repro'
run([sys.executable, '-I', '-B', str(frozen / 'scripts/release/build_bundle.py'),
     '--output', str(output), '--app-wheel', str(wheels[0]), '--app-sha256', pair['app_sha256'],
     '--source-root', pair['source_root'], '--label', 'validation'])
repeated = json.loads((output / 'build-receipt.json').read_text('utf-8'))
assert original['zip_sha256'] == repeated['zip_sha256'] == sha(repeated['zip'])
assert original['manifest_sha256'] == repeated['manifest_sha256']
assert original['source_sha256'] == repeated['source_sha256'] == pair['source_sha256']
evidence = {'validation_only': True, 'final_release_built': False, 'app_sha256': pair['app_sha256'],
            'zip_sha256': repeated['zip_sha256'], 'manifest_sha256': repeated['manifest_sha256'],
            'source_sha256': pair['source_sha256'], 'repeated_wheel_bytes_equal': True,
            'repeated_zip_bytes_equal': True, 'original': original, 'repeated': repeated,
            'commands': commands, 'services_started': False, 'source_requests': 0}
(root / 'docs/verification/T8b-prep-repro-evidence.json').write_text(
    json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: evidence[k] for k in ('validation_only', 'app_sha256', 'zip_sha256',
                                        'manifest_sha256', 'repeated_wheel_bytes_equal',
                                        'repeated_zip_bytes_equal')}, ensure_ascii=False))
