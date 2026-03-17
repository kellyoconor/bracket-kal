"""
Tests for the 6 production hardening fixes.

Fix 1 — Rate limiting (bot.py)
Fix 2 — Safe rule evaluation (kalshi_trader.py)
Fix 3 — Error sanitization (bot.py / monitor.py)
Fix 4 — chat_id validation (bot.py)
Fix 5 — Image size cap (bot.py)
Fix 6 — Hallucination guardrails (bot.py / monitor.py)
"""

import importlib
import inspect
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Add project root to path so we can import the modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers to import modules without triggering side effects from dotenv/etc.
# We patch load_dotenv so it doesn't overwrite env during tests.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_dotenv():
    """Prevent dotenv from loading real .env files during tests."""
    with patch("dotenv.load_dotenv"):
        yield


def _import_bot():
    """Import (or reimport) bot module."""
    if "bot" in sys.modules:
        return importlib.reload(sys.modules["bot"])
    return importlib.import_module("bot")


def _import_kalshi_trader():
    if "kalshi_trader" in sys.modules:
        return importlib.reload(sys.modules["kalshi_trader"])
    return importlib.import_module("kalshi_trader")


def _import_monitor():
    if "monitor" in sys.modules:
        return importlib.reload(sys.modules["monitor"])
    return importlib.import_module("monitor")


# ═══════════════════════════════════════════════════════════════════════════
# Fix 1 — Rate limiting
# ═══════════════════════════════════════════════════════════════════════════


class TestRateLimiting:
    """Tests for is_rate_limited() in bot.py."""

    @pytest.fixture(autouse=True)
    def _reset_state(self):
        """Clear module-level rate-limit state before each test."""
        bot = _import_bot()
        bot.user_request_timestamps.clear()
        bot.global_daily_requests.clear()
        yield

    def test_under_limits_returns_none(self):
        bot = _import_bot()
        result = bot.is_rate_limited("12345")
        assert result is None

    def test_per_minute_limit_triggers_after_10_requests(self):
        bot = _import_bot()
        chat_id = "user1"
        for _ in range(10):
            bot.is_rate_limited(chat_id)

        result = bot.is_rate_limited(chat_id)
        assert result is not None
        assert "wait" in result.lower() or "minute" in result.lower()

    def test_per_hour_limit_triggers_after_50_requests(self):
        bot = _import_bot()
        chat_id = "user2"
        now = time.time()

        # Simulate 50 requests spread across the last hour (but not in the
        # last minute, so the per-minute check does not fire first).
        bot.user_request_timestamps[chat_id] = [
            now - 120 - i for i in range(50)
        ]
        # Also record them globally so global budget stays consistent.
        bot.global_daily_requests.extend(bot.user_request_timestamps[chat_id])

        result = bot.is_rate_limited(chat_id)
        assert result is not None
        assert "hour" in result.lower() or "slow" in result.lower()

    def test_global_daily_budget_cap(self):
        bot = _import_bot()
        now = time.time()

        # Fill global budget to capacity
        bot.global_daily_requests.extend(
            [now - i for i in range(bot.GLOBAL_DAILY_BUDGET)]
        )

        result = bot.is_rate_limited("fresh_user")
        assert result is not None
        assert "capacity" in result.lower() or "tomorrow" in result.lower()

    def test_old_timestamps_are_pruned(self):
        bot = _import_bot()
        chat_id = "user3"
        old_time = time.time() - 7200  # 2 hours ago

        bot.user_request_timestamps[chat_id] = [old_time] * 100
        bot.global_daily_requests.extend([old_time] * 100)

        # Old entries should be pruned; request should succeed
        result = bot.is_rate_limited(chat_id)
        assert result is None

    def test_different_users_have_separate_limits(self):
        bot = _import_bot()
        # Exhaust user A's per-minute limit
        for _ in range(10):
            bot.is_rate_limited("userA")

        # User B should still be fine
        result = bot.is_rate_limited("userB")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Fix 2 — Safe rule evaluation
