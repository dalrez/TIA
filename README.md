# Agente IA para screening del S&P 500 con Yahoo Finance

Este proyecto incluye un script en Python que actúa como **agente de análisis**:

1. Obtiene la lista de empresas del S&P 500.
2. Consulta métricas financieras en endpoints públicos de Yahoo Finance.
3. Evalúa cada acción contra umbrales configurables.
4. Destaca los valores que cumplen todas las métricas.

## Requisitos

- Python 3.10+
- No requiere librerías externas (solo librería estándar)

## Uso rápido

```bash
python sp500_yahoo_agent.py --limit 100 --top 20 --output resultado.csv
```

## Uso con métricas personalizadas

```bash
python sp500_yahoo_agent.py --config config_metricas_ejemplo.json --limit 120 --top 25
```

## Uso con tickers manuales

Si tu entorno bloquea la descarga de la lista del S&P 500, puedes pasar tickers manualmente:

```bash
python sp500_yahoo_agent.py --tickers AAPL,MSFT,NVDA --top 10
```

## Métricas que evalúa

- Capitalización mínima (`min_market_cap`)
- P/E forward máximo (`max_forward_pe`)
- ROE mínimo (`min_roe`)
- Margen neto mínimo (`min_profit_margin`)
- Deuda/Patrimonio máximo (`max_debt_to_equity`)
- Crecimiento de ingresos mínimo (`min_revenue_growth`)
- Volumen medio mínimo 3 meses (`min_avg_volume_3m`)
- Precio por encima de SMA50 (`require_price_above_sma50`)

## Nota

Yahoo Finance puede devolver campos vacíos para algunos tickers. El script continúa el análisis y muestra advertencias en esos casos.
