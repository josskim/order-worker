"""Read-only marketplace category snapshots. No product runner is invoked.

Run: .venv/Scripts/python.exe scripts/collect-category-catalog.py --sites namdo
The JSON array is suitable for a future DB import; its sidecar records coverage.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SITES = ('ownerclan', 'onchannel', 'domeggook', 'domesin', 'specialoffer', 'namdo', 'sinsang')
ROOT = Path(__file__).resolve().parents[1]
APPAREL = re.compile('의류|언더웨어|잡화|가방|신발|주얼리|쥬얼리|액세서리|악세서리|패션|속옷|남성|여성')


async def login_page(page, code):
    module = importlib.import_module(f'order_worker.sites.{code}_registration')
    if code in ('ownerclan', 'onchannel', 'domeggook'):
        await module._login(page, module._account('onch3' if code == 'onchannel' else code))
    else:
        await module._login(page)
    for attempt in range(3):
        try:
            await page.goto(module.REGISTER_URL, wait_until='domcontentloaded', timeout=30000)
            break
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(2)
    return module


async def options(page, selector):
    await page.locator(selector).first.wait_for(state='attached')
    return await page.locator(selector + ' option').evaluate_all('''es=>es.filter(e=>e.value.trim()).map(e=>({
        id:e.value,name:(e.getAttribute('category-name')||e.textContent).replace(/☞/g,'').trim(),
        children:e.getAttribute('data-ca-qty')
    }))''')


async def json_request(page, url, form=None):
    # Only explicit category lookup endpoints are passed by the site adapters.
    response = await (page.request.post(url, form=form, timeout=30000) if form is not None else page.request.get(url, timeout=30000))
    if not response.ok:
        raise RuntimeError('Category lookup HTTP ' + str(response.status))
    return await response.json()


async def collect_api_tree(page, code):
    await login_page(page, code)
    selector = {'ownerclan': 'select[name="code1"]', 'domesin':'select[name="cate1"]', 'specialoffer':'#sel_ca1', 'onchannel':'select[name="category_cate_first"]'}[code]
    roots = await options(page, selector)
    selected = [r for r in roots if APPAREL.search(r['name'])]
    if not selected:
        raise ValueError('No apparel roots found')
    result = []
    semaphore = asyncio.Semaphore(3)

    async def visit(row, path):
        current = path + [row['name']]
        children = []
        leaf = False
        if code == 'ownerclan':
            leaf = row.get('type') == 'LAST'
            if not leaf:
                async with semaphore:
                    data = await json_request(page, 'https://ownerclan.com/V2/service/changecode.php', {'code': row['id']})
                if not isinstance(data.get('result'), list):
                    raise ValueError('Invalid Ownerclan children')
                children = [dict(id=str(r['code']), name=r['name'], type=r['type']) for r in data['result']]
                leaf = not children
        elif code == 'domesin':
            # ca_qty is the site's explicit child count, not a timeout heuristic.
            leaf = str(row.get('children') or '0') == '0'
            if not leaf:
                async with semaphore:
                    data = await json_request(page, 'https://www.domesin.com/admin/M_item/category_json.html', {'depth': str(len(current)), 'val': row['id']})
                if not isinstance(data.get('list'), list) or int(data['cnt']) != len(data['list']):
                    raise ValueError('Invalid Domesin children')
                children = [dict(id=str(r['cid']), name=r['name'], children=r['ca_qty']) for r in data['list']]
                if not children:
                    raise ValueError('Domesin advertised children missing')
        elif code == 'specialoffer':
            async with semaphore:
                data = await json_request(page, 'https://specialoffer.kr/admin/ajax.category_select_json.php', {'mod_type': str(len(current) + 1), 'ca_id': row['id']})
            if not isinstance(data, list):
                raise ValueError('Invalid Specialoffer children')
            children = [dict(id=str(r['optionValue']), name=r['optionText']) for r in data if str(r['optionValue']).strip()]
            leaf = not children
        elif code == 'onchannel':
            if len(current) < 4:
                from urllib.parse import urlencode
                params = {'ubr':'getCategory', 'depth':len(current)}
                params.update(dict(zip(('cate_first','cate_second','cate_third','cate_fourth'), current)))
                async with semaphore:
                    data = await json_request(page, 'https://www.onch3.co.kr/access/ajax_pending_product_access.php?' + urlencode(params))
                if data.get('isSuccess') is not True or not isinstance(data.get('datas'), list):
                    raise ValueError('Invalid Onchannel children')
                children = [dict(id=r['name'], name=r['name']) for r in data['datas'] if r.get('name')]
            leaf = not children
        if len(current) > 6:
            raise ValueError('Category recursion limit')
        # Onchannel uses names as option values; preserve the native tuple as a
        # collision-free JSON external key instead of inventing numeric IDs.
        external = json.dumps(current, ensure_ascii=False, separators=(',', ':')) if code == 'onchannel' else row['id']
        result.append(dict(siteCode=code, externalId=external, path=current, leaf=leaf))
        await asyncio.gather(*(visit(child, current) for child in children))

    await asyncio.gather(*(visit(root, []) for root in selected))
    return result, {'scope':'apparel-accessories', 'includedRoots':[r['name'] for r in selected], 'excludedRoots':[r['name'] for r in roots if r not in selected], 'registrationUrl':page.url, 'externalIdKind':'native-option-value-tuple' if code == 'onchannel' else 'native-id'}


def now():
    return datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.writing')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def normalize(nodes):
    unique = {}
    for n in nodes:
        if n['siteCode'] not in SITES or not isinstance(n['externalId'], str) or not n['externalId'].strip():
            raise ValueError('Invalid category identity')
        if not isinstance(n['path'], list) or not n['path'] or any(not isinstance(p, str) or not p.strip() for p in n['path']):
            raise ValueError('Invalid category path')
        if type(n['leaf']) is not bool:
            raise ValueError('Invalid leaf marker')
        key = (n['siteCode'], n['externalId'])
        if key in unique and unique[key] != n:
            raise ValueError(f'Conflicting category {key}')
        unique[key] = n
    return sorted(unique.values(), key=lambda n: (n['siteCode'], n['path'], n['externalId']))


def namdo_nodes(rows):
    result = []
    parents = {str(row['parent_id']) for row in rows if row.get('parent_id') is not None}
    for row in rows:
        path = [row[f'category{i}_name'] for i in range(1, 4) if row.get(f'category{i}_name')]
        result.append(dict(siteCode='namdo', externalId=str(row['id']), path=path, leaf=str(row['id']) not in parents))
    return result


async def collect_namdo(page):
    # Same complete tree used by the wholesale registration category selector.
    url = 'https://apis.ndmarket.co.kr/v2/categories?include_retail_hidden=true'
    response = await page.request.get(url, timeout=30000)
    if not response.ok:
        raise RuntimeError('Namdo category API HTTP ' + str(response.status))
    payload = await response.json()
    if payload.get('stat') != 1 or not isinstance(payload.get('response'), list):
        raise ValueError('Unexpected Namdo category API response')
    return namdo_nodes(payload['response']), url


async def collect_domeggook(page):
    await login_page(page, 'domeggook')
    base = 'https://www.domeggook.com/sc/item/category/find/'
    async def fetch(category_id):
        from urllib.parse import urlencode
        data = await json_request(page, base + '?' + urlencode({'id':category_id, 'section':'SELL', 'onlyLastLevel':'1', 'limitCategory':''}))
        if data.get('result') != 'OK' or not isinstance(data.get('data', {}).get('list'), list):
            raise ValueError('Invalid Domeggook category response')
        return data['data']['list']
    roots = [r for r in await fetch('') if APPAREL.search(r['name'])]
    nodes = []
    semaphore = asyncio.Semaphore(3)
    async def visit(row, path):
        current = path + [row['name']]
        if len(current) > 5 or not isinstance(row.get('isEnd'), bool):
            raise ValueError('Invalid Domeggook category depth/leaf')
        nodes.append(dict(siteCode='domeggook', externalId=str(row['id']), path=current, leaf=row['isEnd']))
        if not row['isEnd']:
            async with semaphore:
                children = await fetch(row['id'])
            children = [c for c in children if str(c['id']).startswith(str(row['id']) + '_') and int(c['level']) == len(current) + 1]
            if not children:
                raise ValueError('Domeggook child categories missing')
            await asyncio.gather(*(visit(child, current) for child in children))
    await asyncio.gather(*(visit(row, []) for row in roots))
    return nodes, {'scope':'apparel-accessories', 'includedRoots':[r['name'] for r in roots], 'source':base}


async def collect_sinsang(page):
    root = ROOT.parent / 'sinsang'
    sys.path.insert(0, str(root))
    from sinsang_worker.config import load_config
    from sinsang_worker.browser import SinsangBrowser, operation_login_account
    from sinsang_worker.registration import REGISTRATION_URL
    config = load_config(root / 'config.local.json')
    runner = SinsangBrowser(config, lambda message: None)
    url = 'https://abara.sinsang.market/api/v1/goods/categories'
    await runner.login(page, operation_login_account(config.accounts[0], 'registration'))
    async with page.expect_response(lambda response: response.url == url and response.ok, timeout=30000) as response:
        await page.goto(REGISTRATION_URL, wait_until='domcontentloaded')
    data = await (await response.value).json()
    if not isinstance(data.get('items'), list):
        raise ValueError('Invalid Sinsang categories')
    return sinsang_nodes(data), {'scope':'womens-apparel-accessories', 'source':url}


def sinsang_nodes(data):
    nodes = []
    def visit(row, path):
        current = path + [row['name']]
        children = row.get('subCategories', [])
        nodes.append(dict(siteCode='sinsang', externalId=str(row['categoryId']), path=current, leaf=not children))
        for child in children:
            visit(child, current)
    for row in data['items']:
        if row.get('genderName') == '여성':
            visit(row, [])
    return nodes


async def collect_site(code, timeout):
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            if code == 'sinsang':
                root = ROOT.parent / 'sinsang'
                sys.path.insert(0, str(root))
                from sinsang_worker.config import load_config
                from sinsang_worker.browser import SinsangBrowser
                runner = SinsangBrowser(load_config(root / 'config.local.json'), lambda message: None)
                context = await browser.new_context(**runner.context_options())
                page = await context.new_page()
            else:
                page = await browser.new_page()
            page.set_default_timeout(15000)
            page.set_default_navigation_timeout(30000)
            if code == 'namdo':
                return await asyncio.wait_for(collect_namdo(page), timeout)
            if code == 'domeggook':
                return await asyncio.wait_for(collect_domeggook(page), timeout)
            if code == 'sinsang':
                return await asyncio.wait_for(collect_sinsang(page), timeout)
            if code in ('ownerclan','domesin','specialoffer','onchannel'):
                return await asyncio.wait_for(collect_api_tree(page, code), timeout)
            raise NotImplementedError('Collector not yet verified for ' + code)
        finally:
            await browser.close()


async def run(args):
    output = Path(args.output).resolve()
    metadata_path = output.with_suffix('.meta.json')
    existing = json.loads(output.read_text(encoding='utf-8')) if output.exists() else []
    nodes = existing.get('nodes', []) if isinstance(existing, dict) else existing
    metadata = existing['metadata'] if isinstance(existing, dict) else (json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else {'schemaVersion': 1, 'timezone': 'Asia/Seoul', 'sites': {}})
    for code in SITES:
        metadata['sites'].setdefault(code, {'status': 'uncollected', 'count': 0, 'leafCount': 0})
    for code in args.sites:
        started = now()
        try:
            collected, source = await collect_site(code, args.timeout)
            collected = normalize(collected)
            if not collected or not any(n['leaf'] for n in collected):
                raise ValueError('No verified leaf categories returned')
            nodes = normalize([n for n in nodes if n['siteCode'] != code] + collected)
            metadata['sites'][code] = {'status': 'verified', 'completeWithinScope': True, 'collectedAtKst': now(), 'source': source, 'count': len(collected), 'leafCount': sum(n['leaf'] for n in collected)}
            print(code, metadata['sites'][code]['count'], 'nodes', metadata['sites'][code]['leafCount'], 'leaves', flush=True)
        except Exception as exc:
            # Never persist exceptions containing credentials, cookies or request bodies.
            previous = metadata['sites'][code]
            previous.update(lastAttemptAtKst=started, lastAttemptStatus='failed', errorType=type(exc).__name__)
            print(code, 'FAILED', type(exc).__name__, flush=True)
        metadata['exportedAtKst'] = now()
        atomic_json(output, {'nodes': nodes, 'metadata': metadata})
        atomic_json(metadata_path, metadata)
    return 0 if all(metadata['sites'][c]['status'] == 'verified' and metadata['sites'][c].get('lastAttemptStatus') != 'failed' for c in args.sites) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sites', nargs='+', choices=SITES, default=list(SITES))
    parser.add_argument('--output', default=str(ROOT / 'tmp/category-catalog.json'))
    parser.add_argument('--timeout', type=float, default=600, help='Per-site time limit in seconds')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    return asyncio.run(run(args))
