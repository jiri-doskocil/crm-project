import argparse
import csv
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import (
    BASE_URL,
    MAX_PRODUCTS,
    OUTPUT_FILE,
    PROCESSED_PRODUCTS_FILE,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    START_URL,
    USER_AGENT,
)

HEADERS = {"User-Agent": USER_AGENT}


def normalize_url(url: Optional[str], base_url: str = BASE_URL) -> Optional[str]:
    """Převede relativní URL na absolutní a vyčistí ji."""
    if not url:
        return None
    cleaned = url.strip()
    if cleaned.startswith("//"):
        return "https:" + cleaned
    return urljoin(base_url, cleaned)


def fetch_html(session: requests.Session, url: str, delay: float = REQUEST_DELAY) -> Optional[BeautifulSoup]:
    """Načte URL s timeoutem, ošetřením HTTP chyb a čekáním mezi requesty."""
    time.sleep(delay)
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as exc:
        logging.error("Chyba načtení URL %s: %s", url, exc)
        return None


def get_category_urls(soup: BeautifulSoup, base_url: str = BASE_URL) -> Set[str]:
    """Najde odkazy na kategorie a podkategorie ze startovací stránky."""
    category_urls: Set[str] = set()
    for link in soup.select("a[href]"):
        href = normalize_url(link.get("href"), base_url)
        if not href:
            continue
        parsed = urlparse(href)
        if parsed.netloc != urlparse(base_url).netloc:
            continue
        path = parsed.path.lower()
        # Heuristika: necháváme URL, které vypadají jako kategorie,
        # ale vynecháme detailní stránky produktu a pomocné stránky.
        if any(x in path for x in ["/produkt/", "/kosik", "/obchodni-podminky", "/kontakt"]):
            continue
        if path.endswith("/") and path != "/":
            category_urls.add(href)

    # Vždy zahrnout i START_URL, aby scraper fungoval i při slabém výběru odkazů.
    category_urls.add(START_URL)
    return category_urls


def get_next_page_url(soup: BeautifulSoup, current_url: str, base_url: str = BASE_URL) -> Optional[str]:
    """Vrátí URL další stránky z paginace."""
    candidates = soup.select('a[rel="next"], a.next, a[aria-label*="Dal"]')
    for link in candidates:
        href = normalize_url(link.get("href"), base_url)
        if href and href != current_url:
            return href

    for link in soup.select("a[href]"):
        text = link.get_text(" ", strip=True).lower()
        if text in {"další", "next", ">"}:
            href = normalize_url(link.get("href"), base_url)
            if href and href != current_url:
                return href
    return None


def get_product_urls_from_category(session: requests.Session, category_url: str) -> Set[str]:
    """Projde kategorii včetně paginace a vrátí URL produktů."""
    product_urls: Set[str] = set()
    visited_pages: Set[str] = set()
    current_url = category_url

    while current_url and current_url not in visited_pages:
        visited_pages.add(current_url)
        soup = fetch_html(session, current_url)
        if not soup:
            break

        for link in soup.select("a[href]"):
            href = normalize_url(link.get("href"), BASE_URL)
            if not href:
                continue
            path = urlparse(href).path.lower()
            if "/produkt/" in path or "/p/" in path:
                product_urls.add(href)

        current_url = get_next_page_url(soup, current_url)

    return product_urls


def _extract_image_candidates(tag) -> Iterable[str]:
    attrs = ["src", "data-src", "data-original", "data-lazy", "data-zoom-image"]
    for attr in attrs:
        value = tag.get(attr)
        if value:
            yield value

    srcset = tag.get("srcset") or tag.get("data-srcset")
    if srcset:
        for part in srcset.split(","):
            url = part.strip().split(" ")[0]
            if url:
                yield url


