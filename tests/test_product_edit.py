import pytest

from order_worker.sites.product_edit import _option_pairs


@pytest.mark.parametrize(
    ("worker_site", "ui_site"),
    [
        ("ownerclan", "ownerclan"),
        ("Fownerclan", "Fownerclan"),
        ("onchannel", "onch3"),
        ("Fonch3", "Fonch3"),
        ("domeggook", "domeggook"),
        ("Fdomeggook", "Fdomeggook"),
        ("specialoffer", "special"),
        ("domesin", "domegod"),
        ("namdo", "namdo"),
    ],
)
def test_option_pairs_use_ui_site_codes(worker_site: str, ui_site: str) -> None:
    changes = {
        "addOptions": [" 화이트 / FREE ", "화이트/FREE"],
        "optionSites": [ui_site],
    }

    assert _option_pairs(changes, worker_site) == [("화이트", "FREE")]


def test_option_pairs_ignore_unselected_site() -> None:
    changes = {"addOptions": ["화이트 / FREE"], "optionSites": ["namdo"]}

    assert _option_pairs(changes, "ownerclan") == []


@pytest.mark.parametrize("label", ["화이트", "화이트 /", "/ FREE", "화이트 / FREE / 0"])
def test_option_pairs_require_color_and_size(label: str) -> None:
    changes = {"addOptions": [label], "optionSites": ["ownerclan"]}

    with pytest.raises(RuntimeError, match="색상 / 사이즈"):
        _option_pairs(changes, "ownerclan")
