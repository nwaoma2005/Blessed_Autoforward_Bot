import os
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
import requests
from functools import wraps
from flask import Flask, request, jsonify
import threading
import asyncio

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Should be like: https://yourapp.onrender.com
PORT = int(os.getenv("PORT", 10000))

PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")

# Admin user IDs - ADD YOUR TELEGRAM USER ID HERE
ADMIN_IDS = [8177057340]  # Replace with your actual Telegram user ID

MONTHLY_PRICE = 300000  # N3,000 in kobo
DAILY_PRICE = 20000      # N200 in kobo
PLAN_NAME_MONTHLY = "Premium Monthly"
PLAN_NAME_DAILY = "Premium Daily"

RATE_LIMIT_WINDOW = 60
MAX_COMMANDS_PER_WINDOW = 10

SOURCE_CHAT, DEST_CHAT = range(2)

DATA_DIR = "data"
USERS_FILE = f"{DATA_DIR}/users.json"
RULES_FILE = f"{DATA_DIR}/rules.json"
TRANSACTIONS_FILE = f"{DATA_DIR}/transactions.json"

users_data = {}
rules_data = {}
transactions_data = {}
data_lock = threading.Lock()

# Global bot application reference
bot_app = None

# Flask app for Paystack webhook
flask_app = Flask(__name__)

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        logger.info("Data directory created")

def save_data():
    try:
        with data_lock:
            ensure_data_dir()
            
            with open(USERS_FILE, 'w') as f:
                users_serializable = {}
                for uid, user in users_data.items():
                    users_serializable[uid] = {
                        **user,
                        'subscription_end': user['subscription_end'].isoformat() if user.get('subscription_end') else None,
                        'last_reset': user['last_reset'].isoformat() if user.get('last_reset') else None,
                        'last_command_time': user['last_command_time'].isoformat() if user.get('last_command_time') else None,
                        'created_at': user['created_at'].isoformat() if user.get('created_at') else None
                    }
                json.dump(users_serializable, f, indent=2)
            
            with open(RULES_FILE, 'w') as f:
                rules_serializable = {}
                for rid, rule in rules_data.items():
                    rules_serializable[rid] = {
                        **rule,
                        'created_at': rule['created_at'].isoformat() if rule.get('created_at') else None
                    }
                json.dump(rules_serializable, f, indent=2)
            
            with open(TRANSACTIONS_FILE, 'w') as f:
                trans_serializable = {}
                for tid, trans in transactions_data.items():
                    trans_serializable[tid] = {
                        **trans,
                        'created_at': trans['created_at'].isoformat() if trans.get('created_at') else None,
                        'payment_date': trans['payment_date'].isoformat() if trans.get('payment_date') else None
                    }
                json.dump(trans_serializable, f, indent=2)
            
            logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_data():
    global users_data, rules_data, transactions_data
    
    try:
        with data_lock:
            ensure_data_dir()
            
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, 'r') as f:
                    loaded_users = json.load(f)
                    for uid, user in loaded_users.items():
                        users_data[uid] = {
                            **user,
                            'subscription_end': datetime.fromisoformat(user['subscription_end']) if user.get('subscription_end') else None,
                            'last_reset': datetime.fromisoformat(user['last_reset']) if user.get('last_reset') else None,
                            'last_command_time': datetime.fromisoformat(user['last_command_time']) if user.get('last_command_time') else None,
                            'created_at': datetime.fromisoformat(user['created_at']) if user.get('created_at') else None
                        }
            
            if os.path.exists(RULES_FILE):
                with open(RULES_FILE, 'r') as f:
                    loaded_rules = json.load(f)
                    for rid, rule in loaded_rules.items():
                        rules_data[rid] = {
                            **rule,
                            'created_at': datetime.fromisoformat(rule['created_at']) if rule.get('created_at') else None
                        }
            
            if os.path.exists(TRANSACTIONS_FILE):
                with open(TRANSACTIONS_FILE, 'r') as f:
                    loaded_trans = json.load(f)
                    for tid, trans in loaded_trans.items():
                        transactions_data[tid] = {
                            **trans,
                            'created_at': datetime.fromisoformat(trans['created_at']) if trans.get('created_at') else None,
                            'payment_date': datetime.fromisoformat(trans['payment_date']) if trans.get('payment_date') else None
                        }
            
            logger.info(f"Loaded: {len(users_data)} users, {len(rules_data)} rules, {len(transactions_data)} transactions")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

