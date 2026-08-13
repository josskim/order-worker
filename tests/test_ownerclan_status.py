from order_worker.sites.ownerclan_status import option_values_match


def test_matches_single_color_to_color_size_option() -> None:
    assert option_values_match("그레이", ["그레이", "FREE"])


def test_matches_full_intranet_option_name() -> None:
    assert option_values_match("그레이/FREE", ["그레이", "FREE"])


def test_does_not_match_different_color() -> None:
    assert not option_values_match("그레이/FREE", ["블랙", "FREE"])
