# Discord Content Scheduler Bot

A Discord bot that automatically posts scheduled content from a Notion database to specified Discord channels.

## Features

- 📅 Schedule posts days/weeks in advance
- 📝 Support for text, images, videos, and links
- 📢 Announcement posts with @everyone mentions  
- 🔄 Automatic queue management (loads 48 hours ahead)
- 📊 Status checking and manual controls
- 🚨 Error handling with status updates in Notion

## Setup Instructions

### 1. Prerequisites
- Discord bot token (from Discord Developer Portal)
- Notion integration token and database ID
- GitHub account (for Render deployment)

### 2. Local Setup

1. **Clone/Download the files:**
   - `discord_scheduler_bot.py` - Main bot code
   - `requirements.txt` - Python dependencies
   - `.env.example` - Environment variables template

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   ```bash
   # Copy the example file
   cp .env.example .env
   
   # Edit .env with your actual tokens:
   DISCORD_TOKEN=your_discord_bot_token_here
   NOTION_TOKEN=your_notion_integration_token_here
   NOTION_DATABASE_ID=your_notion_database_id_here
   ```

4. **Test locally (optional):**
   ```bash
   python discord_scheduler_bot.py
   ```

### 3. Render Deployment (Free 24/7 Hosting)

1. **Create GitHub repository:**
   - Create a new repository on GitHub
   - Upload all the bot files (discord_scheduler_bot.py, requirements.txt, render.yaml)
   - **DO NOT** upload your .env file (it contains secrets)

2. **Deploy on Render:**
   - Go to https://render.com and sign up
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Render will auto-detect the Python app

3. **Set environment variables in Render:**
   - In your Render dashboard, go to "Environment"
   - Add these variables:
     - `DISCORD_TOKEN` = your_discord_bot_token
     - `NOTION_TOKEN` = your_notion_integration_token  
     - `NOTION_DATABASE_ID` = your_notion_database_id

4. **Deploy:**
   - Click "Create Web Service"
   - Wait for deployment (5-10 minutes)
   - Your bot will be online 24/7!

## Notion Database Setup

Your Notion database should have these exact columns:

| Column | Type | Options |
|--------|------|---------|
| Post ID | Title | (auto-generated) |
| Channel | Text | Discord channel name |
| Scheduled Time | Date | Include time |
| Content | Text | Your message content |
| Media URLs | Text | Image/video URLs (one per line) |
| Post Type | Select | Normal, Announcement |
| Status | Select | Pending, Posted, Failed |

### Example Post Entry:
- **Post ID:** "Daily Update 1"
- **Channel:** "general"  
- **Scheduled Time:** 2024-01-15 09:00 AM
- **Content:** "Good morning everyone! Here's today's update..."
- **Media URLs:** https://example.com/image.jpg
- **Post Type:** Normal
- **Status:** Pending

## Bot Commands

Use these commands in Discord (bot must have permissions in the channel):

- `!status` - Check bot status and upcoming posts count
- `!reload` - Manually refresh posts from Notion  
- `!next 5` - Show next 5 scheduled posts
- `!help` - Show available commands

## How It Works

1. **Every minute:** Bot checks for posts scheduled for current time
2. **Every hour:** Bot refreshes the 48-hour queue from Notion
3. **When posting:** Bot finds the Discord channel by name and sends content
4. **After posting:** Status in Notion updates to "Posted"
5. **On errors:** Status updates to "Failed" with error message

## Troubleshooting

### Bot not responding:
- Check if bot is online in Discord (green dot)
- Verify bot has permissions in target channels
- Check Render logs for errors

### Posts not sending:
- Verify channel names match exactly (case-insensitive)
- Check Scheduled Time format includes timezone
- Ensure Status is set to "Pending"

### Media not working:
- Use direct image/video URLs (ending in .jpg, .png, .mp4, etc.)
- Test URLs in browser first
- Keep file sizes under 25MB

## Support

If you run into issues:
1. Check the bot logs in Render dashboard
2. Use `!status` command to check bot health
3. Verify your Notion database structure matches requirements
4. Test with a simple text-only post first

## Cost

- **Render hosting:** FREE (750 hours/month - enough for 24/7)
- **Notion:** FREE (for personal use)
- **Discord:** FREE

Total cost: **$0/month** ✨
