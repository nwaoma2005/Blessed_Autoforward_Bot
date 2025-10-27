import os
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
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

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
DATABASE_URL = os.getenv("DATABASE_URL")

# Paystack Configuration
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")

# Subscription Pricing (in Kobo - Nigerian currency)
MONTHLY_PRICE = 700000  # ₦7,000
PLAN_NAME = "Premium Monthly"

# Conversation states
SOURCE_CHAT, DEST_CHAT = range(2)

# Database functions
def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            is_premium BOOLEAN DEFAULT FALSE,
            subscription_end TIMESTAMP,
            daily_messages INTEGER DEFAULT 0,
            last_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS forwarding_rules (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            source_chat_id BIGINT,
            source_chat_title VARCHAR(255),
            dest_chat_id BIGINT,
            dest_chat_title VARCHAR(255),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            reference VARCHAR(255) UNIQUE,
            amount INTEGER,
            status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    
    conn.commit()
    conn.close()

def get_or_create_user(user_id, username):
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    
    if not user:
        cur.execute(
            "INSERT INTO users (user_id, username) VALUES (%s, %s) RETURNING *",
            (user_id, username)
        )
        user = cur.fetchone()
        conn.commit()
    
    conn.close()
    return user

def reset_daily_limit(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET daily_messages = 0, last_reset = CURRENT_TIMESTAMP WHERE user_id = %s",
        (user_id,)
    )
    conn.commit()
    conn.close()

def check_message_limit(user_id):
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    
    if user['last_reset'] and (datetime.now() - user['last_reset']).days >= 1:
        reset_daily_limit(user_id)
        user['daily_messages'] = 0
    
    if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
        conn.close()
        return True
    
    if user['daily_messages'] >= 50:
        conn.close()
        return False
    
    cur.execute(
        "UPDATE users SET daily_messages = daily_messages + 1 WHERE user_id = %s",
        (user_id,)
    )
    conn.commit()
    conn.close()
    return True

def generate_payment_link(user_id, email, bot_username):
    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json"
    }
    
    reference = f"SUB_{user_id}_{int(datetime.now().timestamp())}"
    
    data = {
        "email": email,
        "amount": MONTHLY_PRICE,
        "reference": reference,
        "callback_url": f"https://t.me/{bot_username}",
        "metadata": {
            "user_id": user_id,
            "plan": PLAN_NAME
        }
    }
    
    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO transactions (user_id, reference, amount) VALUES (%s, %s, %s)",
            (user_id, reference, MONTHLY_PRICE)
        )
        conn.commit()
        conn.close()
        
        return result['data']['authorization_url'], reference
    
    return None, None

def verify_payment(reference):
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        if result['data']['status'] == 'success':
            return True, result['data']['metadata']['user_id']
    
    return False, None

def activate_premium(user_id):
    conn = get_db()
    cur = conn.cursor()
    
    subscription_end = datetime.now() + timedelta(days=30)
    
    cur.execute(
        """UPDATE users 
           SET is_premium = TRUE, subscription_end = %s 
           WHERE user_id = %s""",
        (subscription_end, user_id)
    )
    conn.commit()
    conn.close()

# Command Handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    welcome_text = f"""
🚀 **Welcome to Auto Forwarder Bot!**

**How it works:**
1. Add me as admin to your source channel/group
2. Add me as admin to your destination channel/group
3. Use /add\_forward to create forwarding rule
4. Messages will auto-forward! 🔥

**Your Plan:** {"✨ Premium" if user['is_premium'] else "🆓 Free (50 msgs/day)"}
**Today's Messages:** {user['daily_messages']}/50

**Commands:**
/add\_forward - Create new forwarding rule
/my\_forwards - View your active forwards
/delete\_forward - Remove a forwarding rule
/subscribe - Upgrade to Premium
/help - Get help

