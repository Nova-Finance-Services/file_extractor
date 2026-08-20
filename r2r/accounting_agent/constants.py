"""Shared constants for the Python R2R accounting agent."""
ACCOUNTING_AGENT_NAME = "r2r.accounting-agent"
# One round can already run several tool calls. This is a ceiling on LLM
# round-trips so a supplier with many POs/PINVs can still walk every document
# and finalize.
MAX_AGENT_ITERATIONS = 16
