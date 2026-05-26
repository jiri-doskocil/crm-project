"""Konfigurace scraperu produktových obrázků."""

BASE_URL = "https://www.lovecky-obchod.cz"
START_URL = f"{BASE_URL}/vsechno-zbozi/"
REQUEST_DELAY = 1.5  # vteřiny mezi requesty
USER_AGENT = (
    "Mozilla/5.0 (compatible; ProductImageScraper/1.0; "
    "+https://example.local/scraper-contact)"
)
OUTPUT_FILE = "data/product_images.csv"
PROCESSED_PRODUCTS_FILE = "data/processed_products.txt"
MAX_PRODUCTS = None  # lze přepsat přes CLI argument
REQUEST_TIMEOUT = 20
