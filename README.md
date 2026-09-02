# Binance Triangular Arbitrage Scanner (Paper Mode)

Scans 8 triangular loops (16 directions) on Binance every 5 minutes, using
only public market data. **No API keys needed. No real orders are placed.**
This is a detection/measurement tool, not a live trading bot.

## Why paper mode first

Real triangular arbitrage windows close in well under a second. A GitHub
Actions cron job checking every 5 minutes cannot realistically capture one
live — by the time it runs, the prices have already moved. What this *can*
do is answer an honest question: **how often, and how large, do these
spreads actually appear after fees, on this specific set of pairs?**

If the logs show meaningfully-sized net-positive spreads showing up with
any regularity, that's a signal it might be worth the much bigger step of
building always-on, low-latency execution (which GitHub Actions is not
suited for). If they rarely or never appear, you've learned that cheaply
without risking your $10.

## What it scans

Eight triangles, each checked in both directions:

- USDT → BTC → ETH → USDT
- USDT → BTC → BNB → USDT
- USDT → ETH → BNB → USDT
- USDT → BTC → SOL → USDT
- USDT → BTC → XRP → USDT
- USDT → BTC → ADA → USDT
- USDT → BTC → LTC → USDT
- USDT → BTC → DOGE → USDT

If Binance has delisted or renamed any of these pairs since this was
written, the script just skips that triangle rather than crashing — check
`scan_log.csv`'s `triangles_scanned` column; if it's consistently below 16,
some pairs are unavailable and can be removed from `TRIANGLE_CYCLES` in
`triangular_scanner.py`.

## Setup

1. Create a GitHub repo (or use an existing one).
2. Upload these files, keeping the structure:
   ```
   requirements.txt
   triangular_scanner.py
   .github/workflows/scanner.yml
   ```
3. Go to **Actions** tab → **Binance Triangular Arbitrage Scanner** → **Run
   workflow** to trigger it manually once and confirm it works.
4. If that run succeeds, the `cron` schedule takes over automatically from
   there — every 5 minutes.

No secrets, no API keys, nothing to configure — it only reads public data.

## Reading the output

Two files get created and committed back to your repo automatically:

- **`scan_log.csv`** — one row per run, showing the single best spread found
  (even if negative). This is your proof-of-life log and also your dataset
  for "how close do spreads usually get to breaking even."
- **`opportunities.csv`** — only rows where a triangle direction was
  net-profitable after fees (controlled by `MIN_PROFIT_PCT`). If this file
  never appears, that itself is a meaningful result — it means true
  triangular arbitrage isn't showing up on this pair set at this scan
  frequency.

## Tuning

Set these as `env:` values in `scanner.yml`:

| Variable | Meaning | Default |
|---|---|---|
| `FEE_RATE` | Per-trade taker fee (decimal) | `0.001` (0.1%) — use `0.00075` if you have BNB fee discount |
| `MIN_PROFIT_PCT` | Minimum net % to count as an "opportunity" | `0.0` |

## Honest limits of this approach

- **Timing**: even if `opportunities.csv` shows historical spreads, you
  could not have actually captured them with this setup — it's
  retrospective, not predictive.
- **Depth**: this uses best bid/ask only (top of book). A real trade of any
  size would move through several price levels, especially with such thin
  amounts — actual fills would be worse than what's logged here.
- **$10 capital**: even if live execution were fast enough, Binance's
  per-order minimum notional (~$5-10 depending on pair) means $10 barely
  covers a single triangle loop with zero room for a failed leg.

## Next step, if the data looks promising

If after a few days/weeks `opportunities.csv` shows real, sizeable, frequent
spreads, the next step isn't "add API keys to this same bot" — it's a
different architecture entirely (a persistent low-latency process, not a
5-minute cron job) since speed is the actual bottleneck. Worth revisiting
that conversation once you have real data in hand.
