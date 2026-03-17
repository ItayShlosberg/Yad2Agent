"""Unit tests for the sliding-window rate limiter."""

import time

import pytest

from src.core.config import RateLimitConfig
from src.services.rate_limiter import RateLimiter


@pytest.fixture
def limiter() -> RateLimiter:
    cfg = RateLimitConfig(max_messages=3, window_seconds=2, cooldown_message="slow down")
    return RateLimiter(cfg)


def test_allows_within_limit(limiter: RateLimiter):
    assert not limiter.is_limited("user1")
    assert not limiter.is_limited("user1")
    assert not limiter.is_limited("user1")


def test_blocks_after_limit(limiter: RateLimiter):
    for _ in range(3):
        limiter.is_limited("user1")
    assert limiter.is_limited("user1")


def test_separate_senders(limiter: RateLimiter):
    for _ in range(3):
        limiter.is_limited("user1")
    assert limiter.is_limited("user1")
    assert not limiter.is_limited("user2")


def test_window_expires(limiter: RateLimiter):
    for _ in range(3):
        limiter.is_limited("user1")
    assert limiter.is_limited("user1")
    time.sleep(2.1)
    assert not limiter.is_limited("user1")


def test_reset(limiter: RateLimiter):
    for _ in range(3):
        limiter.is_limited("user1")
    assert limiter.is_limited("user1")
    limiter.reset("user1")
    assert not limiter.is_limited("user1")


def test_cooldown_message(limiter: RateLimiter):
    assert limiter.cooldown_message == "slow down"
