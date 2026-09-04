from order_worker.sites.status_utils import option_matches


def test_namdo_option_matches_intranet_spacing_and_remote_case() -> None:
    assert option_matches("베이지 / FREE", "베이지/Free")


def test_namdo_option_rejects_another_color() -> None:
    assert not option_matches("베이지 / FREE", "아이보리/Free")
