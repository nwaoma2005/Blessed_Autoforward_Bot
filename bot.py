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

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Should be your Render URL
PORT = int(os.getenv("PORT", 10000))  # Render uses dynamic PORT

# Paystack Configuration
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")

# Subscription Pricing (in Kobo)
MONTHLY_PRICE = 300000  # ₦3,000
DAILY_PRICE = 20000     # ₦200
PLAN_NAME_MONTHLY = "Premium Monthly"
PLAN_NAME_DAILY = "Premium Daily"

# Rate limiting
RATE_LIMIT_WINDOW = 60
MAX_COMMANDS_PER_WINDOW = 10

# Conversation states
SOURCE_CHAT, DEST_CHAT = range(2)

# Data storage files
DATA_DIR = "data"
USERS_FILE = f"{DATA_DIR}/users.json"
RULES_FILE = f"{DATA_DIR}/rules.json"
TRANSACTIONS_FILE = f"{DATA_DIR}/transactions.json"

# In-memory storage
users_data = {}
rules_data = {}
transactions_data = {}

# ==================== FILE STORAGE FUNCTIONS ====================

def ensure_data_dir():
    """Create data directory if it doesn't exist"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        logger.info("✅ Data directory created")

def save_data():
    """Save all data to JSON files"""
    try:
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
        
        logger.info("💾 Data saved successfully")
    except Exception as e:
        logger.error(f"❌ Error saving data: {e}")

def load_data():
    """Load all data from JSON files"""
    global users_data, rules_data, transactions_data
    
    try:
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
        
        logger.info(f"📂 Loaded: {len(users_data)} users, {len(rules_data)} rules, {len(transactions_data)} transactions")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}")

# ==================== HELPER FUNCTIONS ====================

def rate_limit(func):
    """Rate limiting decorator"""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        
        if user_id in users_data:
            user = users_data[user_id]
            current_time = datetime.now()
            
            last_time = user.get('last_command_time')
            if last_time and (current_time - last_time).seconds < RATE_LIMIT_WINDOW:
                count = user.get('command_count', 0)
                if count >= MAX_COMMANDS_PER_WINDOW:
                    await update.message.reply_text(
                        "⚠️ Slow down! Too many requests. Wait a moment."
                    )
                    return
                user['command_count'] = count + 1
            else:
                user['last_command_time'] = current_time
                user['command_count'] = 1
        
        return await func(update, context)
    return wrapper

def get_or_create_user(user_id, username):
    """Get or create user"""
    user_id = str(user_id)
    
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
        logger.info(f"✅ New user: {username} ({user_id})")
    
    return users_data[user_id]

def reset_daily_limit(user_id):
    """Reset daily message limit"""
    user_id = str(user_id)
    if user_id in users_data:
        users_data[user_id]['daily_messages'] = 0
        users_data[user_id]['last_reset'] = datetime.now()
        save_data()

def check_message_limit(user_id):
    """Check and increment message limit"""
    user_id = str(user_id)
    
    if user_id not in users_data:
        return False
    
    user = users_data[user_id]
    
    if user['last_reset'] and (datetime.now() - user['last_reset']).days >= 1:
        reset_daily_limit(user_id)
        user['daily_messages'] = 0
    
    if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
        return True
    
    if user['daily_messages'] >= 50:
        return False
    
    user['daily_messages'] += 1
    save_data()
    return True

def generate_payment_link(user_id, email, bot_username, plan_type='monthly'):
    """Generate Paystack payment link"""
    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    # Determine amount and plan name based on plan type
    if plan_type == 'daily':
        amount = DAILY_PRICE
        plan_name = PLAN_NAME_DAILY
        prefix = "DAILY"
    else:
        amount = MONTHLY_PRICE
        plan_name = PLAN_NAME_MONTHLY
        prefix = "MONTHLY"
    
    reference = f"{prefix}_{user_id}_{int(datetime.now().timestamp())}"
    
    data = {
        "email": email,
        "amount": amount,
        "reference": reference,
        "callback_url": f"https://t.me/{bot_username}",
        "metadata": {
            "user_id": str(user_id),
            "plan": plan_name,
            "plan_type": plan_type
        }
    }
    
    try:
        response = requests.post(url, json=data, headers=headers, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            
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
    """Verify Paystack payment"""
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
    """Activate premium subscription"""
    user_id = str(user_id)
    
    if user_id in users_data:
        # Calculate subscription end based on plan type
        if plan_type == 'daily':
            subscription_end = datetime.now() + timedelta(days=1)
        else:  # monthly
            subscription_end = datetime.now() + timedelta(days=30)
            
        users_data[user_id]['is_premium'] = True
        users_data[user_id]['subscription_end'] = subscription_end
        save_data()
        logger.info(f"💎 Premium {plan_type} activated for user {user_id}")

def get_active_rules_by_source(source_chat_id):
    """Get all active forwarding rules for a source chat"""
    active_rules = []
    for rule_id, rule in rules_data.items():
        if rule['source_chat_id'] == source_chat_id and rule['is_active']:
            active_rules.append(rule)
    return active_rules

def get_user_rules(user_id):
    """Get all active rules for a user"""
    user_id = str(user_id)
    user_rules = []
    for rule_id, rule in rules_data.items():
        if rule['user_id'] == user_id and rule['is_active']:
            user_rules.append({**rule, 'rule_id': rule_id})
    return user_rules

# ==================== COMMAND HANDLERS ====================

@rate_limit
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    premium_status = "✨ Premium" if user['is_premium'] else "🆓 Free (50 msgs/day)"
    
    welcome_text = f"""
