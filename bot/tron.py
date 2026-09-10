import aiohttp

USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


class TronClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str | None = None):
        self.session = session
        self.api_key = api_key
        self.base_url = "https://api.trongrid.io"

    async def get_incoming_transfers(self, address: str, limit: int = 20) -> list[dict]:
        url = f"{self.base_url}/v1/accounts/{address}/transactions/trc20"
        params = {
            "limit": str(limit),
            "contract_address": USDT_TRC20_CONTRACT,
            "only_to": "true",
            "order_by": "block_timestamp,desc",
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
        for item in payload.get("data", []):
            if item.get("to") != address:
                continue
            decimals = int((item.get("token_info") or {}).get("decimals", 6))
            try:
                raw_value = int(item.get("value", 0))
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "transaction_id": item.get("transaction_id"),
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "amount": raw_value / (10**decimals),
                }
            )
        return results
