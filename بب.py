import asyncio
import aiohttp
import time
import random
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from googlesearch import search
import csv
import json
import logging

# === LOGGING CONFIG ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# === TELEGRAM CONFIG ===
TOKEN = '7925209531:AAF5e1jxZiGZB7bKyvLWxIdziGfjAR86blM'  # Replace with your bot token
CHAT_ID = '1296559148'  # Replace with your chat ID

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
DEFAULT_CONFIG = {
    "min_braintree_hits": 4,
    "request_timeout": 15,
    "retry_attempts": 3,
    "retry_delay": 5,
    "concurrent_requests": 5,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "enable_proxy": False,
    "proxies": [],  # Format: ["http://user:pass@host:port", "socks5://host:port"]
    "payment_link_keywords": ['checkout', 'payment', 'cart', 'shop', 'billing', 'purchase', 'order', 'pay', 'product'],
    "automatic_dorks": [
        'inurl:checkout braintree',
        'inurl:payment braintree',
        'site:.com powered by braintree',
        'site:.net powered by braintree',
        'site:.org powered by braintree'
    ],
    "number_of_sites_per_dork": 20  # عدد المواقع التي سيتم فحصها لكل Dork تلقائي
}

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
            # Set default values for missing keys
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

async def get_proxy():
    if ENABLE_PROXY and proxy_pool:
        return random.choice(proxy_pool)
    return None

# === CLEAN AND MINIMAL DISPLAY ===
def print_block(url, hits, pages, status, details=None):
    print(f"{Color.MAGENTA}{'═'*70}{Color.RESET}")
    print(f"{Color.CYAN}🌍 URL: {url}{Color.RESET}")
    print(f"{Color.BLUE}🧾 Pages Checked: {pages}{Color.RESET}")
    print(f"{Color.YELLOW}⚙️ Braintree Signals: {hits}/12 (Threshold: {MIN_BRAINTREE_HITS}){Color.RESET}")
    if details:
        print(f"{Color.YELLOW}🔍 Details: {', '.join(details)}{Color.RESET}")
    if status == 'FOUND':
        print(f"{Color.GREEN}✅ Status: Braintree Likely Present{Color.RESET}")
    else:
        print(f"{Color.RED}❌ Status: Not Detected{Color.RESET}")
    print(f"{Color.MAGENTA}{'═'*70}{Color.RESET}")

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
    try:
        async with session.get(url, timeout=timeout, proxy=proxy, headers={'User-Agent': USER_AGENT}, ssl=False, allow_redirects=True) as response:
            if response.status == 200:
                return await response.text()
            else:
                logging.warning(f"Error fetching {url}: {response.status}")
                return None
    except aiohttp.ClientConnectionError as e:
        logging.error(f"Client connection error fetching {url}: {e}")
        return None
    except asyncio.TimeoutError:
        logging.warning(f"Timeout fetching {url}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error fetching {url}: {e}")
        return None

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

def check_braintree(text):
    checks = {
        "braintree_keyword": lambda t: 'braintree' in t,
        "client_token": lambda t: 'client-token' in t and 'braintree' in t,
        "braintree_api": lambda t: 'braintree-api' in t,
        "braintreegateway_domain": lambda t: 'braintreegateway.com' in t,
        "dropin_create": lambda t: 'dropin.create' in t,
        "sandbox_auth": lambda t: 'authorization:' in t and 'sandbox_' in t,
        "data_braintree_attr": lambda t: 'data-braintree' in t,
        "braintree_client_obj": lambda t: 'braintree.client' in t,
        "hostedfields_create": lambda t: 'hostedfields.create' in t,
        "transaction_id_pattern": lambda t: re.search(r'bt[0-9a-z]{24,}', t),
        "braintree_sdk_path": lambda t: re.search(r'js\/client\/\d+_\d+\/\w+\.js', t),
        "braintree_form_selector": lambda t: re.search(r'\.braintree-form', t)
    }
    hits = 0
    found_details = []
    for key, check in checks.items():
        if check(text.lower()):
            hits += 1
            found_details.append(key)
    return hits, found_details

async def download_js(session, js_urls):
    js_data = ''
    tasks = [fetch(session, url) for url in js_urls if is_valid_url(url)]
    results = await asyncio.gather(*tasks)
    for res in results:
        if res:
            js_data += res + "\n"
    return js_data