🚀 **Welcome to Auto Forwarder Bot!**

**How it works:**
1. Add me as admin to your source channel/group
2. Add me as admin to your destination channel/group  
3. Use /add\_forward to create forwarding rule
4. Messages auto-forward automatically! 🔥

**Your Plan:** {premium_status}
**Today's Messages:** {user['daily_messages']}/50

**Commands:**
/add\_forward - Create new forwarding rule
/my\_forwards - View your active forwards
/delete\_forward - Remove a forwarding rule
/subscribe - Upgrade to Premium
/stats - View bot statistics
/help - Get help

💎 **Premium Benefits:**
• Monthly Plan: ₦3,000/month
• Daily Plan: ₦200/day

✅ Unlimited forwarding rules
✅ Unlimited messages  
✅ No daily limits
✅ Priority support
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Forward Rule", callback_data="add_forward")],
        [InlineKeyboardButton("📋 My Forwards", callback_data="my_forwards")],
        [InlineKeyboardButton("💎 Upgrade to Premium", callback_data="subscribe")]
    ])
    
    await update.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode='Markdown')

@rate_limit
async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe command handler"""
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
        remaining = (user['subscription_end'] - datetime.now()).days
        await update.message.reply_text(
            f"✨ You're already Premium!\n\n"
            f"📅 **{remaining} days** remaining\n"
            f"💫 Enjoying unlimited forwarding!",
            parse_mode='Markdown'
        )
        return
    
    subscribe_text = """
💎 **Premium Plans**

**Monthly Plan - ₦3,000**
✅ 30 days of premium access
✅ Unlimited forwarding rules
✅ Unlimited messages per day
✅ Priority processing
✅ Priority support

**Daily Plan - ₦200**
✅ 24 hours of premium access
✅ Unlimited forwarding rules
✅ Unlimited messages
✅ Perfect for testing

**To subscribe:**
Monthly: `/pay_monthly your@email.com`
Daily: `/pay_daily your@email.com`
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Monthly (₦3,000)", callback_data="pay_monthly")],
        [InlineKeyboardButton("💳 Daily (₦200)", callback_data="pay_daily")]
    ])
    
    await update.message.reply_text(subscribe_text, reply_markup=keyboard, parse_mode='Markdown')

async def pay_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pay now button"""
    query = update.callback_query
    await query.answer()
    
    plan_type = 'monthly' if query.data == 'pay_monthly' else 'daily'
    context.user_data['selected_plan'] = plan_type
    
    amount_text = "₦3,000 (Monthly)" if plan_type == 'monthly' else "₦200 (Daily)"
    
    await query.message.reply_text(
        f"📧 **Payment Setup - {amount_text}**\n\n"
        f"Please send your email address:\n\n"
        f"Example: `/pay_{plan_type} youremail@gmail.com`",
        parse_mode='Markdown'
    )

@rate_limit
async def pay_monthly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate monthly payment link"""
    await pay_command_helper(update, context, 'monthly')

