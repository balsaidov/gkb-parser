"""Парсер цен с arbuz.kz.

Парсит товары из категорий каталога arbuz.kz и сохраняет результаты.

Использование:
    from app.arbuz.parser import ArbuzParser

    parser = ArbuzParser(city="almaty")
    results = await parser.fetch_basic_prices()
"""

import copy
import json
import re
import logging
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.arbuz.models import ArbuzProduct, ArbuzPriceResult

logger = logging.getLogger(__name__)

BASE_URL = "https://arbuz.kz"

# Базовые категории товаров на arbuz.kz
BASIC_CATEGORIES = [
    {"query": "Молоко", "category_id": 20050, "slug": "moloko"},
    {"query": "Хлеб", "category_id": 20144, "slug": "hleb"},
    {"query": "Яйца", "category_id": 20114, "slug": "yaica"},
    {"query": "Сахар", "category_id": 224542, "slug": "sahar"},
    {"query": "Масло подсолнечное", "category_id": 19735, "slug": "podsolnechnoe_maslo"},
    {"query": "Мука", "category_id": 202280, "slug": "pshenichnaya_muka"},
    {"query": "Рис", "category_id": 202281, "slug": "ris"},
    {"query": "Курица", "category_id": 225137, "slug": "kurica_ohlazhd_nnaya"},
    {"query": "Картофель", "category_id": 225178, "slug": "ovoshi"},
    {"query": "Гречка", "category_id": 224782, "slug": "grechka"},
    {"query": "Газировка", "category_id": 20784, "slug": "gazirovka_i_energetiki"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

SAVED_PRODUCTS_FILE = Path(__file__).parent.parent.parent / "data" / "products.json"


class ArbuzParser:
    """Парсер цен с arbuz.kz."""

    def __init__(self, city: str = "almaty"):
        self.city = city
        self.base_catalog_url = f"{BASE_URL}/ru/{city}/catalog"

    async def _fetch_page(self, url: str) -> Optional[str]:
        """Загрузить HTML страницы."""
        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=30.0
        ) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPError as e:
                logger.error("Ошибка загрузки %s: %s", url, e)
                return None

    def _parse_products_from_html(self, html: str, query: str = "") -> list[ArbuzProduct]:
        """Извлечь товары из HTML разметки страницы каталога."""
        soup = BeautifulSoup(html, "html.parser")
        products = []

        # 1. JSON-LD structured data
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld_data = json.loads(script.string)
                if isinstance(ld_data, dict) and ld_data.get("@type") == "ItemList":
                    for item in ld_data.get("itemListElement", []):
                        offer = item.get("item", {})
                        if offer.get("@type") == "Product":
                            offers = offer.get("offers", {})
                            price = float(offers.get("price", 0))
                            if price > 0:
                                products.append(ArbuzProduct(
                                    id=_extract_id_from_url(offer.get("url", "")),
                                    name=offer.get("name", ""),
                                    price=price,
                                    image_url=offer.get("image"),
                                    url=offer.get("url"),
                                    available=offers.get("availability", "")
                                    == "https://schema.org/InStock",
                                ))
                # Один товар (страница товара)
                if isinstance(ld_data, dict) and ld_data.get("@type") == "Product":
                    offers = ld_data.get("offers", {})
                    price = float(offers.get("price", 0))
                    if price > 0:
                        products.append(ArbuzProduct(
                            id=_extract_id_from_url(ld_data.get("url", ld_data.get("@id", ""))),
                            name=ld_data.get("name", ""),
                            price=price,
                            image_url=ld_data.get("image"),
                            url=ld_data.get("url"),
                            available=offers.get("availability", "")
                            == "https://schema.org/InStock",
                        ))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        if products:
            return self._filter_by_query(products, query)

        # 2. Nuxt SSR payload
        nuxt_products = self._parse_nuxt_payload(html)
        if nuxt_products:
            for item in nuxt_products:
                try:
                    price = float(item.get("price", 0))
                    if price <= 0:
                        continue
                    products.append(ArbuzProduct(
                        id=int(item.get("id", 0)),
                        name=item.get("name", item.get("title", "")),
                        price=price,
                        old_price=_safe_float(item.get("old_price")),
                        image_url=item.get("image", item.get("img")),
                        available=bool(item.get("available", True)),
                    ))
                except (TypeError, ValueError):
                    continue

        if products:
            return self._filter_by_query(products, query)

        # 3. HTML-карточки товаров
        card_selectors = [
            "div.product-card",
            "div.catalog-item",
            "article.product",
            "div[class*='product']",
            "div[class*='catalog-item']",
            "a[class*='product-card']",
        ]

        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                for card in cards:
                    product = self._parse_product_card(card)
                    if product:
                        products.append(product)
                break

        return self._filter_by_query(products, query)

    def _parse_nuxt_payload(self, html: str) -> Optional[list[dict]]:
        """Извлечь данные товаров из Nuxt 3 SSR payload."""
        patterns = [
            r'window\.__NUXT__\s*=\s*({.+?})\s*;?\s*</script>',
            r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.+?)</script>',
            r'"products"\s*:\s*(\[.+?\])\s*[,}]',
            r'"items"\s*:\s*(\[.+?\])\s*[,}]',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, list):
                        return data
                    for key in ("products", "items", "data", "catalog"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                except (json.JSONDecodeError, TypeError):
                    continue
        return None

    def _parse_product_card(self, card) -> Optional[ArbuzProduct]:
        """Извлечь данные товара из HTML-карточки."""
        name = ""
        price = 0.0
        old_price = None
        image_url = None
        url = None
        product_id = 0

        # Название
        for sel in ["h3", "h4", ".product-name", ".product-title",
                     "[class*='name']", "[class*='title']", "a[title]"]:
            el = card.select_one(sel)
            if el:
                name = el.get_text(strip=True) or el.get("title", "")
                if name:
                    break

        # Старая цена — извлекаем ПЕРВОЙ
        for sel in [".old-price", "[class*='old']", "[class*='discount']",
                    "s", "del"]:
            el = card.select_one(sel)
            if el:
                old_price = _parse_price(el.get_text(strip=True))
                break

        # Убираем элементы старой цены из копии, чтобы не склеивались
        card_clean = copy.copy(card)
        for old_el in card_clean.find_all(
            lambda tag: tag.name in ("s", "del")
            or (tag.get("class") and any(
                "old" in c or "discount" in c
                for c in tag.get("class", [])
            ))
        ):
            old_el.decompose()

        # Цена (из очищенной карточки)
        for sel in [".product-price", ".price", "[class*='price']",
                    "span[class*='price']", "[class*='cost']"]:
            el = card_clean.select_one(sel)
            if el:
                price_text = el.get_text(strip=True)
                price = _parse_price(price_text)
                if price > 0:
                    break

        # Картинка
        img = card.select_one("img")
        if img:
            image_url = img.get("src") or img.get("data-src")

        # Ссылка и ID
        link = card.select_one("a[href*='/catalog/item/']")
        if not link:
            link = card.find("a", href=True)
        if link:
            url = link.get("href", "")
            if url and not url.startswith("http"):
                url = BASE_URL + url
            product_id = _extract_id_from_url(url)

        if not name or price <= 0:
            return None

        return ArbuzProduct(
            id=product_id,
            name=name,
            price=price,
            old_price=old_price if old_price and old_price > 0 else None,
            image_url=image_url,
            url=url,
        )

    def _filter_by_query(
        self, products: list[ArbuzProduct], query: str
    ) -> list[ArbuzProduct]:
        """Фильтрация товаров по поисковому запросу."""
        if not query:
            return products
        q = query.lower()
        return [p for p in products if q in p.name.lower()]

    async def fetch_category(
        self,
        category_id: int,
        slug: str,
        query: str = "",
    ) -> list[ArbuzProduct]:
        """Загрузить товары из категории."""
        url = f"{self.base_catalog_url}/cat/{category_id}-{slug}"
        logger.info("Загрузка категории: %s", url)
        html = await self._fetch_page(url)
        if not html:
            return []
        return self._parse_products_from_html(html, query)

    async def fetch_basic_prices(self) -> list[ArbuzPriceResult]:
        """Получить цены на базовые товары по категориям."""
        results = []
        for cat in BASIC_CATEGORIES:
            products = await self.fetch_category(
                category_id=cat["category_id"],
                slug=cat["slug"],
            )

            cheapest = min(products, key=lambda p: p.price) if products else None
            avg_price = (
                sum(p.price for p in products) / len(products) if products else None
            )

            result = ArbuzPriceResult(
                query=cat["query"],
                category=cat["slug"],
                city=self.city,
                products=products,
                cheapest=cheapest,
                average_price=round(avg_price, 2) if avg_price else None,
            )
            results.append(result)

            logger.info(
                "%s: найдено %d товаров, мин. цена: %s ₸",
                cat["query"],
                len(products),
                cheapest.price if cheapest else "—",
            )

        return results

    def save_products(self, results: list[ArbuzPriceResult]) -> Path:
        """Сохранить найденные товары в JSON файл."""
        SAVED_PRODUCTS_FILE.parent.mkdir(parents=True, exist_ok=True)

        data = []
        for r in results:
            for p in r.products:
                data.append({
                    "category": r.query,
                    "id": p.id,
                    "name": p.name,
                    "price": p.price,
                    "old_price": p.old_price,
                    "url": p.url,
                    "image_url": p.image_url,
                    "available": p.available,
                })

        SAVED_PRODUCTS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Сохранено %d товаров в %s", len(data), SAVED_PRODUCTS_FILE)
        return SAVED_PRODUCTS_FILE

    def load_saved_products(self) -> list[dict]:
        """Загрузить ранее сохранённые товары."""
        if not SAVED_PRODUCTS_FILE.exists():
            return []
        return json.loads(SAVED_PRODUCTS_FILE.read_text(encoding="utf-8"))


def _parse_price(text: str) -> float:
    """Извлечь числовую цену из текста."""
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.,]", "", text)
    cleaned = cleaned.replace(",", ".")
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    elif len(parts) == 2 and len(parts[1]) == 3:
        cleaned = "".join(parts)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _safe_float(val) -> Optional[float]:
    """Безопасное преобразование в float."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _extract_id_from_url(url: str) -> int:
    """Извлечь ID товара из URL вида /catalog/item/12345-name."""
    match = re.search(r"/(?:item|cat)/(\d+)-", url)
    return int(match.group(1)) if match else 0
