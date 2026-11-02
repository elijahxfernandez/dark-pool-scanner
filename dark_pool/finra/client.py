"""A free, public FINRA API client for the otcMarket/weeklySummaryHistoric dataset
(FINRA's own regulatory disclosure of ATS/dark-pool and non-ATS off-exchange volume
by security, published weekly, going back ~4 years).

No cost, but needs a free account: register at developer.finra.org, create a "Public"
app, and put the Client ID/Secret in .env (see .env.example).

Docs are thin on the exact field names for this dataset, so this client discovers the
real schema from FINRA's own /metadata endpoint at request time instead of guessing -
call `fields()` before building filters.
"""

import time

import requests

from shared.config import finra_credentials

TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token"
API_ROOT = "https://api.finra.org"
GROUP = "otcMarket"
DATASET = "weeklySummaryHistoric"
PAGE_LIMIT = 5000  # FINRA's documented sync-request cap


class FinraClient:
    def __init__(self):
        self._token = None
        self._token_expiry = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        client_id, client_secret = finra_credentials()
        resp = requests.post(
            TOKEN_URL,
            params={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + float(body.get("expires_in", 3600))
        return self._token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}", "Accept": "application/json"}

    def fields(self) -> list[dict]:
        """The dataset's real field schema, straight from FINRA - use this to confirm
        field names (e.g. is it issueSymbolIdentifier or something else?) before
        trusting any filter you build."""
        url = f"{API_ROOT}/metadata/group/{GROUP}/name/{DATASET}"
        resp = requests.get(url, headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def query(self, filters: list[dict] | None = None, limit: int = PAGE_LIMIT, offset: int = 0) -> list[dict]:
        """One page of rows. filters is FINRA's compareFilters list, e.g.:
            [{"compareType": "EQUAL", "fieldName": "issueSymbolIdentifier", "fieldValue": "JPM"}]
        Field names must come from fields() - this dataset's exact names aren't
        publicly documented, so don't assume one without checking first.
        """
        url = f"{API_ROOT}/data/group/{GROUP}/name/{DATASET}"
        body = {"limit": limit, "offset": offset}
        if filters:
            body["compareFilters"] = filters
        resp = requests.post(url, headers=self._headers(), json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def query_all(self, filters: list[dict] | None = None, max_rows: int = 100_000) -> list[dict]:
        """Pages through query() until exhausted or max_rows is hit."""
        rows, offset = [], 0
        while len(rows) < max_rows:
            page = self.query(filters, limit=PAGE_LIMIT, offset=offset)
            if not page:
                break
            rows.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return rows[:max_rows]