@rate_limit
async def pay_daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate daily payment link"""
    await pay_command_helper(update, context, 'daily')

async def pay_command_helper(update: Update, context: ContextTypes.DEFAULT_TYPE, plan_type: str):
    """Helper function for payment commands"""
    if len(context.args) < 1:
        plan_text = "Monthly (₦3,000)" if plan_type == 'monthly' else "Daily (₦200)"
        await update.message.reply_text(
            f"❌ Please provide your email:\n\n"
            f"`/pay_{plan_type} youremail@gmail.com`\n\n"
            f"Plan: {plan_text}",
            parse_mode='Markdown'
        )
        return
    
    email = context.args[0]
    
    if '@' not in email or '.' not in email:
        await update.message.reply_text("❌ Invalid email format. Please try again.")
        return
    
    bot = await context.bot.get_me()
    payment_url, reference, amount = generate_payment_link(
        update.effective_user.id, 
        email, 
        bot.username, 
        plan_type
    )
    
    if payment_url:
        amount_naira = amount / 100  # Convert kobo to naira
        plan_text = "Monthly" if plan_type == 'monthly' else "Daily"
        duration = "30 days" if plan_type == 'monthly' else "24 hours"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💳 Pay Now (₦{amount_naira:,.0f})", url=payment_url)],
            [InlineKeyboardButton("✅ I've Paid - Verify", callback_data=f"verify_{reference}")]
        ])
        
        await update.message.reply_text(
            f"✅ **Payment Link Generated!**\n\n"
            f"📦 Plan: **{plan_text}**\n"
            f"💰 Amount: **₦{amount_naira:,.0f}**\n"
            f"⏰ Duration: **{duration}**\n"
            f"📧 Email: `{email}`\n"
            f"🔖 Reference: `{reference}`\n\n"
            f"After payment, click 'I've Paid' or use:\n"
            f"`/verify {reference}`",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ Failed to generate payment link.\n"
            "Please try again or contact support."
        )

@rate_limit
async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify payment"""
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Please provide payment reference:\n\n"
            "`/verify MONTHLY_xxxxx` or `/verify DAILY_xxxxx`",
            parse_mode='Markdown'
        )
        return
    
    reference = context.args[0]
    
    await update.message.reply_text("🔄 Verifying payment...")
    
    success, user_id = verify_payment(reference)
    
    if success and str(user_id) == str(update.effective_user.id):
        # Get plan type from transaction data
        plan_type = transactions_data.get(reference, {}).get('plan_type', 'monthly')
        activate_premium(update.effective_user.id, plan_type)
        
        if reference in transactions_data:
            transactions_data[reference]['status'] = 'success'
            transactions_data[reference]['payment_date'] = datetime.now()
            save_data()
        
        duration = "30 days" if plan_type == 'monthly' else "24 hours"
        
        await update.message.reply_text(
            f"🎉 **Payment Successful!**\n\n"
            f"✨ You're now **Premium** for {duration}!\n"
            f"💫 Enjoy unlimited forwarding!\n\n"
            f"Use /add\_forward to create rules! 🚀",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ **Payment Verification Failed**\n\n"
            "Possible reasons:\n"
            "• Payment not completed yet\n"
            "• Invalid reference\n"
            "• Transaction belongs to different user\n\n"
            "Please try again or contact support."
        )

# ==================== FORWARDING RULE HANDLERS ====================

