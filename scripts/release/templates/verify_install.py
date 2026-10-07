"""Package-local installation inventory. Never selects or imports a user data root."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    mode, root_text = sys.argv[1:]
    root = Path(root_text).resolve()
    local = root/'.local'
    assert Path(sys.prefix).resolve() == local/'env', 'Interpreter is not this package environment'
    assert sys.version_info[:3] == (3,13,16) and struct.calcsize('P') == 8
    assert sqlite3.sqlite_version_info >= (3,51,3)
    import fashion_scout
    assert Path(fashion_scout.__file__).resolve().is_relative_to(local/'env/Lib/site-packages/fashion_scout')
    assert not any('__editable__' in str(m) for m in sys.meta_path)
    assert all(not p.endswith('fashion-scout-harness/src') for p in sys.path)
    manifest = json.loads((root/'manifest.json').read_text('utf-8'))
    inventory_path = local/'installed-files.json'
    if mode == 'freeze':
        files = {p.relative_to(root).as_posix():sha(p) for p in local.rglob('*')
                 if p.is_file() and p!=inventory_path and p.name not in {'ready.json','preparing.json'}
                 and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        inventory_path.write_text(json.dumps(files,sort_keys=True,indent=2),encoding='utf-8')
        ready = {'schema':1,'root':str(root),'manifest_sha256':sha(root/'manifest.json'),
                 'inventory_sha256':sha(inventory_path),'app_sha256':manifest['app_sha256']}
        (local/'ready.json').write_text(json.dumps(ready,indent=2),encoding='utf-8')
    elif mode == 'check':
        ready = json.loads((local/'ready.json').read_text('utf-8'))
        assert ready['root'] == str(root), 'Prepared folder moved; preserve data and request recovery'
        assert ready['manifest_sha256'] == sha(root/'manifest.json')
        assert ready['inventory_sha256'] == sha(inventory_path)
        files = json.loads(inventory_path.read_text('utf-8'))
        for relative, digest in files.items():
            path = root/relative
            assert path.resolve().is_relative_to(local) and not path.is_symlink()
            assert path.is_file() and sha(path) == digest, 'Installed file changed or missing: '+relative
    else:
        raise ValueError('Unknown verification action')
    print(json.dumps({'verified':True,'python':sys.version.split()[0],'sqlite':sqlite3.sqlite_version,
                      'module':fashion_scout.__file__,'installed_files':len(files)},ensure_ascii=True))


if __name__ == '__main__':
    main()
