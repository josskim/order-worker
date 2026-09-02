import asyncio
from unittest.mock import AsyncMock, MagicMock

from order_worker.sites.ownerclan_status import _goto, _select_model_search, option_values_match


def test_matches_single_color_to_color_size_option() -> None:
    assert option_values_match("그레이", ["그레이", "FREE"])


def test_matches_full_intranet_option_name() -> None:
    assert option_values_match("그레이/FREE", ["그레이", "FREE"])


def test_does_not_match_different_color() -> None:
    assert not option_values_match("그레이/FREE", ["블랙", "FREE"])


def test_ownerclan_search_uses_model_field() -> None:
    page = MagicMock()
    search_type = MagicMock()
    search_type.first = search_type
    search_type.wait_for = AsyncMock()
    search_type.select_option = AsyncMock()
    page.locator.return_value = search_type

    asyncio.run(_select_model_search(page))

    page.locator.assert_called_once_with('select[name="s_check"]:visible')
    search_type.wait_for.assert_awaited_once_with(state="visible", timeout=10000)
    search_type.select_option.assert_awaited_once_with("model")


def test_ownerclan_navigation_does_not_wait_for_network_idle() -> None:
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock()

    asyncio.run(_goto(page, "https://ownerclan.example/products"))

    page.goto.assert_awaited_once_with(
        "https://ownerclan.example/products",
        wait_until="domcontentloaded",
        timeout=15000,
    )
    page.evaluate.assert_awaited_once_with("window.stop()")
