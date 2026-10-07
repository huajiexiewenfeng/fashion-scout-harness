"""Read-only final audit of T6a inputs; writes only fresh T6a delivery evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/verification'
WORK = ROOT / '.runtime/t6a-package-bd0a82ab'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = json.loads((DOC / 'T6a-baseline.json').read_text('utf-8'))
    protected = {name: digest(ROOT / name) for name in baseline}
    assert protected == baseline, 'Protected file changed'
    for original, target in [('evidence.json', 'T6a-package-evidence-v1.json'),
                             ('commands.txt', 'T6a-package-commands-v1.txt')]:
        dest = DOC / target
        if dest.exists():
            assert dest.read_bytes() == (WORK / original).read_bytes()
        else:
            shutil.copyfile(WORK / original, dest)
    package = json.loads((WORK / 'evidence.json').read_text('utf-8'))
    assert digest(Path(package['wheel'])) == package['sha256']
    assert digest(WORK / 'favorites.zip') == package['scenario']['export']['sha256']
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV', 'T6A_AUDIT_DIR'}}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    stopped = []
    code = '''import json,sys
from fashion_scout.config import Paths
from fashion_scout import launcher
p=Paths.at(sys.argv[1]);d=launcher.read_descriptor(p)
assert d and d['port']!=56117
states={r:bool(launcher.verified_process(p,d,r)) for r in ('web','worker')}
assert not any(states.values())
print(json.dumps({'root':str(p.root),'port':d['port'],'live':states}))
'''
    for name in ('t6a-package-3164de71', 't6a-package-bd0a82ab'):
        work = ROOT / '.runtime' / name
        assert work.parent == ROOT / '.runtime' and name.startswith('t6a-')
        env['T6A_AUDIT_DIR'] = str(work / 'delivery-audit')
        result = subprocess.run([str(work / 'env/Scripts/python.exe'), '-B', '-c', code,
                                 str(work / 'data')], cwd=work, env=env,
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        assert result.returncode == 0 and not result.stderr, result.stderr
        stopped.append(json.loads(result.stdout))
    docs = [ROOT/'README.md', ROOT/'docs/roadmap.zh-CN.md', ROOT/'docs/local-preview.zh-CN.md',
            *sorted(DOC.glob('T6a*.md'))]
    links = []
    for doc in docs:
        for target in re.findall(r'\]\(([^)]+)\)', doc.read_text('utf-8')):
            if target.startswith(('https:', 'http:', '#', 'app:', 'codex:')):
                continue
            target = target.split('#', 1)[0]
            resolved = (doc.parent / target).resolve()
            # The final evidence file is written after its link is validated here.
            assert resolved.exists() or resolved == DOC/'T6a-evidence-v1.json', (doc, target)
            links.append({'file':str(doc.relative_to(ROOT)), 'target':target})
    files = [ROOT/'README.md', ROOT/'docs/roadmap.zh-CN.md', ROOT/'docs/local-preview.zh-CN.md',
             *sorted(DOC.glob('T6a*')), *sorted((ROOT/'tests/integration').glob('*readiness*.py'))]
    hashes = {str(p.relative_to(ROOT)):digest(p) for p in files
              if p.is_file() and p.name != 'T6a-evidence-v1.json'}
    evidence = {'at':datetime.now(timezone.utc).isoformat(), 'scope':'T6a v1 preparation only',
                'protected_count':len(baseline), 'protected_sha256':protected,
                'protected_changed':[], 'own_instances':stopped,
                'local_document_links':links, 'artifact_sha256':hashes,
                'wheel_sha256':package['sha256'], 'import_process_records':len(package['provenance']),
                'executed_subprocess_commands':len(package['scenario']['commands']),
                'fixed_command_inventory':len(package['fixed_commands']),
                'package_files':package['package_files'], 'migrations':package['migrations'],
                'source_requests':package['source_requests'], 'new_global_install':False,
                'user_preview_accessed':False, 'full_suite_rerun':False}
    output = DOC/'T6a-evidence-v1.json'
    assert not output.exists(), 'Do not overwrite frozen evidence'
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'protected':len(baseline),'changed':0,'stopped':stopped,
                      'artifact_hashes':len(hashes),'links':len(links)},ensure_ascii=False))


if __name__ == '__main__':
    main()
