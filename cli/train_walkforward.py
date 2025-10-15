import argparse, json
from services.ml.walkforward import WFConfig, train_walk_forward

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-name", required=True)
    p.add_argument("--horizon-bars", type=int, default=5)
    p.add_argument("--train-days", type=int, default=120)
    p.add_argument("--step-days", type=int, default=5)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--symbols", nargs="+", required=True)
    args = p.parse_args()

    cfg = WFConfig(
        model_name=args.model_name,
        horizon_bars=args.horizon_bars,
        train_days=args.train_days,
        step_days=args.step_days,
        start=args.start,
        end=args.end,
        symbol_universe=args.symbols,
    )
    out = train_walk_forward(cfg)
    print(json.dumps(out, indent=2))

if __name__ == "__main__":
    main()
