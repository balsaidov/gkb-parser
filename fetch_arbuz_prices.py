#!/usr/bin/env python3
"""CLI-скрипт для получения цен с arbuz.kz.

Использование:
    python fetch_arbuz_prices.py                  # 10 базовых товаров, Алматы
    python fetch_arbuz_prices.py --city astana     # 10 базовых товаров, Астана
    python fetch_arbuz_prices.py --search молоко   # Поиск конкретного товара
    python fetch_arbuz_prices.py --json            # Вывод в JSON
"""

import argparse
import asyncio
import json
import sys

from app.arbuz.parser import ArbuzParser


async def main():
    parser = argparse.ArgumentParser(description="Парсер цен arbuz.kz")
    parser.add_argument(
        "--city", default="almaty", choices=["almaty", "astana"],
        help="Город (по умолчанию: almaty)",
    )
    parser.add_argument(
        "--search", type=str, default=None,
        help="Поиск конкретного товара",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Вывод в формате JSON",
    )
    args = parser.parse_args()

    arbuz = ArbuzParser(city=args.city)

    if args.search:
        result = await arbuz.fetch_product_prices(query=args.search)
        results = [result]
    else:
        results = await arbuz.fetch_basic_prices()

    if args.as_json:
        print(json.dumps(
            [r.model_dump() for r in results],
            ensure_ascii=False, indent=2,
        ))
        return

    # Человекочитаемый вывод
    print(f"\n{'='*60}")
    print(f"  Цены arbuz.kz — {args.city.capitalize()}")
    print(f"{'='*60}\n")

    for r in results:
        if not r.products:
            print(f"  {r.query}: товары не найдены")
            continue

        print(f"  {r.query}")
        print(f"  {'─'*40}")
        for p in r.products[:5]:  # Показываем топ-5
            discount = ""
            if p.old_price:
                pct = round((1 - p.price / p.old_price) * 100)
                discount = f" (было {p.old_price:.0f} ₸, -{pct}%)"
            print(f"    {p.price:>8.0f} ₸  {p.name}{discount}")

        if r.cheapest:
            print(f"  → Мин: {r.cheapest.price:.0f} ₸ | Средняя: {r.average_price:.0f} ₸")
        if len(r.products) > 5:
            print(f"    ... и ещё {len(r.products) - 5} товаров")
        print()

    print(f"{'='*60}")
    total_found = sum(len(r.products) for r in results)
    print(f"  Всего найдено: {total_found} товаров")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