# ═══════════════════════════════════════════════════════════════════════════


class TestSafeRuleEvaluation:
    """Tests for _eval_clause() and evaluate_rule() in kalshi_trader.py."""

    @pytest.fixture
    def trader(self):
        return _import_kalshi_trader()

    # --- _eval_clause: all 6 operators ---

    def test_eval_clause_greater_than(self, trader):
        ctx = {"divergence": 0.20}
        assert trader._eval_clause("divergence > 0.15", ctx) is True
        assert trader._eval_clause("divergence > 0.25", ctx) is False

    def test_eval_clause_less_than(self, trader):
        ctx = {"market_price": 0.30}
        assert trader._eval_clause("market_price < 0.50", ctx) is True
        assert trader._eval_clause("market_price < 0.20", ctx) is False

    def test_eval_clause_greater_equal(self, trader):
        ctx = {"divergence": 0.15}
        assert trader._eval_clause("divergence >= 0.15", ctx) is True
        assert trader._eval_clause("divergence >= 0.16", ctx) is False

    def test_eval_clause_less_equal(self, trader):
        ctx = {"kalshi_prob": 0.50}
        assert trader._eval_clause("kalshi_prob <= 0.50", ctx) is True
        assert trader._eval_clause("kalshi_prob <= 0.49", ctx) is False

    def test_eval_clause_equal(self, trader):
        ctx = {"claude_prob": 0.75}
        assert trader._eval_clause("claude_prob == 0.75", ctx) is True
        assert trader._eval_clause("claude_prob == 0.76", ctx) is False

    def test_eval_clause_not_equal(self, trader):
        ctx = {"divergence": 0.10}
        assert trader._eval_clause("divergence != 0.20", ctx) is True
        assert trader._eval_clause("divergence != 0.10", ctx) is False

    # --- evaluate_rule: "and" / "or" logic ---

    def test_evaluate_rule_and_conditions(self, trader):
        game = {"abs_divergence": 0.20, "claude_prob": 0.70, "kalshi_prob": 0.50}
        rule = {"condition": "divergence >= 0.15 and claude_prob > 0.60"}
        assert trader.evaluate_rule(rule, game, market_price=0.45) is True

    def test_evaluate_rule_and_conditions_fail(self, trader):
        game = {"abs_divergence": 0.10, "claude_prob": 0.70, "kalshi_prob": 0.50}
        rule = {"condition": "divergence >= 0.15 and claude_prob > 0.60"}
        assert trader.evaluate_rule(rule, game, market_price=0.45) is False

    def test_evaluate_rule_or_conditions(self, trader):
        game = {"abs_divergence": 0.05, "claude_prob": 0.70, "kalshi_prob": 0.50}
        rule = {"condition": "divergence >= 0.15 or claude_prob > 0.60"}
        # divergence fails but claude_prob passes
        assert trader.evaluate_rule(rule, game, market_price=0.45) is True

    def test_evaluate_rule_or_conditions_both_fail(self, trader):
        game = {"abs_divergence": 0.05, "claude_prob": 0.40, "kalshi_prob": 0.50}
        rule = {"condition": "divergence >= 0.15 or claude_prob > 0.60"}
        assert trader.evaluate_rule(rule, game, market_price=0.45) is False

    # --- Security: reject disallowed variables and non-numeric values ---

    def test_rejects_unknown_variable_name(self, trader):
        ctx = {"divergence": 0.20}
        assert trader._eval_clause("__import__ > 0", ctx) is False

    def test_rejects_os_system_variable(self, trader):
        ctx = {"divergence": 0.20}
        assert trader._eval_clause("os.system > 0", ctx) is False

    def test_rejects_non_numeric_value(self, trader):
        ctx = {"divergence": 0.20}
        assert trader._eval_clause("divergence > abc", ctx) is False

    def test_rejects_class_bases_attack(self, trader):
        ctx = {"divergence": 0.20}
        assert trader._eval_clause("__class__.__bases__ > 0", ctx) is False

    def test_rejects_empty_clause(self, trader):
        ctx = {"divergence": 0.20}
        assert trader._eval_clause("", ctx) is False

    def test_rejects_code_injection_in_value(self, trader):
        ctx = {"divergence": 0.20}
        assert trader._eval_clause(
            "divergence > __import__('os').system('echo pwned')", ctx
        ) is False


