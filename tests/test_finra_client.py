import os

import responses

os.environ.setdefault("FINRA_CLIENT_ID", "test_id")
os.environ.setdefault("FINRA_CLIENT_SECRET", "test_secret")

from dark_pool.finra.client import API_ROOT, DATASET, GROUP, TOKEN_URL, FinraClient  # noqa: E402


def _mock_token():
    responses.add(
        responses.POST, TOKEN_URL,
        json={"access_token": "fake-token", "expires_in": 3600}, status=200,
    )


@responses.activate
def test_token_is_fetched_once_and_cached():
    _mock_token()
    responses.add(responses.GET, f"{API_ROOT}/metadata/group/{GROUP}/name/{DATASET}", json=[{"name": "x"}])
    responses.add(responses.GET, f"{API_ROOT}/metadata/group/{GROUP}/name/{DATASET}", json=[{"name": "x"}])

    client = FinraClient()
    client.fields()
    client.fields()

    token_calls = [c for c in responses.calls if c.request.url.startswith(TOKEN_URL)]
    assert len(token_calls) == 1  # second fields() call reused the cached token


@responses.activate
def test_query_sends_compare_filters_in_body():
    _mock_token()
    responses.add(responses.POST, f"{API_ROOT}/data/group/{GROUP}/name/{DATASET}", json=[{"issueSymbolIdentifier": "JPM"}])

    client = FinraClient()
    filters = [{"compareType": "EQUAL", "fieldName": "issueSymbolIdentifier", "fieldValue": "JPM"}]
    rows = client.query(filters)

    assert rows == [{"issueSymbolIdentifier": "JPM"}]
    sent_body = responses.calls[-1].request.body
    assert b"compareFilters" in sent_body and b"JPM" in sent_body


@responses.activate
def test_query_all_pages_until_short_page():
    _mock_token()
    full_page = [{"i": i} for i in range(5000)]
    short_page = [{"i": i} for i in range(5000, 5123)]
    responses.add(responses.POST, f"{API_ROOT}/data/group/{GROUP}/name/{DATASET}", json=full_page)
    responses.add(responses.POST, f"{API_ROOT}/data/group/{GROUP}/name/{DATASET}", json=short_page)

    rows = FinraClient().query_all()
    assert len(rows) == 5123  # stopped after the short (non-full) page, no 3rd request

    data_calls = [c for c in responses.calls if c.request.url.startswith(f"{API_ROOT}/data/")]
    assert len(data_calls) == 2


@responses.activate
def test_query_all_respects_max_rows():
    _mock_token()
    full_page = [{"i": i} for i in range(5000)]
    responses.add(responses.POST, f"{API_ROOT}/data/group/{GROUP}/name/{DATASET}", json=full_page)
    responses.add(responses.POST, f"{API_ROOT}/data/group/{GROUP}/name/{DATASET}", json=full_page)

    rows = FinraClient().query_all(max_rows=7000)
    assert len(rows) == 7000
