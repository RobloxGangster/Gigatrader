# Risk Presets

Risk presets define guardrails for different operating modes. All presets must remain within global caps and will fail closed if breached.

## Safe
- Daily loss limit: $1,000
- Per-trade loss limit: $200
- Max exposure: $10,000 notional
- Max open positions: 5
- Options max notional per expiry: $5,000
- Minimum option liquidity (volume or open interest): 50
- Delta bounds: 0.30 – 0.35
- Vega limit: 0.50
- Theta limit: 0.50

## Balanced
- Daily loss limit: $2,000
- Per-trade loss limit: $400
- Max exposure: $20,000
- Max open positions: 10
- Options max notional per expiry: $10,000
- Minimum option liquidity: 40
- Delta bounds: 0.25 – 0.40
- Vega limit: 0.80
- Theta limit: 0.80

## High Risk
- Daily loss limit: $4,000
- Per-trade loss limit: $800
- Max exposure: $40,000
- Max open positions: 15
- Options max notional per expiry: $20,000
- Minimum option liquidity: 30
- Delta bounds: 0.20 – 0.45
- Vega limit: 1.00
- Theta limit: 1.00

All presets integrate with the `ConfiguredRiskManager`. If greeks or liquidity data are missing, orders are blocked and the reason is logged.
