# Load environment variables FIRST, before any other imports
from dotenv import load_dotenv
import os
load_dotenv()

# Get environment variables immediately
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
NOTION_TOKEN = os.getenv('NOTION_TOKEN') 
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
TIMEZONE = os.getenv('TIMEZONE', 'UTC')

# Debug print to verify variables are loaded
print(f"🔍 Environment check:")
print(f"  Discord token length: {len(DISCORD_TOKEN) if DISCORD_TOKEN else 0}")
print(f"  Notion token: {'✅' if NOTION_TOKEN else '❌'}")
print(f"  Database ID: {NOTION_DATABASE_ID}")

import discord
from discord.ext import commands, tasks
import asyncio
from datetime import datetime, timedelta, timezone
import pytz
import logging
from notion_client import Client
import requests
from typing import List, Dict, Optional
import json
import pickle
from pathlib import Path
import ssl
import certifi

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Fix SSL certificate verification on macOS
try:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context
    logger.info("SSL certificate verification bypassed for development")
except Exception as e:
    logger.warning(f"SSL fix failed: {e}")

class LocalDiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        # Use the pre-loaded environment variables
        self.notion = Client(auth=NOTION_TOKEN)
        self.database_id = NOTION_DATABASE_ID
        self.scheduled_posts = []
        self.timezone = pytz.timezone(TIMEZONE)
        self.cache_file = Path('scheduled_posts_cache.pkl')
        self.startup_time = None
        
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guild(s)')
        
        self.startup_time = datetime.now(self.timezone)
        
        # Check for missed posts first
        await self.check_missed_posts()
        
        # Load upcoming posts (7 days ahead for offline tolerance)
        await self.load_scheduled_posts()
        
        # Start the scheduler
        if not self.post_scheduler.is_running():
            self.post_scheduler.start()
        
        # Save cache every hour
        if not self.cache_saver.is_running():
            self.cache_saver.start()
            
        logger.info("🚀 Bot fully initialized and ready!")
        
    async def check_missed_posts(self):
        """Check for posts that should have been sent while offline"""
        try:
            logger.info("🔍 Checking for missed posts...")
            
            # Get last shutdown time from cache
            last_run_time = self.get_last_run_time()
            if not last_run_time:
                logger.info("No previous run time found - fresh start")
                return
            
            logger.info(f"Last run: {last_run_time}")
            logger.info(f"Current time: {self.startup_time}")
            
            # Query Notion for posts that should have been sent between last run and now
            missed_results = self.notion.databases.query(
                database_id=self.database_id,
                filter={
                    "and": [
                        {
                            "property": "Status",
                            "select": {
                                "equals": "Pending"
                            }
                        },
                        {
                            "property": "Scheduled Time",
                            "date": {
                                "on_or_after": last_run_time.isoformat()
                            }
                        },
                        {
                            "property": "Scheduled Time",
                            "date": {
                                "on_or_before": self.startup_time.isoformat()
                            }
                        }
                    ]
                },
                sorts=[
                    {
                        "property": "Scheduled Time",
                        "direction": "ascending"
                    }
                ]
            )
            
            missed_posts = []
            for page in missed_results['results']:
                post_data = self.parse_notion_page(page)
                if post_data:
                    missed_posts.append(post_data)
            
            if missed_posts:
                logger.info(f"📬 Found {len(missed_posts)} missed posts - sending now...")
                for post in missed_posts:
                    await self.send_scheduled_post(post, is_catchup=True)
                    await asyncio.sleep(2)  # Small delay between catch-up posts
            else:
                logger.info("✅ No missed posts found")
                
        except Exception as e:
            logger.error(f"Error checking missed posts: {e}")
    
    def get_last_run_time(self) -> Optional[datetime]:
        """Get the last time the bot was running"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                    return cache_data.get('last_run_time')
        except Exception as e:
            logger.warning(f"Could not read cache: {e}")
        return None
    
    def save_last_run_time(self):
        """Save current time as last run time"""
        try:
            cache_data = {}
            if self.cache_file.exists():
                with open(self.cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
            
            cache_data['last_run_time'] = datetime.now(self.timezone)
            cache_data['scheduled_posts'] = self.scheduled_posts
            
            with open(self.cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
                
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
        
    async def load_scheduled_posts(self):
        """Load upcoming posts from Notion database - 7 days ahead for offline tolerance"""
        try:
            logger.info("📅 Loading scheduled posts...")
            
            # Get posts for next 7 days (offline tolerance)
            now = datetime.now(self.timezone)
            future_time = now + timedelta(days=7)
            
            # Query Notion database
            results = self.notion.databases.query(
                database_id=self.database_id,
                filter={
                    "and": [
                        {
                            "property": "Status",
                            "select": {
                                "equals": "Pending"
                            }
                        },
                        {
                            "property": "Scheduled Time",
                            "date": {
                                "on_or_after": now.isoformat()
                            }
                        },
                        {
                            "property": "Scheduled Time",
                            "date": {
                                "on_or_before": future_time.isoformat()
                            }
                        }
                    ]
                },
                sorts=[
                    {
                        "property": "Scheduled Time",
                        "direction": "ascending"
                    }
                ]
            )
            
            self.scheduled_posts = []
            for page in results['results']:
                post_data = self.parse_notion_page(page)
                if post_data:
                    self.scheduled_posts.append(post_data)
            
            logger.info(f"✅ Loaded {len(self.scheduled_posts)} scheduled posts (next 7 days)")
            
            # Show next few posts
            if self.scheduled_posts:
                logger.info("📋 Next 3 posts:")
                for i, post in enumerate(self.scheduled_posts[:3]):
                    time_str = post['scheduled_time'].strftime('%Y-%m-%d %H:%M')
                    content_preview = post['content'][:50] + "..." if len(post['content']) > 50 else post['content']
                    logger.info(f"  {i+1}. [{time_str}] #{post['channel']}: {content_preview}")
            
        except Exception as e:
            logger.error(f"Error loading scheduled posts: {e}")
    
    def parse_notion_page(self, page) -> Optional[Dict]:
        """Parse a Notion page into post data"""
        try:
            properties = page['properties']
            
            # Extract data from Notion page
            post_id = properties['Post ID']['title'][0]['text']['content'] if properties['Post ID']['title'] else None
            channel_name = properties['Channel']['rich_text'][0]['text']['content'] if properties['Channel']['rich_text'] else None
            scheduled_time_str = properties['Scheduled Time']['date']['start'] if properties['Scheduled Time']['date'] else None
            content = properties['Content']['rich_text'][0]['text']['content'] if properties['Content']['rich_text'] else ""
            media_urls = properties['Media URLs']['rich_text'][0]['text']['content'] if properties['Media URLs']['rich_text'] else ""
            post_type = properties['Post Type']['select']['name'] if properties['Post Type']['select'] else "Normal"
            
            if not all([post_id, channel_name, scheduled_time_str]):
                logger.warning(f"Missing required fields in post: {post_id}")
                return None
            
            # Parse scheduled time
            scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
            if scheduled_time.tzinfo is None:
                scheduled_time = self.timezone.localize(scheduled_time)
            
            return {
                'id': post_id,
                'page_id': page['id'],
                'channel': channel_name,
                'scheduled_time': scheduled_time,
                'content': content,
                'media_urls': media_urls.split('\n') if media_urls else [],
                'post_type': post_type,
                'posted': False
            }
            
        except Exception as e:
            logger.error(f"Error parsing Notion page: {e}")
            return None
    
    async def update_post_status(self, page_id: str, status: str, error_message: str = ""):
        """Update post status in Notion"""
        try:
            update_data = {
                "Status": {
                    "select": {
                        "name": status
                    }
                }
            }
            
            # Add error message if failed
            if status == "Failed" and error_message:
                # Don't overwrite content, just log the error
                logger.error(f"Post failed: {error_message}")
            
            self.notion.pages.update(
                page_id=page_id,
                properties=update_data
            )
            
        except Exception as e:
            logger.error(f"Error updating post status: {e}")
    
    def find_channel_by_name(self, channel_name: str):
        """Find Discord channel by name"""
        for guild in self.guilds:
            for channel in guild.channels:
                if channel.name.lower() == channel_name.lower() and isinstance(channel, discord.TextChannel):
                    return channel
        return None
    
    async def send_scheduled_post(self, post_data: Dict, is_catchup: bool = False):
        """Send a scheduled post to Discord"""
        try:
            # Find the channel
            channel = self.find_channel_by_name(post_data['channel'])
            if not channel:
                error_msg = f"Channel '{post_data['channel']}' not found"
                logger.error(error_msg)
                await self.update_post_status(post_data['page_id'], "Failed", error_msg)
                return
            
            # Prepare message content
            content = post_data['content']
            files = []
            
            # Add catch-up indicator if this is a missed post
            if is_catchup:
                content = f"🔄 **[Catch-up Post]** {content}"
            
            # Handle media URLs
            for url in post_data['media_urls']:
                if url.strip():
                    try:
                        # Download and attach media
                        response = requests.get(url.strip(), timeout=30)
                        if response.status_code == 200:
                            # Get filename from URL or create one
                            filename = url.split('/')[-1]
                            if '.' not in filename:
                                filename += '.jpg'  # Default extension
                            
                            files.append(discord.File(
                                fp=response.content,
                                filename=filename
                            ))
                    except Exception as e:
                        logger.warning(f"Failed to download media {url}: {e}")
                        # Add URL to content if download fails
                        content += f"\n{url}"
            
            # Send message based on post type
            if post_data['post_type'] == "Announcement":
                # Send as announcement (ping @everyone)
                await channel.send(f"@everyone\n\n{content}", files=files)
            else:
                await channel.send(content, files=files)
            
            # Update status to Posted
            await self.update_post_status(post_data['page_id'], "Posted")
            
            status_prefix = "🔄 Caught up:" if is_catchup else "✅ Posted:"
            logger.info(f"{status_prefix} {post_data['id']}")
            
        except Exception as e:
            error_msg = f"Error sending post: {e}"
            logger.error(error_msg)
            await self.update_post_status(post_data['page_id'], "Failed", str(e))
    
    @tasks.loop(minutes=1)
    async def post_scheduler(self):
        """Check for posts that need to be sent"""
        try:
            now = datetime.now(self.timezone)
            posts_to_send = []
            
            # Find posts that should be sent now
            for post in self.scheduled_posts[:]:  # Copy list to iterate safely
                if not post['posted'] and post['scheduled_time'] <= now:
                    posts_to_send.append(post)
                    post['posted'] = True  # Mark as processed
            
            # Send the posts
            for post in posts_to_send:
                await self.send_scheduled_post(post)
            
            # Refresh scheduled posts every 2 hours (instead of every hour)
            if now.minute == 0 and now.hour % 2 == 0:
                logger.info("🔄 Refreshing scheduled posts...")
                await self.load_scheduled_posts()
                
        except Exception as e:
            logger.error(f"Error in post scheduler: {e}")
    
    @tasks.loop(hours=1)
    async def cache_saver(self):
        """Save cache every hour for offline recovery"""
        self.save_last_run_time()
    
    @post_scheduler.before_loop
    async def before_scheduler(self):
        """Wait for bot to be ready before starting scheduler"""
        await self.wait_until_ready()
    
    @cache_saver.before_loop
    async def before_cache_saver(self):
        """Wait for bot to be ready before starting cache saver"""
        await self.wait_until_ready()

# Bot commands
bot = LocalDiscordBot()

@bot.command(name='status')
async def status(ctx):
    """Check bot status and upcoming posts"""
    try:
        upcoming_count = len([p for p in bot.scheduled_posts if not p['posted']])
        uptime = datetime.now(bot.timezone) - bot.startup_time if bot.startup_time else timedelta(0)
        
        embed = discord.Embed(
            title="🏠 Local Bot Status",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.add_field(
            name="📅 Upcoming Posts",
            value=f"{upcoming_count} posts queued (next 7 days)",
            inline=False
        )
        embed.add_field(
            name="⏱️ Uptime",
            value=f"{str(uptime).split('.')[0]}",
            inline=True
        )
        embed.add_field(
            name="🚀 Status",
            value="✅ Online and monitoring",
            inline=True
        )
        embed.add_field(
            name="💡 Tip",
            value="Bot runs locally - posts will queue up while offline!",
            inline=False
        )
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error checking status: {e}")

@bot.command(name='reload')
async def reload_posts(ctx):
    """Manually reload posts from Notion"""
    try:
        await bot.load_scheduled_posts()
        upcoming_count = len([p for p in bot.scheduled_posts if not p['posted']])
        await ctx.send(f"🔄 Reloaded! Found {upcoming_count} upcoming posts (next 7 days).")
        
    except Exception as e:
        await ctx.send(f"Error reloading posts: {e}")

@bot.command(name='catchup')
async def manual_catchup(ctx):
    """Manually check for missed posts"""
    try:
        await ctx.send("🔍 Checking for missed posts...")
        await bot.check_missed_posts()
        await ctx.send("✅ Catch-up check completed!")
        
    except Exception as e:
        await ctx.send(f"Error during catch-up: {e}")

@bot.command(name='next')
async def next_posts(ctx, count: int = 5):
    """Show next few scheduled posts"""
    try:
        upcoming_posts = [p for p in bot.scheduled_posts if not p['posted']][:count]
        
        if not upcoming_posts:
            await ctx.send("📭 No upcoming posts found in the next 7 days.")
            return
        
        embed = discord.Embed(
            title=f"📋 Next {len(upcoming_posts)} Posts",
            color=0x0099ff
        )
        
        for post in upcoming_posts:
            time_str = post['scheduled_time'].strftime('%Y-%m-%d %H:%M %Z')
            content_preview = post['content'][:50] + "..." if len(post['content']) > 50 else post['content']
            
            embed.add_field(
                name=f"#{post['channel']} - {time_str}",
                value=f"{content_preview}",
                inline=False
            )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        await ctx.send(f"Error showing next posts: {e}")

@bot.event
async def on_disconnect():
    """Save state when disconnecting"""
    logger.info("💾 Bot disconnecting - saving state...")
    bot.save_last_run_time()

if __name__ == "__main__":
    # Check for required environment variables
    required_vars = [
        ('DISCORD_TOKEN', DISCORD_TOKEN),
        ('NOTION_TOKEN', NOTION_TOKEN), 
        ('NOTION_DATABASE_ID', NOTION_DATABASE_ID)
    ]
    
    missing_vars = [name for name, value in required_vars if not value]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        logger.error("Please create a .env file with:")
        for name, _ in required_vars:
            logger.error(f"  {name}=your_token_here")
        exit(1)
    
    # Log startup info
    logger.info("🏠 Starting Local Discord Scheduler Bot...")
    logger.info(f"Timezone: {TIMEZONE}")
    logger.info("Features: 7-day queue, catch-up posts, offline tolerance")
    
    # Run the bot
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure as e:
        logger.error(f"Discord login failed - check your bot token: {e}")
        exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        bot.save_last_run_time()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        import traceback
        logger.error(traceback.format_exc())
        exit(1)
