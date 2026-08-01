"""Plan 11 — research tooling: parameter sweeps + walk-forward + overfit report.

Deliberately NOT part of the engine dependency chain (invariant #6:
`indicators -> filters/strategies -> engine -> api`). This package sits *beside* the
API layer: it consumes `engine.runner` and `analytics.metrics` and must never be
imported by anything below `engine`. Nothing here changes engine behavior — a sweep is
N ordinary runs, each through the ordinary Runner with its own versioned config.
"""
