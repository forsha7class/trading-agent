def position_size(allowed_risk_capital: float, stop_distance: float, leverage: float = 1.0, liquidity: dict | None = None) -> dict | None:
    """size = allowed_risk / stop_distance; adjust for leverage/liquidity. Returns None if invalid."""
    if stop_distance is None or stop_distance <= 0:
        return None
    if allowed_risk_capital is None or allowed_risk_capital <= 0:
        return None
    size = allowed_risk_capital / stop_distance
    # leverage caps effective size (ponytail: full margin model when live execution added)
    if leverage and leverage > 1:
        # risk-based sizing unchanged; leverage only affects notional - cap via limits elsewhere
        pass
    # liquidity haircut: reduce size if spread wide or volume thin
    if liquidity:
        spread = liquidity.get("spread_pct", 0)
        vol_ratio = liquidity.get("vol_ratio", 1.0)
        if spread and spread > 0.002:
            size *= max(0.1, 1 - (spread - 0.002) * 100)
        if vol_ratio and vol_ratio < 0.5:
            size *= vol_ratio * 2
    return {"size": float(size), "capital_at_risk": float(allowed_risk_capital), "max_loss": float(allowed_risk_capital)}
