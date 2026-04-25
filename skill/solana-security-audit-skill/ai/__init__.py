"""LLM-powered analysis for the Solana Security Audit Skill."""

from .analyzer import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENAI_MODEL,
    AIAnalyzer,
)
from .analyzer_tool import AIAnalyzerTool
from .planner import AuditTarget, build_inventory, plan_audit_targets
from .prompts import (
    FEW_SHOT_EXAMPLES,
    SOLANA_AUDIT_SYSTEM_PROMPT,
    SOLANA_AUDIT_USER_PROMPT_TEMPLATE,
    build_user_prompt,
)

__all__ = [
    "AIAnalyzer",
    "AIAnalyzerTool",
    "AuditTarget",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "SOLANA_AUDIT_SYSTEM_PROMPT",
    "SOLANA_AUDIT_USER_PROMPT_TEMPLATE",
    "FEW_SHOT_EXAMPLES",
    "build_inventory",
    "build_user_prompt",
    "plan_audit_targets",
]
