# Scraper produktových obrázků (lovecky-obchod.cz)

Projekt pro získání URL obrázků produktů z e-shopu **https://www.lovecky-obchod.cz** pro účely migrace dat.

> Scraper je navržen šetrně: respektuje `robots.txt`, přidává zpoždění mezi requesty a nic nestahuje kromě HTML. Obrázky samotné nestahuje – ukládá pouze jejich URL.

## Struktura projektu

- `README.md`
- `requirements.txt`
- `scraper.py`
- `config.py`
- `data/`
  - `product_images.csv`
  - `processed_products.txt`

## Instalace

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Konfigurace

Nastavení je v `config.py`:

- `BASE_URL`
- `START_URL`
- `REQUEST_DELAY`
- `USER_AGENT`
- `OUTPUT_FILE`
- `PROCESSED_PRODUCTS_FILE`
- `MAX_PRODUCTS`
- `REQUEST_TIMEOUT`

## Spuštění

Běžný běh:

```bash
python scraper.py
```

Testovací běh s limitem produktů:

```bash
python scraper.py --max-products 10
```

## Co scraper dělá

1. Načte vstupní stránku `/vsechno-zbozi/`.
2. Najde odkazy na kategorie/podkategorie.
3. Projde kategorie včetně stránkování.
4. Získá URL produktových detailů.
5. Z každého produktu vytáhne:
   - název produktu,
   - SKU/kód (pokud existuje),
   - hlavní i galerijní obrázky,
   - lazy-load atributy (`data-src`, `data-original`, `srcset`, ...),
   - fallback přes OpenGraph (`og:image`).
6. Převádí relativní URL na absolutní.
7. Odstraňuje duplicity produktů i obrázků.
8. Ukládá jeden řádek na kombinaci **produkt + obrázek**.
9. Udržuje `processed_products.txt` pro resume mód.

## Resume mód

Soubor `data/processed_products.txt` ukládá URL už zpracovaných produktů. Při dalším spuštění se tyto URL přeskočí.

## CSV výstup

Výstupní soubor: `data/product_images.csv`

Sloupce:

- `product_url`
- `product_name`
- `product_code / sku`
- `image_url`
- `image_position`
- `source_page`
- `scraped_at`

## Volitelná JS varianta (Playwright)

Primární implementace používá `requests + BeautifulSoup`.
Pokud by některé stránky renderovaly klíčová data až přes JavaScript, lze doplnit fallback režim přes Playwright (není vynucen v základní verzi).
