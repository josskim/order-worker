from __future__ import annotations

import re
import unicodedata


class ProductNotFound(RuntimeError):
    """The target product is not registered in this vendor account."""


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def option_tokens(value: str) -> list[str]:
    return [normalize(part) for part in re.split(r"\s*(?:/|\||,)\s*", value or "") if part.strip()]


def option_matches(target: str, remote: str) -> bool:
    wanted = option_tokens(target)
    found = option_tokens(remote)
    if not wanted:
        return False
    if len(wanted) == 1:
        return wanted[0] in found or wanted[0] == normalize(remote)
    return wanted == found


def failed(site: str, site_code: str, action: str, product_code: str, error: Exception | str) -> dict:
    return {
        "site": site,
        "siteCode": site_code,
        "action": action,
        "productCode": product_code,
        "success": False,
        "error": str(error),
    }


def product_not_found(site: str, site_code: str, action: str, product_code: str) -> dict:
    return {
        "site": site,
        "siteCode": site_code,
        "action": action,
        "productCode": product_code,
        "success": True,
        "notFound": True,
        "message": "상품없음",
    }
