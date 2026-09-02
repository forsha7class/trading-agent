"""Risk scenario stress — exact numerical veto checks."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from risk.risk_engine import RiskEngine
from risk.limits import RiskLimits

def scenario(name, ctx, expect_veto):
    re=RiskEngine()
    r=re.check(ctx)
    ok=(r.veto==expect_veto) if expect_veto else r.approved
    assert ok, f"{name}: expected veto={expect_veto} got veto={r.veto} reason={r.reason} approved={r.approved}"
    print(f"{name}: PASS veto={r.veto} rr={r.rr}")

if __name__=="__main__":
    base={"equity":10000,"entry":100,"stop":98,"tp1":103,"risk_pct":0.005,"leverage":1,"signal":"LONG"}
    scenario("normal volatility", base, None)
    # extreme volatility — atr_pct >0.06 flagged in decision engine, but risk engine still checks RR
    wide={**base,"entry":100,"stop":80,"tp1":130}  # sd 20 -> RR 1.5 still ok
    scenario("wide stop", wide, None)
    narrow={**base,"entry":100,"stop":99.5,"tp1":100.75}
    scenario("narrow stop", narrow, None)
    scenario("insufficient RR", {**base,"tp1":100.5}, "NO_INVALID_RR")
    scenario("insufficient liquidity wide spread", {**base,"spread_pct":0.01}, "NO_ILLIQUID")
    scenario("daily loss near limit -199", {**base,"daily_pnl":-199}, None)
    scenario("daily loss beyond limit -250", {**base,"daily_pnl":-250}, "NO_REVENGE")
    scenario("multiple positions at limit", {**base,"positions":3}, "NO_RISK_OVERRIDE")
    scenario("leverage excess", {**base,"leverage":3.1}, "NO_EXCESS_LEVERAGE")
    scenario("martingale flag", {**base,"is_martingale":True}, "NO_MARTINGALE")
    # position sizing exact
    from risk.position_sizing import position_size
    ps=position_size(50, 2, leverage=1)
    assert ps and abs(ps["size"]-25)<1e-9, f"sizing {ps}"
    print(f"position sizing 50/2 -> size 25 PASS")
    # R:R exact
    re=RiskEngine()
    r=re.check({"equity":10000,"entry":100,"stop":98,"tp1":103,"risk_pct":0.005,"leverage":1,"signal":"LONG"})
    assert r.rr and abs(r.rr-1.5)<1e-9
    print(f"RR 103/98 exact 1.5 PASS")
    print("ALL RISK SCENARIO TESTS PASS")
