"""Radar de Tendências (Google Trends RSS) para ideação de conteúdo viral."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

logger = logging.getLogger("shortpipeline.trends")

TRENDS_RSS_URL = "https://trends.google.com/trending/rss"


async def fetch_trends(geo: str = "BR") -> list[dict[str, Any]]:
    """Busca as tendências e assuntos mais buscados do dia via RSS oficial do Google Trends."""
    params = {"geo": geo.upper()}
    trends: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            res = await client.get(
                TRENDS_RSS_URL,
                params=params,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if res.status_code != 200:
                logger.warning(f"Google Trends retornou status {res.status_code}")
                return []

            root = ET.fromstring(res.text)
            ns = {"ht": "https://trends.google.com/trending/rss"}

            for item in root.findall(".//item"):
                title_el = item.find("title")
                approx_traffic_el = item.find("ht:approx_traffic", ns)
                desc_el = item.find("description")
                pub_date_el = item.find("pubDate")
                news_title_el = item.find("ht:news_item/ht:news_item_title", ns)
                news_url_el = item.find("ht:news_item/ht:news_item_url", ns)

                title = title_el.text if title_el is not None and title_el.text else ""
                traffic = approx_traffic_el.text if approx_traffic_el is not None and approx_traffic_el.text else ""
                desc = desc_el.text if desc_el is not None and desc_el.text else ""
                pub_date = pub_date_el.text if pub_date_el is not None and pub_date_el.text else ""
                news_title = news_title_el.text if news_title_el is not None and news_title_el.text else ""
                news_url = news_url_el.text if news_url_el is not None and news_url_el.text else ""

                if title:
                    trends.append({
                        "query": title,
                        "traffic": traffic,
                        "description": desc,
                        "news_title": news_title,
                        "news_url": news_url,
                        "pub_date": pub_date,
                    })
        except Exception as e:
            logger.warning(f"Erro ao buscar Google Trends: {e}")

    return trends[:25]
