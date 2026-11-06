from __future__ import annotations

import unittest

from playwright.async_api import async_playwright

from order_worker.sites.domeggook_registration import _handle_recommended_category
from order_worker.sites.namdo_registration import MANAGEMENT_URL, _already_registered
from order_worker.sites.domesin_registration import _select_text, _set_adult_sale


class RegistrationBrowserRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_recommendation_followed_by_safety_notice_does_not_block_editor(self):
        await self.page.set_content('''
          <div id="lDialogSellReg" style="position:fixed;inset:0;background:white;z-index:10">
            추천 카테고리 안내
            <button>변경하기</button>
          </div>
          <button id="lBtnWriteItemMemo" onclick="window.editorOpened=true">상세정보 작성</button>
        ''')
        await self.page.evaluate('''() => {
          const modal = document.querySelector('#lDialogSellReg');
          modal.querySelector('button').onclick = () => {
            modal.textContent = '안전확인대상 상품 판매 시 유의사항';
            const confirm = document.createElement('button');
            confirm.textContent = '확인';
            confirm.onclick = () => modal.style.display = 'none';
            modal.append(confirm);
          };
        }''')
        await _handle_recommended_category(self.page, timeout=100)
        await self.page.locator('#lBtnWriteItemMemo').click(timeout=1000)
        self.assertTrue(await self.page.evaluate('window.editorOpened'))

    async def test_unknown_dialog_is_reported_without_automatic_confirmation(self):
        await self.page.set_content('<div id="lDialogSellReg">알 수 없는 결제 안내<button>확인</button></div>')
        with self.assertRaisesRegex(RuntimeError, "확인이 필요한"):
            await _handle_recommended_category(self.page, timeout=100)

    async def test_no_dialog_is_optional(self):
        await self.page.set_content('<button id="lBtnWriteItemMemo">상세정보 작성</button>')
        await _handle_recommended_category(self.page, timeout=100)

    async def test_namdo_search_waits_for_actual_row_and_rejects_other_code_prefix(self):
        await self.page.route(MANAGEMENT_URL, lambda route: route.fulfill(content_type='text/html; charset=utf-8', body='''
          <input placeholder="검색어를 입력해주세요.">
          <table><tbody><tr><td class="product-name-cell">G1269560_다른 상품</td></tr></tbody></table>
          <script>
            document.querySelector('input').onkeydown = e => {
              if(e.key === 'Enter') setTimeout(() => {
                document.querySelector('tbody').innerHTML += '<tr><td class="product-name-cell">G126956_[끈팬티]상품</td></tr>';
              }, 1800);
            };
          </script>
        '''))
        self.assertTrue(await _already_registered(self.page, 'G126956'))
        self.assertEqual(await self.page.locator('tbody tr').count(), 2)

    async def test_domesin_minor_selection_sets_and_verifies_the_correct_radio(self):
        await self.page.set_content('''
          <label><input type="radio" name="adult" value="0" checked>일반상품</label>
          <label><input type="radio" name="adult" value="1">성인전용상품</label>
        ''')
        await _set_adult_sale(self.page, {"minorSalesAllowed": False})
        self.assertTrue(await self.page.locator('input[name="adult"][value="1"]').is_checked())
        self.assertFalse(await self.page.locator('input[name="adult"][value="0"]').is_checked())
        await _set_adult_sale(self.page, {"minorSalesAllowed": True})
        self.assertTrue(await self.page.locator('input[name="adult"][value="0"]').is_checked())
        with self.assertRaisesRegex(RuntimeError, "미성년자 판매 설정"):
            await _set_adult_sale(self.page, {})

    async def test_domesin_refuses_to_register_if_adult_choice_is_missing(self):
        await self.page.set_content('<input type="radio" name="adult" value="0" checked>')
        with self.assertRaisesRegex(RuntimeError, "성인전용상품"):
            await _set_adult_sale(self.page, {"minorSalesAllowed": False})

    async def test_domesin_waits_for_ajax_category_option(self):
        await self.page.set_content('''
          <select name="cate2"><option value="">선택</option></select>
          <script>
            setTimeout(() => {
              document.querySelector('select[name="cate2"]').add(
                new Option('여성의류', 'women')
              );
            }, 800);
          </script>
        ''')
        await _select_text(self.page, 'select[name="cate2"]', "여성의류")
        self.assertEqual(await self.page.locator('select[name="cate2"]').input_value(), "women")


if __name__ == '__main__':
    unittest.main()
