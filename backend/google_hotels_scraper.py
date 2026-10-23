#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google Hotels scraper with optional translation"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
import json
import time
from datetime import datetime

class GoogleHotelsScraper:
    def __init__(self, headless=True):
        options = Options()
        if headless:
            options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--window-size=1920,1080')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 30)

    def search(self, location: str):
        url = f"https://www.google.com/travel/hotels/{location}"
        print(f"Loading: {url}")
        self.driver.get(url)

        print("Waiting for content...")
        time.sleep(8)

        # Scroll to trigger loading
        for i in range(3):
            self.driver.execute_script("window.scrollBy(0, 800)")
            time.sleep(2)

    def is_non_english(self, text: str) -> bool:
        """Check if text contains non-ASCII characters"""
        return any(ord(c) > 127 for c in text)

    def extract_hotels(self) -> list[dict]:
        hotels = []
        page_source = self.driver.page_source

        with open("google_page.html", "w", encoding='utf-8') as f:
            f.write(page_source)

        # Find all clickable elements
        possible_selectors = [
            'div[role="button"]',
            'div[jsaction*="hotel"]',
            'li',
            'article',
            'div[data-hotel]',
            'div.uaTTDe',
        ]

        all_candidates = []
        for selector in possible_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"  {selector}: {len(elements)} elements")
                if elements:
                    all_candidates.extend(elements)
            except:
                pass

        print(f"\nParsing {len(all_candidates)} elements...")

        for elem in all_candidates:
            try:
                text = elem.text.strip()
                if not text or len(text) < 10 or len(text) > 1000:
                    continue

                lines = [l.strip() for l in text.split('\n') if l.strip()]

                # Hotel heuristic
                has_currency = any(sym in text for sym in ['$', '₹', 'USD', 'INR', 'EUR', '€'])
                has_numbers = any(c.isdigit() for c in text)

                if has_currency and has_numbers and len(lines) >= 2:
                    name = lines[0]

                    if len(name) < 5 or any(skip in name.lower() for skip in ['search', 'filter', 'sort', 'map', 'list']):
                        continue

                    hotel = {
                        'name': name,
                        'is_non_english': self.is_non_english(name),
                        'price': next((l for l in lines if any(s in l for s in ['$', '₹', 'USD', 'INR'])), ''),
                        'rating': next((l for l in lines if '.' in l and len(l) <= 5 and any(c.isdigit() for c in l)), ''),
                        'info': ' | '.join(lines[1:3]) if len(lines) > 1 else '',
                    }

                    if hotel['name']:
                        hotels.append(hotel)

            except:
                continue

        # Deduplicate
        seen = set()
        unique = []
        for h in hotels:
            if h['name'] not in seen and len(h['name']) > 5:
                seen.add(h['name'])
                unique.append(h)

        return unique

    def scrape(self, location: str) -> list[dict]:
        try:
            self.search(location)
            return self.extract_hotels()
        finally:
            self.driver.quit()

def translate_results(results: list[dict]) -> list[dict]:
    """Translate non-English hotel names with rate limiting"""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source='auto', target='en')

        print("\nTranslating non-English names...")
        translated = 0

        for hotel in results:
            if hotel.get('is_non_english'):
                try:
                    hotel['name_en'] = translator.translate(hotel['name'])
                    translated += 1
                    time.sleep(0.5)  # Rate limit protection
                except Exception as e:
                    hotel['name_en'] = hotel['name']
                    print(f"  Translation failed for: {hotel['name'][:30]}...")
            else:
                hotel['name_en'] = hotel['name']

        print(f"Translated {translated} names")
        return results

    except ImportError:
        print("\nTranslation library not available.")
        print("Install with: pip install deep-translator")
        for hotel in results:
            hotel['name_en'] = hotel['name']
        return results

def main():
    print("Google Hotels Scraper\n")

    location = input("Enter location (city or region): ").strip() or "Goa"
    translate = input("Translate non-English names? (y/n, default n): ").strip().lower() == 'y'

    print(f"\nSearching hotels in {location}...\n")

    scraper = GoogleHotelsScraper(headless=True)
    results = scraper.scrape(location)

    if not results:
        print("\nNo results extracted.")
        print("Check google_page.html to see what loaded.")
        return

    # Translate if requested
    if translate:
        results = translate_results(results)

    print(f"\nFound {len(results)} hotels:\n")

    for i, hotel in enumerate(results[:25], 1):
        name_display = hotel['name']

        # Show translation if available and different
        if 'name_en' in hotel and hotel['name_en'] != hotel['name']:
            name_display = f"{hotel['name']}\n   EN: {hotel['name_en']}"

        print(f"{i}. {name_display}")
        if hotel['price']:
            print(f"   {hotel['price']}")
        if hotel['rating']:
            print(f"   Rating: {hotel['rating']}")
        print()

    # Save
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"google_hotels_{location.replace(' ', '_')}_{timestamp}.json"

    with open(filename, "w", encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(results)} hotels to {filename}")

    # Summary
    non_english = sum(1 for h in results if h.get('is_non_english'))
    if non_english:
        print(f"Note: {non_english} hotels have non-English names")
        if not translate:
            print("Run again with translation enabled to convert them to English")

if __name__ == "__main__":
    main()