async def analyze_site(url, session):
    if not url.startswith('http'):
        url = 'http://' + url
    if not is_valid_url(url):
        logging.warning(f"Invalid URL: {url}")
        await log_results(url, 0, 0, 'ERROR', 'Invalid URL')
        return
    try:
        html = await fetch(session, url, timeout=3)
        if html:
            full_text = html
            payment_pages = extract_payment_links(html, url)
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

            hits, details = check_braintree(full_text)
            status = 'FOUND' if hits >= MIN_BRAINTREE_HITS else 'NOT_FOUND'
            print_block(url, hits, pages_checked, status, details)
            await log_results(url, pages_checked, hits, status, details)

            if status == 'FOUND':
                await send_message(CHAT_ID, f"✅ تم الكشف عن Braintree:\nURL: {url}\nHits: {hits}/{len(check_braintree('test')[1])}\nDetails: {', '.join(details)}")

    except Exception as e:
        logging.error(f"Error analyzing site {url}: {e}")
        await log_results(url, 0, 0, 'ERROR', f'Error: {e}')

async def process_payment_page(session, page, base_url):
    p_html = await fetch(session, page)
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

async def automatic_scan(session):
    print(f"{Color.CYAN}🛠️ Starting automatic scan using predefined Dorks...{Color.RESET}")
    # Initialize CSV log file if it doesn't exist or append if it does
    try:
        with open('braintree_results.csv', 'x', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            await asyncio.to_thread(writer.writerow, ['URL', 'Pages Checked', 'Braintree Signals', 'Status', 'Details'])
    except FileExistsError:
        pass  # File already exists, will append

    all_found_urls = set()
    for dork in AUTOMATIC_DORKS:
        print(f"{Color.YELLOW}🔍 Searching Google for: {dork}{Color.RESET}")
        try:
            urls = await google_dork_search(dork, limit=NUMBER_OF_SITES_PER_DORK)
            valid_new_urls = [url for url in urls if url not in all_found_urls]
            if valid_new_urls:
                print(f"{Color.GREEN}✅ Found {len(valid_new_urls)} new URLs for dork: {dork}{Color.RESET}")
                for index, url in enumerate(valid_new_urls, start=1):
                    print(f"{Color.MAGENTA}🔢 Scanning site {index}/{len(valid_new_urls)} for dork '{dork}'...{Color.RESET}")
                    await analyze_site(url, session)
                    delay = random.randint(config['retry_delay'], config['retry_delay'] + 2)
                    print(f"{Color.YELLOW}⏳ Waiting {delay}s before next...{Color.RESET}\n")
                    await asyncio.sleep(delay)
                    all_found_urls.add(url)
            else:
                print(f"{Color.YELLOW}⚠️ No new URLs found for dork: {dork}{Color.RESET}")
        except Exception as e:
            logging.error(f"Error during automatic scan with dork '{dork}': {e}")
        print(f"{Color.MAGENTA}{'='*50}{Color.RESET}")

    print(f"{Color.GREEN}🎯 Finished automatic scan. Results saved to braintree_results.csv{Color.RESET}")

async def main():
    print(f"{Color.CYAN}🛠️ Braintree Detector Script v2.1 (Async - Automatic){Color.RESET}")
    automatic = input(f"{Color.BLUE}⚙️ Run in automatic mode using predefined Dorks? (yes/no): {Color.RESET}").lower()
    async with aiohttp.ClientSession() as session:
        if automatic == 'yes':
            await automatic_scan(session)
        else:
            dork = input(f"{Color.CYAN}🔎 Enter Google Dork: {Color.RESET}")
            try:
                limit = int(input(f"{Color.BLUE}📌 How many sites to scan? (e.g., 10, 20): {Color.RESET}"))
            except ValueError:
                limit = 10
                print(f"{Color.YELLOW}⚠️ Invalid limit. Using default: {limit}{Color.RESET}")

            # Initialize CSV log file
            try:
                with open('braintree_results.csv', 'x', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    await asyncio.to_thread(writer.writerow, ['URL', 'Pages Checked', 'Braintree Signals', 'Status', 'Details'])
            except FileExistsError:
                pass  # File already exists, will append

            urls = await google_dork_search(dork, limit=limit)

            if not urls:
                print(f"{Color.RED}❌ No valid results found or Google blocked search.{Color.RESET}")
                return

            print(f"{Color.GREEN}✅ {len(urls)} valid URLs loaded for scanning.{Color.RESET}\n")

            for index, url in enumerate(urls, start=1):
                print(f"{Color.MAGENTA}🔢 Scanning site {index}/{len(urls)}...{Color.RESET}")
                
                await analyze_site(url, session)
                delay = random.randint(config['retry_delay'], config['retry_delay'] + 2)
                print(f"{Color.YELLOW}⏳ Waiting {delay}s before next...{Color.RESET}\n")
                await asyncio.sleep(delay)

            print(f"{Color.GREEN}🎯 Finished scanning {len(urls)} sites. Results saved to braintree_results.csv{Color.RESET}")

if __name__ == '__main__':
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    asyncio.run(main())