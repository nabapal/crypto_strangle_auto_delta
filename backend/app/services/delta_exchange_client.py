from __future__ import annotations

import hashlib
import hmac
import time
import json
import logging
import uuid
from typing import Any, Dict, Iterable

import httpx

from ..core.config import get_settings


logger = logging.getLogger("delta.client")


class DeltaExchangeClient:
    """Thin async wrapper around Delta Exchange REST API."""

    def __init__(self, api_key: str | None = None, api_secret: str | None = None, testnet: bool = False):
        settings = get_settings()
        self.api_key = api_key or settings.delta_api_key or ""
        self.api_secret = api_secret or settings.delta_api_secret or ""
        self.base_url = settings.delta_testnet_url if testnet else settings.delta_base_url
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        self._debug_verbose = settings.delta_debug_verbose
        self._max_body_bytes = settings.delta_debug_max_body_bytes

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    async def close(self) -> None:
        await self._client.aclose()

    async def _sign(self, method: str, path: str, params: Dict[str, Any] | None, body: Dict[str, Any] | None) -> Dict[str, str]:
        timestamp = str(int(time.time()))
        method_upper = method.upper()
        payload = f"{method_upper}{timestamp}{path}"
        if params:
            payload += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if body:
            try:
                payload += json.dumps(body, separators=(",", ":"), ensure_ascii=False, default=str)
            except TypeError:
                payload += json.dumps(
                    self._mask_sensitive(body),
                    separators=(",", ":"),
                    ensure_ascii=False,
                    default=str,
                )
        signature = hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return {
            "api-key": self.api_key,
            "signature": signature,
            "timestamp": timestamp,
        }

    async def request(
        self,
        method: str,
        path: str,
        params: Dict[str, Any] | None = None,
        body: Dict[str, Any] | None = None,
        auth: bool = False,
    ) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth:
            headers.update(await self._sign(method, path, params, body))

        call_id = uuid.uuid4().hex
        log_extra = {
            "delta_call_id": call_id,
            "delta_method": method.upper(),
            "delta_path": path,
            "delta_auth": auth,
        }

        if params:
            log_extra["delta_params"] = self._truncated_payload(params)
        if body and self._debug_verbose:
            log_extra["delta_body"] = self._truncated_payload(body)

        logger.info("Delta request start", extra=log_extra)
        start = time.perf_counter()

        try:
            response = await self._client.request(method, path, params=params, json=body, headers=headers)
            latency_ms = (time.perf_counter() - start) * 1000
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            response = exc.response
            error_body: str | None = None
            error_extra = {
                **log_extra,
                "delta_latency_ms": round(latency_ms, 2),
                "delta_status": response.status_code if response is not None else None,
                "delta_error": exc.__class__.__name__,
            }
            if response is not None:
                try:
                    parsed_body = response.json()
                except ValueError:
                    try:
                        error_body = self._truncate_text(response.text)
                    except Exception:  # noqa: BLE001
                        error_body = "<unable to read response body>"
                else:
                    error_body = self._truncated_payload(parsed_body)
                    if isinstance(parsed_body, dict):
                        error_message = parsed_body.get("error") or parsed_body.get("message")
                        error_code = parsed_body.get("error_code") or parsed_body.get("code")
                        if error_message:
                            error_extra["delta_error_message"] = error_message
                        if error_code:
                            error_extra["delta_error_code"] = error_code
            if error_body:
                error_extra["delta_response_body"] = error_body
            logger.error("Delta request failed", extra=error_extra)
            raise
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - start) * 1000
            error_extra = {
                **log_extra,
                "delta_latency_ms": round(latency_ms, 2),
                "delta_error": exc.__class__.__name__,
            }
            logger.exception("Delta request error", extra=error_extra)
            raise

        data = response.json()
        success_extra = {
            **log_extra,
            "delta_latency_ms": round(latency_ms, 2),
            "delta_status": response.status_code,
        }
        if self._debug_verbose:
            success_extra["delta_response_body"] = self._truncated_payload(data)
        logger.info("Delta request success", extra=success_extra)
        return data

    async def get_products(self) -> Dict[str, Any]:
        return await self.request("GET", "/v2/products")

    async def get_product(self, product_id: int | str) -> Dict[str, Any]:
        return await self.request("GET", f"/v2/products/{product_id}")

    async def get_tickers(self, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return await self.request("GET", "/v2/tickers", params=params)

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        return await self.request("GET", f"/v2/tickers/{symbol}")

    async def get_positions(self) -> Dict[str, Any]:
        return await self.request("GET", "/v2/positions", auth=True)

    async def get_margined_positions(self) -> Dict[str, Any]:
        return await self.request("GET", "/v2/positions/margined", auth=True)

    async def get_order(self, order_id: str | int) -> Dict[str, Any]:
        return await self.request("GET", f"/v2/orders/{order_id}", auth=True)

    async def get_orders(self, states: Iterable[str]) -> Dict[str, Any]:
        return await self.request("GET", "/v2/orders", params={"states": ",".join(states)}, auth=True)

    async def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self.request("POST", "/v2/orders", body=payload, auth=True)

    async def cancel_order(self, order_id: str | int, product_id: int | None = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"id": str(order_id)}
        if product_id is not None:
            body["product_id"] = product_id
        return await self.request("DELETE", "/v2/orders", body=body, auth=True)

    def _truncated_payload(self, payload: Any) -> str:
        try:
            text = json.dumps(self._mask_sensitive(payload), ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            text = str(payload)
        return self._truncate_text(text)

    def _truncate_text(self, value: str) -> str:
        if len(value) <= self._max_body_bytes:
            return value
        return value[: self._max_body_bytes] + "… [truncated]"

    def _mask_sensitive(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            masked = {}
            for key, val in payload.items():
                lower = key.lower()
                if any(token in lower for token in {"secret", "signature", "api_key"}):
                    masked[key] = "***"
                else:
                    masked[key] = self._mask_sensitive(val)
            return masked
        if isinstance(payload, list):
            return [self._mask_sensitive(item) for item in payload]
        return payload
