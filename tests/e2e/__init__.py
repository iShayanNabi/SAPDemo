"""End-to-end workflow tests.

``tests/api`` proves each route behaves; these prove each *module* behaves as a
journey. One test per module walks the documented user path from the first call
to the downloaded report, against the bundled demo data, and asserts the things
that only break when steps are chained: an identifier issued by one call being
accepted by the next, a list reflecting what was just created, an export
containing the figures the detail response reported.
"""