# Paystack Webhook endpoint
@flask_app.route('/paystack/webhook', methods=['POST'])
def paystack_webhook():
    try:
        payload = request.get_json()
        
        if payload['event'] == 'charge.success':
            reference = payload['data']['reference']
            
            with data_lock:
                if reference in transactions_data:
                    transaction = transactions_data[reference]
                    user_id = transaction['user_id']
                    plan_type = transaction['plan_type']
                    
                    # Activate premium
                    activate_premium(user_id, plan_type)
                    
                    # Update transaction
                    transaction['status'] = 'success'
                    transaction['payment_date'] = datetime.now()
                    save_data()
                    
                    logger.info(f"Payment successful for user {user_id}, plan: {plan_type}")
                    
                    # Send notification to user
                    if bot_app:
                        try:
                            duration = "30 days" if plan_type == 'monthly' else "24 hours"
                            asyncio.run_coroutine_threadsafe(
                                bot_app.bot.send_message(
                                    chat_id=int(user_id),
                                    text=f"🎉 Payment Successful!\n\n"
                                         f"✨ You're now Premium for {duration}!\n"
                                         f"💫 Enjoy unlimited forwarding!\n\n"
                                         f"Use /add_forward to create rules!"
                                ),
                                bot_app.application.loop
                            )
                        except Exception as e:
                            logger.error(f"Failed to send notification: {e}")
        
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@flask_app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'users': len(users_data),
        'rules': len(rules_data),
        'bot_running': bot_app is not None
    }), 200

def rate_limit(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        
        with data_lock:
            if user_id in users_data:
                user = users_data[user_id]
                current_time = datetime.now()
                
                last_time = user.get('last_command_time')
                if last_time and (current_time - last_time).seconds < RATE_LIMIT_WINDOW:
                    count = user.get('command_count', 0)
                    if count >= MAX_COMMANDS_PER_WINDOW:
                        await update.message.reply_text("⚠️ Slow down! Too many requests.")
                        return
                    user['command_count'] = count + 1
                else:
                    user['last_command_time'] = current_time
                    user['command_count'] = 1
        
        return await func(update, context)
    return wrapper

def get_or_create_user(user_id, username):
    user_id = str(user_id)
    
    with data_lock:
        if user_id not in users_data:
            users_data[user_id] = {
                'user_id': user_id,
                'username': username,
                'is_premium': False,
                'subscription_end': None,
                'daily_messages': 0,
                'last_reset': datetime.now(),
                'last_command_time': datetime.now(),
                'command_count': 0,
                'created_at': datetime.now()
            }
            save_data()
            logger.info(f"New user: {username} ({user_id})")
        
        return users_data[user_id].copy()

def reset_daily_limit(user_id):
    user_id = str(user_id)
    with data_lock:
        if user_id in users_data:
            users_data[user_id]['daily_messages'] = 0
            users_data[user_id]['last_reset'] = datetime.now()
            save_data()

def check_message_limit(user_id):
    user_id = str(user_id)
    
    with data_lock:
        if user_id not in users_data:
            return False
        
        user = users_data[user_id]
        
        if user['last_reset'] and (datetime.now() - user['last_reset']).days >= 1:
            user['daily_messages'] = 0
            user['last_reset'] = datetime.now()
        
        if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
            return True
        
        if user['daily_messages'] >= 50:
            return False
        
        user['daily_messages'] += 1
        save_data()
        return True

def generate_payment_link(user_id, plan_type='monthly'):
    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    if plan_type == 'daily':
        amount = DAILY_PRICE
        plan_name = PLAN_NAME_DAILY
        prefix = "DAILY"
    else:
        amount = MONTHLY_PRICE
        plan_name = PLAN_NAME_MONTHLY
        prefix = "MONTHLY"
    
    reference = f"{prefix}_{user_id}_{int(datetime.now().timestamp())}"
    
    # Generate a default email (Paystack requires email)
    email = f"user{user_id}@autoforward.bot"
    
    data = {
        "email": email,
        "amount": amount,
        "reference": reference,
        "callback_url": f"{WEBHOOK_URL}/payment/callback",
        "metadata": {
            "user_id": str(user_id),
            "plan": plan_name,
            "plan_type": plan_type
        },
        "channels": ["card", "bank", "ussd", "qr", "mobile_money", "bank_transfer"]
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            
            with data_lock:
                transactions_data[reference] = {
                    'user_id': str(user_id),
                    'reference': reference,
                    'amount': amount,
                    'plan_type': plan_type,
                    'status': 'pending',
                    'created_at': datetime.now(),
                    'payment_date': None
                }
                save_data()
            
            return result['data']['authorization_url'], reference, amount
    except Exception as e:
        logger.error(f"Payment link error: {e}")
    
    return None, None, None

def verify_payment(reference):
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result['data']['status'] == 'success':
                return True, result['data']['metadata']['user_id']
    except Exception as e:
        logger.error(f"Payment verification error: {e}")
    
    return False, None

def activate_premium(user_id, plan_type='monthly'):
    user_id = str(user_id)
    
    with data_lock:
        if user_id in users_data:
            if plan_type == 'daily':
                subscription_end = datetime.now() + timedelta(days=1)
            else:
                subscription_end = datetime.now() + timedelta(days=30)
                
            users_data[user_id]['is_premium'] = True
            users_data[user_id]['subscription_end'] = subscription_end
            save_data()
            logger.info(f"Premium {plan_type} activated for user {user_id}")

def get_active_rules_by_source(source_chat_id):
    with data_lock:
        active_rules = []
        for rule_id, rule in rules_data.items():
            if rule['source_chat_id'] == source_chat_id and rule['is_active']:
                active_rules.append(rule.copy())
        return active_rules

def get_user_rules(user_id):
    user_id = str(user_id)
    with data_lock:
        user_rules = []
        for rule_id, rule in rules_data.items():
            if rule['user_id'] == user_id and rule['is_active']:
                user_rules.append({**rule, 'rule_id': rule_id})
        return user_rules

@rate_limit
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    premium_status = "✨ Premium" if user['is_premium'] else "🆓 Free"
    
    welcome_text = (
        "🚀 *Welcome to Auto Forwarder Bot!*\n\n"
        "📋 *How it works:*\n"
        "1️⃣ Add me as admin to source channel\n"
        "2️⃣ Add me as admin to destination channel\n"
        "3️⃣ Use /add\\_forward to create rule\n"
        "4️⃣ Messages auto\\-forward automatically\\!\n\n"
        f"*Your Plan:* {premium_status}\n"
        f"*Today's Messages:* {user['daily_messages']}/50\n\n"
        "💎 *Premium Plans:*\n"
        "• Monthly: ₦3,000 \\(30 days\\)\n"
        "• Daily: ₦200 \\(24 hours\\)\n"
        "• Unlimited rules \\& messages\\!"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Forward Rule", callback_data="add_forward")],
        [InlineKeyboardButton("📋 My Forwards", callback_data="my_forwards")],
        [
            InlineKeyboardButton("💎 Monthly (₦3,000)", callback_data="pay_monthly"),
            InlineKeyboardButton("⚡ Daily (₦200)", callback_data="pay_daily")
        ],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("❓ Help", callback_data="help")]
    ])
    
    await update.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode='MarkdownV2')

