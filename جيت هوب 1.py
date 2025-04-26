import asyncio
import aiohttp
import random
import re
import csv
import json
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from googlesearch import search
from transformers import GPT2LMHeadModel, GPT2Tokenizer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import train_test_split
from sklearn import metrics
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

# === LOGGING CONFIG ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === TELEGRAM CONFIG ===
TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
CHAT_ID = 'YOUR_CHAT_ID'

# === ANSI COLORS ===
class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

# === CONFIGURATIONS ===
CONFIG_FILE = 'config.json'
AI_MEMORY_FILE = 'ai_memory.json'
DEFAULT_CONFIG = {
    "min_braintree_hits": 4,
    "request_timeout": 15,
    "retry_attempts": 3,
    "retry_delay": 5,
    "concurrent_requests": 5,
    "user_agent": "Mozilla/5.0 (Linux; Android 10; Pixel 3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.101 Mobile Safari/537.36",
    "enable_proxy": False,
    "proxies": [],
    "payment_link_keywords": ['checkout', 'payment', 'cart', 'shop', 'billing', 'purchase', 'order', 'pay', 'product'],
    "automatic_dorks": [
        '/soap inurl:"/catalog/product/view/id/" -inurl:products -inurl:collections',
        '"shop" + "Women" + "Kids" + "Men\'s" + "My cart"',
        '"cheap children\'s clothing" OR "discount kids apparel" "Braintree credit card processing" seasonal discounts -site:stripe.com -site:paypal.com -site:shopify.com'
    ],
    "number_of_sites_per_dork": 20
}

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            for key in DEFAULT_CONFIG:
                config.setdefault(key, DEFAULT_CONFIG[key])
            return config
    except FileNotFoundError:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    except json.JSONDecodeError:
        print(f"{Color.RED}⚠️ Error decoding config.json. Using default configuration.{Color.RESET}")
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG

config = load_config()
MIN_BRAINTREE_HITS = config['min_braintree_hits']
REQUEST_TIMEOUT = config['request_timeout']
RETRY_ATTEMPTS = config['retry_attempts']
RETRY_DELAY = config['retry_delay']
CONCURRENT_REQUESTS = config['concurrent_requests']
USER_AGENT = config['user_agent']
ENABLE_PROXY = config['enable_proxy']
PROXIES = config['proxies']
proxy_pool = PROXIES[:]
PAYMENT_LINK_KEYWORDS = config['payment_link_keywords']
AUTOMATIC_DORKS = config['automatic_dorks']
NUMBER_OF_SITES_PER_DORK = config['number_of_sites_per_dork']

# AI Memory
def load_ai_memory():
    try:
        with open(AI_MEMORY_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "successful_dorks": [],
            "bad_domains": [],
            "best_user_agents": [],
            "proxy_scores": {}
        }

ai_memory = load_ai_memory()

# إعداد نموذج GPT-2 لتوليد Dorks
tokenizer = GPT2Tokenizer.from_pretrained('gpt2')
model = GPT2LMHeadModel.from_pretrained('gpt2')

# نموذج لتوليد Dorks
def generate_dork(prompt, max_length=50):
    """توليد Dork باستخدام GPT-2."""
    inputs = tokenizer.encode(prompt, return_tensors='pt')
    outputs = model.generate(inputs, max_length=max_length, num_return_sequences=1)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

async def get_proxy():
    if ENABLE_PROXY and proxy_pool:
        return random.choice(proxy_pool)
    return None

# === CLEAN AND MINIMAL DISPLAY ===
def print_enhanced_message(url, hits, pages_checked, status, details=None):
    status_icon = "✅" if status == "FOUND" else "❌"
    details_str = ', '.join(details) if details else "لا توجد تفاصيل"
    
    print(f"{Color.MAGENTA}╔════════════════════════════════════╗{Color.RESET}")
    print(f"{Color.CYAN}🌐 URL: {url}{Color.RESET}")
    print(f"{Color.BLUE}📄 Pages Checked: {pages_checked}{Color.RESET}")
    print(f"{Color.YELLOW}⚙️ Braintree Signals: {hits}/{MIN_BRAINTREE_HITS}{Color.RESET}")
    print(f"{Color.YELLOW}🔍 Details: {details_str}{Color.RESET}")
    print(f"{Color.GREEN}{status_icon} Status: {status}{Color.RESET}")
    print(f"{Color.MAGENTA}╚════════════════════════════════════╝{Color.RESET}")

async def log_results(url, pages, hits, status, details=None):
    with open('braintree_results.csv', 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        await asyncio.to_thread(writer.writerow, [url, pages, hits, status, details if details else ''])

async def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, params={'chat_id': chat_id, 'text': text}, timeout=5)
    except Exception as e:
        logging.error(f"Telegram Error: {e}")