def parse_product_detail(session: requests.Session, product_url: str) -> List[Dict[str, str]]:
    """Z produktu vytěží metadata a všechny URL obrázků."""
    soup = fetch_html(session, product_url)
    if not soup:
        return []

    product_name = ""
    h1 = soup.select_one("h1")
    if h1:
        product_name = h1.get_text(" ", strip=True)

    sku = ""
    sku_selectors = [
        '[itemprop="sku"]',
        ".sku",
        "span.code",
        "div.product-code",
        "td.product-code",
    ]
    for selector in sku_selectors:
        el = soup.select_one(selector)
        if el and el.get_text(strip=True):
            sku = el.get_text(" ", strip=True)
            break

    image_urls: List[str] = []
    seen_images: Set[str] = set()

    for img in soup.select("img"):
        for candidate in _extract_image_candidates(img):
            absolute = normalize_url(candidate, BASE_URL)
            if absolute and absolute not in seen_images:
                seen_images.add(absolute)
                image_urls.append(absolute)

    # fallback: OpenGraph image
    og_image = soup.select_one('meta[property="og:image"]')
    if og_image:
        og_url = normalize_url(og_image.get("content"), BASE_URL)
        if og_url and og_url not in seen_images:
            image_urls.append(og_url)

    scraped_at = datetime.now(timezone.utc).isoformat()
    rows: List[Dict[str, str]] = []
    for index, image_url in enumerate(image_urls, start=1):
        rows.append(
            {
                "product_url": product_url,
                "product_name": product_name,
                "product_code / sku": sku,
                "image_url": image_url,
                "image_position": index,
                "source_page": product_url,
                "scraped_at": scraped_at,
            }
        )

    return rows


def load_processed_products(processed_file: str = PROCESSED_PRODUCTS_FILE) -> Set[str]:
    """Načte již zpracované produkty pro resume mód."""
    if not os.path.exists(processed_file):
        return set()
    with open(processed_file, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def mark_product_processed(product_url: str, processed_file: str = PROCESSED_PRODUCTS_FILE) -> None:
    """Zapíše produkt do souboru zpracovaných URL."""
    with open(processed_file, "a", encoding="utf-8") as f:
        f.write(product_url + "\n")


def save_rows_to_csv(rows: List[Dict[str, str]], output_file: str = OUTPUT_FILE) -> None:
    """Uloží řádky do CSV (append mód)."""
    if not rows:
        return

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    file_exists = os.path.exists(output_file)

    df = pd.DataFrame(rows)
    df.to_csv(output_file, mode="a", header=not file_exists, index=False, quoting=csv.QUOTE_MINIMAL)


def can_fetch_by_robots(url: str, user_agent: str = USER_AGENT) -> bool:
    """Zkontroluje robots.txt pravidla."""
    rp = RobotFileParser()
    rp.set_url(urljoin(BASE_URL, "/robots.txt"))
    try:
        rp.read()
    except Exception as exc:  # pragma: no cover
        logging.warning("Nepodařilo se načíst robots.txt (%s), pokračuji konzervativně.", exc)
    return rp.can_fetch(user_agent, url)


def run_scraper(max_products: Optional[int] = None) -> None:
    session = requests.Session()
    session.headers.update(HEADERS)

    if not can_fetch_by_robots(START_URL):
        logging.error("START_URL není povolen robots.txt: %s", START_URL)
        return

    start_soup = fetch_html(session, START_URL)
    if not start_soup:
        logging.error("Nepodařilo se načíst startovní stránku.")
        return

    category_urls = get_category_urls(start_soup)
    logging.info("Nalezeno kategorií/podkategorií: %s", len(category_urls))

    all_product_urls: Set[str] = set()
    for category_url in sorted(category_urls):
        if not can_fetch_by_robots(category_url):
            logging.warning("Přeskakuji (robots.txt): %s", category_url)
            continue
        product_urls = get_product_urls_from_category(session, category_url)
        all_product_urls.update(product_urls)

    logging.info("Nalezeno unikátních produktů: %s", len(all_product_urls))

    processed_products = load_processed_products()
    logging.info("Již zpracovaných produktů (resume): %s", len(processed_products))

    processed_count = 0
    image_count = 0

    for product_url in sorted(all_product_urls):
        if max_products is not None and processed_count >= max_products:
            break

        if product_url in processed_products:
            continue

        if not can_fetch_by_robots(product_url):
            logging.warning("Přeskakuji produkt (robots.txt): %s", product_url)
            continue

        rows = parse_product_detail(session, product_url)
        save_rows_to_csv(rows)
        mark_product_processed(product_url)

        processed_count += 1
        image_count += len(rows)

        logging.info(
            "Zpracován produkt %s | obrázků: %s | celkem produktů: %s",
            product_url,
            len(rows),
            processed_count,
        )

    logging.info("Dokončeno. Zpracováno produktů v tomto běhu: %s", processed_count)
    logging.info("Nalezeno obrázků v tomto běhu: %s", image_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scraper URL produktových obrázků")
    parser.add_argument(
        "--max-products",
        type=int,
        default=MAX_PRODUCTS,
        help="Limit počtu nově zpracovaných produktů (testovací režim).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = parse_args()
    run_scraper(max_products=args.max_products)
