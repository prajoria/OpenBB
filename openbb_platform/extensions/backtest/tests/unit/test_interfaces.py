"""Unit tests for interface protocols (component 02)."""

from __future__ import annotations

import pandas as pd
from openbb_backtest.engine.execution import RealisticBroker
from openbb_backtest.interfaces import Broker, Engine, Strategy
from openbb_backtest.models import CommissionModel, SlippageModel


def test_realistic_broker_satisfies_broker_protocol():
    broker = RealisticBroker(CommissionModel(), SlippageModel())
    assert isinstance(broker, Broker)


def test_strategy_protocol_runtime_checkable():
    class _Strat:
        id = "x"

        def generate(self, data):  # noqa: ANN001
            return pd.DataFrame()

    assert isinstance(_Strat(), Strategy)


def test_engine_protocol_runtime_checkable():
    class _Engine:
        name = "x"

        def run(self, strategy, config, feed, broker):  # noqa: ANN001
            return None

    assert isinstance(_Engine(), Engine)


def test_non_conforming_object_is_not_broker():
    class _NotBroker:
        pass

    assert not isinstance(_NotBroker(), Broker)
