"""Bounded, checkpointed T8b upgrade evidence; no source requests or business SQL writes."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
LIVE = Path(r'E:\github-workspace\FashionScout')
DATA = LIVE / 'data'
WORK = ROOT / '.runtime/t8b-upgrade-v1'
PERSONAL = Path(r'C:\Users\Administrator\.codex\skills\fashion-scout')
FINAL = ROOT / '.runtime/t8b-final-inputs/.runtime/t8b-final/build-receipt.json'
PS = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
ACTION = sys.argv[1]


def check_path(path):
    info = path.lstat()
    assert not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400, path


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load(path):
    return json.loads(path.read_text('utf-8-sig'))


def write(name, value):
    path = WORK / (name + '.json')
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def inventory(root):
    check_path(root)
    files = {}
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            check_path(Path(parent) / name)
        for name in names:
            path = Path(parent) / name
            files[path.relative_to(root).as_posix()] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    return files


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      default=lambda blob: {'bytes_hex': blob.hex()}).encode('utf-8')


def db_audit(data, *, immutable=False):
    uri = (data / 'scout.sqlite3').as_uri() + '?mode=ro' + ('&immutable=1' if immutable else '')
    with sqlite3.connect(uri, uri=True) as connection:
        connection.execute('BEGIN')
        assert connection.execute('PRAGMA quick_check').fetchall() == [('ok',)]
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        tables = {}
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            info = connection.execute('PRAGMA table_info(' + quoted + ')').fetchall()
            # Process heartbeat/state are runtime lifecycle fields; keep worker identity columns.
            columns = [row[1] for row in info if name != 'workers' or row[1] not in {'heartbeat_at', 'state'}]
            pk = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
            selected = ','.join('"' + column.replace('"', '""') + '"' for column in columns)
            rows = connection.execute('SELECT ' + selected + ' FROM ' + quoted).fetchall()
            hashes = {}
            if pk:
                indexes = [columns.index(column) for column in pk]
                for row in rows:
                    key = hashlib.sha256(canonical([row[index] for index in indexes])).hexdigest()
                    assert key not in hashes
                    hashes[key] = hashlib.sha256(canonical(row)).hexdigest()
            else:
                hashes = dict(Counter(hashlib.sha256(canonical(row)).hexdigest() for row in rows))
            tables[name] = {'columns': columns, 'pk': pk, 'count': len(rows), 'rows': hashes}
        counts = {name: row['count'] for name, row in tables.items()}
        user = dict(zip(('favorites', 'excluded'), connection.execute('SELECT SUM(favorite),SUM(excluded) FROM product_user_state').fetchone()))
        active = {}
        for table in ('runs', 'export_jobs', 'maintenance_jobs'):
            active[table] = connection.execute("SELECT COUNT(*) FROM " + table + " WHERE state NOT IN ('succeeded','partial','failed','cancelled')").fetchone()[0]
        active['browser_receiving'] = connection.execute("SELECT COUNT(*) FROM browser_assets WHERE state IN ('uploading','received')").fetchone()[0]
        roots = [row[0] for row in connection.execute('SELECT path FROM storage_roots')]
        for value in roots:
            assert Path(value).resolve().is_relative_to(DATA.resolve()), ('External storage root requires separate backup scope', value)
        return {'quick_check': 'ok', 'foreign_key_violations': 0, 'tables': tables,
                'counts': counts, 'user_state': user, 'active_jobs': active, 'storage_roots': roots}


def retained(before, after):
    for name, table in before['tables'].items():
        current = after['tables'][name]
        assert current['columns'] == table['columns'], ('Column changes require explicit comparison', name)
        assert current['pk'] == table['pk']
        if table['pk']:
            for key, digest in table['rows'].items():
                assert current['rows'].get(key) == digest, ('Historical row changed/lost', name, key)
        else:
            assert all(current['rows'].get(key, 0) >= count for key, count in table['rows'].items()), name
    assert before['user_state'] == after['user_state']


def run(label, command):
    environment = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}}
    environment.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')
    result = subprocess.run(command, cwd=LIVE, env=environment, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=130)
    write(label, {'argv': list(map(str, command)), 'returncode': result.returncode,
                  'stdout': result.stdout, 'stderr': result.stderr})
    assert result.returncode == 0, (label, result.returncode, result.stderr[-1000:])
    return result.stdout


def package(action):
    return run(ACTION + '-package-' + action.lower(), [str(PS), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
               '-File', str(LIVE / 'package.ps1'), '-Action', action])


def request(command, payload=None):
    directory = DATA / 'requests/t8b-upgrade-v1'
    directory.mkdir(exist_ok=True)
    path = directory / (ACTION + '-' + command + '.json')
    path.write_text(json.dumps(payload or {}), encoding='utf-8')
    stdout = run(ACTION + '-client-' + command, [str(LIVE / '.local/env/Scripts/python.exe'), '-I', '-B',
                 '-m', 'fashion_scout.client', 'request', command, '--data-root', str(DATA), '--json-input', str(path)])
    response = json.loads(stdout)
    assert response['ok']
    return response['data']


def probe_processes():
    stdout = run(ACTION + '-owned-processes', [str(LIVE / '.local/env/Scripts/python.exe'), '-I', '-B', '-c',
        'import json,sys; from fashion_scout.config import Paths; from fashion_scout import launcher; '
        'p=Paths.at(sys.argv[1]); d=launcher.read_descriptor(p); '
        'print(json.dumps({"instance":d["instance"],"live":{r:bool(launcher.verified_process(p,d,r)) for r in ("web","worker")}}))', str(DATA)])
    return json.loads(stdout)


def api_summary():
    result = {name: request(name, {'limit': 100} if name in {'new', 'favorites'} else {})
              for name in ('status', 'latest', 'new', 'favorites', 'intents', 'sites', 'storage', 'maintenance', 'default-plan')}
    current = result['latest']['latest_run']
    assert current['id'] == '0f711f657c78497c99590ade6ea354b4' and current['state'] == 'partial'
    assert result['new']['total'] == len(result['new']['items']) == 20
    images = sum(len(item['images']) for item in result['new']['items'])
    assert images == 89 and all(item['images'] for item in result['new']['items'])
    assert not any(item['state'] in {'prepared', 'sending'} for item in result['intents']['items'])
    write(ACTION + '-api', result)
    return {'visible_products': 20, 'visible_images': images, 'empty_cards': 0,
            'favorites': result['favorites']['total'], 'intents': len(result['intents']['items']),
            'latest_run': current['id'], 'latest_state': current['state']}


check_path(LIVE)
assert LIVE.resolve() == LIVE and LIVE.parent == Path(r'E:\github-workspace')
assert WORK.parent == ROOT / '.runtime' and WORK.name == 't8b-upgrade-v1'
if ACTION == 'preflight':
    WORK.mkdir()
else:
    check_path(WORK)
    assert WORK.is_dir()

receipt = load(FINAL)
if ACTION == 'preflight':
    package('Status')
    summary = api_summary()
    audit = db_audit(DATA)
    assert not any(audit['active_jobs'].values()), audit['active_jobs']
    write('preflight-db', audit)
    assert sha(Path(receipt['zip'])) == receipt['zip_sha256']
    with zipfile.ZipFile(receipt['zip']) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read('FashionScout/manifest.json'))
        assert {item.filename for item in archive.infolist()} == {'FashionScout/manifest.json'} | {'FashionScout/' + item['path'] for item in manifest['files']}
        for item in archive.infolist():
            assert not item.is_dir() and not stat.S_ISLNK(item.external_attr >> 16)
            relative = Path(item.filename)
            assert relative.parts[0] == 'FashionScout' and not any(part in {'.', '..'} for part in relative.parts)
            assert '\\' not in item.filename and ':' not in item.filename
        for member in manifest['files']:
            value = archive.read('FashionScout/' + member['path'])
            assert len(value) == member['bytes'] and hashlib.sha256(value).hexdigest() == member['sha256']
        assert hashlib.sha256(archive.read('FashionScout/manifest.json')).hexdigest() == receipt['manifest_sha256']
        stage = WORK / 'staged'
        stage.mkdir()
        archive.extractall(stage)
    summary.update(instance=load(DATA / 'control/runtime.json')['instance'], counts=audit['counts'], user_state=audit['user_state'])
    write('preflight-summary', summary)
    print(json.dumps(summary), flush=True)
elif ACTION == 'backup':
    assert (WORK / 'preflight-summary.json').is_file() and not (WORK / 'backup-summary.json').exists()
    package('Stop')
    stopped = probe_processes()
    assert not any(stopped['live'].values())
    audit = db_audit(DATA)
    retained(load(WORK / 'preflight-db.json'), audit)
    assert not any(audit['active_jobs'].values())
    wal = DATA / 'scout.sqlite3-wal'
    assert not wal.exists() or wal.stat().st_size == 0, 'Keep coherent WAL backup; do not proceed without reconciliation'
    write('before-db', audit)
    before = inventory(LIVE)
    assert shutil.disk_usage(WORK).free > sum(row['bytes'] for row in before.values()) * 2 + 200 * 1024 * 1024
    backup = WORK / 'backup/FashionScout'
    backup.parent.mkdir()
    shutil.copytree(LIVE, backup)
    assert inventory(backup) == before == inventory(LIVE)
    write('backup-files', before)
    shutil.copytree(PERSONAL, WORK / 'backup/personal-skill')
    personal_files = inventory(PERSONAL)
    assert inventory(WORK / 'backup/personal-skill') == personal_files
    write('personal-before-files', personal_files)
    restored = WORK / 'restored-copy/FashionScout'
    restored.parent.mkdir()
    shutil.copytree(backup, restored)
    assert inventory(restored) == before
    recovered = db_audit(restored / 'data', immutable=True)
    assert recovered == audit
    write('restored-db', recovered)
    result = {'full_backup': str(backup), 'restore_copy': str(restored), 'files': len(before),
              'bytes': sum(row['bytes'] for row in before.values()), 'all_files_match': True,
              'restore_copy_db_equal': True, 'runtime_rollback_started': False, 'stopped': stopped,
              'counts': audit['counts'], 'user_state': audit['user_state']}
    write('backup-summary', result)
    print(json.dumps(result), flush=True)
elif ACTION == 'replace':
    assert load(WORK / 'backup-summary.json')['all_files_match']
    assert not any(probe_processes()['live'].values())
    source, destination = LIVE / '.local', WORK / 'original-local'
    assert source.resolve() == LIVE / '.local' and destination.resolve().is_relative_to(WORK.resolve()) and not destination.exists()
    # Both absolute targets are checked above; only this stopped package runtime is moved.
    source.rename(destination)
    stage = WORK / 'staged/FashionScout'
    manifest = load(stage / 'manifest.json')
    for member in manifest['files']:
        assert not member['path'].startswith(('data/', '.local/'))
        source = stage / member['path']
        target = LIVE / member['path']
        assert target.resolve().is_relative_to(LIVE) and source.resolve().is_relative_to(stage.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert sha(target) == member['sha256']
    shutil.copyfile(stage / 'manifest.json', LIVE / 'manifest.json')
    assert sha(LIVE / 'manifest.json') == receipt['manifest_sha256']
    write('replace-summary', {'resources': len(manifest['files']), 'manifest_sha256': receipt['manifest_sha256'],
                               'old_runtime_preserved': str(destination), 'data_moved': False})
    print('Replaced verified package resources; original data remains in place.', flush=True)
elif ACTION == 'prepare':
    assert (WORK / 'replace-summary.json').is_file()
    package('Prepare')
    ready = load(LIVE / '.local/ready.json')
    assert ready['app_sha256'] == receipt['app_sha256'] and ready['manifest_sha256'] == receipt['manifest_sha256']
    assert retained(load(WORK / 'before-db.json'), db_audit(DATA)) is None
    write('prepare-summary', ready)
    print(json.dumps({'prepared': True, 'app_sha256': ready['app_sha256']}), flush=True)
elif ACTION == 'verify':
    assert (WORK / 'prepare-summary.json').is_file()
    package('Open')
    owned = probe_processes()
    assert all(owned['live'].values())
    assert owned['instance'] != load(WORK / 'preflight-summary.json')['instance']
    audit = db_audit(DATA)
    retained(load(WORK / 'before-db.json'), audit)
    write('after-db', audit)
    old_files = load(WORK / 'backup-files.json')
    checked = 0
    for relative, row in old_files.items():
        if not relative.startswith('data/') or relative.startswith('data/logs/') or relative in {'data/scout.sqlite3', 'data/scout.sqlite3-wal', 'data/scout.sqlite3-shm', 'data/control/runtime.json'}:
            continue
        path = LIVE / relative
        assert path.is_file() and sha(path) == row['sha256'], ('Prior data file changed/lost', relative)
        checked += 1
    summary = api_summary()
    sites = request('sites')['source_modes']['browser']['site_adapters']
    assert set(sites) == {'futario', 'rihoas', 'simpleretro'}
    manifest = load(LIVE / 'manifest.json')
    for relative, digest in manifest['skill_files'].items():
        source = LIVE / relative
        resource = Path(relative).relative_to('skills/fashion-scout')
        assert sha(ROOT / 'skills/fashion-scout' / resource) == digest == sha(source)
        target = PERSONAL / resource
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert sha(target) == digest
    binding = {'schema': 1, 'package_root': str(LIVE), 'manifest_sha256': receipt['manifest_sha256'], 'app_sha256': receipt['app_sha256']}
    temporary = PERSONAL / 'local-binding.t8b.tmp'
    temporary.write_text(json.dumps(binding), encoding='utf-8')
    os.replace(temporary, PERSONAL / 'local-binding.json')
    for action in ('Locate', 'Status'):
        run('personal-' + action.lower(), [str(PS), '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(PERSONAL / 'scripts/entry.ps1'), '-Action', action])
    summary.update(instance=owned['instance'], previous_instance=load(WORK / 'preflight-summary.json')['instance'],
                   owned_processes=owned, counts=audit['counts'], user_state=audit['user_state'],
                   retained_db_tables=len(audit['tables']), unchanged_prior_data_files=checked,
                   skill_resources=7, binding=binding, sites=sites,
                   ready_at_shanghai=datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).isoformat(),
                   source_requests_during_upgrade=0)
    write('verified-summary', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
else:
    raise ValueError('Unknown phase')
