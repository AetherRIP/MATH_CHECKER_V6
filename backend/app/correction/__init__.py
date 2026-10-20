"""Phase 3 mathematical correction engine.

The package is deliberately split so each part is independently testable:

``documents``  input validation and PDF/image text extraction
``scheme``     deterministic mark-scheme question/maximum extraction
``prompts``    the provider prompts and required JSON shape
``provider``   the AI provider seam (Gemini implementation + errors)
``parsing``    strict JSON response parsing
``validation`` conversion of a model response into a validated report
``verify``     deterministic arithmetic/algebraic checks (never changes marks)
``service``    orchestration behind the :class:`app.engine.CorrectionEngine` protocol

The engine does not import the frontend, the database or the HTTP layer.
"""
