"""Bucket arithmetic (spec 003 §3.4).

Bucket edges decide which window every event is counted in. If they drift,
aggregation stops being idempotent — the same event lands in a different
bucket on a re-run — so the edges are pinned here rather than trusted.
"""

from datetime import UTC, datetime, timedelta, timezone

from brownbear.aggregation import MAX_BUCKETS_PER_RUN, bucket_bounds
from brownbear.models.tokens import PeriodType
from brownbear.routers.tokens import _resolve_range, _utc


class TestBucketBounds:
    def test_hourly_truncates_to_the_hour(self):
        start, end = bucket_bounds(
            PeriodType.hourly, datetime(2026, 7, 30, 14, 37, 12, 500, tzinfo=UTC)
        )
        assert start == datetime(2026, 7, 30, 14, 0, tzinfo=UTC)
        assert end == datetime(2026, 7, 30, 15, 0, tzinfo=UTC)

    def test_daily_truncates_to_midnight(self):
        start, end = bucket_bounds(
            PeriodType.daily, datetime(2026, 7, 30, 23, 59, 59, tzinfo=UTC)
        )
        assert start == datetime(2026, 7, 30, tzinfo=UTC)
        assert end == datetime(2026, 7, 31, tzinfo=UTC)

    def test_weekly_starts_on_monday(self):
        # 2026-07-30 is a Thursday.
        start, end = bucket_bounds(PeriodType.weekly, datetime(2026, 7, 30, 12, tzinfo=UTC))
        assert start == datetime(2026, 7, 27, tzinfo=UTC)  # Monday
        assert start.weekday() == 0
        assert end == datetime(2026, 8, 3, tzinfo=UTC)

    def test_weekly_on_a_monday_does_not_jump_back_a_week(self):
        start, _ = bucket_bounds(PeriodType.weekly, datetime(2026, 7, 27, 0, 0, tzinfo=UTC))
        assert start == datetime(2026, 7, 27, tzinfo=UTC)

    def test_monthly_spans_the_calendar_month(self):
        start, end = bucket_bounds(PeriodType.monthly, datetime(2026, 7, 15, tzinfo=UTC))
        assert start == datetime(2026, 7, 1, tzinfo=UTC)
        assert end == datetime(2026, 8, 1, tzinfo=UTC)

    def test_december_rolls_into_january_of_the_next_year(self):
        start, end = bucket_bounds(PeriodType.monthly, datetime(2026, 12, 9, tzinfo=UTC))
        assert start == datetime(2026, 12, 1, tzinfo=UTC)
        assert end == datetime(2027, 1, 1, tzinfo=UTC)

    def test_february_length_follows_the_calendar(self):
        _, end = bucket_bounds(PeriodType.monthly, datetime(2028, 2, 3, tzinfo=UTC))
        assert end == datetime(2028, 3, 1, tzinfo=UTC)  # 2028 is a leap year

    def test_non_utc_input_is_bucketed_in_utc(self):
        """A moment given in +06:00 must land in the UTC bucket, not the local one."""
        dhaka = timezone(timedelta(hours=6))
        # 2026-07-30 02:30 +06:00 is 2026-07-29 20:30 UTC — the previous day.
        start, _ = bucket_bounds(
            PeriodType.daily, datetime(2026, 7, 30, 2, 30, tzinfo=dhaka)
        )
        assert start == datetime(2026, 7, 29, tzinfo=UTC)

    def test_buckets_tile_without_gaps_or_overlap(self):
        for period in PeriodType:
            _, end = bucket_bounds(period, datetime(2026, 7, 30, 14, 37, tzinfo=UTC))
            next_start, _ = bucket_bounds(period, end)
            assert next_start == end, f"{period} leaves a gap at the boundary"

    def test_every_period_has_a_catch_up_cap(self):
        assert set(MAX_BUCKETS_PER_RUN) == set(PeriodType)


class TestRangeResolution:
    def test_naive_input_is_read_as_utc_not_host_local(self):
        assert _utc(datetime(2026, 7, 30, 12)) == datetime(2026, 7, 30, 12, tzinfo=UTC)

    def test_explicit_range_is_preserved(self):
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 7, 15, tzinfo=UTC)
        assert _resolve_range(PeriodType.daily, start, end) == (start, end)

    def test_default_range_ends_after_now_and_looks_backwards(self):
        start, end = _resolve_range(PeriodType.daily, None, None)
        assert start < datetime.now(UTC) < end
        assert (end - start).days >= 30
