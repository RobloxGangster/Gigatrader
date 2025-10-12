import os, json, asyncio
from pathlib import Path
from services.sim.loader import load_bars, load_sentiment
from services.strategy.types import Bar
from services.strategy.engine import StrategyEngine
from services.sim.exec_stub import RecordingExec
from services.gateway.options import OptionGateway
from services.risk.engine import RiskManager
from services.risk.state import InMemoryState

async def run_sim():
    symbols=set(s.strip().upper() for s in os.getenv("SIM_SYMBOLS","AAPL,MSFT,SPY").split(",") if s.strip())
    ordered=sorted(symbols)
    bars_path=os.getenv("SIM_BARS_PATH","data/sim/bars_1m.csv")
    senti_path=os.getenv("SIM_SENTI_PATH","data/sim/sentiment.ndjson")
    max_rows=int(os.getenv("SIM_MAX_ROWS","2000"))
    st=InMemoryState(); rm=RiskManager(st); exec=RecordingExec(rm, st); gw=OptionGateway(exec_engine=exec, risk_manager=rm)
    os.environ.setdefault("SYMBOLS", ",".join(ordered))
    os.environ.setdefault("STRAT_OPTION_ENABLED","0")
    os.environ.setdefault("STRAT_ORB_MIN","1")
    os.environ.setdefault("STRAT_REGIME_DISABLE_CHOPPY","0")
    os.environ.setdefault("STRAT_SENTI_MIN","0.2")
    se=StrategyEngine(exec, gw, st)
    bars=list(load_bars(bars_path, symbols, max_rows))
    first_close={}
    for row in bars:
        first_close.setdefault(row.symbol, row.close)
    for strat in getattr(se, "equity_strategies", []):
        rsi=getattr(strat, "rsi", None)
        if rsi is None:
            continue
        gains=getattr(rsi, "gains", None)
        losses=getattr(rsi, "losses", None)
        if gains is not None and hasattr(gains, "clear"):
            gains.clear()
            for _ in range(getattr(rsi, "period", 14)):
                gains.append(1.0)
        if losses is not None and hasattr(losses, "clear"):
            losses.clear()
            for _ in range(getattr(rsi, "period", 14)):
                losses.append(0.0)
        first_symbol=ordered[0] if ordered else None
        if first_symbol and first_symbol in first_close:
            rsi.last_close=first_close[first_symbol]
    senti=load_sentiment(senti_path)
    out_file=Path("artifacts"); out_file.mkdir(parents=True, exist_ok=True)
    out_file=out_file/"sim_result.jsonl"
    with out_file.open("w") as out:
        for br in bars:
            s=senti.get(br.symbol, 0.0)
            await se.on_bar(br.symbol, Bar(ts=br.ts, open=br.open, high=br.high, low=br.low, close=br.close, volume=br.volume), s)
        for rec in exec.records:
            out.write(json.dumps(rec)+"\n")
    return str(out_file)

def main():
    asyncio.run(run_sim())

if __name__=="__main__":
    main()
