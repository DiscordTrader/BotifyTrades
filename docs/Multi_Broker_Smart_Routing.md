# Multi-Broker Smart Routing

## How BotifyTrades Uses Your Connected Brokers Together

When you connect multiple brokers to BotifyTrades, the bot doesn't treat them as separate islands. Instead, it creates a **shared intelligence network** where all your brokers work together — even if only one broker is executing a trade.

---

## The Two Roles Every Broker Can Play

### 1. Price Watcher
Some brokers provide fast, real-time price feeds. When connected, the bot automatically uses their live data streams to watch prices across all your active trades and conditional orders — regardless of which broker the trade is placed on.

### 2. Trade Executor
When a signal arrives or a conditional order triggers, the bot sends the actual buy/sell order to the broker you've assigned for that channel or order.

**The key insight:** The broker watching the price doesn't have to be the same broker executing the trade.

---

## Why This Matters

Not all brokers deliver price data at the same speed. Some brokers offer lightning-fast streaming prices, while others rely on slower periodic checks. BotifyTrades automatically picks the fastest available price source from any of your connected brokers, so your conditional orders trigger at exactly the right moment — even if the executing broker has slower data.

This means:
- **Faster triggers** — Your conditional orders fire the instant the price is hit, using the best available data
- **More reliability** — If one broker's data feed goes down, the bot seamlessly switches to another broker's feed
- **No extra cost** — This happens automatically with no additional subscriptions or fees

---

## Example: How It Works in Practice

> **Setup:** You have three brokers connected — Webull, Schwab, and Trading212.
>
> **Scenario:** You set a conditional buy order on Trading212 for AAPL at $185.00.
>
> **What happens behind the scenes:**
>
> 1. The bot detects that Webull has the fastest live price stream for AAPL
> 2. It uses Webull's real-time feed to monitor AAPL's price — checking multiple times per second
> 3. The moment Webull's feed shows AAPL hits $185.00, the bot instantly triggers
> 4. The buy order is sent directly to Trading212 (your chosen broker for this trade)
> 5. Trading212 executes the purchase
>
> **Result:** You got the speed of Webull's data with the execution on Trading212 — the best of both worlds.

If Webull's data had gone temporarily offline, the bot would have automatically switched to Schwab's feed without missing a beat. You would never need to intervene.

---

## Automatic Failover — Built-In Safety Net

The bot continuously ranks your connected brokers by data quality and speed. If the primary price source becomes unavailable or stale, it automatically moves through backup sources:

**Fastest available stream → Next fastest stream → Next → Direct broker check**

This failover happens in milliseconds. Your orders stay protected even if a broker experiences temporary issues.

---

## What You Need to Do

**Nothing.** Simply connect your brokers and the bot handles everything automatically. There's no configuration needed to enable smart routing — it activates the moment you have more than one broker connected.

The more brokers you connect, the more resilient your price monitoring becomes.

---

## Quick Summary

| Feature | What It Does |
|---|---|
| **Shared Price Monitoring** | All connected brokers contribute their price data to a shared pool |
| **Fastest Source Selection** | The bot always uses the fastest available price feed automatically |
| **Cross-Broker Execution** | Orders execute on your chosen broker, monitored by whichever has the best data |
| **Automatic Failover** | If one data source drops, the bot switches to the next best source instantly |
| **Zero Configuration** | Works automatically — just connect your brokers and go |
