from dataclasses import dataclass


@dataclass
class WebullConfig:
    app_key: str
    app_secret: str
    account_id: str = ""
    environment: str = "production"

    @property
    def base_url(self) -> str:
        if self.environment == "test":
            return "https://us-openapi-alb.uat.webullbroker.com"
        return "https://api.webull.com"

    @property
    def events_url(self) -> str:
        if self.environment == "test":
            return "us-openapi-events.uat.webullbroker.com"
        return "events-api.webull.com"

    @property
    def mqtt_host(self) -> str:
        return "data-api.webull.com"

    @property
    def mqtt_port(self) -> int:
        return 1883

    @property
    def mqtt_wss_url(self) -> str:
        return "wss://data-api.webull.com:8883/mqtt"
