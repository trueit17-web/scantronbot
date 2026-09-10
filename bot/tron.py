import aiohttp

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_DECIMALS = 6


class TronClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str | None = None):
        self.session = session
        self.api_key = api_key
        self.base_url = "https://apilist.tronscan.org/api"

    async def get_incoming_transfers(self, address: str, limit: int = 20) -> list[dict]:
        url = f"{self.base_url}/token_trc20/transfers"
        params = {
            "limit": str(limit),
            "start": "0",
            "sort": "-timestamp",
            "count": "true",
            "filterTokenValue": "0",
            "relatedAddress": address,
            "trc20Id": USDT_TRC20_CONTRACT,
        }
        headers = {"TRON-PRO-API-KEY": self.api_key} if self.api_key else {}

        async with self.session.get(
            url,
            params=params,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()

        results = []
        for item in payload.get("token_transfers", []):
            if item.get("to_address") != address:
                continue
            if item.get("contract_address") != USDT_TRC20_CONTRACT:
                continue
            if not item.get("confirmed") or item.get("contractRet") != "SUCCESS":
                continue
            try:
                raw_value = int(item.get("quant", 0))
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "transaction_id": item.get("transaction_id"),
                    "from": item.get("from_address"),
                    "to": item.get("to_address"),
                    "amount": raw_value / (10**USDT_DECIMALS),
                }
            )
        return results