💎 **Premium Benefits (₦7,000/month):**
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

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
        remaining = (user['subscription_end'] - datetime.now()).days
        await update.message.reply_text(f"✨ You're already Premium! {remaining} days remaining.")
        return
    
    subscribe_text = """
💎 **Premium Plan - ₦7,000/month**

**Benefits:**
✅ Unlimited forwarding rules
✅ Unlimited messages per day
✅ Advanced filters (coming soon)
✅ Remove 'Forwarded from' tag (coming soon)
✅ Priority support

**To subscribe:**
Click the button below and send your email, or use:
/pay your@email.com
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Start Payment", callback_data="pay_now")]
    ])
    
    await update.message.reply_text(subscribe_text, reply_markup=keyboard, parse_mode='Markdown')

async def pay_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "Please send your email address for payment:\n\n"
        "Example: /pay youremail@gmail.com"
    )

async def pay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Please provide your email:\n/pay youremail@gmail.com")
        return
    
    email = context.args[0]
    bot = await context.bot.get_me()
    
    payment_url, reference = generate_payment_link(update.effective_user.id, email, bot.username)
    
    if payment_url:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Now (₦7,000)", url=payment_url)]
        ])
        
        await update.message.reply_text(
            f"✅ **Payment Link Generated!**\n\n"
            f"Amount: ₦7,000\n"
            f"Reference: `{reference}`\n\n"
            f"After payment, use:\n"
            f"/verify {reference}",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Failed to generate payment link. Try again.")

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text("❌ Please provide payment reference:\n/verify SUB_xxxxx")
        return
    
    reference = context.args[0]
    
    success, user_id = verify_payment(reference)
    
    if success and str(user_id) == str(update.effective_user.id):
        activate_premium(update.effective_user.id)
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE transactions SET status = 'success' WHERE reference = %s",
            (reference,)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            "🎉 **Payment Successful!**\n\n"
            "✨ You're now Premium for 30 days!\n"
            "Enjoy unlimited forwarding! 🚀",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Payment verification failed. Contact support.")

# Conversation handler for adding forward rules
async def add_forward_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_or_create_user(update.effective_user.id, update.effective_user.username)
    
    if not user['is_premium']:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as count FROM forwarding_rules WHERE user_id = %s AND is_active = TRUE",
            (update.effective_user.id,)
        )
        count = cur.fetchone()['count']
        conn.close()
        
        if count >= 1:
            await update.message.reply_text(
                "⚠️ Free plan allows only 1 forwarding rule.\n"
                "Upgrade to Premium for unlimited rules!\n\n"
                "/subscribe"
            )
            return ConversationHandler.END
    
    await update.message.reply_text(
        "📝 **Add Forwarding Rule - Step 1/2**\n\n"
        "Send me the SOURCE chat username or ID where messages come FROM:\n\n"
        "Examples:\n"
        "• @mynewschannel\n"
        "• -1001234567890\n\n"
        "Or forward any message from that chat.\n\n"
        "Send /cancel to abort.",
        parse_mode='Markdown'
    )
    
    return SOURCE_CHAT

async def source_chat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    source_input = update.message.text.strip()
    
    # Try to get chat info
    try:
        if source_input.startswith('@'):
            chat = await context.bot.get_chat(source_input)
        elif source_input.lstrip('-').isdigit():
            chat = await context.bot.get_chat(int(source_input))
        elif update.message.forward_from_chat:
            chat = update.message.forward_from_chat
        else:
            await update.message.reply_text(
                "❌ Invalid format. Please send:\n"
                "• Channel username (@channel)\n"
                "• Chat ID (-1001234567890)\n"
                "• Or forward a message from the chat"
            )
            return SOURCE_CHAT
        
        # Check if bot is admin
        try:
            member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    f"❌ I'm not an admin in **{chat.title}**\n\n"
                    f"Please add me as admin with:\n"
                    f"• Post messages permission\n"
                    f"• Manage messages permission",
                    parse_mode='Markdown'
                )
                return SOURCE_CHAT
        except Exception as e:
            await update.message.reply_text(
                f"❌ Cannot access chat. Make sure I'm added as admin.\n\nError: {str(e)}"
            )
            return SOURCE_CHAT
        
        # Store source chat info
        context.user_data['source_chat_id'] = chat.id
        context.user_data['source_chat_title'] = chat.title or chat.first_name or str(chat.id)
        
        await update.message.reply_text(
            f"✅ Source chat: **{context.user_data['source_chat_title']}**\n\n"
            f"📝 **Step 2/2**\n\n"
            f"Now send me the DESTINATION chat where messages go TO:\n\n"
            f"Examples:\n"
            f"• @mydestchannel\n"
            f"• -1001234567890\n\n"
            f"Send /cancel to abort.",
            parse_mode='Markdown'
        )
        
        return DEST_CHAT
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}\n\nPlease try again with valid chat username or ID."
        )
        return SOURCE_CHAT

async def dest_chat_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dest_input = update.message.text.strip()
    
    try:
        if dest_input.startswith('@'):
            chat = await context.bot.get_chat(dest_input)
        elif dest_input.lstrip('-').isdigit():
            chat = await context.bot.get_chat(int(dest_input))
        elif update.message.forward_from_chat:
            chat = update.message.forward_from_chat
        else:
            await update.message.reply_text(
                "❌ Invalid format. Please send:\n"
                "• Channel username (@channel)\n"
                "• Chat ID (-1001234567890)\n"
                "• Or forward a message from the chat"
            )
            return DEST_CHAT
        
        # Check if bot is admin
        try:
            member = await context.bot.get_chat_member(chat.id, context.bot.id)
            if member.status not in ['administrator', 'creator']:
                await update.message.reply_text(
                    f"❌ I'm not an admin in **{chat.title}**\n\n"
                    f"Please add me as admin with post messages permission.",
                    parse_mode='Markdown'
                )
                return DEST_CHAT
        except Exception as e:
            await update.message.reply_text(
                f"❌ Cannot access chat. Make sure I'm added as admin.\n\nError: {str(e)}"
            )
            return DEST_CHAT
        
        dest_chat_id = chat.id
        dest_chat_title = chat.title or chat.first_name or str(chat.id)
        
        # Save forwarding rule
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO forwarding_rules 
               (user_id, source_chat_id, source_chat_title, dest_chat_id, dest_chat_title)
               VALUES (%s, %s, %s, %s, %s)""",
            (update.effective_user.id, context.user_data['source_chat_id'],
             context.user_data['source_chat_title'], dest_chat_id, dest_chat_title)
        )
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ **Forwarding Rule Created!**\n\n"
            f"📥 From: {context.user_data['source_chat_title']}\n"
            f"📤 To: {dest_chat_title}\n\n"
            f"Messages will now auto-forward! 🚀",
            parse_mode='Markdown'
        )
        
        # Clear user data
        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}\n\nPlease try again with valid chat username or ID."
        )
        return DEST_CHAT

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Operation cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

