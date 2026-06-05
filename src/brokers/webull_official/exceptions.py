class WebullAPIError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(f"[{status_code}] {error_code}: {message}")


class WebullAuthError(WebullAPIError):
    pass


class WebullRateLimitError(WebullAPIError):
    pass


class WebullOrderError(WebullAPIError):
    pass


class WebullConnectionError(Exception):
    pass
