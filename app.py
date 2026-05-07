# -*- coding: utf-8 -*-
"""
Новостной агрегатор — Flask приложение.
Собирает новости из RSS-лент, фильтрует по ключевым словам.
Запуск: python app.py
Сайт откроется по адресу: http://127.0.0.1:5001
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for
import urllib.request
import xml.etree.ElementTree as ET
import json
import re
import time
import urllib.parse
from datetime import datetime, timedelta

app = Flask(__name__)

# ============================================================
# НАСТРОЙКИ VKONTAKTE
# ============================================================
VK_TOKEN = "vk1.a.RpzKVrorv3v_kLEcVI-sufpADtWD0kzPg_iG1cjEhMzH2cYagL4xue6FD6B04kKirnmZ79_o1xlBrkNpL3TUwuFLdXxggkXKo-X66hz3LqS4wT7i5mvLwEH9CXKUyS8_ph1qtVhUwQgEaSkfABt0uxo7TLzKZ4D8QlS3AyVB-6SeeLw_kgd6qx1QypkmWuEcmjixKHzOWxIlrp-W80YVXg"
VK_GROUP_ID = 238433455


def publish_to_vk(text, attachment=None):
    """
    Публикует текст в сообществе ВКонтакте.
    Возвращает True при успехе или текст ошибки.
    """
    try:
        api_url = "https://api.vk.com/method/wall.post"
        params = {
            "access_token": VK_TOKEN,
            "owner_id": -VK_GROUP_ID,
            "message": text,
            "v": "5.131",
        }
        if attachment:
            params["attachments"] = attachment

        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(api_url, data=data, method="POST")

        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))

        if "response" in result and "post_id" in result["response"]:
            return True
        elif "error" in result:
            return f"VK error: {result['error'].get('error_msg', 'Unknown')}"
        else:
            return "Unknown VK API response"
    except Exception as e:
        return f"Connection error: {str(e)}"


# ============================================================
# НАСТРОЙКИ
# ============================================================
SOURCES_FILE = "news_sources.json"
MAX_NEWS = 500  # Увеличено для большего покрытия

# Кэш новостей
NEWS_CACHE = {"data": [], "timestamp": 0}
CACHE_TTL = 300  # 5 минут

# ============================================================
# ЗАГРУЗКА ИСТОЧНИКОВ
# ============================================================

def load_sources():
    """Загружает RSS-источники из JSON."""
    try:
        with open(SOURCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("sources", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return [
            {"name": "Lenta.ru", "url": "https://lenta.ru/rss", "icon": "📰"},
            {"name": "Habr", "url": "https://habr.com/ru/rss/best/daily/", "icon": "💻"},
            {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml", "icon": "📡"},
        ]

# ============================================================
# ПАРСИНГ RSS
# ============================================================

def parse_rss(url, timeout=15):
    """Загружает и парсит RSS-ленту."""
    news_items = []
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw_data = response.read()
            content_type = response.headers.get("Content-Type", "")
        
        # Декодируем байты в строку
        xml_string = decode_xml_data(raw_data, content_type)
        
        # Парсим XML
        root = ET.fromstring(xml_string)
        
        # Ищем item элементы
        items = root.findall(".//item")
        
        for item in items:
            title = get_text(item, "title")
            description = get_text(item, "description")
            link = get_text(item, "link")
            pub_date = get_text(item, "pubDate")
            
            # Альтернативные поля описания
            if not description:
                description = get_text(item, "summary")
            if not description:
                description = get_text(item, "content")
            
            description = clean_html(description)
            
            # Сохраняем полный текст из RSS
            full_text = description.strip() if description else ""
            short_desc = full_text[:300] if full_text else ""
            
            # Если в RSS нет полного текста — пробуем получить со страницы статьи
            if not full_text and link:
                try:
                    page_text = fetch_article_text(link)
                    full_text = page_text
                    short_desc = full_text[:300]
                except Exception:
                    pass
            
            if title:
                news_items.append({
                    "title": title.strip(),
                    "description": short_desc,
                    "full_text": full_text,
                    "link": link,
                    "date": pub_date,
                })
            
    except Exception as e:
        print(f"RSS error {url}: {e}")
        
    return news_items


def decode_xml_data(data, content_type=""):
    """Декодирует XML-данные с учётом кодировки."""
    # Извлекаем charset из Content-Type
    match = re.search(r'charset=([^\s;]+)', content_type, re.IGNORECASE)
    if match:
        charset = match.group(1)
        try:
            return data.decode(charset)
        except (UnicodeDecodeError, LookupError):
            pass
    
    # Пробуем UTF-8
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    
    # Фоллбэк
    return data.decode("utf-8", errors="replace")


def get_text(item, tag):
    """Безопасно получает текст из XML элемента."""
    elem = item.find(tag)
    if elem is not None and elem.text:
        return elem.text.strip()
    return ""


def fetch_article_text(url, timeout=10):
    """
    Загружает страницу статьи и извлекает основной текст.
    Возвращает текст или пустую строку.
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_data = resp.read()
            content_type = resp.headers.get("Content-Type", "")
        
        html_text = decode_xml_data(raw_data, content_type)
        
        # Извлекаем текст из тегов параграфов и заголовков
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html_text, re.DOTALL)
        headings = re.findall(r'<h[1-6][^>]*>(.*?)</h[1-6]>', html_text, re.DOTALL)
        
        all_text = []
        for p in paragraphs + headings:
            text = clean_html(p).strip()
            # Фильтруем короткие бессмысленные фрагменты
            if len(text) > 30:
                all_text.append(text)
        
        # Объединяем первые 10 параграфов
        result = "\n\n".join(all_text[:10])
        
        # Ограничиваем длину
        if len(result) > 8000:
            result = result[:8000] + "..."
        
        return result
        
    except Exception:
        return ""


