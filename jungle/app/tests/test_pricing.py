"""Cost calculation (spec 003 §3.5)."""

from decimal import Decimal

from brownbear.pricing import FALLBACK_MODEL, _candidates, calculate_cost


class TestCandidates:
    def test_tagged_model_tries_exact_then_family_then_fallback(self):
        assert _candidates("llama3:8b") == ["llama3:8b", "llama3", FALLBACK_MODEL]

    def test_untagged_model_skips_family_lookup(self):
        assert _candidates("gpt-4") == ["gpt-4", FALLBACK_MODEL]


class TestCalculateCost:
    def test_input_and_output_are_priced_separately(self):
        # GPT-4 defaults: $0.03 per 1k in, $0.06 per 1k out.
        cost = calculate_cost(1000, 500, Decimal("0.03"), Decimal("0.06"))
        assert cost == Decimal("0.060000")

    def test_free_model_costs_nothing(self):
        assert calculate_cost(9999, 9999, Decimal("0"), Decimal("0")) == Decimal("0")

    def test_zero_tokens_costs_nothing(self):
        assert calculate_cost(0, 0, Decimal("0.03"), Decimal("0.06")) == Decimal("0")

    def test_sub_cent_usage_is_not_rounded_away(self):
        """Six decimal places: a single short local-scale call must not vanish."""
        cost = calculate_cost(10, 0, Decimal("0.03"), Decimal("0.06"))
        assert cost == Decimal("0.000300")

    def test_result_is_quantized_to_six_places(self):
        cost = calculate_cost(1, 0, Decimal("0.000001"), Decimal("0"))
        assert cost.as_tuple().exponent == -6
