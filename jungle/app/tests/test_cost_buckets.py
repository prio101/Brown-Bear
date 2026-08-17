"""Bucketed input pricing and the savings report (spec 003 §3.5 rev 2).

These pin the arithmetic that decides money. The bug they exist to prevent is not
subtle in effect but was invisible in code: every input token priced at the base
rate, when providers bill cache reads at a tenth of it. On the live instance that
reported $887 for a month, including one turn charged $248 for 15.7M input tokens —
more than the context window holds, so almost all of it was cache reads.
"""

from decimal import Decimal

import pytest

from brownbear.pricing import (
    Rates,
    calculate_avoided_cost,
    calculate_bucketed_cost,
    calculate_cost,
    estimate_tokens,
)

# claude-opus-5's live rates.
OPUS = Rates(
    input_per_1k=Decimal("0.015"),
    output_per_1k=Decimal("0.075"),
    currency="USD",
    matched="claude-opus-5",
)


class TestBucketedCost:
    def test_fresh_input_is_priced_at_the_base_rate(self):
        cost = calculate_bucketed_cost(
            tokens_in_fresh=1000, tokens_cache_write=0, tokens_cache_read=0,
            tokens_out=0, rates=OPUS,
        )
        assert cost == Decimal("0.015000")

    def test_cache_writes_cost_more_than_fresh(self):
        """Creating a cache entry is billed above par — 1.25x for Anthropic."""
        cost = calculate_bucketed_cost(
            tokens_in_fresh=0, tokens_cache_write=1000, tokens_cache_read=0,
            tokens_out=0, rates=OPUS,
        )
        assert cost == Decimal("0.018750")

    def test_cache_reads_cost_a_tenth(self):
        cost = calculate_bucketed_cost(
            tokens_in_fresh=0, tokens_cache_write=0, tokens_cache_read=1000,
            tokens_out=0, rates=OPUS,
        )
        assert cost == Decimal("0.001500")

    def test_output_is_unaffected_by_the_multipliers(self):
        cost = calculate_bucketed_cost(
            tokens_in_fresh=0, tokens_cache_write=0, tokens_cache_read=0,
            tokens_out=1000, rates=OPUS,
        )
        assert cost == Decimal("0.075000")

    def test_the_real_overcharge(self):
        """The live event that made this worth fixing.

        15,677,716 input tokens and 179,801 output, recorded at $248.65 under the
        flat rule. A turn cannot send 15.7M fresh tokens — the context window is
        1M — so it is overwhelmingly cache reads.
        """
        flat = calculate_cost(15_677_716, 179_801, OPUS.input_per_1k, OPUS.output_per_1k)
        assert flat == Decimal("248.650815")

        bucketed = calculate_bucketed_cost(
            tokens_in_fresh=20_000,
            tokens_cache_write=100_000,
            tokens_cache_read=15_557_716,
            tokens_out=179_801,
            rates=OPUS,
        )
        # Roughly a seventh of what was reported.
        assert bucketed < flat / 6
        assert Decimal("35") < bucketed < Decimal("40")

    def test_multipliers_are_configurable_per_model(self):
        """A provider that bills reads at par needs one row edited, not three
        rates kept in sync."""
        flat_provider = Rates(
            input_per_1k=Decimal("0.010"), output_per_1k=Decimal("0.030"),
            currency="USD", matched="x",
            cache_write_multiplier=Decimal("1.0"), cache_read_multiplier=Decimal("1.0"),
        )
        cost = calculate_bucketed_cost(
            tokens_in_fresh=1000, tokens_cache_write=1000, tokens_cache_read=1000,
            tokens_out=0, rates=flat_provider,
        )
        assert cost == Decimal("0.030000")

    def test_an_unpriced_model_is_free_not_untracked(self):
        free = Rates(Decimal("0"), Decimal("0"), "USD", None)
        cost = calculate_bucketed_cost(
            tokens_in_fresh=999_999, tokens_cache_write=0, tokens_cache_read=0,
            tokens_out=999_999, rates=free,
        )
        assert cost == Decimal("0.000000")


class TestAvoidedCost:
    def test_prices_avoided_output_at_the_output_rate(self):
        assert calculate_avoided_cost(1000, OPUS) == Decimal("0.075000")

    def test_zero_avoided_is_zero(self):
        assert calculate_avoided_cost(0, OPUS) == Decimal("0.000000")

    def test_input_is_never_claimed(self):
        """What the avoided call would have cost in INPUT is unknowable — Brown
        Bear never sees the context the client would have sent. Claiming it would
        be invention, so the saving is deliberately under-reported."""
        assert calculate_avoided_cost(1000, OPUS) == (Decimal("1000") / 1000) * OPUS.output_per_1k


class TestEstimateTokens:
    def test_roughly_four_characters_per_token(self):
        assert estimate_tokens("a" * 400) == 100

    def test_empty_is_zero(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0

    def test_short_text_is_at_least_one(self):
        assert estimate_tokens("hi") == 1


class TestRecording:
    """Through record_token_event_sync, with the session faked."""

    @pytest.fixture
    def captured(self, monkeypatch):
        from brownbear import tracking

        rows = []

        class _Session:
            def add(self, obj):
                rows.append(obj)

            def flush(self):
                obj = rows[-1]
                obj.id = len(rows)

        class _Scope:
            def __enter__(self):
                return _Session()

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(tracking, "session_scope", lambda: _Scope())
        monkeypatch.setattr(tracking, "resolve", lambda session, model: OPUS)
        return rows

    def test_buckets_are_priced_and_stored(self, captured):
        from brownbear.tracking import record_token_event_sync

        record_token_event_sync(
            model="claude-opus-5",
            tokens_in=0,
            tokens_out=1000,
            tokens_in_fresh=1000,
            tokens_cache_write=0,
            tokens_cache_read=100_000,
        )
        event = captured[0]

        assert event.pricing_model == "bucketed"
        assert event.tokens_cache_read == 100_000
        # tokens_in is the sum of the buckets, not the caller's field.
        assert event.tokens_in == 101_000
        assert event.cost_usd == Decimal("0.240000")

    def test_without_buckets_it_stays_flat_and_says_so(self, captured):
        """Legacy clients keep working, and their rows are labelled rather than
        mixed in with correctly-priced ones."""
        from brownbear.tracking import record_token_event_sync

        record_token_event_sync(model="claude-opus-5", tokens_in=1000, tokens_out=0)
        event = captured[0]

        assert event.pricing_model == "flat"
        assert event.cost_usd == Decimal("0.015000")
        assert event.tokens_cache_read == 0

    def test_a_client_supplied_cost_still_wins(self, captured):
        """A client billed by its own provider knows the real figure."""
        from brownbear.tracking import record_token_event_sync

        record_token_event_sync(
            model="claude-opus-5",
            tokens_in=0,
            tokens_out=1000,
            tokens_in_fresh=1_000_000,
            cost_usd=Decimal("1.23"),
        )
        assert captured[0].cost_usd == Decimal("1.23")


class TestSavingsSemantics:
    def test_only_blocking_modes_count_as_avoided(self):
        """The distinction the whole card rests on: an inject-mode hit grounds the
        answer and the model still runs, so nothing is avoided."""
        from brownbear.savings import BLOCKING_MODES

        assert "block" in BLOCKING_MODES
        assert "inject" not in BLOCKING_MODES
