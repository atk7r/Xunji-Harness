"""Shared harness for active proof-only verification tools.

guard.py holds the machine-enforced proof-only verification floor (rate limit,
body cap, brute-force lock, upload cleanup registry). All active tools
(probe / render / scan) import from here so the few hard limits from
safety-boundary are enforced in code, not just prose.
"""
