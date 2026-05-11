from .client import WebullClient
from .models import WebullAccount, WebullBalance


class AccountsAPI:
    def __init__(self, client: WebullClient):
        self._client = client

    async def list_accounts(self) -> list[WebullAccount]:
        data = await self._client.get("/openapi/account/list")
        if not isinstance(data, list):
            data = data.get("accounts", data.get("data", []))
        return [
            WebullAccount(
                account_id=a.get("account_id", ""),
                account_type=a.get("account_type", ""),
                account_class=a.get("account_class", ""),
                account_label=a.get("account_label", ""),
                user_id=a.get("user_id", ""),
            )
            for a in data
        ]

    async def get_balance(self, account_id: str) -> WebullBalance:
        data = await self._client.get(
            "/openapi/assets/balance",
            params={"account_id": account_id},
        )
        return WebullBalance.from_api(data)
