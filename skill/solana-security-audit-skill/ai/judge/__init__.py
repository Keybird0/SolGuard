# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Layer-4 judgment primitives.

v0.8 split (skill-driven L3/L4):

* :mod:`kill_signal` — **Gate1** deterministic regex / AST matcher.
* :mod:`counter_question` — **Gate2** *landing* helpers only
  (``apply_verdict``). The 6-question LLM prompt is now played by the
  outer Agent per ``references/l4-judge-playbook.md §2``.
* :mod:`attack_scenario` — **Gate3** *landing* helpers only
  (``classify_scenario``). The 6-step LLM prompt is now played by the
  outer Agent per ``references/l4-judge-playbook.md §3``.
* :mod:`seven_q_gate` — **Gate4** deterministic 7-question gate.
* :mod:`llm_shim` — legacy shared provider / retry / JSON-repair used
  by :mod:`ai.analyzer` (deprecated) and tests.

Thin tool adapters in :mod:`tools.solana_kill_signal` /
:mod:`tools.solana_cq_verdict` / :mod:`tools.solana_attack_classify` /
:mod:`tools.solana_seven_q` / :mod:`tools.solana_judge_lite` expose
these primitives as skill tools.
"""

from . import attack_scenario, counter_question, kill_signal, seven_q_gate

__all__ = [
    "kill_signal",
    "counter_question",
    "attack_scenario",
    "seven_q_gate",
]