# ═══════════════════════════════════════════════════════════════════════════
# Fix 3 — Error sanitization
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorSanitization:
    """Verify that user-facing error messages do not leak internals."""

    def test_bot_main_loop_sends_generic_error(self):
        bot_source = (PROJECT_ROOT / "bot.py").read_text()
        assert "Something went wrong. Please try again." in bot_source

    def test_monitor_sends_generic_error(self):
        monitor_source = (PROJECT_ROOT / "monitor.py").read_text()
        assert "Something went wrong. Please try again." in monitor_source

    def test_kalshi_trader_sends_generic_error(self):
        trader_source = (PROJECT_ROOT / "kalshi_trader.py").read_text()
        assert "Something went wrong." in trader_source

    def test_bot_no_raw_exception_in_tg_send(self):
        """The old pattern f'Something went wrong: {e}' must be gone."""
        bot_source = (PROJECT_ROOT / "bot.py").read_text()
        assert "Something went wrong: {e}" not in bot_source
        assert 'f"Something went wrong' not in bot_source

    def test_monitor_no_raw_exception_in_telegram_send(self):
        """The old pattern 'couldn't process that: {e}' must be gone."""
        monitor_source = (PROJECT_ROOT / "monitor.py").read_text()
        assert "{e}" not in _extract_telegram_send_lines(monitor_source)

    def test_kalshi_no_raw_exception_in_telegram_send(self):
        """Trade failure messages must not include {e}."""
        trader_source = (PROJECT_ROOT / "kalshi_trader.py").read_text()
        assert "{e}" not in _extract_telegram_send_lines(trader_source)


def _extract_telegram_send_lines(source: str) -> str:
    """Return only lines containing tg_send/telegram_send calls."""
    return "\n".join(
        line for line in source.splitlines()
        if "tg_send(" in line or "telegram_send(" in line
    )


# ═══════════════════════════════════════════════════════════════════════════
# Fix 4 — chat_id validation
# ═══════════════════════════════════════════════════════════════════════════


class TestChatIdValidation:
    """Tests for user_dir() in bot.py."""

    @pytest.fixture
    def bot(self, tmp_path):
        """Return bot module with USERS_DIR pointed at a temp directory."""
        bot = _import_bot()
        bot.USERS_DIR = tmp_path / "users"
        return bot

    def test_valid_numeric_chat_id(self, bot, tmp_path):
        result = bot.user_dir("12345")
        assert result.name == "12345"
        assert result.exists()

    def test_negative_chat_id_for_group_chats(self, bot, tmp_path):
        result = bot.user_dir("-100987654")
        assert result.name == "-100987654"
        assert result.exists()

    def test_rejects_path_traversal(self, bot):
        with pytest.raises(ValueError):
            bot.user_dir("../etc")

    def test_rejects_non_numeric_string(self, bot):
        with pytest.raises(ValueError):
            bot.user_dir("hello")

    def test_rejects_empty_string(self, bot):
        with pytest.raises(ValueError):
            bot.user_dir("")

    def test_rejects_slash_in_chat_id(self, bot):
        with pytest.raises(ValueError):
            bot.user_dir("123/456")

    def test_rejects_dot_dot(self, bot):
        with pytest.raises(ValueError):
            bot.user_dir("..")


# ═══════════════════════════════════════════════════════════════════════════
# Fix 5 — Image size cap
# ═══════════════════════════════════════════════════════════════════════════


