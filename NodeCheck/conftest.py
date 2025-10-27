#!/usr/bin/env python3
"""Pytest configuration for NodeCheck tests."""

import pytest
import importlib
import lib.Constants  # noqa: F401


@pytest.fixture(autouse=True, scope="function")
def isolate_constants():
    """Ensure Constants module is in clean state before each test"""
    importlib.reload(lib.Constants)
    yield