def clean_html(text):
    """Удаляет HTML-теги из текста."""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'</p>', '. ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# ============================================================
# ФИЛЬТРАЦИЯ
# ============================================================

# Синонимы для расширения поиска (ключевое слово -> список синонимов)
SYNONYMS = {
    "искусственный интеллект": ["искусственный", "интеллект", " ии ", "ai", "нейросет", "gpt", "chatgpt", "machine learning", "машинное обучение", "deep learning", "llm", "transformer"],
    "нейросет": ["нейросет", "нейрон", "llm", "gpt", "chatgpt", "ai", "генеративн", "stable diffusion", "midjourney", "dall"],
    "технологии": ["технолог", "цифров", "айти", "it-", "software", "digital", "гаджет", "устройств", "инноваци"],
    "программ": ["программ", "разработ", "код", "кодир", "python", "javascript", "typescript", "java", "c++", "c#", "go ", "rust", "swift", "kotlin"],
    "криптовалют": ["крипто", "биткоин", "bitcoin", "ethereum", "eth", "блокчейн", "blockchain", "defi", "nft", "web3"],
    "безопасност": ["безопасност", "кибер", "взлом", "атак", "malware", "вирус", "фишинг", "шифрован", "privacy"],
    "мобильн": ["смартфон", "мобильн", "android", "ios", "iphone", "samsung", "xiaomi", "app store"],
    "интернет": ["интернет", "онлайн", "соединен", "5g", "4g", "wifi", "роутер", "провайдер"],
    "бизнес": ["бизнес", "компан", "стартап", "инвестиц", "рынок", "акци", "прибыл", "убыток"],
    "политик": ["президент", "правительств", "закон", "санкци", "депутат", "выбор", "парламент"],
    "медицин": ["медицин", "здоровь", "лечен", "вакцин", "препарат", "болезн", "клиник"],
}

def expand_keywords(keywords):
    """Расширяет ключевые слова синонимами."""
    words = [w.strip().lower() for w in re.split(r'[,\s]+', keywords) if w.strip()]
    expanded = set(words)
    
    for word in words:
        for key, synonyms in SYNONYMS.items():
            if word in key or key in word:
                expanded.update(synonyms)
    
    return list(expanded)


