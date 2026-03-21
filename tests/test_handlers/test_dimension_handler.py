"""Tests for accounting dimension handler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.api_client import TripletexApiError
from src.handlers.base import get_handler
from src.models import ApiError
from tests.conftest import sample_api_response

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestFindOrCreateDimension:
    def test_finds_existing_dimension(self):
        from src.handlers.dimension import _find_or_create_dimension

        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 5, "dimensionName": "Region", "number": 2}]
        )
        dim_id, dim_index = _find_or_create_dimension(client, "Region")
        assert dim_id == 5
        assert dim_index == 2
        client.post.assert_not_called()

    def test_creates_new_dimension(self):
        from src.handlers.dimension import _find_or_create_dimension

        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        client.post.return_value = sample_api_response(value={"id": 10, "number": 3})
        dim_id, dim_index = _find_or_create_dimension(client, "Segment")
        assert dim_id == 10
        assert dim_index == 3

    def test_case_insensitive_match(self):
        from src.handlers.dimension import _find_or_create_dimension

        client = MagicMock()
        client.get.return_value = sample_api_response(
            values=[{"id": 7, "dimensionName": "REGION", "number": 1}]
        )
        dim_id, _ = _find_or_create_dimension(client, "region")
        assert dim_id == 7


class TestFindOrCreateDimensionValue:
    def test_finds_existing_value(self):
        from src.handlers.dimension import _find_or_create_dimension_value

        client = MagicMock()
        client.get.return_value = sample_api_response(values=[{"id": 20, "displayName": "Oslo"}])
        val_id = _find_or_create_dimension_value(client, 1, "Oslo")
        assert val_id == 20

    def test_creates_new_value(self):
        from src.handlers.dimension import _find_or_create_dimension_value

        client = MagicMock()
        client.get.return_value = sample_api_response(values=[])
        client.post.return_value = sample_api_response(value={"id": 30})
        val_id = _find_or_create_dimension_value(client, 1, "Bergen")
        assert val_id == 30


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestDimensionRegistration:
    def test_create_dimension_voucher_registered(self):
        import src.handlers  # noqa: F401

        assert get_handler("create_dimension_voucher") is not None


# ---------------------------------------------------------------------------
# CreateDimensionVoucherHandler
# ---------------------------------------------------------------------------


class TestCreateDimensionVoucherHandler:
    @patch("src.handlers.dimension._find_or_create_dimension", return_value=(5, 2))
    @patch("src.handlers.dimension._find_or_create_dimension_value", return_value=20)
    def test_dimension_only_no_postings(self, _mock_val, _mock_dim):
        client = MagicMock()
        handler = get_handler("create_dimension_voucher")
        result = handler.execute(
            client,
            {
                "dimensionName": "Region",
                "dimensionValues": ["Oslo", "Bergen"],
            },
        )
        assert result["dimensionId"] == 5
        assert result["dimensionIndex"] == 2
        assert result["action"] == "dimension_created"

    def test_no_dimension_name_returns_error(self):
        client = MagicMock()
        handler = get_handler("create_dimension_voucher")
        result = handler.execute(client, {})
        assert result == {"error": "no_dimension_name"}

    @patch("src.handlers.dimension._find_or_create_dimension", return_value=(5, 2))
    @patch("src.handlers.dimension._find_or_create_dimension_value", return_value=20)
    def test_with_custom_dimension_param(self, _mock_val, _mock_dim):
        client = MagicMock()
        handler = get_handler("create_dimension_voucher")
        result = handler.execute(
            client,
            {
                "customDimension": {
                    "name": "Segment",
                    "values": ["A", "B"],
                    "linkedValue": "A",
                },
            },
        )
        assert result["dimensionId"] == 5
        assert result["action"] == "dimension_created"

    @patch("src.handlers.dimension._find_or_create_dimension", return_value=(5, 2))
    @patch("src.handlers.dimension._find_or_create_dimension_value", return_value=20)
    @patch("src.handlers.dimension._build_posting")
    @patch("src.handlers.dimension._resolve_account", return_value=({"id": 1}, 1920))
    def test_with_postings_creates_voucher(self, _acct, _posting, _val, _dim):
        _posting.return_value = {"row": 1, "account": {"id": 1}, "amountGross": 1000}

        client = MagicMock()
        client.post.return_value = sample_api_response(value={"id": 99})

        handler = get_handler("create_dimension_voucher")
        result = handler.execute(
            client,
            {
                "dimensionName": "Region",
                "linkedValue": "Oslo",
                "postings": [{"account": 4000, "debit": 1000}],
            },
        )
        assert result["id"] == 99
        assert result["action"] == "voucher_with_dimension_created"

    @patch("src.handlers.dimension._find_or_create_dimension", return_value=(5, 2))
    @patch("src.handlers.dimension._find_or_create_dimension_value", return_value=20)
    @patch("src.handlers.dimension._build_posting")
    @patch("src.handlers.dimension._resolve_account", return_value=({"id": 1}, 1920))
    def test_voucher_creation_failure(self, _acct, _posting, _val, _dim):
        _posting.return_value = {"row": 1, "account": {"id": 1}, "amountGross": 500}

        client = MagicMock()
        client.post.side_effect = TripletexApiError(ApiError(status=400, message="Bad postings"))

        handler = get_handler("create_dimension_voucher")
        result = handler.execute(
            client,
            {
                "dimensionName": "Region",
                "postings": [{"account": 4000, "debit": 500}],
            },
        )
        assert result["dimensionId"] == 5
        assert result["action"] == "dimension_created_voucher_failed"
