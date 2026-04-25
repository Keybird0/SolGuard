# SPDX-License-Identifier: MIT
# Copyright (c) 2026 SolGuard Contributors
"""Layer-3 agent data contracts.

Since v0.8 the A1 (Explorer) and A2 (Checklist) roles are played by the
outer OpenHarness Agent per ``references/l3-agents-playbook.md``; the
old Python implementations have been removed. What remains here is the
:class:`Candidate` data contract that flows through the L4 thin tools
(``solana_kill_signal`` / ``solana_cq_verdict`` / ``solana_attack_classify``
/ ``solana_seven_q`` / ``solana_judge_lite``).
"""

from .types import (
    Candidate,
    candidate_from_dict,
    candidate_to_finding,
    finding_to_candidate,
)

__all__ = [
    "Candidate",
    "candidate_from_dict",
    "candidate_to_finding",
    "finding_to_candidate",
]
