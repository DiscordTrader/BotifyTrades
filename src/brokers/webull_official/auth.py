import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import quote


class WebullAuth:
    def __init__(self, app_key: str, app_secret: str):
        self._app_key = app_key
        self._signing_key = (app_secret + "&").encode("utf-8")

    def sign_request(self, method: str, path: str, host: str,
                     query_params: dict = None, body: dict = None) -> dict:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nonce = uuid.uuid4().hex

        signing_headers = {
            "x-app-key": self._app_key,
            "x-timestamp": timestamp,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "host": host,
        }

        all_params = {}
        all_params.update(signing_headers)
        if query_params:
            all_params.update(query_params)

        sorted_pairs = sorted(all_params.items())
        str1 = "&".join(f"{k}={v}" for k, v in sorted_pairs)

        str3 = path + "&" + str1
        if body is not None:
            compact_body = json.dumps(body, separators=(",", ":"), sort_keys=False)
            str2 = hashlib.md5(compact_body.encode("utf-8")).hexdigest().upper()
            str3 += "&" + str2

        encoded_string = quote(str3, safe="")

        sig_bytes = hmac.new(
            self._signing_key,
            encoded_string.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        signature = base64.b64encode(sig_bytes).decode("utf-8")

        headers = {
            "x-app-key": self._app_key,
            "x-timestamp": timestamp,
            "x-signature": signature,
            "x-signature-algorithm": "HMAC-SHA1",
            "x-signature-version": "1.0",
            "x-signature-nonce": nonce,
            "x-version": "v2",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        return headers
