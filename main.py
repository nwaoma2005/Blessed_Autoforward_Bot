import os
import asyncio
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import psycopg2
from psycopg2.extras import RealDictCursor
import requests

# Bot Configuration
API_ID = os.getenv("API_ID")  # Get from my.telegram.org
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Paystack Configuration
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")

# Subscription Pricing (in Kobo - Nigerian currency)
MONTHLY_PRICE = 150000  # ₦7,000 = 700000 kobo
PLAN_NAME = "Premium Monthly"

# Initialize bot
app = Client("forwarder_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Database connection
def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# Initialize database tables
def init_db():
    conn = get_db()
    cur = conn.cursor()
    
    # Users table
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
    
    # Forwarding rules table
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
    
    # Payment transactions table
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

# Check if user exists, create if not
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

# Reset daily message count
def reset_daily_limit(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET daily_messages = 0, last_reset = CURRENT_TIMESTAMP WHERE user_id = %s",
        (user_id,)
    )
    conn.commit()
    conn.close()

# Check and update message limit
def check_message_limit(user_id):
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    
    # Check if 24 hours passed, reset counter
    if user['last_reset'] and (datetime.now() - user['last_reset']).days >= 1:
        reset_daily_limit(user_id)
        user['daily_messages'] = 0
    
    # Premium users have unlimited
    if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
        conn.close()
        return True
    
    # Free users: 50/day limit
    if user['daily_messages'] >= 50:
        conn.close()
        return False
    
    # Increment counter
    cur.execute(
        "UPDATE users SET daily_messages = daily_messages + 1 WHERE user_id = %s",
        (user_id,)
    )
    conn.commit()
    conn.close()
    return True

# Generate Paystack payment link
def generate_payment_link(user_id, email):
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
        "callback_url": f"https://t.me/{app.username}",
        "metadata": {
            "user_id": user_id,
            "plan": PLAN_NAME
        }
    }
    
    response = requests.post(url, json=data, headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        
        # Save transaction
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

# Verify payment
def verify_payment(reference):
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        if result['data']['status'] == 'success':
            return True, result['data']['metadata']['user_id']
    
    return False, None

# Activate premium subscription
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

# Bot Commands

@app.on_message(filters.command("start"))
async def start_command(client, message):
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    
    welcome_text = f"""
🚀 **Welcome to Auto Forwarder Bot!**

**How it works:**
1. Add me as admin to your source channel/group
2. Add me as admin to your destination channel/group
3. Use /add_forward to create forwarding rule
4. Messages will auto-forward! 🔥

**Your Plan:** {"✨ Premium" if user['is_premium'] else "🆓 Free (50 msgs/day)"}
**Today's Messages:** {user['daily_messages']}/50

**Commands:**
/add_forward - Create new forwarding rule
/my_forwards - View your active forwards
/delete_forward - Remove a forwarding rule
/subscribe - Upgrade to Premium
/help - Get help

💎 **Premium Benefits ($7/month):**
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
    
    await message.reply_text(welcome_text, reply_markup=keyboard)

@app.on_message(filters.command("subscribe"))
async def subscribe_command(client, message):
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    
    if user['is_premium'] and user['subscription_end'] and user['subscription_end'] > datetime.now():
        remaining = (user['subscription_end'] - datetime.now()).days
        await message.reply_text(f"✨ You're already Premium! {remaining} days remaining.")
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
Click the button below to pay with Paystack.
After payment, send me your email used for payment with:
/verify your@email.com
    """
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay with Paystack", callback_data="pay_now")]
    ])
    
    await message.reply_text(subscribe_text, reply_markup=keyboard)

@app.on_callback_query(filters.regex("pay_now"))
async def pay_now_callback(client, callback_query):
    await callback_query.message.reply_text(
        "Please send your email address for payment:\n\n"
        "Example: /pay youremail@gmail.com"
    )

@app.on_message(filters.command("pay"))
async def pay_command(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide your email:\n/pay youremail@gmail.com")
        return
    
    email = message.command[1]
    
    payment_url, reference = generate_payment_link(message.from_user.id, email)
    
    if payment_url:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Now (₦7,000)", url=payment_url)]
        ])
        
        await message.reply_text(
            f"✅ **Payment Link Generated!**\n\n"
            f"Amount: ₦7,000\n"
            f"Reference: `{reference}`\n\n"
            f"After payment, use:\n"
            f"/verify {reference}",
            reply_markup=keyboard
        )
    else:
        await message.reply_text("❌ Failed to generate payment link. Try again.")

