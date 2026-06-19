<div align="center">
<img width="1200" height="475" alt="WhatsApp Bot Banner" src="https://via.placeholder.com/1200x475?text=WhatsApp+MD+Bot+Runner+Manager" />

# 🤖 WhatsApp MD Bot Runner Manager

**An Advanced WhatsApp Bot Management System with AI Integration**

[![Node.js](https://img.shields.io/badge/Node.js-Required-green?style=flat-square)](https://nodejs.org/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](#license)
[![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square)](#)

</div>

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Project](#running-the-project)
- [Project Structure](#project-structure)
- [Bot Runner Architecture](#bot-runner-architecture)
- [WhatsApp Integration](#whatsapp-integration)
- [Usage Guide](#usage-guide)
- [API Documentation](#api-documentation)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## 🎯 Overview

**WhatsApp MD Bot Runner Manager** is a comprehensive bot management system designed to handle multiple WhatsApp bot instances simultaneously. This project provides a robust framework for deploying, monitoring, and managing autonomous WhatsApp bots using the Multi-Device (MD) protocol.

The system is built to be scalable, modular, and developer-friendly, enabling you to create sophisticated chatbots and automation tools for WhatsApp without complexity.

### Key Objectives:
- 🚀 **Multi-Bot Management** - Run and control multiple bot instances
- 💬 **WhatsApp MD Protocol** - Full support for modern WhatsApp multi-device
- 🎨 **Beautiful UI** - Intuitive dashboard for bot management
- ⚡ **Fast & Reliable** - Production-ready performance
- 🔧 **Easy Configuration** - Simple setup and deployment

---

## ✨ Features

### Core Bot Management
- ✅ **Multi-Instance Support** - Run multiple WhatsApp bots simultaneously
- ✅ **Bot Runner Control** - Start, stop, restart bot instances
- ✅ **Real-time Monitoring** - Track bot status and activity
- ✅ **Process Management** - Automatic recovery and failover
- ✅ **Logging & Analytics** - Comprehensive activity logs

### WhatsApp Integration
- ✅ **MD Protocol Support** - Full multi-device WhatsApp support
- ✅ **Message Handling** - Process text, media, and group messages
- ✅ **Auto-Reply System** - Configure automatic responses
- ✅ **Group Management** - Handle group chats and members
- ✅ **Contact Management** - Maintain and organize contacts
- ✅ **Message Scheduling** - Schedule messages for later delivery

### Intelligence & Automation
- ✅ **AI Integration Ready** - Support for AI/ML models
- ✅ **Custom Command System** - Create custom bot commands
- ✅ **Webhooks Support** - Integrate with external services
- ✅ **Rate Limiting** - Built-in protection and throttling
- ✅ **Error Handling** - Robust error recovery mechanisms

### Developer Features
- ✅ **Hot Reload** - Development server with auto-refresh
- ✅ **Environment Configuration** - Secure .env setup
- ✅ **Modular Architecture** - Clean, maintainable codebase
- ✅ **API Routes** - RESTful endpoints for management
- ✅ **Plugin System** - Extensible architecture for custom plugins

---

## 🛠️ Tech Stack

### Frontend & UI
| Technology | Purpose |
|-----------|---------|
| **React** | UI framework |
| **Next.js** | Full-stack framework |
| **Tailwind CSS** | Styling & design |

### Backend & Runtime
| Technology | Purpose |
|-----------|---------|
| **Node.js** | JavaScript runtime |
| **Express** | Web framework |
| **NPM** | Package management |

### WhatsApp Integration
| Technology | Purpose |
|-----------|---------|
| **WhatsApp Web API** | Message protocol |
| **MD Protocol** | Multi-device support |
| **QR Code Auth** | Secure authentication |

### Database & Storage
| Technology | Purpose |
|-----------|---------|
| **JSON/File Store** | Local data storage |
| **Session Management** | Bot session persistence |

---

## 📦 Prerequisites

Before you begin, ensure you have the following installed on your system:

### System Requirements
- **Operating System**: Windows, macOS, or Linux
- **RAM**: Minimum 2GB (4GB recommended for multiple bots)
- **Storage**: At least 500MB free space
- **Internet**: Stable, high-speed connection

### Required Software
- **Node.js** (v14.0.0 or higher) - [Download](https://nodejs.org/)
- **NPM** (v6.0.0 or higher) - Included with Node.js
- **Git** (optional, for cloning) - [Download](https://git-scm.com/)

### Required Accounts & Access
- **WhatsApp Account** - Working WhatsApp account with active phone number
- **Phone Number** - For WhatsApp authentication via QR code
- **Text Editor** - For configuration files (VS Code recommended)

---

## 🚀 Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager.git
cd Whatsapp-MD-bot-Runner-Manager
```

Or download as ZIP and extract:
```bash
unzip Whatsapp-MD-bot-Runner-Manager.zip
cd Whatsapp-MD-bot-Runner-Manager
```

### Step 2: Install Dependencies

```bash
npm install
```

**What gets installed:**
- WhatsApp protocol handlers (Baileys/etc)
- Express web server
- React & Next.js framework
- Database drivers
- Utility libraries
- Development tools

### Step 3: Verify Installation

```bash
# Check Node.js version
node --version
# Output should be v14.0.0 or higher

# Check NPM version
npm --version
# Output should be v6.0.0 or higher

# Check installed packages
npm list
```

### Step 4: Complete Setup

```bash
# Optional: Install additional optional dependencies
npm install --save-dev nodemon

# Verify everything works
npm run dev
```

---

## ⚙️ Configuration

### Basic Configuration (.env.local)

Create a `.env.local` file in the project root:

```bash
touch .env.local
```

### Environment Variables

Add these configurations to `.env.local`:

```env
# ============================================
# SERVER CONFIGURATION
# ============================================
PORT=3000
NODE_ENV=development
HOST=0.0.0.0

# ============================================
# BOT SETTINGS
# ============================================
BOT_NAME=MyWhatsAppBot
BOT_PREFIX=!
AUTO_RESPONSE=true
MAX_BOT_INSTANCES=5

# ============================================
# WHATSAPP CONFIGURATION
# ============================================
WHATSAPP_AUTO_RECONNECT=true
WHATSAPP_RECONNECT_TIMEOUT=5000
SESSION_STORAGE_PATH=./sessions

# ============================================
# MESSAGE HANDLING
# ============================================
MESSAGE_QUEUE_SIZE=1000
MESSAGE_TIMEOUT=30000
ENABLE_MEDIA_HANDLING=true

# ============================================
# LOGGING & DEBUGGING
# ============================================
LOG_LEVEL=info
DEBUG_MODE=false
SAVE_LOGS=true
LOG_FILE_PATH=./logs

# ============================================
# SECURITY
# ============================================
ENABLE_MESSAGE_ENCRYPTION=true
API_KEY=your_secret_key_here
```

### Advanced Configuration

#### Bot Runner Configuration (`config/bots.json`)

```json
{
  "bots": [
    {
      "id": "bot_001",
      "name": "Support Bot",
      "enabled": true,
      "autoStart": true,
      "settings": {
        "prefix": "!",
        "responseTimeout": 5000,
        "maxRetries": 3
      }
    },
    {
      "id": "bot_002",
      "name": "Notification Bot",
      "enabled": true,
      "autoStart": true,
      "settings": {
        "prefix": "~",
        "responseTimeout": 10000,
        "maxRetries": 2
      }
    }
  ]
}
```

#### Security Considerations

⚠️ **IMPORTANT SECURITY NOTES:**

1. **Never commit `.env.local` to version control**
   ```bash
   # Add to .gitignore
   echo ".env.local" >> .gitignore
   ```

2. **Protect your API keys**
   - Keep credentials private
   - Use strong, random API keys
   - Rotate keys regularly

3. **Session Security**
   - Store sessions in secure locations
   - Clear old sessions periodically
   - Use encryption for sensitive data

4. **Rate Limiting**
   - Implement request throttling
   - Protect against abuse
   - Monitor for suspicious activity

---

## 🎮 Running the Project

### Development Mode

Start the development server with auto-reload:

```bash
npm run dev
```

**Expected Output:**
```
> Whatsapp-MD-bot-Runner-Manager@1.0.0 dev
> next dev

ready - started server on 0.0.0.0:3000, url: http://localhost:3000
```

Access the dashboard: `http://localhost:3000`

### Production Mode

Build and run for production:

```bash
# Build the project
npm run build

# Start production server
npm start
```

### Available NPM Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server with hot reload |
| `npm run build` | Create optimized production build |
| `npm start` | Run production build |
| `npm run lint` | Check code quality and style |
| `npm test` | Run test suite |
| `npm run format` | Format code with prettier |

### Running Multiple Bot Instances

```bash
# Terminal 1: Start main server
npm run dev

# Terminal 2: Start additional bot runner (if supported)
npm run start-bot -- --id bot_001

# Terminal 3: Start another bot instance
npm run start-bot -- --id bot_002
```

---

## 📁 Project Structure

```
Whatsapp-MD-bot-Runner-Manager/
│
├── 📄 Configuration Files
│   ├── .env.local                    # Environment variables (DO NOT COMMIT)
│   ├── .gitignore                    # Git ignore rules
│   ├── package.json                  # Project dependencies
│   ├── package-lock.json             # Dependency lock file
│   └── README.md                     # This file
│
├── 📁 pages/                         # Next.js Application
│   ├── api/                          # Backend API Routes
│   │   ├── bots/                    # Bot management endpoints
│   │   │   ├── start.js            # Start bot instance
│   │   │   ├── stop.js             # Stop bot instance
│   │   │   ├── status.js           # Get bot status
│   │   │   └── list.js             # List all bots
│   │   ├── messages/               # Message handling
│   │   │   ├── send.js             # Send message
│   │   │   ├── history.js          # Message history
│   │   │   └── queue.js            # Message queue
│   │   ├── sessions/               # Session management
│   │   │   ├── create.js           # Create session
│   │   │   ├── restore.js          # Restore session
│   │   │   └── delete.js           # Delete session
│   │   └── health.js               # Health check endpoint
│   │
│   ├── dashboard/                   # Dashboard Pages
│   │   ├── index.js                # Main dashboard
│   │   ├── bots.js                 # Bots management page
│   │   ├── messages.js             # Messages page
│   │   └── settings.js             # Settings page
│   │
│   ├── _app.js                     # App wrapper & global config
│   ├── _document.js                # Document template
│   └── index.js                    # Home page
│
├── 📁 components/                   # React Components
│   ├── layouts/
│   │   ├── MainLayout.jsx          # Main layout wrapper
│   │   └── DashboardLayout.jsx     # Dashboard layout
│   │
│   ├── dashboard/
│   │   ├── BotCard.jsx             # Bot status card
│   │   ├── BotList.jsx             # Bot listing component
│   │   ├── BotControls.jsx         # Bot control buttons
│   │   ├── StatusIndicator.jsx     # Status display
│   │   └── BotMetrics.jsx          # Bot statistics
│   │
│   ├── messages/
│   │   ├── MessageInput.jsx        # Message input form
│   │   ├── MessageDisplay.jsx      # Message viewer
│   │   ├── ChatInterface.jsx       # Chat interface
│   │   └── MessageHistory.jsx      # History viewer
│   │
│   ├── common/
│   │   ├── Button.jsx              # Reusable button
│   │   ├── Modal.jsx               # Modal dialog
│   │   ├── Alert.jsx               # Alert component
│   │   ├── Spinner.jsx             # Loading spinner
│   │   └── Header.jsx              # Header component
│   │
│   └── settings/
│       ├── SettingsForm.jsx        # Settings editor
│       ├── BotConfig.jsx           # Bot configuration
│       └── SecuritySettings.jsx    # Security settings
│
├── 📁 lib/                          # Utility Libraries
│   ├── whatsapp/
│   │   ├── client.js               # WhatsApp client
│   │   ├── handlers.js             # Message handlers
│   │   ├── auth.js                 # Authentication
│   │   └── utils.js                # WhatsApp utilities
│   │
│   ├── botRunner/
│   │   ├── manager.js              # Bot manager
│   │   ├── runner.js               # Individual runner
│   │   ├── scheduler.js            # Task scheduling
│   │   └── logger.js               # Logging system
│   │
│   ├── api/
│   │   ├── client.js               # API client
│   │   └── endpoints.js            # API definitions
│   │
│   ├── database/
│   │   ├── storage.js              # Data storage
│   │   └── queries.js              # Query helpers
│   │
│   ├── utils/
│   │   ├── helpers.js              # General helpers
│   │   ├── validators.js           # Input validation
│   │   ├── formatters.js           # Data formatting
│   │   └── constants.js            # App constants
│   │
│   └── middleware/
│       ├── auth.js                 # Authentication
│       ├── errorHandler.js         # Error handling
│       └── logger.js               # Request logging
│
├── 📁 public/                       # Static Assets
│   ├── favicon.ico                 # Site favicon
│   ├── robots.txt                  # SEO robots
│   ├── images/
│   │   ├── logo.png               # App logo
│   │   └── banner.png             # Banner image
│   └── styles/
│       └── globals.css            # Global styles (if any)
│
├── 📁 styles/                       # CSS/Styling
│   ├── globals.css                # Global styles
│   ├── variables.css              # CSS variables
│   ├── components/                # Component styles
│   │   ├── dashboard.module.css   # Dashboard styles
│   │   ├── messages.module.css    # Message styles
│   │   └── buttons.module.css     # Button styles
│   └── themes/
│       ├── light.css              # Light theme
│       └── dark.css               # Dark theme
│
├── 📁 config/                       # Configuration Files
│   ├── bots.json                  # Bot configuration
│   ├── commands.json              # Command definitions
│   └── webhooks.json              # Webhook settings
│
├── 📁 sessions/                     # WhatsApp Sessions (Generated)
│   ├── bot_001/
│   └── bot_002/
│
├── 📁 logs/                         # Application Logs (Generated)
│   ├── app.log                    # General logs
│   ├── errors.log                 # Error logs
│   └── whatsapp.log               # WhatsApp logs
│
└── 📁 scripts/                      # Utility Scripts
    ├── setup.js                   # Setup script
    ├── migrate.js                 # Data migration
    └── cleanup.js                 # Cleanup script
```

---

## 🏗️ Bot Runner Architecture

### System Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│          WhatsApp MD Bot Runner Manager                 │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────────┐                                     │
│  │  Dashboard UI  │ ← React Components                  │
│  └────────┬───────┘                                     │
│           │                                              │
│  ┌────────▼────────────────────────────────────┐       │
│  │   Next.js API Routes & Server                │       │
│  │  (Message Handler, Bot Manager, etc)         │       │
│  └────────┬────────────────────────────────────���┘       │
│           │                                              │
│  ┌────────▼──────────────────────────────────┐         │
│  │   Bot Runner Manager                      │         │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐  │         │
│  │  │ Bot #1   │ │ Bot #2   │ │ Bot #N   │  │         │
│  │  └──────────┘ └──────────┘ └──────────┘  │         │
│  └────────┬──────────────────────────────────┘         │
│           │                                              │
│  ┌────────▼────────────────────────────────────┐       │
│  │  WhatsApp Protocol Handler (MD)             │       │
│  │  ├─ Message Processing                     │       │
│  │  ├─ QR Code Authentication                 │       │
│  │  ├─ Session Management                     │       │
│  │  └─ Contact & Group Management             │       │
│  └────────┬─────────────────────────────────────┘       │
│           │                                              │
│  ┌────────▼──────────────────────────────────────┐     │
│  │      WhatsApp Web Infrastructure             │     │
│  └──────────────────────────────────────────────┘     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Bot Runner Lifecycle

```
START
  │
  ├─→ Load Configuration
  │
  ├─→ Initialize WhatsApp Client
  │
  ├─→ Generate/Scan QR Code
  │
  ├─→ Authenticate Session
  │
  ├─→ Load Message Handlers
  │
  ├─→ Start Message Listener
  │
  └─→ RUNNING (Accept Messages)
      │
      ├─→ Process Incoming Messages
      │
      ├─→ Execute Commands
      │
      ├─→ Send Responses
      │
      └─→ STOP (on command or error)
```

---

## 💬 WhatsApp Integration

### Message Flow

```
WhatsApp Server
      ↓
   MD Protocol
      ↓
Bot Client (WhatsApp Web)
      ↓
Message Handler
      ↓
Command Parser
      ↓
Response Generator
      ↓
Message Sender
      ↓
WhatsApp Server
```

### Supported Message Types

| Type | Support | Description |
|------|---------|-------------|
| Text | ✅ | Plain text messages |
| Image | ✅ | Image media files |
| Video | ✅ | Video files |
| Audio | ✅ | Audio/voice messages |
| Document | ✅ | File attachments |
| Groups | ✅ | Group chat messages |
| Status | ✅ | Status updates |

---

## 💬 Usage Guide

### Starting Your First Bot

#### Step 1: Start the Server
```bash
npm run dev
```

#### Step 2: Access Dashboard
Open browser: `http://localhost:3000`

#### Step 3: Create New Bot Instance
1. Click "New Bot" button
2. Enter bot name and settings
3. Click "Create"

#### Step 4: Authenticate with WhatsApp
1. QR code will appear on screen
2. Open WhatsApp on your phone
3. Go to Settings → Linked Devices
4. Scan the QR code
5. Bot will authenticate automatically

#### Step 5: Send Test Message
1. Message the bot's WhatsApp number
2. Bot will respond with confirmation
3. You can now use bot commands

### Managing Bot Instances

#### View All Bots
```bash
# Via API
curl http://localhost:3000/api/bots/list

# Response:
{
  "bots": [
    {
      "id": "bot_001",
      "name": "Support Bot",
      "status": "running",
      "uptime": "2h 30m"
    }
  ]
}
```

#### Start a Bot
```bash
curl -X POST http://localhost:3000/api/bots/start \
  -H "Content-Type: application/json" \
  -d '{"botId": "bot_001"}'
```

#### Stop a Bot
```bash
curl -X POST http://localhost:3000/api/bots/stop \
  -H "Content-Type: application/json" \
  -d '{"botId": "bot_001"}'
```

#### Get Bot Status
```bash
curl http://localhost:3000/api/bots/status?botId=bot_001
```

### Creating Custom Commands

Create a file `lib/botRunner/commands.js`:

```javascript
module.exports = {
  // Help command
  help: {
    handler: async (message) => {
      return "Available commands: !help, !info, !status";
    }
  },
  
  // Custom greeting
  hello: {
    handler: async (message) => {
      return "Hello! How can I help you today?";
    }
  },
  
  // Echo command
  echo: {
    handler: async (message, args) => {
      return args.join(" ");
    }
  }
};
```

---

## 🔌 API Documentation

### Authentication

All API requests should include authorization:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:3000/api/bots/list
```

### Available Endpoints

#### Bot Management

**List All Bots**
```
GET /api/bots/list
```

**Get Bot Details**
```
GET /api/bots/:botId
```

**Create New Bot**
```
POST /api/bots/create
Body: { name, prefix, settings }
```

**Start Bot**
```
POST /api/bots/start
Body: { botId }
```

**Stop Bot**
```
POST /api/bots/stop
Body: { botId }
```

#### Message API

**Send Message**
```
POST /api/messages/send
Body: { botId, to, message }
```

**Get Message History**
```
GET /api/messages/history?botId=ID&limit=50
```

**Clear Message Queue**
```
POST /api/messages/queue/clear
Body: { botId }
```

#### Sessions

**Create Session**
```
POST /api/sessions/create
Body: { botId }
```

**Get Session**
```
GET /api/sessions/:sessionId
```

**Delete Session**
```
POST /api/sessions/delete
Body: { sessionId }
```

---

## 🐛 Troubleshooting

### Common Issues & Solutions

#### Issue 1: "Cannot find module 'whatsapp-web.js'"

**Solution:**
```bash
# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install
npm run dev
```

#### Issue 2: "QR Code not appearing"

**Causes & Solutions:**
1. Browser compatibility issue
   - Try Chrome/Edge instead of Firefox
   - Clear browser cache

2. Server not running
   - Verify server started: `npm run dev`
   - Check port 3000 is available

3. Port already in use
   ```bash
   # Find and kill process on port 3000
   lsof -ti:3000 | xargs kill -9
   npm run dev
   ```

#### Issue 3: "WhatsApp session keeps disconnecting"

**Solutions:**
1. Check internet connection stability
2. Verify phone has stable connection
3. Don't use account on multiple devices
4. Restart bot: Stop → Wait 5s → Start

#### Issue 4: "Messages not being sent"

**Debug Steps:**
1. Check bot is running
   ```bash
   curl http://localhost:3000/api/bots/status
   ```

2. Verify recipient number format
   - Use format: `+1234567890`
   - Include country code

3. Check message queue
   ```bash
   curl http://localhost:3000/api/messages/queue
   ```

4. Review logs
   ```bash
   cat logs/app.log
   cat logs/errors.log
   ```

#### Issue 5: "Bot not responding to commands"

**Solutions:**
1. Check command prefix in config
2. Ensure bot has message handlers
3. Review command file syntax
4. Check message log for errors

#### Issue 6: "High CPU/Memory usage"

**Optimization:**
1. Limit max bot instances
2. Implement message rate limiting
3. Clear old logs and sessions
   ```bash
   rm -rf logs/* sessions/*/
   ```
4. Monitor resource usage
   ```bash
   npm run monitor
   ```

### Getting Help

1. **Check Logs**
   ```bash
   tail -f logs/app.log
   tail -f logs/errors.log
   ```

2. **Enable Debug Mode**
   ```env
   DEBUG_MODE=true
   LOG_LEVEL=debug
   ```

3. **Restart Everything**
   ```bash
   npm run dev
   ```

---

## 🤝 Contributing

We welcome contributions! Here's how to contribute:

### Fork & Clone
```bash
# Fork the repo on GitHub
# Then clone your fork
git clone https://github.com/YOUR_USERNAME/Whatsapp-MD-bot-Runner-Manager.git
cd Whatsapp-MD-bot-Runner-Manager
```

### Create Feature Branch
```bash
git checkout -b feature/amazing-feature
```

### Make Changes & Commit
```bash
git add .
git commit -m "Add amazing feature: description of changes"
```

### Push to GitHub
```bash
git push origin feature/amazing-feature
```

### Open Pull Request
1. Go to original repository
2. Click "New Pull Request"
3. Select your branch
4. Describe your changes
5. Submit PR

### Code Guidelines

- **Follow existing code style**
- **Add comments for complex logic**
- **Test your changes thoroughly**
- **Update documentation**
- **Keep commits atomic**

### Areas for Contribution

- 🐛 Bug fixes
- ✨ New features
- 📚 Documentation improvements
- 🎨 UI/UX enhancements
- 🔒 Security improvements
- ⚡ Performance optimization

---

## 📄 License

This project is licensed under the **MIT License**.

```
MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

---

## 📞 Support & Contact

- **GitHub Issues**: [Report Issues](https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager/issues)
- **Discussions**: [Join Discussions](https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager/discussions)
- **Email**: Contact via GitHub profile

---

## 🙏 Acknowledgments

- **WhatsApp** - For the WhatsApp platform and MD protocol
- **Baileys Library** - For WhatsApp protocol implementation
- **Node.js & NPM** - For amazing runtime and package management
- **Open Source Community** - For countless libraries and tools
- **All Contributors** - For making this project better

---

## 📈 Project Statistics

- **GitHub Stars**: ⭐ [Give us a star!](https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager)
- **Contributors**: 👥 [Contribute to the project](#contributing)
- **Last Updated**: June 2024
- **Status**: ✅ Active Development

---

## 🔗 Related Resources

- [Node.js Documentation](https://nodejs.org/docs)
- [Next.js Guide](https://nextjs.org/docs)
- [React Documentation](https://react.dev)
- [WhatsApp Developer Info](https://www.whatsapp.com/business/developers)
- [GitHub Guides](https://guides.github.com)

---

<div align="center">

**WhatsApp MD Bot Runner Manager**

Made with ❤️ by the community

[⭐ Star us on GitHub](https://github.com/darksafari6/Whatsapp-MD-bot-Runner-Manager)

</div>
