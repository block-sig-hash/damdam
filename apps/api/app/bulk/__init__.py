"""Bulk orders, per-recipient assignment and activation requests — US-40.

A bulk order is fifty independent purchases that share a button. The per-item
state in `models.py` is what makes "forty-seven provisioned, two unknown, one
invalid" expressible rather than rounded to "failed".
"""
