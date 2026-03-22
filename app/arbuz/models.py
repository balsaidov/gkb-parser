from pydantic import BaseModel
from typing import Optional


class ArbuzProduct(BaseModel):
    """Товар с arbuz.kz."""
    id: int
    name: str
    price: float
    old_price: Optional[float] = None
    unit: Optional[str] = None
    image_url: Optional[str] = None
    category: Optional[str] = None
    available: bool = True
    url: Optional[str] = None


class ArbuzCategory(BaseModel):
    """Категория каталога arbuz.kz."""
    id: int
    slug: str
    name: str


class ArbuzPriceResult(BaseModel):
    """Результат парсинга цен по одному базовому товару."""
    query: str
    category: Optional[str] = None
    city: str = "almaty"
    products: list[ArbuzProduct] = []
    cheapest: Optional[ArbuzProduct] = None
    average_price: Optional[float] = None