async def add_forward_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding forward rule"""
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    if not user['is_premium']:
        user_rules = get_user_rules(update.effective_user.id)
        if len(user_rules) >= 1:
            await update.message.reply_text(
                "⚠️ **Free Plan Limit Reached**\n\n"
                "Free users can only have 1 active forwarding rule.\n\n"
                "💎 Upgrade to Premium for unlimited rules!\n"
                "/subscribe",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    
    await update.message.reply_text(
        "📝 **Add Forwarding Rule - Step 1/2**\n\n"
        "Send me the **SOURCE** chat (where messages come FROM):\n\n"
        "**Options:**\n"
        "• Channel username: `@mynewschannel`\n"
        "• Chat ID: `-1001234567890`\n"
        "• Forward any message from that chat\n\n"
        "Send /cancel to abort.",
        parse_mode='Markdown'
    )
    
    return SOURCE_CHAT

async def source_chat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle source chat input"""
    source_input = update.message.text.strip() if update.message.text else None
    
    try:
        if update.message.forward_from_chat:
            chat = update.message.forward_from_chat
        elif source_input and source_input.startswith('@'):
            chat = await context.bot.get_chat(source_input)
        elif source_input and source_input.lstrip('-').isdigit():
            chat = await context.bot.get_chat(int(source_input))
        else:
            await update.message.reply_text(
                "❌ **Invalid Format**\n\n"
                "Please send:\n"
                "• Channel username: `@channel`\n"
                "• Chat ID: `-1001234567890`\n"
                "• Or forward a message from the chat",
                parse_mode='Markdown'
            )
            return SOURCE_CHAT
        
        try:
            member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    f"❌ **Not An Admin**\n\n"
                    f"I'm not an admin in **{chat.title}**\n\n"
                    f"Please add me as admin with these permissions:\n"
                    f"• Read messages\n"
                    f"• Send messages",
                    parse_mode='Markdown'
                )
                return SOURCE_CHAT
        except Exception as e:
            await update.message.reply_text(
                f"❌ **Cannot Access Chat**\n\n"
                f"Make sure I'm added as admin.\n\n"
                f"Error: `{str(e)}`",
                parse_mode='Markdown'
            )
            return SOURCE_CHAT
        
        context.user_data['source_chat_id'] = chat.id
        context.user_data['source_chat_title'] = chat.title or chat.first_name or str(chat.id)
        
        await update.message.reply_text(
            f"✅ **Source Chat Set**\n\n"
            f"📥 From: **{context.user_data['source_chat_title']}**\n\n"
            f"📝 **Step 2/2**\n\n"
            f"Now send the **DESTINATION** chat (where messages go TO):\n\n"
            f"**Options:**\n"
            f"• Channel username: `@mydestchannel`\n"
            f"• Chat ID: `-1001234567890`\n\n"
            f"Send /cancel to abort.",
            parse_mode='Markdown'
        )
        
        return DEST_CHAT
        
    
    except Exception as e:
        logger.error(f"Error in source_chat_received: {e}")
        await update.message.reply_text(
            f"❌ **Error**\n\n"
            f"`{str(e)}`\n\n"
            f"Please try again with valid chat username or ID.",
            parse_mode='Markdown'
        )
        return SOURCE_CHAT

async def dest_chat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle destination chat input"""
    dest_input = update.message.text.strip() if update.message.text else None
    
    try:
        if update.message.forward_from_chat:
            chat = update.message.forward_from_chat
        elif dest_input and dest_input.startswith('@'):
            chat = await context.bot.get_chat(dest_input)
        elif dest_input and dest_input.lstrip('-').isdigit():
            chat = await context.bot.get_chat(int(dest_input))
        else:
            await update.message.reply_text(
                "❌ **Invalid Format**\n\n"
                "Please send:\n"
                "• Channel username: `@channel`\n"
                "• Chat ID: `-1001234567890`\n"
                "• Or forward a message from the chat",
                parse_mode='Markdown'
            )
            return DEST_CHAT
        
        try:
            member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    f"❌ **Not An Admin**\n\n"
                    f"I'm not an admin in **{chat.title}**\n\n"
                    f"Please add me as admin with post messages permission.",
                    parse_mode='Markdown'
                )
                return DEST_CHAT
        except Exception as e:
            await update.message.reply_text(
                f"❌ **Cannot Access Chat**\n\n"
                f"Make sure I'm added as admin.\n\n"
                f"Error: `{str(e)}`",
                parse_mode='Markdown'
            )
            return DEST_CHAT
        
        dest_chat_id = chat.id
        dest_chat_title = chat.title or chat.first_name or str(chat.id)
        
        rule_id = f"rule_{int(datetime.now().timestamp())}_{update.effective_user.id}"
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
        
        await update.message.reply_text(
            f"✅ **Forwarding Rule Created!**\n\n"
            f"📥 **From:** {context.user_data['source_chat_title']}\n"
            f"📤 **To:** {dest_chat_title}\n"
            f"🆔 **Rule ID:** `{rule_id}`\n\n"
            f"Messages will now auto-forward! 🚀\n\n"
            f"Use /my\_forwards to view all rules.",
            parse_mode='Markdown'
        )
        
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in dest_chat_received: {e}")
        await update.message.reply_text(
            f"❌ **Error**\n\n"
            f"`{str(e)}`\n\n"
            f"Please try again with valid chat username or ID.",
            parse_mode='Markdown'
        )
        return DEST_CHAT

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await update.message.reply_text("❌ Operation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

@rate_limit
async def my_forwards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's forwarding rules"""
    user_rules = get_user_rules(update.effective_user.id)
    
    if not user_rules:
        await update.message.reply_text(
            "📭 **No Active Forwards**\n\n"
            "You don't have any forwarding rules yet.\n\n"
            "Use /add\_forward to create one!",
            parse_mode='Markdown'
        )
        return
    
    text = "📋 **Your Active Forwards:**\n\n"
    for idx, rule in enumerate(user_rules, 1):
        text += (
            f"{idx}. **Rule:** `{rule['rule_id']}`\n"
            f"   📥 From: {rule['source_chat_title']}\n"
            f"   📤 To: {rule['dest_chat_title']}\n"
            f"   📊 Forwarded: {rule['messages_forwarded']} messages\n\n"
        )
    
    text += "💡 To delete a rule:\n`/delete_forward RULE_ID`"
    
    await update.message.reply_text(text, parse_mode='Markdown')