def filter_news(news_items, keywords=None, exclude_keywords=None, source_filter=None, search_full_text=False, date_filter=None):
    """Фильтрует новости по ключевым словам с расширением синонимами."""
    filtered = news_items
    
    # Фильтр по источнику
    if source_filter:
        filtered = [n for n in filtered if n.get("source", "").lower() == source_filter.lower()]
    
    # Фильтр по дате
    if date_filter and date_filter != "all":
        now = datetime.now()
        cutoff_date = None
        
        if date_filter == "today":
            cutoff_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif date_filter == "week":
            cutoff_date = now - timedelta(days=7)
        elif date_filter == "month":
            cutoff_date = now - timedelta(days=30)
        
        if cutoff_date:
            filtered = [n for n in filtered if is_news_recent(n.get("date", ""), cutoff_date)]
    
    # Фильтр по ключевым словам
    if keywords:
        words = expand_keywords(keywords)
        if words:
            temp = []
            for news in filtered:
                title_lower = news["title"].lower()
                desc_lower = news["description"].lower()
                full_text_lower = news.get("full_text", "").lower() if search_full_text else ""
                
                # Поиск в заголовке и описании (всегда)
                combined = title_lower + " " + desc_lower
                if search_full_text and full_text_lower:
                    combined += " " + full_text_lower
                
                for word in words:
                    if word in combined:
                        temp.append(news)
                        break
            filtered = temp
    
    # Исключающие ключевые слова
    if exclude_keywords:
        exclude_words = [w.strip().lower() for w in re.split(r'[,\s]+', exclude_keywords) if w.strip()]
        filtered = [
            n for n in filtered
            if not any(w in (n["title"].lower() + " " + n["description"].lower()) for w in exclude_words)
        ]
            
    return filtered


def is_news_recent(date_str, cutoff_date):
    """Проверяет, является ли новость новее указанной даты."""
    if not date_str:
        return True
    
    # Пробуем разные форматы дат
    date_formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ]
    
    for fmt in date_formats:
        try:
            news_date = datetime.strptime(date_str.strip(), fmt)
            if news_date.tzinfo:
                news_date = news_date.replace(tzinfo=None)
            return news_date >= cutoff_date
        except ValueError:
            continue
    
    return True

# ============================================================
# СБОР ВСЕХ НОВОСТЕЙ
# ============================================================

def fetch_all_news(force=False):
    """Загружает новости из всех источников с кэшированием."""
    now = time.time()
    
    # Возвращаем кэш если валиден
    if not force and NEWS_CACHE["data"] and (now - NEWS_CACHE["timestamp"]) < CACHE_TTL:
        return NEWS_CACHE["data"]
    
    sources = load_sources()
    all_news = []
    
    for source in sources:
        items = parse_rss(source["url"])
        for item in items:
            item["source"] = source["name"]
            item["icon"] = source.get("icon", "📰")
        all_news.extend(items)
    
    # Сортируем по дате
    all_news.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    result = all_news[:MAX_NEWS]
    
    # Сохраняем в кэш
    NEWS_CACHE["data"] = result
    NEWS_CACHE["timestamp"] = now
    
    return result

# ============================================================
# МАРШРУТЫ
# ============================================================

@app.route("/")
def index():
    """Главная страница."""
    news = fetch_all_news()
    all_sources = sorted(set(item.get("source", "Неизвестно") for item in news))
    return render_template("index.html", news=news, all_sources=all_sources, SYNONYMS=SYNONYMS)


@app.route("/filter", methods=["POST"])
def filter_news_route():
    """Фильтрация новостей."""
    keywords = request.form.get("keywords", "").strip()
    exclude_keywords = request.form.get("exclude_keywords", "").strip()
    source_filter = request.form.get("source_filter", "").strip()
    search_full_text = request.form.get("search_full_text") == "on"
    date_filter = request.form.get("date_filter", "all")
    
    news = fetch_all_news()
    
    if keywords or exclude_keywords or source_filter or date_filter != "all":
        news = filter_news(news, keywords, exclude_keywords, source_filter, search_full_text, date_filter)
    
    # Получаем список всех источников для фильтра
    all_sources = sorted(set(item.get("source", "Неизвестно") for item in fetch_all_news()))
    
    return render_template("index.html", news=news, keywords=keywords, 
                          exclude_keywords=exclude_keywords, source_filter=source_filter,
                          search_full_text=search_full_text, all_sources=all_sources, 
                          date_filter=date_filter, SYNONYMS=SYNONYMS)


