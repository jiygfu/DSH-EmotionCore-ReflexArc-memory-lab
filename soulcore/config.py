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
    # Public default: same provider/model as the DSH host.
    # Local users override this in data/appraisal-config.json (Ollama).
    "provider": "api",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout_s": 300,
}

# Sleep "dream" event review. Deliberately online-only: local 2B is used for
# appraisal/vision side work, not for deciding whether a long event ended.
SNAPSHOT = {
    # Called only at the 80% pre-compaction point. Keep a bounded event packet;
    # never send a duplicate full-context request.
    "enabled": True,
    "provider": "api",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout_s": 180,
    "max_messages": 80,
    "max_chars": 40000,
    "event_limit": 20,
    # Only verified anchors are written; thread_loops closure/anchors remain
    # under the existing local lifecycle.
    "auto_apply": True,
}

DREAM = {
    # Temporarily off: old backlog is human-reviewed first, and nightly online
    # event review is too expensive. Keep the API path for an explicit manual
    # deep review only.
    "enabled": False,
    "provider": "api",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "timeout_s": 180,
    "event_limit": 12,
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


