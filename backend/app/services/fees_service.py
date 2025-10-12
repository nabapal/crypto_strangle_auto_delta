from typing import Literal


class FeeCalculationError(Exception):
    """Raised when fee calculation inputs are invalid."""


def calculate_option_fee(
    underlying_price: float,
    contract_size: float,
    quantity: int,
    premium: float,
    fee_rate: float = 0.00015,
    premium_cap_rate: float = 0.05,
    order_type: Literal["maker", "taker"] = "taker",
) -> dict:
    """Calculate Delta Exchange option trading fee with premium cap consideration."""

    if underlying_price <= 0:
        raise FeeCalculationError("Underlying price must be greater than zero.")
    if contract_size <= 0:
        raise FeeCalculationError("Contract size must be greater than zero.")
    if quantity <= 0:
        raise FeeCalculationError("Quantity must be greater than zero.")
    if premium < 0:
        raise FeeCalculationError("Premium cannot be negative.")
    if fee_rate < 0:
        raise FeeCalculationError("Fee rate cannot be negative.")
    if premium_cap_rate < 0:
        raise FeeCalculationError("Premium cap rate cannot be negative.")

    notional = underlying_price * contract_size * quantity
    premium_value = contract_size * quantity * premium

    notional_fee = notional * fee_rate
    premium_cap = premium_value * premium_cap_rate

    if premium_value <= 0:
        applied_fee = notional_fee
        cap_applied = False
    else:
        applied_fee = min(notional_fee, premium_cap)
        cap_applied = applied_fee == premium_cap

    gst_rate = 0.18
    total_fee_with_gst = applied_fee * (1 + gst_rate)

    return {
        "underlying_price": underlying_price,
        "contract_size": contract_size,
        "quantity": quantity,
        "premium": premium,
        "fee_rate": fee_rate,
        "premium_cap_rate": premium_cap_rate,
        "notional": notional,
        "notional_fee": notional_fee,
        "premium_value": premium_value,
        "premium_cap": premium_cap,
        "fee": applied_fee,
        "applied_fee": applied_fee,
        "cap_applied": cap_applied,
        "order_type": order_type,
        "gst_rate": gst_rate,
        "total_fee_with_gst": total_fee_with_gst,
        "breakdown": {
            "notional_fee": notional_fee,
            "premium_cap": premium_cap,
            "applied_fee": applied_fee,
            "cap_applied": cap_applied,
            "gst_rate": gst_rate,
            "total_fee_with_gst": total_fee_with_gst,
        },
    }
