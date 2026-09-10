"""The consumer-facing read surface the mobile app navigates from (US-37).

Chunks 09-17 built the commerce and connectivity domain as services with no HTTP
surface. This package adds the first consumer-facing part of it: *what does this
account currently have, and is any of it usable yet.* It reads; it never
provisions.
"""
