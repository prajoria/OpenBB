"""Pydantic response models for FinancialToolkit discovery domain."""

from pydantic import BaseModel

from openbb_financialtoolkit.common.enums import CoverageStatus


class DomainCapability(BaseModel):
    """Represents one exposed domain capability."""

    command: str
    coverage: CoverageStatus
    notes: str
