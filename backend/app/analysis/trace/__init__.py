"""Execution-trace complexity analysis.

The module replaces the previous static-structure plus wall-clock approach. A
per-language adapter runs the submission on a small ladder of generated inputs
and records *counts* of executed work (line jumps, loop iterations, function
calls, allocation bytes) instead of timings. Counts are exact integers, so the
growth class of two algorithms that differ by a log factor is separable, the
measurement is independent of the machine, and a stored report can be checked
again without re-running the program.

The inference layer is language neutral: adapters provide a normalized
:class:`~app.analysis.trace.schema.LadderTrace`, :mod:`app.analysis.trace.fit`
derives a closed-form growth class, and :mod:`app.analysis.trace.recurrence`
turns the call structure of recursive programs into a recurrence, solves it and
cross-checks the solution against the measured counts.
"""