@app.route("/api/news", methods=["GET"])
def api_news():
    """API для получения новостей в JSON."""
    keywords = request.args.get("keywords", "").strip()
    exclude_keywords = request.args.get("exclude", "").strip()
    source_filter = request.args.get("source", "").strip()
    search_full_text = request.args.get("full_text") == "1"
    
    news = fetch_all_news()
    
    if keywords or exclude_keywords or source_filter:
        news = filter_news(news, keywords, exclude_keywords, source_filter, search_full_text)
    
    return jsonify({
        "count": len(news),
        "news": news,
    })


@app.route("/publish", methods=["POST"])
def publish_route():
    """Публикация выбранных новостей в VK — каждая новость как отдельный пост с полным текстом."""
    news_titles = request.form.getlist("news_item")
    
    if not news_titles:
        news = fetch_all_news()
        all_sources = sorted(set(item.get("source", "Неизвестно") for item in news))
        return render_template("index.html", news=news, publish_error="Не выбрано ни одной новости", all_sources=all_sources, SYNONYMS=SYNONYMS)
    
    published_count = 0
    errors = []
    
    for i, item_json in enumerate(news_titles):
        try:
            item = json.loads(item_json)
            title = item.get("title", "")
            full_text = item.get("full_text", "")
            link = item.get("link", "")
            source = item.get("source", "")
            
            # Формируем пост с полным текстом статьи
            post_text = title
            
            if full_text:
                post_text += f"\n\n{full_text}"
            
            if source:
                post_text += f"\n\nИсточник: {source}"
            
            # Ограничиваем длину поста (VK лимит ~ 50000 символов)
            if len(post_text) > 40000:
                post_text = post_text[:40000] + "..."
            
            result = publish_to_vk(post_text)
            
            if result is True:
                published_count += 1
            else:
                errors.append(f"Новость {i+1}: {result}")
            
            # Задержка между публикациями
            import time
            time.sleep(0.5)
            
        except Exception as e:
            errors.append(f"Новость {i+1}: {str(e)}")
    
    news = fetch_all_news()
    all_sources = sorted(set(item.get("source", "Неизвестно") for item in news))
    
    if published_count > 0:
        success_msg = f"Опубликовано новостей: {published_count}"
        if errors:
            success_msg += f". Ошибки: {'; '.join(errors[:3])}"
        return render_template("index.html", news=news, publish_success=success_msg, all_sources=all_sources, SYNONYMS=SYNONYMS)
    else:
        error_msg = "Не удалось опубликовать новости"
        if errors:
            error_msg += f". Ошибки: {'; '.join(errors[:3])}"
        return render_template("index.html", news=news, publish_error=error_msg, all_sources=all_sources, SYNONYMS=SYNONYMS)


@app.route("/proxy")
def proxy_page():
    """
    Прокси для загрузки страницы новости через наш сервер.
    Позволяет обойти ограничения X-Frame-Options для iframe.
    """
    url = request.args.get("url", "")
    
    if not url:
        return '{"error": "No URL provided"}', 400
    
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read()
            content_type = response.headers.get("Content-Type", "text/html")
        
        # Декодируем контент
        html_text = decode_xml_data(content, content_type)
        
        # Удаляем скрипты, которые могут блокировать отображение в iframe
        html_text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL)
        
        return html_text, 200, {"Content-Type": content_type}
        
    except Exception as e:
        return f'<html><body style="color:#fff;background:#1a2634;font-family:sans-serif;padding:40px;"><h2>Не удалось загрузить страницу</h2><p>{str(e)}</p><a href="{url}" target="_blank" style="color:#4a9eff;">Открыть на сайте-источнике</a></body></html>', 200, {"Content-Type": "text/html; charset=utf-8"}


if __name__ == "__main__":
    app.run(debug=True, port=5001)
