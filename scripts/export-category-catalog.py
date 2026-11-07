"""Upgrade an existing live snapshot to the DB import envelope, without login."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from order_worker.category_catalog import atomic_json, normalize, sinsang_nodes, now

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'tmp/category-catalog.json'
data = json.loads(path.read_text(encoding='utf-8'))
if isinstance(data, list):
    metadata = json.loads(path.with_suffix('.meta.json').read_text(encoding='utf-8'))
    data = {'nodes': normalize(data), 'metadata': metadata}
atomic_json(path, data)
print('Exported', len(data['nodes']), 'nodes to', path)
if '--sinsang-source' in sys.argv:
    source_path = path.parent / 'category-source-sinsang.json'
    source = json.loads(source_path.read_text(encoding='utf-8'))
    response = next(r for r in source['responses'] if r['url'] == 'https://abara.sinsang.market/api/v1/goods/categories')
    nodes = normalize(sinsang_nodes(json.loads(response['body'])))
    # This is the actual API response already captured during the initial collection.
    atomic_json(path.parent / 'sinsang-catalog.json', {'nodes': nodes, 'metadata': {'source': response['url'], 'sourceSnapshot':source_path.name, 'exportedAtKst':now()}})
    print('Exported actual Sinsang snapshot:', len(nodes), 'nodes')
