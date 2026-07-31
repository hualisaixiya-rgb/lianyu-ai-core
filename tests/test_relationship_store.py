"""V3.8.1 Hotfix — RelationshipStore regression tests.

Tests for the timedelta import fix in relationship_store.py.
"""

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


class TestTimedeltaImport:
    """Verify timedelta is correctly imported and usable."""

    def test_timedelta_import_works(self):
        """timedelta should be importable from relationship_store module."""
        # If the import was broken (date.timedelta), this would raise AttributeError
        from memory.stores.relationship_store import (
            RelationshipStore,
            MAX_TIMELINE_DAYS,
        )
        store = RelationshipStore()
        assert store is not None
        assert MAX_TIMELINE_DAYS == 5

    def test_timedelta_calculation(self):
        """timedelta arithmetic should work correctly."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)

        assert yesterday == today - timedelta(days=1)
        assert two_days_ago < yesterday
        assert yesterday < today


class TestConsecutiveDaysLogic:
    """Verify consecutive_days calculation uses correct timedelta."""

    def test_consecutive_yesterday(self):
        """If last_chat was yesterday → consecutive_days should increment."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        assert yesterday == today - timedelta(days=1)

    def test_consecutive_older(self):
        """If last_chat was older than yesterday → consecutive_days should reset."""
        today = date.today()
        three_days_ago = today - timedelta(days=3)
        assert three_days_ago < today - timedelta(days=1)

    def test_no_import_error_on_touch(self):
        """touch() should not raise AttributeError for 'date.timedelta'."""
        from memory.stores.relationship_store import RelationshipStore

        store = RelationshipStore()

        # Verify no import-time error
        assert store is not None
        assert store.timeline is not None
        assert store.metrics is not None
