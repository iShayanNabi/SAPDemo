"""Invoice Validator (module 4).

Validates uploaded invoices against purchase orders and goods receipts using
configurable deterministic rules. Unlike modules 1-3, this module joins *three*
uploaded datasets rather than analysing one, which is the new capability it adds
to the lab.

Every exception is produced by ordinary Python (three-way matching, tolerance
arithmetic, date checks). The optional AI layer only summarises the exceptions;
it never decides whether an invoice is valid.
"""