@rate_limit
async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
        remaining = (user['subscription_end'] - datetime.now()).days
        await update.message.reply_text(
            f"✨ You're already Premium!\n\n"
            f"📅 {remaining} days remaining\n"
            f"💫 Enjoying unlimited forwarding!"
        )
        return
    
    subscribe_text = (
        "💎 *Premium Plans*\n\n"
        "*Monthly Plan \\- ₦3,000*\n"
        "✅ 30 days premium access\n"
        "✅ Unlimited forwarding rules\n"
        "✅ Unlimited messages\n"
        "✅ Priority support\n\n"
        "*Daily Plan \\- ₦200*\n"
        "✅ 24 hours premium access\n"
        "✅ Unlimited forwarding\n"
        "✅ Perfect for testing\n\n"
        "👇 *Click a button below to pay:*"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Monthly (₦3,000)", callback_data="pay_monthly")],
        [InlineKeyboardButton("💳 Pay Daily (₦200)", callback_data="pay_daily")],
        [InlineKeyboardButton("🔙 Back", callback_data="start")]
    ])
    
    await update.message.reply_text(subscribe_text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def handle_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_type: str):
    query = update.callback_query
    await query.answer("🔄 Generating payment link...")
    
    user_id = query.from_user.id
    
    payment_url, reference, amount = generate_payment_link(user_id, plan_type)
    
    if payment_url:
        amount_naira = amount / 100
        plan_text = "Monthly" if plan_type == 'monthly' else "Daily"
        duration = "30 days" if plan_type == 'monthly' else "24 hours"
        
        payment_text = (
            f"💳 *Payment Link Generated\\!*\n\n"
            f"📦 *Plan:* {plan_text}\n"
            f"💰 *Amount:* ₦{amount_naira:,.0f}\n"
            f"⏰ *Duration:* {duration}\n"
            f"🔖 *Reference:* `{reference}`\n\n"
            f"✨ *Payment will be confirmed automatically\\!*\n"
            f"You'll receive a notification once done\\."
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💳 Pay ₦{amount_naira:,.0f}", url=payment_url)],
            [InlineKeyboardButton("🔄 Check Payment Status", callback_data=f"verify_{reference}")],
            [InlineKeyboardButton("🔙 Back", callback_data="subscribe")]
        ])
        
        await query.message.edit_text(payment_text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await query.message.edit_text(
            "❌ Failed to generate payment link\\.\n"
            "Please try again or contact support\\.",
            parse_mode='MarkdownV2'
        )

async def add_forward_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if update.callback_query else None
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    if not user['is_premium']:
        user_rules = get_user_rules(update.effective_user.id)
        if len(user_rules) >= 1:
            text = (
                "⚠️ *Free Plan Limit Reached*\n\n"
                "Free users can only have 1 active forwarding rule\\.\n\n"
                "💎 Upgrade to Premium for unlimited rules\\!"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Upgrade Now", callback_data="subscribe")],
                [InlineKeyboardButton("🔙 Back", callback_data="start")]
            ])
            
            if query:
                await query.message.edit_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
            else:
                await update.message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
            return ConversationHandler.END
    
    text = (
        "📝 *Add Forwarding Rule \\- Step 1/2*\n\n"
        "Send me the *SOURCE* chat \\(where messages come FROM\\):\n\n"
        "*Options:*\n"
        "• Channel username: `@mynewschannel`\n"
        "• Chat ID: `\\-1001234567890`\n"
        "• Forward any message from that chat\n\n"
        "Send /cancel to abort\\."
    )
    
    if query:
        await query.answer()
        await query.message.reply_text(text, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(text, parse_mode='MarkdownV2')
    
    return SOURCE_CHAT

async def source_chat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    source_input = update.message.text.strip() if update.message.text else None
    
    try:
        if update.message.forward_origin:
            forward_origin = update.message.forward_origin
            
            if forward_origin.type == "channel":
                chat = forward_origin.chat
            elif forward_origin.type == "chat":
                chat_id = forward_origin.sender_chat.id if hasattr(forward_origin, 'sender_chat') else None
                if chat_id:
                    chat = await context.bot.get_chat(chat_id)
                else:
                    await update.message.reply_text(
                        "❌ Cannot determine source chat from this forward\\.\n\n"
                        "Please send the chat username or ID instead\\.",
                        parse_mode='MarkdownV2'
                    )
                    return SOURCE_CHAT
            else:
                await update.message.reply_text(
                    "❌ This forward type is not supported\\.\n\n"
                    "Please send:\n"
                    "• Channel username: `@channel`\n"
                    "• Chat ID: `\\-1001234567890`",
                    parse_mode='MarkdownV2'
                )
                return SOURCE_CHAT
                
        elif source_input and source_input.startswith('@'):
            chat = await context.bot.get_chat(source_input)
        elif source_input and source_input.lstrip('-').isdigit():
            chat = await context.bot.get_chat(int(source_input))
        else:
            await update.message.reply_text(
                "❌ *Invalid Format*\n\n"
                "Please send:\n"
                "• Channel username: `@channel`\n"
                "• Chat ID: `\\-1001234567890`\n"
                "• Or forward a message from the chat",
                parse_mode='MarkdownV2'
            )
            return SOURCE_CHAT
        
        try:
            member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if member.status not in ['administrator', 'creator']:
                chat_title_escaped = chat.title.replace('-', '\\-').replace('.', '\\.')
                await update.message.reply_text(
                    f"❌ *Not An Admin*\n\n"
                    f"I'm not an admin in *{chat_title_escaped}*\n\n"
                    f"Please add me as admin with these permissions:\n"
                    f"• Read messages\n"
                    f"• Send messages",
                    parse_mode='MarkdownV2'
                )
                return SOURCE_CHAT
        except Exception as e:
            error_msg = str(e).replace('-', '\\-').replace('.', '\\.')
            await update.message.reply_text(
                f"❌ *Cannot Access Chat*\n\n"
                f"Make sure I'm added as admin\\.\n\n"
                f"Error: `{error_msg}`",
                parse_mode='MarkdownV2'
            )
            return SOURCE_CHAT
        
        context.user_data['source_chat_id'] = chat.id
        context.user_data['source_chat_title'] = chat.title or chat.first_name or str(chat.id)
        
        title_escaped = context.user_data['source_chat_title'].replace('-', '\\-').replace('.', '\\.')
        chat_id_escaped = str(chat.id).replace('-', '\\-')
        
        await update.message.reply_text(
            f"✅ *Source Chat Set*\n\n"
            f"📥 From: *{title_escaped}*\n"
            f"🆔 ID: `{chat_id_escaped}`\n\n"
            f"📝 *Step 2/2*\n\n"
            f"Now send the *DESTINATION* chat \\(where messages go TO\\):\n\n"
            f"*Options:*\n"
            f"• Channel username: `@mydestchannel`\n"
            f"• Chat ID: `\\-1001234567890`\n"
            f"• Forward a message from destination\n\n"
            f"Send /cancel to abort\\.",
            parse_mode='MarkdownV2'
        )
        
        return DEST_CHAT
        
    except Exception as e:
        logger.error(f"Error in source_chat_received: {e}")
        error_msg = str(e).replace('-', '\\-').replace('.', '\\.')
        await update.message.reply_text(
            f"❌ *Error*\n\n"
            f"`{error_msg}`\n\n"
            f"Please try again with valid chat username or ID\\.",
            parse_mode='MarkdownV2'
        )
        return SOURCE_CHAT

async def dest_chat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dest_input = update.message.text.strip() if update.message.text else None
    
    try:
        if update.message.forward_origin:
            forward_origin = update.message.forward_origin
            
            if forward_origin.type == "channel":
                chat = forward_origin.chat
            elif forward_origin.type == "chat":
                chat_id = forward_origin.sender_chat.id if hasattr(forward_origin, 'sender_chat') else None
                if chat_id:
                    chat = await context.bot.get_chat(chat_id)
                else:
                    await update.message.reply_text(
                        "❌ Cannot determine destination chat from this forward\\.\n\n"
                        "Please send the chat username or ID instead\\.",
                        parse_mode='MarkdownV2'
                    )
                    return DEST_CHAT
            else:
                await update.message.reply_text(
                    "❌ This forward type is not supported\\.\n\n"
                    "Please send:\n"
                    "• Channel username: `@channel`\n"
                    "• Chat ID: `\\-1001234567890`",
                    parse_mode='MarkdownV2'
                )
                return DEST_CHAT
                
        elif dest_input and dest_input.startswith('@'):
            chat = await context.bot.get_chat(dest_input)
        elif dest_input and dest_input.lstrip('-').isdigit():
            chat = await context.bot.get_chat(int(dest_input))
        else:
            await update.message.reply_text(
                "❌ *Invalid Format*\n\n"
                "Please send:\n"
                "• Channel username: `@channel`\n"
                "• Chat ID: `\\-1001234567890`\n"
                "• Or forward a message from the chat",
                parse_mode='MarkdownV2'
            )
            return DEST_CHAT
        
        try:
            member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if member.status not in ['administrator', 'creator']:
                chat_title_escaped = chat.title.replace('-', '\\-').replace('.', '\\.')
                await update.message.reply_text(
                    f"❌ *Not An Admin*\n\n"
                    f"I'm not an admin in *{chat_title_escaped}*\n\n"
                    f"Please add me as admin with post messages permission\\.",
                    parse_mode='MarkdownV2'
                )
                return DEST_CHAT
        except Exception as e:
            error_msg = str(e).replace('-', '\\-').replace('.', '\\.')
            await update.message.reply_text(
                f"❌ *Cannot Access Chat*\n\n"
                f"Make sure I'm added as admin\\.\n\n"
                f"Error: `{error_msg}`",
                parse_mode='MarkdownV2'
            )
            return DEST_CHAT
        
        dest_chat_id = chat.id
        dest_chat_title = chat.title or chat.first_name or str(chat.id)
        
        rule_id = f"rule_{int(datetime.now().timestamp())}_{update.effective_user.id}"
        
        with data_lock:
            rules_data[rule_id] = {
                'user_id': str(update.effective_user.id),
                'source_chat_id': context.user_data['source_chat_id'],
                'source_chat_title': context.user_data['source_chat_title'],
                'dest_chat_id': dest_chat_id,
                'dest_chat_title': dest_chat_title,
                'is_active': True,
                'messages_forwarded': 0,
                'created_at': datetime.now()
            }
            save_data()
        
        source_escaped = context.user_data['source_chat_title'].replace('-', '\\-').replace('.', '\\.')
        dest_escaped = dest_chat_title.replace('-', '\\-').replace('.', '\\.')
        rule_id_escaped = rule_id.replace('_', '\\_')
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 View My Forwards", callback_data="my_forwards")],
            [InlineKeyboardButton("➕ Add Another", callback_data="add_forward")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
        ])
        
        await update.message.reply_text(
            f"✅ *Forwarding Rule Created\\!*\n\n"
            f"📤 *From:* {source_escaped}\n"
            f"📥 *To:* {dest_escaped}\n"
            f"🆔 *Rule ID:* `{rule_id_escaped}`\n\n"
            f"✨ Messages will now auto\\-forward\\!",
            reply_markup=keyboard,
            parse_mode='MarkdownV2'
        )
        
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in dest_chat_received: {e}")
        error_msg = str(e).replace('-', '\\-').replace('.', '\\.')
        await update.message.reply_text(
            f"❌ *Error*\n\n"
            f"`{error_msg}`\n\n"
            f"Please try again with valid chat username or ID\\.",
            parse_mode='MarkdownV2'
        )
        return DEST_CHAT

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Operation cancelled\\.",
        parse_mode='MarkdownV2'
    )
    context.user_data.clear()
    return ConversationHandler.END

