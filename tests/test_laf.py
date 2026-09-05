from order_worker.sites.laf import _article_id


def test_article_id_from_short_url() -> None:
    assert _article_id("https://cafe.naver.com/liveprice/80415") == "80415"


def test_article_id_from_editor_url() -> None:
    assert _article_id("https://cafe.naver.com/ca-fe/cafes/26667015/articles/80415") == "80415"


def test_article_id_from_encoded_legacy_url() -> None:
    url = "https://cafe.naver.com/liveprice?iframe_url_utf8=%2FArticleRead.nhn%253Fclubid%3D26667015%2526articleid%3D80415"
    assert _article_id(url) == "80415"
