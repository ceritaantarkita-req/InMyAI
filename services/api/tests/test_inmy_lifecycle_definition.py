import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_product_local_lifecycle_definition_is_bounded_and_control_disabled():
    value = json.loads((ROOT / 'inmy.lifecycle.json').read_text(encoding='utf-8'))

    assert value['schemaVersion'] == '1.0.0'
    assert value['serviceId'] == 'inmyai.api'
    assert value['canonicalId'] == 'inmyai'
    assert value['platform'] == 'win32'
    assert value['state'] == 'contract-only'
    assert value['source']['codeCommit'] == '256ccdd09ef11206b87d75b617af8c0eb8a34258'
    assert value['launch']['executable'] == {'resolver': 'node-runtime'}
    assert value['launch']['args'] == ['scripts/run-api.mjs']
    assert value['launch']['cwd'] == '.'
    assert value['launch']['environment']['set'] == {'INMYAI_API_PORT': '8000'}
    assert 'OPENAI_API_KEY' not in value['launch']['environment']['inherit']
    assert value['health']['url'] == 'http://127.0.0.1:8000/api/health'
    assert all(value['security'][key] is False for key in ('allowHttpOverrides', 'allowShell', 'allowSecrets', 'allowPathTraversal'))
