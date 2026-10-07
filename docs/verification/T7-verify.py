import hashlib
import json
from pathlib import Path
import re
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/verification'
SKILL=ROOT/'skills/fashion-scout'
PERSONAL=Path(r'C:\Users\Administrator\.codex\skills\fashion-scout')
APP=Path(r'E:\github-workspace\FashionScout')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline=json.loads((DOC/'T7-baseline.json').read_text('utf-8'));current={name:sha(ROOT/name) for name in baseline}
    changed={name for name in baseline if baseline[name]!=current[name]}
    allowed={'README.md','docs\\delivery.zh-CN.md','skills\\fashion-scout\\SKILL.md','skills\\fashion-scout\\references\\setup.md','skills\\fashion-scout\\references\\browser-acquisition.md'}
    assert changed==allowed,changed
    source={p.relative_to(SKILL).as_posix():sha(p) for p in SKILL.rglob('*') if p.is_file()}
    installed={p.relative_to(PERSONAL).as_posix():sha(p) for p in PERSONAL.rglob('*') if p.is_file() and p.name!='local-binding.json'}
    assert source==installed and not (SKILL/'local-binding.json').exists()
    links=[]
    for doc in SKILL.rglob('*.md'):
        for target in re.findall(r'\]\(([^)]+)\)',doc.read_text('utf-8')):
            if target.startswith(('https:','http:','#')):continue
            assert (doc.parent/target).exists(),(doc,target)
            links.append({'file':str(doc.relative_to(SKILL)),'target':target})
    binding=json.loads((PERSONAL/'local-binding.json').read_text('utf-8'))
    assert set(binding)=={'schema','package_root','manifest_sha256','app_sha256'} and binding['package_root']==str(APP)
    assert binding['manifest_sha256']==sha(APP/'manifest.json')=='f79f619e62c732736ea4a647e486510cb36ca3eb887c3f9bf5b8da646dd7dc2f'
    manifest=json.loads((APP/'manifest.json').read_text('utf-8'))
    for member in manifest['files']:assert sha(APP/member['path'])==member['sha256']
    placement=json.loads((DOC/'T7-placement.json').read_text('utf-8'))
    assert placement['zip_sha256']=='e84136524449677efb8c72b2a3042f414b36c25cd10c325182e639eb14cedc42'
    smoke=json.loads((DOC/'T7-smoke-evidence.json').read_text('utf-8'));assert not any(smoke['empty_counts'].values()) and not any(smoke['verified_exit'].values())
    report={'at':datetime.now(timezone.utc).isoformat(),'scope':'T7 installed single Skill; independent review pending',
            'baseline_count':len(baseline),'allowed_changed':sorted(changed),'unchanged_count':len(baseline)-len(changed),
            'baseline_sha256':baseline,'current_sha256':current,'skill_source_sha256':source,'personal_resource_match':True,
            'local_binding':binding,'references':links,'application_manifest_sha256':sha(APP/'manifest.json'),
            'empty_counts':smoke['empty_counts'],'exited':smoke['verified_exit'],'skill_selection_refresh_verified':False,
            'source_requests':0,'artifact_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'README.md',ROOT/'docs/delivery.zh-CN.md',*DOC.glob('T7*')] if p.is_file() and p.name!='T7-evidence-v1.json'}}
    path=DOC/'T7-evidence-v1.json';assert not path.exists();path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'baseline':len(baseline),'changed':sorted(changed),'unchanged':len(baseline)-len(changed),'skill_resources':len(source),'links':len(links),'empty':smoke['empty_counts'],'exited':smoke['verified_exit']}))


if __name__=='__main__':main()
