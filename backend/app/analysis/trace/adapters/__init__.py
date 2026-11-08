"""Per-language trace collection adapters.

Each adapter turns a submission and a list of generated inputs into a
:class:`~app.analysis.trace.schema.LadderTrace`. The inference layer and the
report layer never branch on language.
"""
