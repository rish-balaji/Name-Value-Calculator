import os
import asyncio
import json
import re
import datetime as dt
from fake_useragent import UserAgent
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async, stealth_sync

# Configuration for proxy
PROXY_SERVER   = os.getenv("RES_PROXY")
PROXY_USERNAME = os.getenv("RES_PROXY_USER")
PROXY_PASSWORD = os.getenv("RES_PROXY_PASS")

class StealthScraper:
    BASE_URL = "https://www.insubuy.com/new-immigrant-insurance/"

    async def get_quotes(self, page, params):
        # Inject stealth evasion
        await stealth_async(page)

        # Go headful so CF sees a real browser
        await page.goto(self.BASE_URL, timeout=60000)
        await page.wait_for_load_state("networkidle")

        # Fill Age
        await page.fill('input[id="traveler_age"]', str(params["age"]))

        # Gender
        await page.select_option('select[name="gender"]',
                                  "M" if params["sex"] == "male" else "F")

        # State
        await page.select_option('select[name="state"]', params["landing_state"])

        # Submit & wait for quotes
        await page.click('button[type="submit"]')
        await page.wait_for_selector(".quote-results", timeout=60000)

        # Scrape rows
        plans = []
        for row in await page.query_selector_all(".quote-row"):
            name    = await row.query_selector_eval(".plan-name", "el=>el.textContent.trim()")
            max_cov = await row.query_selector_eval(".coverage",  "el=>el.textContent")
            price   = await row.query_selector_eval(".price",     "el=>el.textContent")
            plans.append({
                "provider":       "Insubuy",
                "plan":           name,
                "coverage_limit": self._parse_money(max_cov),
                "monthly_cost":   self._parse_money(price),
                "raw_html":       await row.inner_html()
            })
        return plans

    def _parse_money(self, txt):
        num = re.sub(r"[^\d.]", "", txt or "")
        return float(num) if num else 0.0

class QuoteEngine:
    def __init__(self):
        self.scraper = StealthScraper()

    async def gather(self, params):
        ua = UserAgent().random
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            ctx = await browser.new_context(
                user_agent=ua,
                proxy={
                    "server":   PROXY_SERVER,
                    "username": PROXY_USERNAME,
                    "password": PROXY_PASSWORD
                },
            )
            page = await ctx.new_page()
            plans = await self.scraper.get_quotes(page, params)
            await ctx.close()
            await browser.close()
        return plans

def rank(plans):
    if not plans:
        return []
    max_cov  = max(p["coverage_limit"] for p in plans)
    max_cost = max(p["monthly_cost"]  for p in plans)
    for p in plans:
        cov_score = p["coverage_limit"] / max_cov if max_cov else 0
        breadth   = sum(1 for f in ["medical evacuation","rx","acute onset","ad&d","ppo"]
                        if f in p["raw_html"].lower())
        cost_norm = p["monthly_cost"] / max_cost if max_cost else 1
        p["score"] = cov_score*0.6 + (breadth/10)*0.2 + (1-cost_norm)*0.2
    return sorted(plans, key=lambda x: x["score"], reverse=True)

if __name__ == "__main__":
    params = {
        "age":           40,
        "sex":           "male",
        "origin":        "IN",
        "dest":          "US",
        "start":         dt.date(2025,10,1),
        "end":           dt.date(2026,3,31),
        "landing_state": "TX"
    }
    plans = asyncio.run(QuoteEngine().gather(params))
    best  = rank(plans)[:5]
    print(json.dumps(best, indent=2, default=str))
