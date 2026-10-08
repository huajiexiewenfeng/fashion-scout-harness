"""Reuse accepted package checks on this exact T9 ZIP; no live-instance access."""
import json
from pathlib import Path
import runpy
root = Path(__file__).resolve().parents[2]
receipt = json.loads((root / '.runtime/t8b-t9f/.runtime/t8b-t9r/build-receipt.json').read_text('utf-8'))
work = root / '.runtime/t8b-t9checks'
work.mkdir()
suite = runpy.run_path(str(root / 'tests/release/test_bundle.py'))
release = receipt, work
steps = [('test_bundle_immutable_inputs_and_no_user_data', ())]
steps += [('test_prepare_rejects_before_touching_data', (case,)) for case in
          ('damaged-wheel', 'missing-resource', 'existing-data', 'config-conflict')]
steps += [(name, ()) for name in ('test_real_prepare_failure_preserves_existing_configuration',
                                 'test_long_path_refused_before_preparation',
                                 'test_fresh_prepare_configures_default_without_starting',
                                 'test_independent_zip_install_entries_and_synthetic_export')]
passed = []
for name, arguments in steps:
    print('Running', name, *arguments, flush=True)
    suite[name](release, *arguments)
    passed.append({'test': name, 'arguments': arguments})
    (work / 'check-results.json').write_text(json.dumps(passed, indent=2), encoding='utf-8')
assert len(passed) == 9
print(json.dumps({'passed':len(passed),'work':str(work),'zip_sha256':receipt['zip_sha256'],
                  'app_sha256':receipt['app_sha256']}),flush=True)
