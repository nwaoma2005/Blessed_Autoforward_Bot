# 🚀 Deployment Guide - Auto Forwarder Bot

## 📋 Prerequisites

1. **Telegram Bot Token** - Get from [@BotFather](https://t.me/BotFather)
2. **Paystack Account** - Get API keys from [Paystack Dashboard](https://dashboard.paystack.com/)
3. **Render Account** - Sign up at [render.com](https://render.com) (Free)

---

## 🎯 Step-by-Step Deployment

### 1️⃣ Create Your Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name: `My Auto Forwarder`
4. Choose a username: `my_autoforward_bot`
5. **Copy the bot token** (looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2️⃣ Get Paystack API Keys

1. Go to [Paystack Dashboard](https://dashboard.paystack.com/)
2. Navigate to **Settings → API Keys & Webhooks**
3. Copy your **Secret Key** (starts with `sk_test_` or `sk_live_`)
4. Copy your **Public Key** (starts with `pk_test_` or `pk_live_`)

### 3️⃣ Prepare Your Code

1. Create a new folder on your computer
2. Save these files:
   - `bot.py` (the main bot code)
   - `requirements.txt`
   - `.env.example` (rename to `.env` for local testing)

### 4️⃣ Deploy to Render

#### Option A: Deploy via GitHub (Recommended)

1. **Create GitHub Repository**
   - Go to [github.com](https://github.com/new)
   - Create a new repository: `telegram-autoforward-bot`
   - Upload your files: `bot.py`, `requirements.txt`, `render.yaml`

2. **Connect to Render**
   - Go to [render.com](https://dashboard.render.com/)
   - Click **"New +"** → **"Web Service"**
   - Connect your GitHub account
   - Select your repository

3. **Configure Environment Variables**
   - In Render dashboard, go to **Environment**
   - Add these variables:
     ```
     BOT_TOKEN = your_bot_token_from_botfather
     PAYSTACK_SECRET_KEY = sk_test_your_secret_key
     PAYSTACK_PUBLIC_KEY = pk_test_your_public_key
     PORT = 8443
     ```

4. **Deploy**
   - Click **"Create Web Service"**
   - Wait 2-5 minutes for deployment
   - Check logs for "✅ Bot started successfully!"

#### Option B: Deploy Directly (No GitHub)

1. Go to [render.com](https://dashboard.render.com/)
2. Click **"New +"** → **"Web Service"**
3. Choose **"Deploy an existing image from a registry"** or **"Public Git repository"**
4. If using public repo: Use this template: `https://github.com/yourusername/telegram-bot`
5. Add environment variables as shown above
6. Deploy!

### 5️⃣ Configure Your Bot

1. **Start your bot** on Telegram
2. Send `/start` to see if it's working
3. **Make yourself admin** (optional):
   - Open `bot.py`
   - Find line: `ADMIN_IDS = [123456789]`
   - Replace with your Telegram user ID (get it from [@userinfobot](https://t.me/userinfobot))

---

## 🔧 Configuration Options

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ Yes | Your Telegram bot token |
| `PAYSTACK_SECRET_KEY` | ✅ Yes | Paystack secret key |
| `PAYSTACK_PUBLIC_KEY` | ❌ No | Paystack public key (for reference) |
| `WEBHOOK_URL` | ❌ No | For webhook mode (optional) |
| `PORT` | ❌ No | Port number (default: 8443) |

### Running Modes

**Polling Mode (Default)**
- No webhook URL needed
- Works everywhere
- Uses more resources
- Good for free tier

**Webhook Mode (Production)**
- Set `WEBHOOK_URL` environment variable
- More efficient
- Better for high traffic
- Example: `https://your-app.onrender.com`

---

## 📂 File Structure

```
your-bot/
├── bot.py                 # Main bot code
├── requirements.txt       # Python dependencies
├── render.yaml           # Render configuration
├── .env                  # Environment variables (local only)
├── .gitignore           # Ignore data and env files
└── data/                # Auto-created for storage
    ├── users.json       # User data
    ├── rules.json       # Forwarding rules
    └── transactions.json # Payment records
```

---

## 🐛 Troubleshooting

### Bot won't start
- ✅ Check if `BOT_TOKEN` is correct
- ✅ Check Render logs for errors
- ✅ Ensure `requirements.txt` has all dependencies

### Payment not working
- ✅ Verify Paystack keys are correct
- ✅ Check if using test mode (`sk_test_`) or live mode (`sk_live_`)
- ✅ Ensure Paystack account is verified

### Forwarding not working
- ✅ Bot must be admin in BOTH source and destination chats
- ✅ Bot needs "Read Messages" permission in source
- ✅ Bot needs "Send Messages" permission in destination
- ✅ Check if daily limit reached (free tier: 50 messages/day)

### Data not persisting
- ✅ Render free tier may restart your app
- ✅ Data is saved in `data/` folder
- ✅ For permanent storage, upgrade to paid tier or use external database

### App keeps sleeping (Render Free Tier)
- ✅ Free tier sleeps after 15 minutes of inactivity
- ✅ Use a service like [UptimeRobot](https://uptimerobot.com/) to ping your app every 5 minutes
- ✅ Or upgrade to paid tier ($7/month)

---

## 🎯 Post-Deployment Checklist

- [ ] Bot responds to `/start`
- [ ] Can create forwarding rules
- [ ] Messages forward correctly
- [ ] Payment links generate
- [ ] Premium activation works
- [ ] Data persists after restart
- [ ] Logs show no errors

---

## 💡 Tips for Free Tier

1. **Data Persistence**: Render free tier may lose data on restart. For production, consider:
   - Upgrading to paid tier ($7/month)
   - Using external storage (Google Drive, Dropbox API)
   - Backing up `data/` folder regularly

2. **Keep App Awake**: Use [UptimeRobot](https://uptimerobot.com/) to ping your Render URL every 5 minutes

3. **Monitor Usage**: Free tier has 750 hours/month (enough for 24/7 operation)

4. **Optimize**: Bot uses minimal resources with JSON storage

---

## 🆘 Support

If you encounter issues:

1. Check Render logs: Dashboard → Your Service → Logs
2. Test locally first: `python bot.py`
3. Verify all environment variables are set
4. Ensure bot token is valid
5. Check Paystack dashboard for transaction status

---

## 🔐 Security Best Practices

- ✅ Never commit `.env` file to GitHub
- ✅ Use test keys for development
- ✅ Switch to live keys only for production
- ✅ Add your user ID to `ADMIN_IDS` for admin commands
- ✅ Keep your bot token secret

---

## 📈 Upgrading to Production

When ready for production:

1. **Switch to Live Keys**: Use `sk_live_` and `pk_live_`
2. **Enable Webhook**: Set `WEBHOOK_URL` environment variable
3. **Upgrade Render**: Consider paid tier for reliability
4. **Monitor**: Set up error tracking
5. **Backup**: Regular backups of `data/` folder

---

## 🎉 Success!

Your bot is now live! Test it by:
1. Adding bot to two channels as admin
2. Creating a forwarding rule with `/add_forward`
3. Sending a test message in source channel
4. Verifying it appears in destination channel

**Enjoy your Auto Forwarder Bot! 🚀**