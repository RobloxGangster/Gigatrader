from dataclasses import dataclass
from typing import Iterator, Dict
import csv, json

@dataclass
class BarRow:
    ts: float; symbol: str; open: float; high: float; low: float; close: float; volume: float

def load_bars(csv_path: str, symbols: set[str], max_rows: int) -> Iterator[BarRow]:
    with open(csv_path, "r", newline="") as f:
        r=csv.DictReader(f)
        n=0
        for row in r:
            if n>=max_rows: break
            sym=row["symbol"].upper()
            if sym not in symbols: continue
            yield BarRow(
                ts=float(row["ts"]), symbol=sym,
                open=float(row["open"]), high=float(row["high"]),
                low=float(row["low"]), close=float(row["close"]),
                volume=float(row["volume"])
            )
            n+=1

def load_sentiment(ndjson_path: str) -> Dict[str, float]:
    out={}
    try:
        with open(ndjson_path,"r") as f:
            for line in f:
                if not line.strip(): continue
                obj=json.loads(line)
                sym=obj.get("symbol","").upper()
                if not sym: continue
                out[sym]=float(obj.get("score",0.0))
    except FileNotFoundError:
        pass
    return out
