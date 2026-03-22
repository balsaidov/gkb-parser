#!/usr/bin/env python3
"""CLI-скрипт для получения цен с arbuz.kz.

Использование:
    python fetch_arbuz_prices.py                          # Все базовые категории
    python fetch_arbuz_prices.py --city astana             # Астана
    python fetch_arbuz_prices.py --category 20784 gazirovka_i_energetiki  # Одна категория
    python fetch_arbuz_prices.py --save                    # Сохранить товары в data/products.json
    python fetch_arbuz_prices.py --json                    # Вывод в JSON
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
        "--category", nargs=2, metavar=("ID", "SLUG"),
        help="Парсить одну категорию: ID и slug (напр. 20784 gazirovka_i_energetiki)",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Вывод в формате JSON",
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Сохранить найденные товары в data/products.json",
    )
    args = parser.parse_args()

    arbuz = ArbuzParser(city=args.city)

    if args.category:
        cat_id, cat_slug = int(args.category[0]), args.category[1]
        products = await arbuz.fetch_category(cat_id, cat_slug)
        from app.arbuz.models import ArbuzPriceResult
        cheapest = min(products, key=lambda p: p.price) if products else None
        avg = sum(p.price for p in products) / len(products) if products else None
        results = [ArbuzPriceResult(
            query=cat_slug, category=cat_slug, city=args.city,
            products=products, cheapest=cheapest,
            average_price=round(avg, 2) if avg else None,
        )]
    else:
        results = await arbuz.fetch_basic_prices()

    if args.save:
        path = arbuz.save_products(results)
        print(f"\nСохранено в {path}")

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

        print(f"  {r.query} ({len(r.products)} товаров)")
        print(f"  {'─'*40}")
        for p in r.products[:5]:  # Показываем топ-5
            discount = ""
            if p.old_price and p.old_price > p.price:
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
