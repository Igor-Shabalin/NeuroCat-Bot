#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import aiohttp
from ddgs import DDGS   # современный пакет, замена duckduckgo_search
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from config import OPENAI_API_KEY

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


async def fetch_html(session, url, timeout=5):
    """Скачивает HTML страницы"""
    try:
        async with session.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"}
        ) as resp:
            if resp.status == 200:
                print(f"[web_search] response: {url} {resp.status}")
                return await resp.text()
            else:
                print(f"[web_search] ❌ {url} status {resp.status}")
    except Exception as e:
        print(f"[web_search] ❌ Ошибка при загрузке {url}: {e}")
    return ""


def extract_text(html, limit=1200):
    """Достаёт читаемый текст из HTML"""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for script in soup(["script", "style", "noscript"]):
            script.extract()
        text = " ".join(soup.stripped_strings)
        return text[:limit]
    except Exception:
        return ""


async def search_duckduckgo(query: str, num_results: int = 10):
    """Ищет ссылки через DuckDuckGo"""
    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                link = r.get("href") or r.get("url")
                if link:
                    print(f"[web_search] найдено: {link}")
                    results.append({
                        "title": r.get("title"),
                        "link": link,
                        "text": r.get("body", "")  # ⚡️ сохраняем body как текст
                    })
    except Exception as e:
        print(f"[web_search] ❌ Ошибка DuckDuckGo: {e}")
    return results


async def summarize_texts(results, query):
    """Просит GPT сделать конспект из найденных текстов"""
    texts = [r.get("text", "") for r in results if r.get("text")]
    joined = "\n\n".join(texts[:6])  # ⚡️ максимум 6 источника

    if not joined.strip():
        return "⚠️ Не удалось собрать текст из источников."

    prompt = f"""
Ты — умный ассистент. У тебя есть результаты поиска по запросу: "{query}".

Сделай краткий конспект (3–4 предложения), используй только факты.
Не придумывай от себя, опирайся на текст.
"""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": joined},
        ],
    )
    return response.choices[0].message.content.strip()


async def search_and_summarize(query: str, num_results: int = 5):
    """Главная функция: ищет → парсит → конспектирует"""
    results = await search_duckduckgo(query, num_results=num_results)
    if not results:
        print("[web_search] ❌ Нет результатов поиска")
        return "Ничего не найдено.", []

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_html(session, r["link"]) for r in results]
        pages = await asyncio.gather(*tasks)

    for i, html in enumerate(pages):
        if html:
            results[i]["text"] += "\n" + extract_text(html)
        # если html пустой, остаётся только body

    summary = await summarize_texts(results, query)
    sources = [r["link"] for r in results if r.get("link")]

    return summary, sources