async def my_forwards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if update.callback_query else None
    user_rules = get_user_rules(update.effective_user.id)
    
    if not user_rules:
        text = (
            "📭 *No Active Forwards*\n\n"
            "You don't have any forwarding rules yet\\.\n\n"
            "Click below to create one\\!"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Forward Rule", callback_data="add_forward")],
            [InlineKeyboardButton("🔙 Back", callback_data="start")]
        ])
        
        if query:
            await query.answer()
            await query.message.edit_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
        else:
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
        return
    
    text = "📋 *Your Active Forwards:*\n\n"
    buttons = []
    
    for idx, rule in enumerate(user_rules[:10], 1):
        source_escaped = rule['source_chat_title'].replace('-', '\\-').replace('.', '\\.')
        dest_escaped = rule['dest_chat_title'].replace('-', '\\-').replace('.', '\\.')
        
        text += (
            f"{idx}\\. {source_escaped} → {dest_escaped}\n"
            f"   📊 Forwarded: {rule['messages_forwarded']} messages\n\n"
        )
        
        buttons.append([
            InlineKeyboardButton(
                f"🗑️ Delete Rule {idx}", 
                callback_data=f"delete_{rule['rule_id']}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("➕ Add New Rule", callback_data="add_forward")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="start")])
    
    keyboard = InlineKeyboardMarkup(buttons)
    
    if query:
        await query.answer()
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def delete_forward_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    rule_id = query.data.replace("delete_", "")
    
    with data_lock:
        if rule_id in rules_data:
            rule = rules_data[rule_id]
            if rule['user_id'] == str(query.from_user.id):
                rule['is_active'] = False
                save_data()
                
                source_escaped = rule['source_chat_title'].replace('-', '\\-').replace('.', '\\.')
                dest_escaped = rule['dest_chat_title'].replace('-', '\\-').replace('.', '\\.')
                
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 View Forwards", callback_data="my_forwards")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
                ])
                
                await query.message.edit_text(
                    f"✅ *Rule Deleted*\n\n"
                    f"Forwarding rule has been removed\\.\n\n"
                    f"Was: {source_escaped} → {dest_escaped}",
                    reply_markup=keyboard,
                    parse_mode='MarkdownV2'
                )
            else:
                await query.message.edit_text("❌ You don't own this rule\\.", parse_mode='MarkdownV2')
        else:
            await query.message.edit_text("❌ Rule not found\\.", parse_mode='MarkdownV2')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if update.callback_query else None
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    user_rules = get_user_rules(update.effective_user.id)
    
    total_forwarded = sum(rule['messages_forwarded'] for rule in user_rules)
    
    premium_status = "✨ Premium" if user['is_premium'] else "🆓 Free Plan"
    remaining_days = ""
    if user['is_premium'] and user['subscription_end']:
        days = (user['subscription_end'] - datetime.now()).days
        hours = (user['subscription_end'] - datetime.now()).seconds // 3600
        if days > 0:
            remaining_days = f"\n📅 Expires in: *{days} days*"
        else:
            remaining_days = f"\n📅 Expires in: *{hours} hours*"
    
    stats_text = (
        f"📊 *Your Statistics*\n\n"
        f"👤 *Account Status:* {premium_status}{remaining_days}\n"
        f"📨 *Today's Messages:* {user['daily_messages']}/{'∞' if user['is_premium'] else '50'}\n"
        f"📋 *Active Rules:* {len(user_rules)}\n"
        f"🚀 *Total Forwarded:* {total_forwarded} messages\n\n"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 My Forwards", callback_data="my_forwards")],
        [InlineKeyboardButton("💎 Upgrade", callback_data="subscribe")],
        [InlineKeyboardButton("🔙 Back", callback_data="start")]
    ])
    
    if query:
        await query.answer()
        await query.message.edit_text(stats_text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(stats_text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if update.callback_query else None
    
    help_text = (
        "📚 *Help & Support*\n\n"
        "*🎯 Quick Start:*\n"
        "1\\. Add bot as admin to source channel\n"
        "2\\. Add bot as admin to destination channel\n"
        "3\\. Use /add\\_forward to link them\n"
        "4\\. Done\\! Messages auto\\-forward\n\n"
        "*📝 Commands:*\n"
        "/start \\- Start bot & see overview\n"
        "/subscribe \\- Upgrade to premium\n"
        "/help \\- This message\n\n"
        "*💎 Premium Features:*\n"
        "• Unlimited forwarding rules\n"
        "• Unlimited messages per day\n"
        "• Priority processing\n\n"
        "*⚙️ Required Permissions:*\n"
        "Bot needs admin rights with:\n"
        "• Read messages \\(source\\)\n"
        "• Send messages \\(destination\\)"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Forward", callback_data="add_forward")],
        [InlineKeyboardButton("💎 Get Premium", callback_data="subscribe")],
        [InlineKeyboardButton("🔙 Back", callback_data="start")]
    ])
    
    if query:
        await query.answer()
        await query.message.edit_text(help_text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(help_text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def forward_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post and not update.message:
        return
    
    message = update.channel_post or update.message
    source_chat_id = message.chat.id
    
    active_rules = get_active_rules_by_source(source_chat_id)
    
    if not active_rules:
        return
    
    for rule in active_rules:
        user_id = rule['user_id']
        
        if not check_message_limit(user_id):
            with data_lock:
                user = users_data.get(user_id)
                if user and user.get('daily_messages') == 50:
                    try:
                        keyboard = InlineKeyboardMarkup([
                            [InlineKeyboardButton("💎 Upgrade to Premium", callback_data="subscribe")]
                        ])
                        
                        await context.bot.send_message(
                            int(user_id),
                            "⚠️ *Daily Limit Reached\\!*\n\n"
                            "You've used all 50 free messages today\\.\n\n"
                            "💎 Upgrade to Premium for unlimited forwarding\\!",
                            reply_markup=keyboard,
                            parse_mode='MarkdownV2'
                        )
                        user['daily_messages'] += 1  # Prevent spam
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id}: {e}")
            continue
        
        try:
            await message.forward(rule['dest_chat_id'])
            
            with data_lock:
                rule_in_data = rules_data.get(list(rules_data.keys())[list(rules_data.values()).index(rule)])
                if rule_in_data:
                    rule_in_data['messages_forwarded'] += 1
                    save_data()
            
            logger.info(
                f"Forwarded from {rule['source_chat_title']} "
                f"to {rule['dest_chat_title']} (User: {user_id})"
            )
        except Exception as e:
            logger.error(f"Forward error for rule: {e}")
            
            if "bot was blocked" in str(e).lower() or "chat not found" in str(e).lower():
                try:
                    source_escaped = rule['source_chat_title'].replace('-', '\\-').replace('.', '\\.')
                    dest_escaped = rule['dest_chat_title'].replace('-', '\\-').replace('.', '\\.')
                    
                    await context.bot.send_message(
                        int(user_id),
                        f"⚠️ *Forwarding Error*\n\n"
                        f"Failed to forward from *{source_escaped}* "
                        f"to *{dest_escaped}*\n\n"
                        f"Please check bot permissions\\.",
                        parse_mode='MarkdownV2'
                    )
                except:
                    pass

async def admin_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query if update.callback_query else None
    user_id = query.from_user.id if query else update.effective_user.id
    
    if user_id not in ADMIN_IDS:
        return
    
    with data_lock:
        total_users = len(users_data)
        premium_users = sum(1 for u in users_data.values() if u['is_premium'])
        free_users = total_users - premium_users
        total_rules = len([r for r in rules_data.values() if r['is_active']])
        total_forwarded = sum(r['messages_forwarded'] for r in rules_data.values())
        
        pending_trans = sum(1 for t in transactions_data.values() if t['status'] == 'pending')
        success_trans = sum(1 for t in transactions_data.values() if t['status'] == 'success')
        total_revenue = sum(t['amount'] for t in transactions_data.values() if t['status'] == 'success') / 100
        
        recent_users = sorted(users_data.values(), key=lambda x: x['created_at'], reverse=True)[:5]
        recent_payments = sorted(
            [t for t in transactions_data.values() if t['status'] == 'success'],
            key=lambda x: x['payment_date'] if x['payment_date'] else datetime.min,
            reverse=True
        )[:5]
    
    admin_text = (
        f"🔐 *Admin Dashboard*\n\n"
        f"*📊 User Statistics:*\n"
        f"👥 Total Users: {total_users}\n"
        f"✨ Premium: {premium_users}\n"
        f"🆓 Free: {free_users}\n\n"
        f"*📋 System Statistics:*\n"
        f"📌 Active Rules: {total_rules}\n"
        f"🚀 Total Forwarded: {total_forwarded}\n\n"
        f"*💰 Revenue Statistics:*\n"
        f"✅ Successful: {success_trans}\n"
        f"⏳ Pending: {pending_trans}\n"
        f"💵 Total Revenue: ₦{total_revenue:,.2f}\n\n"
        f"*📈 Recent Users:*\n"
    )
    
    for idx, user in enumerate(recent_users, 1):
        username = user['username'] or 'Unknown'
        status = "✨" if user['is_premium'] else "🆓"
        admin_text += f"{idx}\\. {status} @{username}\n"
    
    admin_text += "\n*💳 Recent Payments:*\n"
    for idx, trans in enumerate(recent_payments, 1):
        amount = trans['amount'] / 100
        plan = "Monthly" if trans['plan_type'] == 'monthly' else "Daily"
        admin_text += f"{idx}\\. ₦{amount:,.0f} \\({plan}\\)\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin")],
        [InlineKeyboardButton("🔙 Back", callback_data="start")]
    ])
    
    if query:
        await query.answer()
        await query.message.edit_text(admin_text, reply_markup=keyboard, parse_mode='MarkdownV2')
    else:
        await update.message.reply_text(admin_text, reply_markup=keyboard, parse_mode='MarkdownV2')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    if query.data == "start":
        await query.answer()
        user = get_or_create_user(query.from_user.id, query.from_user.username)
        
        premium_status = "✨ Premium" if user['is_premium'] else "🆓 Free"
        
        welcome_text = (
            "🚀 *Welcome to Auto Forwarder Bot\\!*\n\n"
            "📋 *How it works:*\n"
            "1️⃣ Add me as admin to source channel\n"
            "2️⃣ Add me as admin to destination channel\n"
            "3️⃣ Use /add\\_forward to create rule\n"
            "4️⃣ Messages auto\\-forward automatically\\!\n\n"
            f"*Your Plan:* {premium_status}\n"
            f"*Today's Messages:* {user['daily_messages']}/50\n\n"
            "💎 *Premium Plans:*\n"
            "• Monthly: ₦3,000 \\(30 days\\)\n"
            "• Daily: ₦200 \\(24 hours\\)\n"
            "• Unlimited rules \\& messages\\!"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Forward Rule", callback_data="add_forward")],
            [InlineKeyboardButton("📋 My Forwards", callback_data="my_forwards")],
            [
                InlineKeyboardButton("💎 Monthly (₦3,000)", callback_data="pay_monthly"),
                InlineKeyboardButton("⚡ Daily (₦200)", callback_data="pay_daily")
            ],
            [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
            [InlineKeyboardButton("❓ Help", callback_data="help")]
        ])
        
        await query.message.edit_text(welcome_text, reply_markup=keyboard, parse_mode='MarkdownV2')
    
    elif query.data == "add_forward":
        await add_forward_start(update, context)
    
    elif query.data == "my_forwards":
        await my_forwards_command(update, context)
    
    elif query.data == "subscribe":
        await query.answer()
        user = get_or_create_user(query.from_user.id, query.from_user.username)
        
        if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
            remaining = (user['subscription_end'] - datetime.now()).days
            await query.message.edit_text(
                f"✨ You're already Premium\\!\n\n"
                f"📅 {remaining} days remaining\n"
                f"💫 Enjoying unlimited forwarding\\!",
                parse_mode='MarkdownV2'
            )
            return
        
        subscribe_text = (
            "💎 *Premium Plans*\n\n"
            "*Monthly Plan \\- ₦3,000*\n"
            "✅ 30 days premium access\n"
            "✅ Unlimited forwarding rules\n"
            "✅ Unlimited messages\n"
            "✅ Priority support\n\n"
            "*Daily Plan \\- ₦200*\n"
            "✅ 24 hours premium access\n"
            "✅ Unlimited forwarding\n"
            "✅ Perfect for testing\n\n"
            "👇 *Click a button below to pay:*"
        )
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Monthly (₦3,000)", callback_data="pay_monthly")],
            [InlineKeyboardButton("💳 Pay Daily (₦200)", callback_data="pay_daily")],
            [InlineKeyboardButton("🔙 Back", callback_data="start")]
        ])
        
        await query.message.edit_text(subscribe_text, reply_markup=keyboard, parse_mode='MarkdownV2')
    
    elif query.data == "pay_monthly":
        await handle_payment(update, context, "monthly")
    
    elif query.data == "pay_daily":
        await handle_payment(update, context, "daily")
    
    elif query.data.startswith("verify_"):
        reference = query.data.replace("verify_", "")
        await query.answer("🔄 Checking payment status...")
        
        success, user_id = verify_payment(reference)
        
        if success and str(user_id) == str(query.from_user.id):
            with data_lock:
                plan_type = transactions_data.get(reference, {}).get('plan_type', 'monthly')
            
            activate_premium(query.from_user.id, plan_type)
            
            with data_lock:
                if reference in transactions_data:
                    transactions_data[reference]['status'] = 'success'
                    transactions_data[reference]['payment_date'] = datetime.now()
                    save_data()
            
            duration = "30 days" if plan_type == 'monthly' else "24 hours"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Forward Rule", callback_data="add_forward")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="start")]
            ])
            
            await query.message.edit_text(
                f"🎉 *Payment Successful\\!*\n\n"
                f"✨ You're now Premium for {duration}\\!\n"
                f"💫 Enjoy unlimited forwarding\\!",
                reply_markup=keyboard,
                parse_mode='MarkdownV2'
            )
        else:
            await query.message.edit_text(
                "⚠️ *Payment Not Confirmed Yet*\n\n"
                "Please complete the payment and try again\\.\n\n"
                "If you've already paid, wait a moment and click verify again\\.",
                parse_mode='MarkdownV2'
            )
    
    elif query.data.startswith("delete_"):
        await delete_forward_handler(update, context)
    
    elif query.data == "stats":
        await stats_command(update, context)
    
    elif query.data == "help":
        await help_command(update, context)
    
    elif query.data == "admin":
        await admin_dashboard(update, context)

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        await admin_dashboard(update, context)

