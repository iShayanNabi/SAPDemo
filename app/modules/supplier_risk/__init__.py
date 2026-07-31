"""Module 5 - Supplier Risk Copilot.

Aggregates the supplier, purchase-order, contract, delivery, quality, invoice and
compliance information the lab already holds into a transparent, per-supplier risk
profile, and answers questions about that loaded data.

Every risk number is produced by deterministic Python in :mod:`scoring` and
:mod:`engine`. The copilot in :mod:`copilot` answers from the same computed
profiles and cites the internal records it used. AI is optional and only ever
rephrases what the rules already decided.
"""
