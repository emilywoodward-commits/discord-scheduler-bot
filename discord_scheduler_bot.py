import discord
from discord.ext import commands, tasks
import asyncio
import os
from datetime import datetime, timedelta, timezone
import pytz
import logging
from notion_client import Client
import requests
from typing import List, Dict, Optional
import json

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

class DiscordSchedulerBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        # Initialize Notion client
        self.notion = Client(auth=os.getenv('NOTION_TOKEN'))
        self.database_id = os.getenv('NOTION_DATABASE_ID')
        self.scheduled_posts = []
        self.timezone = pytz.timezone('UTC')  # Change this to your timezone if needed
        
    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guild(s)')
        
        # Start the scheduler
        if not self.post_scheduler.is_running():
            self.post_scheduler.start()
        
        # Load initial posts
        await self.load_scheduled_posts()
        
    async def load_scheduled_posts(self):
        """Load upcoming posts from Notion database"""
        try:
            # Get posts for next 48 hours that are still pending
            now = datetime.now(self.timezone)
            future_time = now + timedelta(hours=48)
            
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
            
            logger.info(f"Loaded {len(self.scheduled_posts)} scheduled posts")
            
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
                update_data["Content"] = {
                    "rich_text": [
                        {
                            "text": {
                                "content": f"ERROR: {error_message}"
                            }
                        }
                    ]
                }
            
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
    
    async def send_scheduled_post(self, post_data: Dict):
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
            logger.info(f"Successfully posted: {post_data['id']}")
            
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
            
            # Refresh scheduled posts every hour
            if now.minute == 0:
                await self.load_scheduled_posts()
                
        except Exception as e:
            logger.error(f"Error in post scheduler: {e}")
    
    @post_scheduler.before_loop
    async def before_scheduler(self):
        """Wait for bot to be ready before starting scheduler"""
        await self.wait_until_ready()

# Bot commands
bot = DiscordSchedulerBot()

@bot.command(name='status')
async def status(ctx):
    """Check bot status and upcoming posts"""
    try:
        upcoming_count = len([p for p in bot.scheduled_posts if not p['posted']])
        embed = discord.Embed(
            title="📅 Scheduler Status",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.add_field(
            name="Upcoming Posts",
            value=f"{upcoming_count} posts in next 48 hours",
            inline=False
        )
        embed.add_field(
            name="Bot Status",
            value="✅ Online and running",
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
        await ctx.send(f"✅ Reloaded! Found {upcoming_count} upcoming posts.")
        
    except Exception as e:
        await ctx.send(f"Error reloading posts: {e}")

@bot.command(name='next')
async def next_posts(ctx, count: int = 5):
    """Show next few scheduled posts"""
    try:
        upcoming_posts = [p for p in bot.scheduled_posts if not p['posted']][:count]
        
        if not upcoming_posts:
            await ctx.send("No upcoming posts found.")
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

if __name__ == "__main__":
    # Check for required environment variables
    required_vars = ['DISCORD_TOKEN', 'NOTION_TOKEN', 'NOTION_DATABASE_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        exit(1)
    
    # Run the bot
    try:
        bot.run(os.getenv('DISCORD_TOKEN'))
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
