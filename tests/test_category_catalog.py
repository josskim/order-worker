import unittest
from playwright.async_api import async_playwright
from order_worker.category_catalog import sinsang_nodes, normalize
from order_worker.category_selection import wait_category_option


class CategoryCatalogTests(unittest.TestCase):
    def test_actual_tree_preserves_ids_and_full_paths_and_womens_scope(self):
        data = {"items": [
            {"categoryId": 1, "name": "여성의류", "genderName": "여성", "subCategories": [
                {"categoryId": 16, "name": "아우터", "subCategories": [
                    {"categoryId": 112, "name": "조끼/베스트"}
                ]}
            ]},
            {"categoryId": 2, "name": "남성의류", "genderName": "남성"},
        ]}
        nodes = normalize(sinsang_nodes(data))
        leaves = [node for node in nodes if node['leaf']]
        self.assertEqual(leaves, [{"siteCode": "sinsang", "externalId": "112", "path": ["여성의류", "아우터", "조끼/베스트"], "leaf": True}])
        with self.assertRaises(ValueError):
            normalize([leaves[0], {**leaves[0], 'path': ['충돌']}])


class CategoryOptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_delayed_child_is_selected_only_when_exact_text_arrives(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.set_content('''<select name="cate"><option value="wrong">패딩조끼</option></select>
                    <script>setTimeout(() => document.querySelector('select').add(new Option('☞ 조끼', 'right')), 800)</script>''')
                await wait_category_option(page, 'select[name="cate"]', '조끼')
                self.assertEqual(await page.locator('option[value="right"]').count(), 1)
            finally:
                await browser.close()