async def my_forwards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM forwarding_rules WHERE user_id = %s AND is_active = TRUE",
        (update.effective_user.id,)
    )
    rules = cur.fetchall()
    conn.close()
    
    if not rules:
        await update.message.reply_text(
            "📭 You have no active forwarding rules.\n\nUse /add_forward to create one!"
        )
        return
    
    text = "📋 **Your Active Forwards:**\n\n"
    for idx, rule in enumerate(rules, 1):
        text += f"{idx}. `{rule['id']}`: {rule['source_chat_title']} → {rule['dest_chat_title']}\n"
    
    text += "\n💡 Use /delete\\_forward ID to remove a rule"
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def delete_forward_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Please provide the rule ID:\n/delete_forward ID\n\n"
            "Use /my_forwards to see your rules and their IDs."
        )
        return
    
    try:
        rule_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Please provide a number.")
        return
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE forwarding_rules SET is_active = FALSE WHERE id = %s AND user_id = %s",
        (rule_id, update.effective_user.id)
    )
    
    if cur.rowcount > 0:
        conn.commit()
        await update.message.reply_text(f"✅ Forwarding rule {rule_id} deleted!")
    else:
        await update.message.reply_text("❌ Rule not found or you don't own it.")
    
    conn.close()

# Message forwarder
async def forward_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.channel_post and not update.message:
        return
    
    message = update.channel_post or update.message
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM forwarding_rules WHERE source_chat_id = %s AND is_active = TRUE",
        (message.chat.id,)
    )
    rules = cur.fetchall()
    conn.close()
    
    for rule in rules:
        if not check_message_limit(rule['user_id']):
            try:
                await context.bot.send_message(
                    rule['user_id'],
                    "⚠️ Daily limit reached (50 messages)!\n"
                    "Upgrade to Premium for unlimited forwarding:\n"
                    "/subscribe"
                )
            except:
                pass
            continue
        
        try:
            await message.forward(rule['dest_chat_id'])
        except Exception as e:
            logger.error(f"Forward error: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 **Help & Support**

**Setup Steps:**
1. Add bot as admin to source channel
2. Add bot as admin to destination channel
3. Use /add\_forward to link them
4. Done! Messages auto-forward

**Commands:**
/start - Start bot
/add\_forward - Create forwarding rule
/my\_forwards - View active forwards
/delete\_forward ID - Remove forward rule
/subscribe - Upgrade to premium
/pay email - Generate payment link
/verify REF - Verify payment
/help - This message

**Need help?** Contact: @YourSupportUsername
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

# Callback query handlers
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_forward":
        await add_forward_start(query.message, context)
    elif query.data == "my_forwards":
        await my_forwards_command(query.message, context)
    elif query.data == "subscribe":
        await subscribe_command(query.message, context)

# Main function
def main():
    print("🚀 Initializing bot...")
    init_db()
    print("✅ Database initialized")
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Conversation handler for adding forwards
    add_forward_conv = ConversationHandler(
        entry_points=[CommandHandler('add_forward', add_forward_start)],
        states={
            SOURCE_CHAT: [MessageHandler(filters.TEXT | filters.FORWARDED, source_chat_received)],
            DEST_CHAT: [MessageHandler(filters.TEXT | filters.FORWARDED, dest_chat_received)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("pay", pay_command))
    application.add_handler(CommandHandler("verify", verify_command))
    application.add_handler(CommandHandler("my_forwards", my_forwards_command))
    application.add_handler(CommandHandler("delete_forward", delete_forward_command))
    application.add_handler(add_forward_conv)
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Message forwarder (must be last)
    application.add_handler(MessageHandler(
        filters.Chat(chat_id=[]) | filters.ALL,  # Will match all chats
        forward_message_handler
    ), group=1)
    
    print("✅ Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()