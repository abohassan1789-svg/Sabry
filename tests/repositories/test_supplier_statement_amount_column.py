"""Config tests for the Supplier Statement repository amount-column selection.

No database: these pin the mapping from نوع الحساب to the purchase-invoice total
column («عدد» -> total_count_price, «وزن» -> total_weight_price), the whitelist
that guards the interpolated column name, and the service passing the account
type through to a repository it builds itself.
"""

from __future__ import annotations

import pytest

from app.repositories.supplier_statement_report_repository import (
    ACCOUNT_TYPE_COUNT,
    ACCOUNT_TYPE_WEIGHT,
    SupplierStatementReportRepository,
)
from app.services.supplier_statement_report_service import SupplierStatementReportService


class _FakeDB:
    def fetch_all(self, *a, **k):
        return []

    def fetch_one(self, *a, **k):
        return None


def test_count_type_uses_count_price():
    repo = SupplierStatementReportRepository(_FakeDB(), account_type=ACCOUNT_TYPE_COUNT)
    assert repo.amount_column == "total_count_price"
    assert repo.account_type == "عدد"


def test_weight_type_uses_weight_price():
    repo = SupplierStatementReportRepository(_FakeDB(), account_type=ACCOUNT_TYPE_WEIGHT)
    assert repo.amount_column == "total_weight_price"
    assert repo.account_type == "وزن"


def test_default_is_count_type():
    assert SupplierStatementReportRepository(_FakeDB()).amount_column == "total_count_price"


def test_bad_amount_column_is_rejected():
    with pytest.raises(ValueError):
        SupplierStatementReportRepository(
            _FakeDB(), account_type="عدد", amount_column="1; DROP TABLE suppliers"
        )


def test_service_builds_repo_for_its_account_type():
    svc = SupplierStatementReportService(account_type=ACCOUNT_TYPE_WEIGHT)
    assert svc.account_type == "وزن"
    assert svc.repository.amount_column == "total_weight_price"
