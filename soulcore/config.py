"""Phase 1 configuration defaults.

These are the initial coefficients I in:

    P = normalize(I + sum(w_i * appraisal_i)) / (1 + sum(w_i))

They are a prior, not a fixed personality. Phase 1 stores them only; P is not
computed or injected yet.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

INITIAL_COEFFICIENTS = {
    "security": 0.55,
    "trust": 0.60,
    "self_efficacy": 0.50,
    "caution": 0.45,
    "sociability": 0.50,
    "openness": 0.55,
    "valence": 0.00,
    "arousal": 0.30,
}

APPRAISER = {
    # Public default: same provider/model as the SurfCore/DSH host.
    # Local users override this in data/appraisal-config.json (Ollama).
    "provider": "api",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout_s": 300,
}

# Day-end / shutdown consolidation.
# Keep only events that are important or "上心"; ignore the rest for affect/P.
CONSOLIDATION = {
    "importance_min": 0.50,
    "unresolved_min": 0.50,
    "abs_valence_min": 0.60,
    "arousal_min": 0.70,
    "ambient_mean_min": 0.40,
    "modes": ["day_end", "shutdown"],
}

# Long-term store policy.
# No hard record cap. Capacity is bounded by bytes; important/pinned memories
# are never evicted by the local sidecar.
STORAGE = {
    "max_records": 0,                 # 0 = unlimited
    "soft_bytes": 512 * 1024 * 1024,  # 512 MiB soft budget
    "protect_important": True,
    "cold_archive": False,            # Phase 2: move cold low-importance text out of hot DB
}

# P = normalize(I + sum(w_i * appraisal_i)) with a prior strength for I.
P_PRIOR_STRENGTH = 3.0