class TestImageSizeCap:
    """Verify oversized images are rejected before hitting Claude Vision."""

    def test_five_mb_threshold_in_source(self):
        bot_source = (PROJECT_ROOT / "bot.py").read_text()
        assert "5 * 1024 * 1024" in bot_source

    def test_oversized_image_rejected(self):
        """A 6MB photo should trigger the rejection message, not call
        handle_screenshot."""
        bot = _import_bot()
        bot.user_request_timestamps.clear()
        bot.global_daily_requests.clear()

        sent_messages = []
        original_tg_send = bot.tg_send

        def mock_tg_send(chat_id, text):
            sent_messages.append(text)

        oversized_data = b"x" * (6 * 1024 * 1024)  # 6 MB

        def mock_tg_get_photo(file_id):
            return oversized_data

        with patch.object(bot, "tg_send", mock_tg_send), \
             patch.object(bot, "tg_get_photo", mock_tg_get_photo), \
             patch.object(bot, "load_user", return_value={"state": "active", "picks": []}):
            bot.handle_message({
                "chat_id": "12345",
                "text": "",
                "photo": [{"file_id": "abc", "width": 100, "height": 100}],
                "first_name": "Test",
            })

        assert any("Image too large" in m for m in sent_messages)

    def test_normal_image_not_rejected(self):
        """A 1MB photo should NOT trigger the size rejection."""
        bot = _import_bot()
        bot.user_request_timestamps.clear()
        bot.global_daily_requests.clear()

        sent_messages = []

        def mock_tg_send(chat_id, text):
            sent_messages.append(text)

        small_data = b"x" * (1 * 1024 * 1024)  # 1 MB

        def mock_tg_get_photo(file_id):
            return small_data

        with patch.object(bot, "tg_send", mock_tg_send), \
             patch.object(bot, "tg_get_photo", mock_tg_get_photo), \
             patch.object(bot, "handle_screenshot", return_value="Screenshot processed"), \
             patch.object(bot, "load_user", return_value={"state": "new", "picks": []}):
            bot.handle_message({
                "chat_id": "12345",
                "text": "",
                "photo": [{"file_id": "abc", "width": 100, "height": 100}],
                "first_name": "Test",
            })

        assert not any("Image too large" in m for m in sent_messages)


# ═══════════════════════════════════════════════════════════════════════════
# Fix 6 — Hallucination guardrails
# ═══════════════════════════════════════════════════════════════════════════


class TestHallucinationGuardrails:
    """Verify that both bot.py and monitor.py include grounding rules in
    their Claude prompts."""

    def test_bot_answer_user_question_has_guardrails(self):
        bot_source = (PROJECT_ROOT / "bot.py").read_text()
        # Check that the key grounding rules appear in the prompt
        assert "Only cite facts from the BRACKET DATA" in bot_source
        assert "Do not invent statistics" in bot_source
        assert "not financial advice" in bot_source.lower() or "not financial advice" in bot_source

    def test_monitor_answer_question_has_guardrails(self):
        monitor_source = (PROJECT_ROOT / "monitor.py").read_text()
        assert "Only cite facts from the BRACKET DATA" in monitor_source
        assert "Do not invent statistics" in monitor_source

    def test_bot_prompt_rejects_uncovered_questions(self):
        bot_source = (PROJECT_ROOT / "bot.py").read_text()
        assert "I don't have that information" in bot_source

    def test_monitor_prompt_rejects_uncovered_questions(self):
        monitor_source = (PROJECT_ROOT / "monitor.py").read_text()
        assert "I don't have that information" in monitor_source

    def test_bot_prompt_forbids_betting_advice(self):
        bot_source = (PROJECT_ROOT / "bot.py").read_text()
        assert "Never suggest placing bets" in bot_source

    def test_monitor_prompt_forbids_betting_advice(self):
        monitor_source = (PROJECT_ROOT / "monitor.py").read_text()
        assert "Never suggest placing bets" in monitor_source