@rate_limit
async def delete_forward_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete forwarding rule"""
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ **Missing Rule ID**\n\n"
            "Usage: `/delete_forward RULE_ID`\n\n"
            "Use /my\_forwards to see your rules.",
            parse_mode='Markdown'
        )
        return
    
    rule_id = context.args[0]
    
    if rule_id in rules_data:
        rule = rules_data[rule_id]
        if rule['user_id'] == str(update.effective_user.id):
            rule['is_active'] = False
            save_data()
            await update.message.reply_text(
                f"✅ **Rule Deleted**\n\n"
                f"Forwarding rule `{rule_id}` has been removed.\n\n"
                f"📥 Was: {rule['source_chat_title']} → {rule['dest_chat_title']}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ You don't own this rule.")
    else:
        await update.message.reply_text("❌ Rule not found.")

@rate_limit
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    user_rules = get_user_rules(update.effective_user.id)
    
    total_forwarded = sum(rule['messages_forwarded'] for rule in user_rules)
    
    premium_status = "✨ Premium" if user['is_premium'] else "🆓 Free Plan"
    remaining_days = ""
    if user['is_premium'] and user['subscription_end']:
        days = (user['subscription_end'] - datetime.now()).days
        hours = (user['subscription_end'] - datetime.now()).seconds // 3600
        if days > 0:
            remaining_days = f"\n📅 Expires in: **{days} days**"
        else:
            remaining_days = f"\n📅 Expires in: **{hours} hours**"
    
    stats_text = f"""
📊 **Your Statistics**

👤 **Account Status:** {premium_status}{remaining_days}
📨 **Today's Messages:** {user['daily_messages']}/{'∞' if user['is_premium'] else '50'}
📋 **Active Rules:** {len(user_rules)}
🚀 **Total Forwarded:** {total_forwarded} messages

