# 🤖 Telegram Auto Forwarder Bot

A professional Telegram bot that automatically forwards messages between channels/groups with a freemium subscription model powered by Paystack.

![Python](https://img.shields.io/badge/python-v3.9+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)

## ✨ Features

### 🆓 Free Plan
- ✅ 1 forwarding rule
- ✅ 50 messages per day
- ✅ Basic forwarding
- ✅ Easy setup

### 💎 Premium Plan (₦7,000/month)
- ✅ Unlimited forwarding rules
- ✅ Unlimited messages
- ✅ Priority processing
- ✅ Advanced features (coming soon)
- ✅ Priority support

## 🚀 Quick Start

### For Users

1. **Start the bot**: Search for `@YourBotUsername` on Telegram
2. **Add bot as admin** to your source channel
3. **Add bot as admin** to your destination channel
4. **Create rule**: Use `/add_forward` command
5. **Done!** Messages now auto-forward

### For Developers

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for full deployment instructions.

## 📋 Commands

| Command | Description |
|---------|-------------|
| `/start` | Start bot & view overview |
| `/add_forward` | Create new forwarding rule |
| `/my_forwards` | View active forwarding rules |
| `/delete_forward` | Remove a forwarding rule |
| `/subscribe` | Upgrade to Premium |
| `/pay <email>` | Generate payment link |
| `/verify <ref>` | Verify payment |
| `/stats` | View your statistics |
| `/help` | Get help |

## 🛠️ Technical Details

### Architecture
- **Language**: Python 3.9+
- **Framework**: python-telegram-bot 21.5
- **Storage**: JSON file-based (no database required!)
- **Payment**: Paystack API integration
- **Hosting**: Optimized for Render free tier

### Storage
All data stored in JSON files:
- `data/users.json` - User profiles
- `data/rules.json` - Forwarding rules
- `data/transactions.json` - Payment records

### Requirements
```
python-telegram-bot==21.5
python-dotenv==1.0.0
requests==2.31.0
```

## 🔧 Setup & Deployment

### 1. Clone Repository
```bash
git clone https://github.com/yourusername/telegram-autoforward-bot.git
cd telegram-autoforward-bot
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Run Locally
```bash
python bot.py
```

### 5. Deploy to Render
See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for detailed instructions.

## 🌐 Deployment Options

### ☁️ Render (Recommended)
- Free tier available
- Auto-deploys from GitHub
- Simple environment variable management
- **[Deploy Now →](https://render.com)**

### 🐳 Docker (Alternative)
```bash
docker build -t autoforward-bot .
docker run -d --env-file .env autoforward-bot
```

### 🖥️ VPS (Manual)
```bash
# Install Python 3.9+
sudo apt update && sudo apt install python3.9
# Clone repo and run
git clone <repo>
python3 bot.py
```

## 📊 Features Comparison

| Feature | Free | Premium |
|---------|------|---------|
| Forwarding Rules | 1 | Unlimited |
| Messages/Day | 50 | Unlimited |
| Priority Processing | ❌ | ✅ |
| Advanced Filters | ❌ | Coming Soon |
| Remove "Forwarded" Tag | ❌ | Coming Soon |
| Support | Basic | Priority |

## 🔐 Security

- ✅ Environment variables for sensitive data
- ✅ Rate limiting on commands
- ✅ User authentication
- ✅ Secure payment processing
- ✅ No database = no SQL injection risk

## 🐛 Known Limitations

1. **Free Tier Sleep**: Render free tier sleeps after 15 min inactivity
   - **Solution**: Use UptimeRobot to ping every 5 minutes

2. **Data Persistence**: May lose data on restart (free tier)
   - **Solution**: Upgrade to paid tier or implement backup system

3. **Rate Limits**: Telegram API limits apply
   - **Solution**: Built-in rate limiting to prevent bans

## 🛡️ Error Handling

The bot includes comprehensive error handling for:
- ❌ Invalid chat IDs
- ❌ Missing admin permissions
- ❌ Network failures
- ❌ Payment failures
- ❌ Rate limit violations

## 📈 Roadmap

- [ ] Advanced filtering (keywords, media types)
- [ ] Remove "Forwarded from" tag
- [ ] Scheduled forwarding
- [ ] Bulk operations
- [ ] Statistics dashboard
- [ ] Multi-language support
- [ ] Webhook notifications

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/repo/issues)
- **Telegram**: [@YourSupportUsername](https://t.me/YourSupportUsername)
- **Email**: support@yourdomain.com

## 🙏 Acknowledgments

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) - Telegram Bot API wrapper
- [Paystack](https://paystack.com) - Payment processing
- [Render](https://render.com) - Cloud hosting

---

**Made with Blessed Nwamoma for the Telegram community**

⭐ **Star this repo if you find it useful!**