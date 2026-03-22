"""Парсер цен с arbuz.kz.

Поддерживает два подхода:
1. Парсинг HTML страниц каталога (SSR от Nuxt 3)
2. Поиск товаров через поисковую страницу

Использование:
    from app.arbuz.parser import ArbuzParser

    parser = ArbuzParser(city="almaty")
    results = await parser.fetch_basic_prices()
"""

import json
import re
import logging
from typing import Optional
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.arbuz.models import ArbuzProduct, ArbuzPriceResult

logger = logging.getLogger(__name__)

BASE_URL = "https://arbuz.kz"

# 10 базовых товаров с их категориями на arbuz.kz
BASIC_PRODUCTS = [
    {"query": "Молоко", "category_id": 20050, "category_slug": "moloko"},
    {"query": "Хлеб", "category_id": 20144, "category_slug": "hleb"},
    {"query": "Яйца", "category_id": 19986, "category_slug": "molochnye_produkty_yaica"},
    {"query": "Сахар", "category_id": 224542, "category_slug": "sahar"},
    {"query": "Масло подсолнечное", "category_id": 25401, "category_slug": "rastitelnye_masla"},
    {"query": "Мука", "category_id": 202280, "category_slug": "pshenichnaya_muka"},
    {"query": "Рис", "category_id": 19666, "category_slug": "krupa"},
    {"query": "Курица", "category_id": 19914, "category_slug": "kurica_zamorozhennaya"},
    {"query": "Картофель", "category_id": 225178, "category_slug": "ovoshi"},
    {"query": "Гречка", "category_id": 224398, "category_slug": "krupy_bobovye"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


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

    def _parse_nuxt_payload(self, html: str) -> Optional[list[dict]]:
        """Извлечь данные товаров из Nuxt 3 SSR payload."""
        # Nuxt 3 встраивает данные в <script> теги
        # Ищем паттерны: window.__NUXT__, __NUXT_DATA__, или inline JSON
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
                    # Если это объект, ищем вложенный список продуктов
                    for key in ("products", "items", "data", "catalog"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                except (json.JSONDecodeError, TypeError):
                    continue
        return None

    def _parse_products_from_html(self, html: str, query: str = "") -> list[ArbuzProduct]:
        """Извлечь товары из HTML разметки страницы каталога."""
        soup = BeautifulSoup(html, "html.parser")
        products = []

        # Пробуем JSON-LD structured data
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
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        if products:
            return self._filter_by_query(products, query)

        # Пробуем Nuxt SSR payload
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

        # Fallback: парсим HTML-элементы карточек товаров
        # Типичная структура Vue/Nuxt магазина: карточки с data-атрибутами или классами
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

        # Цена
        for sel in [".product-price", ".price", "[class*='price']",
                    "span[class*='price']", "[class*='cost']"]:
            el = card.select_one(sel)
            if el:
                price_text = el.get_text(strip=True)
                price = _parse_price(price_text)
                if price > 0:
                    break

        # Старая цена (скидка)
        for sel in [".old-price", "[class*='old']", "[class*='discount']",
                    "s", "del"]:
            el = card.select_one(sel)
            if el:
                old_price = _parse_price(el.get_text(strip=True))
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
        category_slug: str,
        query: str = "",
        limit: int = 50,
        page: int = 1,
    ) -> list[ArbuzProduct]:
        """Загрузить товары из категории."""
        url = (
            f"{self.base_catalog_url}/cat/{category_id}-{category_slug}"
            f"?limit={limit}&page={page}"
        )
        logger.info("Загрузка категории: %s", url)
        html = await self._fetch_page(url)
        if not html:
            return []
        return self._parse_products_from_html(html, query)

    async def search(self, query: str) -> list[ArbuzProduct]:
        """Поиск товаров через поисковую страницу."""
        encoded = quote(query)
        url = f"{BASE_URL}/ru/{self.city}/search?q={encoded}"
        logger.info("Поиск: %s", url)
        html = await self._fetch_page(url)
        if not html:
            return []
        return self._parse_products_from_html(html, query)

    async def fetch_product_prices(
        self,
        query: str,
        category_id: Optional[int] = None,
        category_slug: Optional[str] = None,
    ) -> ArbuzPriceResult:
        """Получить цены на конкретный товар."""
        products = []

        # Сначала пробуем категорию, если указана
        if category_id and category_slug:
            products = await self.fetch_category(
                category_id, category_slug, query
            )

        # Если мало результатов — дополняем поиском
        if len(products) < 3:
            search_results = await self.search(query)
            existing_ids = {p.id for p in products}
            for p in search_results:
                if p.id not in existing_ids:
                    products.append(p)

        cheapest = min(products, key=lambda p: p.price) if products else None
        avg_price = (
            sum(p.price for p in products) / len(products) if products else None
        )

        return ArbuzPriceResult(
            query=query,
            category=category_slug,
            city=self.city,
            products=products,
            cheapest=cheapest,
            average_price=round(avg_price, 2) if avg_price else None,
        )

    async def fetch_basic_prices(self) -> list[ArbuzPriceResult]:
        """Получить цены на 10 базовых товаров."""
        results = []
        for item in BASIC_PRODUCTS:
            result = await self.fetch_product_prices(
                query=item["query"],
                category_id=item["category_id"],
                category_slug=item["category_slug"],
            )
            results.append(result)
            logger.info(
                "%s: найдено %d товаров, мин. цена: %s ₸",
                item["query"],
                len(result.products),
                result.cheapest.price if result.cheapest else "—",
            )
        return results


def _parse_price(text: str) -> float:
    """Извлечь числовую цену из текста."""
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.,]", "", text)
    cleaned = cleaned.replace(",", ".")
    # Убираем точки-разделители тысяч (например "1.200" = 1200)
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    elif len(parts) == 2 and len(parts[1]) == 3:
        # Скорее всего разделитель тысяч, не десятичная часть
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
