#!/usr/bin/env python3
"""Unit tests for Tesla/tesla_client.py — retry + TeslaFleetError rewrap."""

import sys
import unittest
from typing import Any, Awaitable, Callable
from unittest.mock import MagicMock, patch

sys.modules.setdefault("lib", MagicMock())
sys.modules.setdefault("lib.logger", MagicMock())

from tesla_fleet_api.exceptions import InternalServerError, TeslaFleetError  # noqa: E402
from tesla_fleet_api.tesla import TeslaFleetOAuth  # noqa: E402

from Tesla.tesla_client import TeslaAPIClient, TeslaAPIError  # noqa: E402


async def _noop(_oauth: TeslaFleetOAuth) -> Any:  # placeholder for the Callable type
    return None


_FN: Callable[[TeslaFleetOAuth], Awaitable[Any]] = _noop


def _make_client() -> TeslaAPIClient:
    client = TeslaAPIClient.__new__(TeslaAPIClient)
    client.logger = MagicMock()
    return client


class TestRetryAndRewrap(unittest.TestCase):
    def test_success_no_retry(self) -> None:
        client = _make_client()
        with patch("Tesla.tesla_client.asyncio.run", return_value="ok") as run:
            self.assertEqual(client._run(_FN), "ok")
            self.assertEqual(run.call_count, 1)

    def test_transient_then_success(self) -> None:
        client = _make_client()
        side_effects = [InternalServerError({"error": "boom"}), "ok"]
        with patch("Tesla.tesla_client.asyncio.run", side_effect=side_effects) as run:
            with patch("time.sleep"):  # tenacity uses time.sleep
                self.assertEqual(client._run(_FN), "ok")
        self.assertEqual(run.call_count, 2)

    def test_gives_up_after_three_and_rewraps(self) -> None:
        client = _make_client()
        boom = InternalServerError({"error": "boom"})
        with patch("Tesla.tesla_client.asyncio.run", side_effect=[boom, boom, boom]) as run:
            with patch("time.sleep"):
                with self.assertRaises(TeslaAPIError) as ctx:
                    client._run(_FN)
        self.assertEqual(run.call_count, 3)
        self.assertIsInstance(ctx.exception.__cause__, TeslaFleetError)

    def test_teslaapierror_is_exception_not_baseexception_only(self) -> None:
        # Guard against regression where callers can't catch Tesla errors with
        # `except Exception`.
        self.assertTrue(issubclass(TeslaAPIError, Exception))


if __name__ == "__main__":
    unittest.main()
