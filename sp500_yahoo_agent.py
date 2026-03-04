#!/usr/bin/env python3
"""Agente para filtrar acciones del S&P 500 con métricas de Yahoo Finance (sin dependencias externas)."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from typing import Any

SP500_CSV_URL = "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"
YAHOO_QUOTE_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=price,summaryDetail,defaultKeyStatistics,financialData"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1y"


@dataclass
class MetricThresholds:
    min_market_cap: float = 10_000_000_000
    max_forward_pe: float = 25.0
    min_roe: float = 0.10
    min_profit_margin: float = 0.10
    max_debt_to_equity: float = 150.0
    min_revenue_growth: float = 0.05
    min_avg_volume_3m: float = 1_000_000
    require_price_above_sma50: bool = True
    require_price_below_sma200: bool = False


@dataclass
class StockEvaluation:
    ticker: str
    company: str
    passed: bool
    score: int
    price: float | None
    market_cap: float | None
    forward_pe: float | None
    roe: float | None
    profit_margin: float | None
    debt_to_equity: float | None
    revenue_growth: float | None
    avg_volume_3m: float | None
    sma50: float | None
    sma200: float | None


def http_get_json(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_sp500_tickers(limit: int | None = None) -> list[tuple[str, str]]:
    req = urllib.request.Request(SP500_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        rows = list(csv.DictReader(response.read().decode("utf-8").splitlines()))

    pairs = [(row["Symbol"].replace(".", "-"), row["Name"]) for row in rows]
    return pairs[:limit] if limit else pairs


def parse_manual_tickers(raw: str) -> list[tuple[str, str]]:
    return [(x.strip().upper(), x.strip().upper()) for x in raw.split(",") if x.strip()]


def extract_raw(node: Any) -> float | None:
    if node is None:
        return None
    if isinstance(node, (int, float)):
        return float(node)
    if isinstance(node, dict):
        if "raw" in node and node["raw"] is not None:
            return extract_raw(node["raw"])
        if "fmt" in node and node["fmt"] is not None:
            try:
                return float(str(node["fmt"]).replace(",", ""))
            except ValueError:
                return None
    return None


def get_nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def get_quote_metrics(ticker: str) -> dict[str, float | None]:
    url = YAHOO_QUOTE_SUMMARY_URL.format(ticker=urllib.parse.quote(ticker))
    data = http_get_json(url)
    result = get_nested(data, "quoteSummary", "result")
    if not result:
        raise ValueError("Sin datos en quoteSummary")
    payload = result[0]

    return {
        "price": extract_raw(get_nested(payload, "price", "regularMarketPrice")),
        "market_cap": extract_raw(get_nested(payload, "price", "marketCap")),
        "forward_pe": extract_raw(get_nested(payload, "summaryDetail", "forwardPE")),
        "roe": extract_raw(get_nested(payload, "financialData", "returnOnEquity")),
        "profit_margin": extract_raw(get_nested(payload, "defaultKeyStatistics", "profitMargins")),
        "debt_to_equity": extract_raw(get_nested(payload, "financialData", "debtToEquity")),
        "revenue_growth": extract_raw(get_nested(payload, "financialData", "revenueGrowth")),
    }


def get_technical_metrics(ticker: str) -> dict[str, float | None]:
    url = YAHOO_CHART_URL.format(ticker=urllib.parse.quote(ticker))
    data = http_get_json(url)
    result = get_nested(data, "chart", "result")
    if not result:
        raise ValueError("Sin datos en chart")

    quote = get_nested(result[0], "indicators", "quote")
    if not quote:
        raise ValueError("Sin indicadores de chart")

    close = [x for x in (quote[0].get("close") or []) if isinstance(x, (int, float))]
    volume = [x for x in (quote[0].get("volume") or []) if isinstance(x, (int, float))]

    avg_volume_3m = statistics.mean(volume[-60:]) if volume else None
    sma50 = statistics.mean(close[-50:]) if close else None
    sma200 = statistics.mean(close[-200:]) if len(close) >= 200 else None
    price_from_close = close[-1] if close else None

    return {
        "avg_volume_3m": avg_volume_3m,
        "sma50": sma50,
        "sma200": sma200,
        "price_from_close": price_from_close,
    }


def evaluate_stock(ticker: str, company: str, thresholds: MetricThresholds) -> StockEvaluation:
    quote = get_quote_metrics(ticker)
    technical = get_technical_metrics(ticker)

    price = quote["price"] if quote["price"] is not None else technical["price_from_close"]
    market_cap = quote["market_cap"]
    forward_pe = quote["forward_pe"]
    roe = quote["roe"]
    profit_margin = quote["profit_margin"]
    debt_to_equity = quote["debt_to_equity"]
    revenue_growth = quote["revenue_growth"]
    avg_volume_3m = technical["avg_volume_3m"]
    sma50 = technical["sma50"]
    sma200 = technical["sma200"]

    checks = [
        market_cap is not None and market_cap >= thresholds.min_market_cap,
        forward_pe is not None and forward_pe <= thresholds.max_forward_pe,
        roe is not None and roe >= thresholds.min_roe,
        profit_margin is not None and profit_margin >= thresholds.min_profit_margin,
        debt_to_equity is not None and debt_to_equity <= thresholds.max_debt_to_equity,
        revenue_growth is not None and revenue_growth >= thresholds.min_revenue_growth,
        avg_volume_3m is not None and avg_volume_3m >= thresholds.min_avg_volume_3m,
        (
            not thresholds.require_price_above_sma50
            or (price is not None and sma50 is not None and price > sma50)
        ),
        (
            not thresholds.require_price_below_sma200
            or (price is not None and sma200 is not None and price < sma200)
        ),
    ]

    return StockEvaluation(
        ticker=ticker,
        company=company,
        passed=all(checks),
        score=sum(checks),
        price=price,
        market_cap=market_cap,
        forward_pe=forward_pe,
        roe=roe,
        profit_margin=profit_margin,
        debt_to_equity=debt_to_equity,
        revenue_growth=revenue_growth,
        avg_volume_3m=avg_volume_3m,
        sma50=sma50,
        sma200=sma200,
    )


def scan_sp500(thresholds: MetricThresholds, limit: int | None, workers: int, manual_tickers: str | None) -> list[StockEvaluation]:
    tickers = parse_manual_tickers(manual_tickers) if manual_tickers else get_sp500_tickers(limit)
    results: list[StockEvaluation] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(evaluate_stock, t, c, thresholds): (t, c) for t, c in tickers}
        for fut in as_completed(futures):
            ticker, _ = futures[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                print(f"[WARN] {ticker}: {exc}")

    return sorted(results, key=lambda r: (r.passed, r.score, r.market_cap or 0), reverse=True)


def save_csv(results: list[StockEvaluation], path: str) -> None:
    if not results:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for row in results:
            writer.writerow(asdict(row))


def load_thresholds(config_path: str | None) -> MetricThresholds:
    t = MetricThresholds()
    if not config_path:
        return t
    with open(config_path, "r", encoding="utf-8") as fh:
        user_cfg = json.load(fh)
    for key, value in user_cfg.items():
        if hasattr(t, key):
            setattr(t, key, value)
    return t


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Agente de scraping/filtrado S&P 500 con Yahoo Finance")
    p.add_argument("--limit", type=int, default=80, help="Número de tickers a evaluar")
    p.add_argument("--top", type=int, default=15, help="Top de resultados a mostrar")
    p.add_argument("--workers", type=int, default=8, help="Número de hilos")
    p.add_argument("--output", default="sp500_screening.csv", help="CSV de salida")
    p.add_argument("--config", help="JSON con umbrales personalizados")
    p.add_argument("--tickers", help="Lista manual separada por coma (ej: AAPL,MSFT,NVDA)")
    return p


def main() -> None:
    args = build_parser().parse_args()
    thresholds = load_thresholds(args.config)
    results = scan_sp500(thresholds, args.limit, args.workers, args.tickers)
    save_csv(results, args.output)

    print("\n=== Top acciones por score ===")
    for row in results[: args.top]:
        print(
            f"{row.ticker:6} | score={row.score}/9 | passed={row.passed} | "
            f"price={row.price} | PE={row.forward_pe} | ROE={row.roe}"
        )

    passed = [r for r in results if r.passed]
    print(f"\nAcciones que cumplen TODAS las métricas: {len(passed)}")
    for row in passed[: args.top]:
        print(f"  - {row.ticker} ({row.company})")


if __name__ == "__main__":
    main()
