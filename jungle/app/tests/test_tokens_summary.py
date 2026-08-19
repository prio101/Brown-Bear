"""What `/api/tokens/summary` says about silence (BB-205).

The totals were never the problem: they were right, and a right zero is what the
page could not read. Brown Bear's client hooks fail open and silent, so "nothing
reported today" and "reporting has been dead since yesterday afternoon" produce an
identical response — and for eighteen hours the dashboard showed the second as the
first.

So these assert the fields that separate them, not the arithmetic: when anything
last arrived, where it came from, and the window past which silence stops being
innocent. The database is stubbed, like everywhere else in this suite.
"""

from datetime import UTC, datetime, timedelta

import pytest

from brownbear.db import get_db
from brownbear.models.tokens import TokenSource


class _Row:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class _Result:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row

    def first(self):
        return self._row


class _Session:
    """Answers the two queries `summary()` makes, in the order it makes them.

    Order rather than statement inspection: the second query exists precisely
    because it is NOT the first one narrowed to the window, and a stub that
    answered both from one canned row could not tell the two apart.
    """

    def __init__(self, totals, latest):
        self._answers = [_Result(totals), _Result(latest)]

    def execute(self, statement):
        return self._answers.pop(0)


ZERO = _Row(tokens_in=0, tokens_out=0, total_tokens=0, cost=0, requests=0)


@pytest.fixture
def summary_of(client):
    """Install a stub session, then read the summary it produces."""

    def _install(latest, totals=ZERO):
        client.app.dependency_overrides[get_db] = lambda: _Session(totals, latest)
        response = client.get("/api/tokens/summary")
        assert response.status_code == 200
        return response.json()

    yield _install
    client.app.dependency_overrides.pop(get_db, None)


class TestLastReport:
    def test_reports_when_usage_last_arrived(self, summary_of):
        moment = datetime.now(UTC) - timedelta(hours=18)
        body = summary_of(_Row(timestamp=moment, source=TokenSource.remote_api))

        assert body["last_event_at"] == moment.isoformat()
        assert body["last_event_source"] == "remote_api"

    def test_the_last_report_is_not_scoped_to_the_window(self, summary_of):
        """The bug in one assertion.

        Today's total is zero and the last report is from yesterday: both facts
        have to survive into the same response, or the page cannot say which kind
        of zero it is showing.
        """
        yesterday = datetime.now(UTC) - timedelta(days=1)
        body = summary_of(_Row(timestamp=yesterday, source=TokenSource.remote_api))

        assert body["total_tokens"] == 0
        assert body["last_event_at"] is not None

    def test_never_reported_is_null_rather_than_an_epoch(self, summary_of):
        """A stack nobody has reported to yet is a different state from a stale
        one, and reads differently to a person. Null, never 1970."""
        body = summary_of(None)

        assert body["last_event_at"] is None
        assert body["last_event_source"] is None

    def test_declares_the_window_past_which_silence_is_suspect(self, summary_of):
        """Published for the same reason the agent inventory publishes its own:
        the page must not carry a private opinion about what stale means."""
        from brownbear.config import get_settings

        body = summary_of(None)

        assert body["stale_after_hours"] == get_settings().usage_stale_hours

    def test_the_totals_still_come_from_the_open_window(self, summary_of):
        """The freshness fields are additions, not a replacement — the live total
        is what the page was built to watch."""
        body = summary_of(
            None,
            totals=_Row(tokens_in=120, tokens_out=30, total_tokens=150, cost=0.5, requests=2),
        )

        assert body["total_tokens"] == 150
        assert body["request_count"] == 2
        assert body["live"] is True
        assert body["source"] == "token_events"
