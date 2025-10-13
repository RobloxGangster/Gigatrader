from app.alpaca_client import get_trading_client


def main():
    tc = get_trading_client(paper=True)
    try:
        for p in tc.get_all_positions():
            try:
                tc.close_position(p.symbol)
            except Exception as e:
                print(f"warn: {p.symbol} close failed: {e}")
    except Exception as e:
        print(f"flatten failed: {e}")


if __name__ == "__main__":
    main()
