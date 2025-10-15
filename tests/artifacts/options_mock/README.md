# Options Mock Data

The mock option chain for `SPY` on `2023-08-01` contains six contracts encoded
as a JSON list so that the fixture stays reviewable in plain text for pull
requests. Only the weekly Friday contracts with sufficient liquidity survive
the adapter filters, leaving the near-term 445 call and put as the
at-the-money pair used by the expected-move helper.

| symbol | as_of      | expiry     | strike | side | iv     | bid  | ask  | oi   |
|--------|------------|------------|--------|------|--------|------|------|------|
| SPY    | 2023-08-01 | 2023-08-18 | 445.0  | call | 0.1820 | 5.10 | 5.60 | 1820 |
| SPY    | 2023-08-01 | 2023-08-18 | 445.0  | put  | 0.1864 | 4.90 | 5.45 | 1650 |
| SPY    | 2023-08-01 | 2023-08-18 | 443.0  | put  | 0.2150 | 0.10 | 2.00 |    8 |
| SPY    | 2023-08-01 | 2023-08-17 | 447.0  | call | 0.2600 | 3.20 | 3.90 |  900 |
| SPY    | 2023-08-01 | 2023-08-18 | 450.0  | call | 0.2200 | 1.20 | 2.80 | 1120 |
| SPY    | 2023-08-01 | 2023-08-25 | 445.0  | call | 0.2300 | 6.50 | 6.90 | 1500 |

The adapter will load a Parquet artifact when available, but in test fixtures we
rely on this JSON representation to remain text-friendly while preserving the
same numeric precision as the original mock chain.
