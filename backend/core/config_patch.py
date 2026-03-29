def _apply_retention_profile(s):
    p = (getattr(s, "RETENTION_PROFILE", "prod") or "prod").strip().lower()
    if p != "fast":
        return
    # fast profile: only override if still at prod default
    if s.RETENTION_HL_CONSENT == 30.0: s.RETENTION_HL_CONSENT = 2.0
    if s.RETENTION_HL_PONDERING == 7.0: s.RETENTION_HL_PONDERING = 1.0
    if s.RETENTION_HL_DISSONANCE == 3.0: s.RETENTION_HL_DISSONANCE = 0.5
    if s.RETENTION_HL_DEFAULT == 5.0: s.RETENTION_HL_DEFAULT = 1.0
    if s.RETENTION_GRACE_DAYS == 1.0: s.RETENTION_GRACE_DAYS = 0.0
    if s.RETENTION_PROMOTE_TH == 0.70: s.RETENTION_PROMOTE_TH = 0.60
    if s.RETENTION_BACKGROUND_TH == 0.10: s.RETENTION_BACKGROUND_TH = 0.20
