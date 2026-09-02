"""MTF confirmation. ponytail: stale = > 2x timeframe gap; upgrade with exchange heartbeat."""
from dataclasses import dataclass, field
import time

DEFAULT_WEIGHTS = {"4h": 0.30, "1h": 0.30, "15m": 0.25, "5m": 0.15}
STALE_FACTOR = 2  # times timeframe
TF_MINUTES = {"4h": 240, "1h": 60, "15m": 15, "5m": 5, "1d": 1440}

@dataclass
class MTFResult:
    aligned: bool
    score: float  # 0-1
    veto: str | None = None
    details: dict = field(default_factory=dict)

def _is_stale(tf: str, data_ts, now_ms) -> bool:
    if data_ts is None: return True
    try:
        dt = int(data_ts)
        # if seconds epoch, convert
        if dt < 1e12: dt *= 1000
        age_ms = now_ms - dt
        mins = TF_MINUTES.get(tf, 60)
        return age_ms > mins * 60 * 1000 * STALE_FACTOR
    except Exception:
        return True

def check_mtf(tf_signals: dict, weights: dict | None = None, now_ms: int | None = None) -> MTFResult:
    """
    tf_signals: {tf: {"direction": LONG|SHORT|NEUTRAL, "strength":0-1, "ts": ms }  or  StrategySignal/CombinedSignal
               also accepts {tf: "LONG"} shorthand
    """
    if weights is None: weights = DEFAULT_WEIGHTS
    if now_ms is None: now_ms = int(time.time()*1000)
    if not tf_signals:
        return MTFResult(False, 0.0, "no MTF data", {})
    # stale veto — any provided TF stale => veto
    for tf, v in tf_signals.items():
        ts = None
        if isinstance(v, dict): ts = v.get("ts", v.get("data_ts", v.get("close_time")))
        else: ts = getattr(v, "ts", getattr(v, "data_ts", None))
        if ts is not None and _is_stale(tf, ts, now_ms):
            return MTFResult(False, 0.0, f"stale {tf}", {"stale_tf": tf})
        if ts is None and tf in weights:
            # missing ts treated as stale if we have weights for it? only if explicitly required — be lenient: no veto
            pass
    # weighted alignment relative to anchor (highest weight TF present)
    present = [tf for tf in tf_signals if tf in weights]
    if not present:
        present = list(tf_signals.keys())
        # fallback equal weights
        weights = {k: 1/len(present) for k in present}
    # anchor = tf with max weight
    anchor = max(present, key=lambda k: weights.get(k, 0))
    def _dir(v):
        if isinstance(v, str): return v
        if isinstance(v, dict): return v.get("direction", "NEUTRAL")
        return getattr(v, "direction", "NEUTRAL")
    def _stren(v):
        if isinstance(v, dict): return float(v.get("strength", 0.5) or 0.5)
        s=getattr(v,"strength",None)
        if s is None: s=getattr(v,"score",50)
        try: return float(s)/100 if float(s)>1 else float(s)
        except: return 0.5
    anchor_dir = _dir(tf_signals[anchor])
    if anchor_dir == "NEUTRAL":
        return MTFResult(False, 0.15, None, {"anchor": anchor, "anchor_dir": anchor_dir, "reason": "anchor neutral"})
    total_w = sum(weights.get(tf,0) for tf in present)
    aligned_w = 0.0
    details={}
    for tf in present:
        d = _dir(tf_signals[tf])
        w = weights.get(tf, 0)
        ok = d == anchor_dir
        contrib = w * _stren(tf_signals[tf]) if ok else 0
        if ok: aligned_w += w
        details[tf] = {"direction": d, "aligned": ok, "weight": w}
    score = (aligned_w / total_w) if total_w else 0
    # also factor strength
    # already aligned_w is weight, score in 0-1
    aligned = score >= 0.6
    veto = None
    # hard veto if anchor disagrees with majority anti-anchor (>50% weight opposite)
    opposite_w = sum(weights.get(tf,0) for tf in present if _dir(tf_signals[tf]) not in (anchor_dir,"NEUTRAL") and _dir(tf_signals[tf]) != anchor_dir)
    # opposite is same as not aligned but not neutral
    if opposite_w / total_w > 0.5 if total_w else False:
        veto = None  # not hard veto on disagreement alone; stale only vetoes per spec
    return MTFResult(aligned, round(float(score),3), veto, details)

# alias for decision.engine compatibility
confirm = check_mtf
