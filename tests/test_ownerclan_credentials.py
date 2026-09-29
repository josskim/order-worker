from __future__ import annotations

import pytest

from order_worker import config
from order_worker.sites import ownerclan, ownerclan_invoice


def test_primary_ownerclan_account_uses_environment_password() -> None:
    account = next(item for item in ownerclan.ACCOUNTS if item[0] == "ownerclan")

    assert account[1] == config.OWNERCLAN_ID == "2010019378"
    assert account[2] == config.OWNERCLAN_PASSWORD
    assert ownerclan_invoice.ACCOUNTS["ownerclan"][1] == config.OWNERCLAN_PASSWORD
    assert config.OWNERCLAN_PASSWORD


def test_missing_ownerclan_password_fails_before_browser_login() -> None:
    with pytest.raises(RuntimeError, match="OWNERCLAN_PASSWORD"):
        config.require_credential("", "OWNERCLAN_PASSWORD")