@app.on_message(filters.command("verify"))
async def verify_command(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide payment reference:\n/verify SUB_xxxxx")
        return
    
    reference = message.command[1]
    
    success, user_id = verify_payment(reference)
    
    if success and str(user_id) == str(message.from_user.id):
        activate_premium(message.from_user.id)
        
        # Update transaction status
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE transactions SET status = 'success' WHERE reference = %s",
            (reference,)
        )
        conn.commit()
        conn.close()
        
        await message.reply_text(
            "🎉 **Payment Successful!**\n\n"
            "✨ You're now Premium for 30 days!\n"
            "Enjoy unlimited forwarding! 🚀"
        )
    else:
        await message.reply_text("❌ Payment verification failed. Contact support.")

@app.on_message(filters.command("add_forward"))
async def add_forward_command(client, message):
    user = get_or_create_user(message.from_user.id, message.from_user.username)
    
    # Check rule limit for free users
    if not user['is_premium']:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as count FROM forwarding_rules WHERE user_id = %s AND is_active = TRUE",
            (message.from_user.id,)
        )
        count = cur.fetchone()['count']
        conn.close()
        
        if count >= 1:
            await message.reply_text(
                "⚠️ Free plan allows only 1 forwarding rule.\n"
                "Upgrade to Premium for unlimited rules!\n\n"
                "/subscribe"
            )
            return
    
    await message.reply_text(
        "📝 **Add Forwarding Rule**\n\n"
        "1. Add me as admin to SOURCE channel/group\n"
        "2. Add me as admin to DESTINATION channel/group\n"
        "3. Send source channel username or ID\n\n"
        "Example: @mynewschannel or -1001234567890"
    )

@app.on_message(filters.command("my_forwards"))
async def my_forwards_command(client, message):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM forwarding_rules WHERE user_id = %s AND is_active = TRUE",
        (message.from_user.id,)
    )
    rules = cur.fetchall()
    conn.close()
    
    if not rules:
        await message.reply_text("📭 You have no active forwarding rules.\n\nUse /add_forward to create one!")
        return
    
    text = "📋 **Your Active Forwards:**\n\n"
    for idx, rule in enumerate(rules, 1):
        text += f"{idx}. {rule['source_chat_title']} → {rule['dest_chat_title']}\n"
    
    await message.reply_text(text)

# Message forwarder (this runs for every message in channels where bot is admin)
@app.on_message(filters.channel | filters.group)
async def forward_message(client, message):
    # Get forwarding rules for this source chat
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM forwarding_rules WHERE source_chat_id = %s AND is_active = TRUE",
        (message.chat.id,)
    )
    rules = cur.fetchall()
    conn.close()
    
    for rule in rules:
        # Check message limit
        if not check_message_limit(rule['user_id']):
            # Notify user about limit (only once per day)
            try:
                await client.send_message(
                    rule['user_id'],
                    "⚠️ Daily limit reached (50 messages)!\n"
                    "Upgrade to Premium for unlimited forwarding:\n"
                    "/subscribe"
                )
            except:
                pass
            continue
        
        # Forward the message
        try:
            await message.forward(rule['dest_chat_id'])
        except Exception as e:
            print(f"Forward error: {e}")

@app.on_message(filters.command("help"))
async def help_command(client, message):
    help_text = """
📚 **Help & Support**

**Setup Steps:**
1. Add bot as admin to source channel
2. Add bot as admin to destination channel
3. Use /add_forward to link them
4. Done! Messages auto-forward

**Commands:**
/start - Start bot
/add_forward - Create forwarding rule
/my_forwards - View active forwards
/delete_forward - Remove forward rule
/subscribe - Upgrade to premium
/help - This message

**Need help?** Contact: @YourSupportUsername
    """
    await message.reply_text(help_text)

# Run bot
if __name__ == "__main__":
    print("🚀 Bot starting...")
    init_db()
    print("✅ Database initialized")
    app.run()
    print("✅ Bot running!")