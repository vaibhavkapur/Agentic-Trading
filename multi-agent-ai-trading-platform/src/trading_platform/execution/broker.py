"""Paper broker protocol and deterministic SimulatedPaperBroker with fault injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from trading_platform.domain.contracts import FillRecord, OrderIntent, QuoteSnapshot
from trading_platform.domain.types import OrderStatus


class BrokerTimeoutError(TimeoutError):
    """Raised when the paper broker transport times out (outcome on broker side may be uncertain)."""


@dataclass
class BrokerOrderResponse:
    broker_order_id: str
    client_order_id: str
    status: OrderStatus
    fills: list[FillRecord] = field(default_factory=list)


class PaperBroker(Protocol):
    def submit_order(
        self,
        *,
        order_id: str,
        client_order_id: str,
        order_intent: OrderIntent,
        quote: QuoteSnapshot,
        now_utc: datetime,
    ) -> BrokerOrderResponse: ...

    def query_by_client_order_id(self, client_order_id: str) -> BrokerOrderResponse | None: ...


class SimulatedPaperBroker:
    """Deterministic in-memory paper broker supporting full/partial fills, timeouts, and idempotent lookup."""

    def __init__(self) -> None:
        self._orders_by_client_id: dict[str, BrokerOrderResponse] = {}
        self._order_intents: dict[str, OrderIntent] = {}
        self._order_ids: dict[str, str] = {}
        self._last_quotes: dict[str, QuoteSnapshot] = {}
        # Fault injection knobs for deterministic failure-scenario testing
        self.fail_next_submit_with_timeout: bool = False
        self.accept_order_before_timeout: bool = True
        self.partial_fill_ratio: float = 1.0  # 1.0 = full fill; e.g. 0.5 = 50% partial fill
        self.submit_attempt_count: int = 0

    def submit_order(
        self,
        *,
        order_id: str,
        client_order_id: str,
        order_intent: OrderIntent,
        quote: QuoteSnapshot,
        now_utc: datetime,
    ) -> BrokerOrderResponse:
        self.submit_attempt_count += 1

        # Broker-side idempotency by client_order_id
        if client_order_id in self._orders_by_client_id:
            return self._orders_by_client_id[client_order_id]

        should_timeout = self.fail_next_submit_with_timeout
        if should_timeout:
            self.fail_next_submit_with_timeout = False
            if self.accept_order_before_timeout:
                # Realistic uncertain timeout: broker accepted & filled, but response was lost in transit
                self._record_fill_execution(
                    order_id=order_id,
                    client_order_id=client_order_id,
                    order_intent=order_intent,
                    quote=quote,
                    now_utc=now_utc,
                )
            raise BrokerTimeoutError(
                f"Simulated broker transport timeout for client_order_id={client_order_id}"
            )

        return self._record_fill_execution(
            order_id=order_id,
            client_order_id=client_order_id,
            order_intent=order_intent,
            quote=quote,
            now_utc=now_utc,
        )

    def _record_fill_execution(
        self,
        *,
        order_id: str,
        client_order_id: str,
        order_intent: OrderIntent,
        quote: QuoteSnapshot,
        now_utc: datetime,
    ) -> BrokerOrderResponse:
        broker_order_id = f"BRK-{uuid4().hex[:10].upper()}"
        exec_price = (
            order_intent.limit_price
            if order_intent.limit_price is not None
            else (quote.ask if order_intent.side.value == "BUY" else quote.bid)
        )
        # Paper execution improves slightly or fills at quote if limit is marketable
        if order_intent.side.value == "BUY":
            fill_price = min(exec_price, quote.ask) if order_intent.limit_price else quote.ask
        else:
            fill_price = max(exec_price, quote.bid) if order_intent.limit_price else quote.bid

        fill_price = Decimal(fill_price).quantize(Decimal("0.01"))
        ratio = max(0.0, min(1.0, self.partial_fill_ratio))
        if ratio < 1.0 and order_intent.quantity > 1:
            fill_qty = max(1, int(order_intent.quantity * ratio))
            status = OrderStatus.PARTIALLY_FILLED
        else:
            fill_qty = order_intent.quantity
            status = OrderStatus.FILLED

        fill = FillRecord(
            fill_id=f"FILL-{uuid4().hex[:10].upper()}",
            broker_fill_id=f"BF-{client_order_id}-1",
            order_id=order_id,
            client_order_id=client_order_id,
            symbol=order_intent.symbol,
            side=order_intent.side,
            quantity=fill_qty,
            price=fill_price,
            currency=order_intent.currency,
            executed_at_utc=now_utc,
        )
        response = BrokerOrderResponse(
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            status=status,
            fills=[fill],
        )
        self._orders_by_client_id[client_order_id] = response
        self._order_intents[client_order_id] = order_intent
        self._order_ids[client_order_id] = order_id
        self._last_quotes[client_order_id] = quote
        return response

    def complete_partial_fill(
        self,
        *,
        client_order_id: str,
        now_utc: datetime,
    ) -> FillRecord:
        """Emit the remaining fill leg for a partially filled paper order."""
        existing = self._orders_by_client_id.get(client_order_id)
        if existing is None:
            raise ValueError(f"Unknown client_order_id={client_order_id}")
        intent = self._order_intents[client_order_id]
        filled_so_far = sum(f.quantity for f in existing.fills)
        remaining = intent.quantity - filled_so_far
        if remaining <= 0:
            raise ValueError(f"Order {client_order_id} is already completely filled.")
        fill_price = existing.fills[-1].price
        second_fill = FillRecord(
            fill_id=f"FILL-{uuid4().hex[:10].upper()}",
            broker_fill_id=f"BF-{client_order_id}-{len(existing.fills) + 1}",
            order_id=self._order_ids[client_order_id],
            client_order_id=client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=remaining,
            price=fill_price,
            currency=intent.currency,
            executed_at_utc=now_utc,
        )
        existing.fills.append(second_fill)
        existing.status = OrderStatus.FILLED
        return second_fill

    def query_by_client_order_id(self, client_order_id: str) -> BrokerOrderResponse | None:
        return self._orders_by_client_id.get(client_order_id)

    def total_broker_orders(self) -> int:
        return len(self._orders_by_client_id)
