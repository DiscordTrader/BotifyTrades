from .client import WebullClient
from .models import WebullPosition


class PositionsAPI:
    def __init__(self, client: WebullClient):
        self._client = client

    async def get_positions(self, account_id: str) -> list[WebullPosition]:
        data = await self._client.get(
            "/openapi/assets/positions",
            params={"account_id": account_id},
        )
        items = data if isinstance(data, list) else data.get("positions", [])
        return [WebullPosition.from_api(p) for p in items]