async def post_init(application: Application):
    global bot_app
    bot_app = application
    load_data()
    
    # Set webhook if WEBHOOK_URL is provided
    if WEBHOOK_URL:
        webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        logger.info(f"Webhook set to: {webhook_url}")
    
    logger.info("Bot initialized successfully")

async def post_shutdown(application: Application):
    save_data()
    logger.info("Data saved before shutdown")

def run_flask():
    """Run Flask server for webhooks"""
    logger.info(f"Starting Flask server on port {PORT}")
    flask_app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

def main():
    print("="*50)
    print("Initializing Auto Forwarder Bot...")
    print("="*50)
    
    # Validate environment variables
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not found in environment variables!")
        return
    
    if not PAYSTACK_SECRET_KEY:
        print("WARNING: PAYSTACK_SECRET_KEY not set. Payment features will not work!")
    
    ensure_data_dir()
    load_data()
    
    # Build application
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Conversation handler for adding forwards
    add_forward_conv = ConversationHandler(
        entry_points=[
            CommandHandler('add_forward', add_forward_start),
        ],
        states={
            SOURCE_CHAT: [MessageHandler(filters.TEXT | filters.FORWARDED, source_chat_received)],
            DEST_CHAT: [MessageHandler(filters.TEXT | filters.FORWARDED, dest_chat_received)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )
    
    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(add_forward_conv)
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(
        MessageHandler(filters.ALL, forward_message_handler),
        group=1
    )
    
    print(f"Loaded: {len(users_data)} users, {len(rules_data)} rules")
    
    if WEBHOOK_URL:
        print(f"Starting in WEBHOOK mode")
        print(f"Webhook URL: {WEBHOOK_URL}/{BOT_TOKEN}")
        print(f"Flask server will run on port {PORT}")
        print("="*50)
        
        # Start Flask in a separate thread
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        # Run webhook mode
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
            secret_token=None
        )
    else:
        print("Starting in POLLING mode (local development)")
        print("="*50)
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
        save_data()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        save_data()