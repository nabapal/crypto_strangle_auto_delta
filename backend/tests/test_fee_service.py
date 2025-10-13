import pytest

from backend.app.services.fees_service import FeeCalculationError, calculate_option_fee


def test_fee_capping_applies():
    result = calculate_option_fee(
        underlying_price=26200,
        contract_size=0.001,
        quantity=300,
        premium=15,
        order_type="taker",
    )

    assert result["notional"] == pytest.approx(7860)
    assert result["notional_fee"] == pytest.approx(1.179)
    assert result["premium_value"] == pytest.approx(4.5)
    assert result["premium_cap"] == pytest.approx(0.225)
    assert result["applied_fee"] == pytest.approx(0.225)
    assert result["cap_applied"] is True
    assert result["fee_rate"] == pytest.approx(0.00015)
    assert result["premium_cap_rate"] == pytest.approx(0.05)


def test_fee_capping_not_applies():
    result = calculate_option_fee(
        underlying_price=10000,
        contract_size=0.001,
        quantity=100,
        premium=50,
        order_type="maker",
    )

    assert result["applied_fee"] == pytest.approx(0.15)
    assert result["cap_applied"] is False


def test_zero_premium_uses_notional_fee():
    result = calculate_option_fee(
        underlying_price=10000,
        contract_size=0.001,
        quantity=10,
        premium=0,
        order_type="taker",
    )

    assert result["premium_value"] == 0
    assert result["premium_cap"] == 0
    assert result["applied_fee"] == pytest.approx(result["notional_fee"])
    assert result["cap_applied"] is False


@pytest.mark.parametrize(
    "args",
    [
        {"underlying_price": 0, "contract_size": 0.001, "quantity": 10, "premium": 10},
        {"underlying_price": 10000, "contract_size": 0, "quantity": 10, "premium": 10},
        {"underlying_price": 10000, "contract_size": 0.001, "quantity": 0, "premium": 10},
        {"underlying_price": 10000, "contract_size": 0.001, "quantity": 10, "premium": -5},
        {"underlying_price": 10000, "contract_size": 0.001, "quantity": 10, "premium": 5, "fee_rate": -0.1},
        {
            "underlying_price": 10000,
            "contract_size": 0.001,
            "quantity": 10,
            "premium": 5,
            "premium_cap_rate": -0.5,
        },
    ],
)
def test_invalid_inputs(args):
    with pytest.raises(FeeCalculationError):
        calculate_option_fee(**args)