async def fetch(session, url, timeout=REQUEST_TIMEOUT):
    proxy = await get_proxy()
    attempts = 0
    while attempts < RETRY_ATTEMPTS:  # عدد المحاولات
        try:
            async with session.get(url, timeout=timeout, proxy=proxy, headers={'User-Agent': USER_AGENT}, ssl=False, allow_redirects=True) as response:
                if response.status == 200:
                    return await response.text(), response.status
                else:
                    logging.warning(f"Error fetching {url}: {response.status}")
                    return None, response.status
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
            attempts += 1
            logging.error(f"Error fetching {url}, attempt {attempts}: {e}")
            await asyncio.sleep(RETRY_DELAY)  # الانتظار قبل المحاولة مرة أخرى
        except Exception as e:
            logging.error(f"Unexpected error fetching {url}: {e}")
            return None, None
    return None, None  # إذا فشلت جميع المحاولات

def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def extract_payment_links(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    return list(set(
        urljoin(base_url, a['href']) for a in soup.find_all('a', href=True)
        if a.get('href') and any(k in a['href'].lower() for k in PAYMENT_LINK_KEYWORDS)
    ))

def extract_js(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    return list(set(
        urljoin(base_url, script['src']) for script in soup.find_all('script', src=True)
        if script.get('src')
    ))

def extract_inline_scripts(html):
    soup = BeautifulSoup(html, 'html.parser')
    return "\n".join([s.text for s in soup.find_all('script') if s.string])

def extract_forms(html):
    soup = BeautifulSoup(html, 'html.parser')
    return "".join(str(i) for i in soup.find_all(['form', 'input']))

async def check_braintree(text):
    checks = {
        "braintree_keyword": lambda t: 'braintree' in t,
        "client_token": lambda t: 'client-token' in t and 'braintree' in t,
        "braintree_api": lambda t: 'api.braintreegateway.com' in t,
        "dropin_create": lambda t: 'dropin.create' in t,
        "payment_method_nonce": lambda t: 'payment_method_nonce' in t,
        "sandbox_auth": lambda t: 'sandbox_' in t and 'authorization:' in t,
        "data_braintree_attr": lambda t: 'data-braintree' in t,
        "braintree_client_obj": lambda t: 'braintree.client' in t,
        "hostedfields_create": lambda t: 'hostedfields.create' in t,
        "iframe_braintree": lambda t: '<iframe' in t and 'braintree' in t,
        "transaction_id_pattern": lambda t: re.search(r'bt[0-9a-z]{24,}', t)
    }
    hits = 0
    found_details = []
    for key, check in checks.items():
        if check(text.lower()):
            hits += 1
            found_details.append(key)
    return hits, found_details

async def additional_checks(url, session):
    """إجراء فحوصات إضافية على الموقع لتأكيد دعم Braintree."""
    additional_checks = [
        lambda html: 'paypal' in html.lower(),  # تحقق من PayPal
        lambda html: 'braintreegateway.com' in html.lower(),  # تحقق من المجال
    ]
    
    html, _ = await fetch(session, url)
    for check in additional_checks:
        if check(html):
            return True
    return False

async def dynamic_analysis(url):
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    driver.get(url)
    html = driver.page_source
    driver.quit()
    return html

async def download_js(session, js_urls):
    js_data = ''
    tasks = [fetch(session, url) for url in js_urls if is_valid_url(url)]
    results = await asyncio.gather(*tasks)
    for res, _ in results:
        if res:
            js_data += res + "\n"
    return js_data

async def analyze_site(url, session, feedback_data):
    if not url.startswith('http'):
        url = 'http://' + url
    if not is_valid_url(url):
        logging.warning(f"Invalid URL: {url}")
        await log_results(url, 0, 0, 'ERROR', 'Invalid URL')
        return
    try:
        html, status = await fetch(session, url, timeout=3)
        if html:
            # استخدم Selenium لتحليل الصفحة
            dynamic_html = await dynamic_analysis(url)
            full_text = dynamic_html
            payment_pages = extract_payment_links(dynamic_html, url)
            pages_checked = 1

            payment_tasks = []
            for page in payment_pages:
                if is_valid_url(page):
                    payment_tasks.append(process_payment_page(session, page, url))

            payment_results = await asyncio.gather(*payment_tasks)
            for p_html, js_urls in payment_results:
                if p_html:
                    pages_checked += 1
                    full_text += extract_inline_scripts(p_html)
                    full_text += extract_forms(p_html)
                    full_text += await download_js(session, js_urls)

            hits, details = await check_braintree(full_text)
            status = 'FOUND' if hits >= MIN_BRAINTREE_HITS else 'NOT_FOUND'
            print_enhanced_message(url, hits, pages_checked, status, details)

            # إجراء فحوصات إضافية إذا تم العثور على إشارات
            if hits > 0:
                if await additional_checks(url, session):
                    await send_message(CHAT_ID, f"✅ تم الكشف عن Braintree:\nURL: {url}\nHits: {hits}/{len(check_braintree('test')[1])}\nDetails: {', '.join(details)}")
                    feedback_data.append((url, True))  # إضافة بيانات التغذية الراجعة على أنها ناجحة
                else:
                    feedback_data.append((url, False))  # إضافة بيانات التغذية الراجعة على أنها غير ناجحة

    except Exception as e:
        logging.error(f"Error analyzing site {url}: {e}")
        await log_results(url, 0, 0, 'ERROR', f'Error: {e}')

async def process_payment_page(session, page, base_url):
    p_html, _ = await fetch(session, page)
    js_urls = []
    if p_html:
        js_urls = extract_js(p_html, page)
    return p_html, js_urls

async def google_dork_search(dork, limit=100):
    print(f"{Color.BOLD}{Color.YELLOW}🔍 Searching Google for: {dork}{Color.RESET}")
    results = []
    try:
        for result in search(dork, num_results=limit):
            if is_valid_url(result) and result not in results:
                results.append(result)
    except Exception as e:
        logging.error(f"Google Search error: {e}")
    return results

async def check_ip_ban():
    # منطق للتحقق مما إذا كان IP محظورًا
    # يمكن استخدام دالة fetch للتأكد من الردود
    test_url = "http://www.google.com"
    response, _ = await fetch(session, test_url)
    if response is None:
        return True
    return False

async def automatic_scan(session, feedback_data):
    print(f"{Color.CYAN}🛠️ Starting automatic scan using predefined Dorks...{Color.RESET}")
    # Initialize CSV log file if it doesn't exist or append if it does
    try:
        with open('braintree_results.csv', 'x', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            await asyncio.to_thread(writer.writerow, ['URL', 'Pages Checked', 'Braintree Signals', 'Status', 'Details'])
    except FileExistsError:
        pass  # File already exists, will append

    all_found_urls = set()
    while True:
        for dork in AUTOMATIC_DORKS:
            print(f"{Color.YELLOW}🔍 Searching Google for: {dork}{Color.RESET}")
            try:
                urls = await google_dork_search(dork, limit=NUMBER_OF_SITES_PER_DORK)
                valid_new_urls = [url for url in urls if url not in all_found_urls]
                if valid_new_urls:
                    print(f"{Color.GREEN}✅ Found {len(valid_new_urls)} new URLs for dork: {dork}{Color.RESET}")
                    for index, url in enumerate(valid_new_urls, start=1):
                        print(f"{Color.MAGENTA}🔢 Scanning site {index}/{len(valid_new_urls)} for dork '{dork}'...{Color.RESET}")
                        await analyze_site(url, session, feedback_data)
                        delay = random.randint(10, 20)  # تأخير عشوائي بين 10 إلى 20 ثانية
                        print(f"{Color.YELLOW}⏳ Waiting {delay}s before next...{Color.RESET}\n")
                        await asyncio.sleep(delay)
                        all_found_urls.add(url)
                else:
                    print(f"{Color.YELLOW}⚠️ No new URLs found for dork: {dork}{Color.RESET}")

            except Exception as e:
                logging.error(f"Error during automatic scan with dork '{dork}': {e}")

            # تحقق من إذا كان IP محظورًا
            if await check_ip_ban():
                await send_message(CHAT_ID, "❌ IP محظور. سيتم الانتظار لمدة دقيقة قبل المحاولة مرة أخرى.")
                await asyncio.sleep(60)  # الانتظار لمدة دقيقة
                continue

            print(f"{Color.MAGENTA}{'='*50}{Color.RESET}")

async def train_model(feedback_data):
    """تدريب نموذج تصنيف باستخدام بيانات التغذية الراجعة."""
    if feedback_data:
        # إعداد البيانات
        texts, labels = zip(*feedback_data)

        # تقسيم البيانات إلى مجموعة تدريب واختبار
        X_train, X_test, y_train, y_test = train_test_split(texts, labels, test_size=0.2, random_state=42)

        # إنشاء نموذج باستخدام CountVectorizer و Naive Bayes
        model = make_pipeline(CountVectorizer(), MultinomialNB())
        model.fit(X_train, y_train)

        # تقييم النموذج
        predictions = model.predict(X_test)
        print("Model Accuracy:", metrics.accuracy_score(y_test, predictions))

        # توليد Dorks جديدة
        for _ in range(3):  # توليد 3 Dorks جديدة
            dork = generate_dork("Generate a strong Dork based on Braintree")
            print(f"Generated Dork: {dork}")

async def main():
    print(f"{Color.CYAN}🛠️ Braintree Detector Script v2.1 (Async - Automatic){Color.RESET}")
    
    async with aiohttp.ClientSession() as session:
        feedback_data = []  # لتخزين بيانات التغذية الراجعة
        await automatic_scan(session, feedback_data)  # بدء الفحص التلقائي

if __name__ == '__main__':
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    asyncio.run(main())