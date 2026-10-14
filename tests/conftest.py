"""Seeded shuffle of test order: set TEST_SEED to an int to shuffle (standard library only)."""
import os, random


def pytest_collection_modifyitems(items):
    seed = os.environ.get("TEST_SEED")
    if seed is not None:
        random.Random(int(seed)).shuffle(items)
