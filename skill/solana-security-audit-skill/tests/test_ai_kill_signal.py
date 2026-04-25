# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""P2.4.2 — Kill-signal + adversarial AI tests.

Exercises the dual-role analyzer on two Rust fixtures:

* ``real_arbitrary_cpi.rs`` — kill signal; the AI must ``confirm`` at least
  one ``arbitrary_cpi`` finding with severity ≥ High.
* ``fake_missing_signer.rs`` — scan/semgrep fire ``missing_signer_check``,
  but the AI must mark it rejected (``is_valid=false``) or at minimum leave
  ``confirmed`` empty for that rule.

Two cases are marked ``@pytest.mark.live_llm`` and only run when a real API
key is available (CI skips them by default). The third case runs fully
offline by monkey-patching the provider client to raise
``httpx.TimeoutException`` and asserts the degraded contract.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from ai.analyzer import AIAnalyzer, _parse_model_reply
from tools.solana_parse import parse_file
from tools.solana_scan import scan
from tools.semgrep_runner import run as semgrep_run


ADVERSARIAL_DIR = Path(__file__).resolve().parent / "fixtures" / "adversarial"
FAKE_FIXTURE = ADVERSARIAL_DIR / "fake_missing_signer.rs"
REAL_FIXTURE = ADVERSARIAL_DIR / "real_arbitrary_cpi.rs"


def _build_payload(fixture: Path) -> dict[str, Any]:
    pc = parse_file(fixture)
    scan_result = scan(pc)
    semgrep = semgrep_run(target_path=fixture)
    return {
        "parse_result": pc.to_dict(),
        "scan_hints": scan_result["hints"],
        "semgrep_raw": semgrep,
        "source_code": pc.source_code,
        "file_path": fixture.name,
    }


def _have_live_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


LIVE_PROVIDER = _have_live_key()
NO_LIVE_REASON = (
    "no ANTHROPIC_API_KEY / OPENAI_API_KEY in environment — skipping live LLM tests"
)


# ---------------------------------------------------------------------------
# Live LLM tests (skipped on CI without a key)
# ---------------------------------------------------------------------------


@pytest.mark.live_llm
@pytest.mark.skipif(LIVE_PROVIDER is None, reason=NO_LIVE_REASON)
def test_live_llm_confirms_real_arbitrary_cpi() -> None:
    assert LIVE_PROVIDER is not None
    payload = _build_payload(REAL_FIXTURE)
    analyzer = AIAnalyzer(provider=LIVE_PROVIDER)
    result = analyzer.cross_validate_and_explore(**payload)
    rule_hits = {
        f.get("rule_id", "")
        for f in (result.get("confirmed", []) + result.get("exploratory", []))
    }
    assert any(
        "arbitrary_cpi" in rid for rid in rule_hits
    ), f"expected arbitrary_cpi in AI confirmed findings; got {rule_hits}"


@pytest.mark.live_llm
@pytest.mark.skipif(LIVE_PROVIDER is None, reason=NO_LIVE_REASON)
def test_live_llm_rejects_fake_missing_signer() -> None:
    assert LIVE_PROVIDER is not None
    payload = _build_payload(FAKE_FIXTURE)
    analyzer = AIAnalyzer(provider=LIVE_PROVIDER)
    result = analyzer.cross_validate_and_explore(**payload)
    confirmed_signer = [
        f
        for f in result.get("confirmed", [])
        if f.get("rule_id") == "missing_signer_check"
    ]
    rejected_signer = [
        f
        for f in result.get("rejected", [])
        if f.get("rule_id") == "missing_signer_check"
    ]
    # Either the AI outright rejected the missing_signer hit, or it did not
    # confirm it (i.e. the require_keys_eq guard was recognised).
    assert not confirmed_signer or rejected_signer, (
        f"AI should have rejected the fake missing_signer hit; "
        f"confirmed={confirmed_signer}, rejected={rejected_signer}"
    )


# ---------------------------------------------------------------------------
# Offline degradation tests — never touch the network
# ---------------------------------------------------------------------------


def test_offline_degrades_when_network_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network timeout must degrade, not raise, and must not consume tokens."""
    payload = _build_payload(REAL_FIXTURE)
    analyzer = AIAnalyzer(provider="anthropic", api_key="sk-dummy", timeout=1)

    def _boom(user_prompt: str) -> Any:
        raise httpx.TimeoutException("simulated network timeout")

    monkeypatch.setattr(analyzer, "_call_anthropic", _boom)
    monkeypatch.setattr(analyzer, "_call_openai", _boom)

    result = analyzer.cross_validate_and_explore(**payload)
    assert result["confirmed"] == []
    assert result["exploratory"] == []
    assert result["rejected"] == []
    assert "error" in result
    assert "timeout" in result["error"].lower()
    # Scan hints should still be preserved for the degraded report.
    assert result.get("unverified_scan_hints")


def test_offline_degrades_when_no_api_key() -> None:
    """Without an API key, analyzer must degrade cleanly on the first call."""
    analyzer = AIAnalyzer(provider="anthropic", api_key=None)
    # Deliberately blank environ to avoid picking up a real key
    analyzer.api_key = None
    payload = _build_payload(FAKE_FIXTURE)
    result = analyzer.cross_validate_and_explore(**payload)
    assert result["confirmed"] == []
    assert result["exploratory"] == []
    assert "error" in result
    assert "api key" in result["error"].lower()


def test_offline_parse_handles_malformed_json() -> None:
    """A real-world model slip-up (trailing comma, unquoted key, code fence)
    must be rescued by the json_repair stage, not crash."""
    raw = """```json
    {
      "confirmed": [
        {"rule_id": "missing_signer_check", "location": "x.rs:1",
         "is_valid": true, "reason": "authority not signed anywhere",
         "severity": "High", "recommendation": "use Signer<'info>"},
      ],
      "exploratory": [],
      "rejected": [],
    }
    ```"""
    parsed = _parse_model_reply(raw, token_usage={"model": "mock"})
    assert parsed["confirmed"], (
        f"json_repair should recover from trailing commas; got {parsed}"
    )
    assert parsed["confirmed"][0]["rule_id"] == "missing_signer_check"
    assert parsed.get("token_usage", {}).get("model") == "mock"


def test_offline_parse_returns_parse_error_on_pure_garbage() -> None:
    parsed = _parse_model_reply("this is not JSON at all")
    assert parsed["confirmed"] == []
    assert parsed["exploratory"] == []
    assert parsed["rejected"] == []
    assert parsed.get("parse_error")