💡 Use /my\_forwards to manage your rules
    """
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
📚 **Help & Support**

**🎯 Quick Start:**
1. Add bot as admin to source channel
2. Add bot as admin to destination channel
3. Use /add\_forward to link them
4. Done! Messages auto-forward

**📝 Commands:**
/start - Start bot & see overview
/add\_forward - Create forwarding rule
/my\_forwards - View active forwards
/delete\_forward - Remove forward rule
/stats - View your statistics
/subscribe - Upgrade to premium
/pay\_monthly email - Pay ₦3,000 (30 days)
/pay\_daily email - Pay ₦200 (24 hours)
/verify REF - Verify payment
/help - This message

**💎 Premium Features:**
✅ Unlimited forwarding rules
✅ Unlimited messages per day
✅ Priority processing

**⚙️ Required Permissions:**
Bot needs admin rights in both chats with:
• Read messages (source)
• Send messages (destination)

**❓ Need help?**
Contact support: @YourSupportUsername
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ==================== MESSAGE FORWARDER ====================

async def forward_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle message forwarding"""
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
            try:
                user = users_data.get(user_id)
                if user and user.get('daily_messages') == 50:
                    await context.bot.send_message(
                        int(user_id),
                        "⚠️ **Daily Limit Reached!**\n\n"
                        "You've used all 50 free messages today.\n\n"
                        "💎 Upgrade to Premium:\n"
                        "• Monthly: ₦3,000 (/pay_monthly)\n"
                        "• Daily: ₦200 (/pay_daily)",
                        parse_mode='Markdown'
                    )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
            continue
        
        try:
            await message.forward(rule['dest_chat_id'])
            
            rule['messages_forwarded'] += 1
            save_data()
            
            logger.info(
                f"✅ Forwarded from {rule['source_chat_title']} "
                f"to {rule['dest_chat_title']} (User: {user_id})"
            )
        except Exception as e:
            logger.error(f"❌ Forward error for rule {rule}: {e}")
            
            if "bot was blocked" in str(e).lower() or "chat not found" in str(e).lower():
                try:
                    await context.bot.send_message(
                        int(user_id),
                        f"⚠️ **Forwarding Error**\n\n"
                        f"Failed to forward from **{rule['source_chat_title']}** "
                        f"to **{rule['dest_chat_title']}**\n\n"
                        f"Error: `{str(e)}`\n\n"
                        f"Please check bot permissions.",
                        parse_mode='Markdown'
                    )
                except:
                    pass

# ==================== ADMIN COMMANDS ====================

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to view bot statistics"""
    ADMIN_IDS = [123456789]  # Replace with your Telegram user ID
    
    if update.effective_user.id not in ADMIN_IDS:
        return
    
    total_users = len(users_data)
    premium_users = sum(1 for u in users_data.values() if u['is_premium'])
    total_rules = len([r for r in rules_data.values() if r['is_active']])
    total_forwarded = sum(r['messages_forwarded'] for r in rules_data.values())
    
    admin_text = f"""
🔐 **Admin Statistics**

👥 **Total Users:** {total_users}
💎 **Premium Users:** {premium_users}
📋 **Active Rules:** {total_rules}
🚀 **Total Forwarded:** {total_forwarded}

**Transaction Stats:**
💰 Pending: {sum(1 for t in transactions_data.values() if t['status'] == 'pending')}
✅ Success: {sum(1 for t in transactions_data.values() if t['status'] == 'success')}
    """
    
    await update.message.reply_text(admin_text, parse_mode='Markdown')

# ==================== MAIN FUNCTION ====================

async def post_init(application: Application):
    """Run after bot initialization"""
    load_data()
    logger.info("✅ Bot initialized successfully")

async def post_shutdown(application: Application):
    """Run before bot shutdown"""
    save_data()
    logger.info("💾 Data saved before shutdown")

def main():
    """Main function to run the bot"""
    print("🚀 Initializing Auto Forwarder Bot...")
    
    ensure_data_dir()
    load_data()
    
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    
    add_forward_conv = ConversationHandler(
        entry_points=[
            CommandHandler('add_forward', add_forward_start),
            CallbackQueryHandler(button_callback, pattern="^add_forward$")
        ],
        states={
            SOURCE_CHAT: [MessageHandler(filters.TEXT | filters.FORWARDED, source_chat_received)],
            DEST_CHAT: [MessageHandler(filters.TEXT | filters.FORWARDED, dest_chat_received)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("pay_monthly", pay_monthly_command))
    application.add_handler(CommandHandler("pay_daily", pay_daily_command))
    application.add_handler(CommandHandler("verify", verify_command))
    application.add_handler(CommandHandler("my_forwards", my_forwards_command))
    application.add_handler(CommandHandler("delete_forward", delete_forward_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("admin_stats", admin_stats_command))
    
    application.add_handler(add_forward_conv)
    application.add_handler(CallbackQueryHandler(button_callback))
    
    application.add_handler(
        MessageHandler(filters.ALL, forward_message_handler),
        group=1
    )
    
    print("✅ Bot started successfully!")
    print(f"📊 Loaded: {len(users_data)} users, {len(rules_data)} rules")
    
    if WEBHOOK_URL:
        print(f"🌐 Starting webhook mode on port {PORT}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
        )
    else:
        print("🔄 Starting polling mode")
        application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
        save_data()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        save_data()
```

