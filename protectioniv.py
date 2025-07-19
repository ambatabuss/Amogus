import discord
from discord.ext import commands
import re
from collections import defaultdict
import asyncio
import os
from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)



TOKEN = os.getenv("DISCORD_BOT_TOKEN")
# قم بتغيير هذا إلى معرف مالك السيرفر الخاص بك
OWNER_ID = 1003599497475133530

# إعدادات الحالة والنشاط الافتراضية
DEFAULT_ACTIVITY_TYPE = discord.ActivityType.playing # يمكن أن تكون playing, streaming, listening, watching
DEFAULT_ACTIVITY_NAME = 'داشوفك'
DEFAULT_STATUS = discord.Status.idle # يمكن أن تكون online, idle, dnd, invisible

intents = discord.Intents.all()
intents.members = True  # تمكين Intent الأعضاء للحصول على معلومات الأعضاء
intents.presences = True # تمكين Intent التواجد للحصول على معلومات التواجد
intents.guilds = True # تمكين Intent السيرفرات للوصول إلى سجلات التدقيق
intents.message_content = True # تمكين Intent محتوى الرسائل لميزات الحماية

bot = commands.Bot(command_prefix='!', intents=intents)

# Dictionary to store channel deletion counts for nuke prevention
channel_delete_counts = {}

# Dictionaries for spam prevention
user_message_counts = defaultdict(lambda: {'count': 0, 'last_message_time': None})
last_messages = defaultdict(lambda: {"content": [], "time": []})

# List of common invite links to block
INVITE_REGEX = r''

# List of bad words (add more as needed)
BAD_WORDS = ["كلمة1", "كلمة2", "كلمة3"]

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    activity = discord.Activity(type=DEFAULT_ACTIVITY_TYPE, name=DEFAULT_ACTIVITY_NAME)
    await bot.change_presence(status=DEFAULT_STATUS, activity=activity)
    print(f'Bot status set to {DEFAULT_STATUS} and activity to {DEFAULT_ACTIVITY_TYPE.name}: {DEFAULT_ACTIVITY_NAME}')

@bot.event
async def on_member_join(member):
    if member.bot:
        guild = member.guild
        
        try:
            # Fetch audit log entries for bot additions
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                if entry.target.id == member.id:
                    inviter = entry.user
                    if inviter.id != OWNER_ID:
                        print(f"Bot {member.name} ({member.id}) was added by {inviter.name} ({inviter.id}), who is not the owner. Banning...")
                        try:
                            await guild.ban(member, reason="Bot added by non-owner")
                            print(f"Successfully banned {member.name}.")
                        except discord.Forbidden:
                            print(f"Failed to ban {member.name}. Missing permissions. Make sure the bot has 'Ban Members' permission.")
                        except Exception as e:
                            print(f"An error occurred while banning {member.name}: {e}")
                    else:
                        print(f"Bot {member.name} ({member.id}) was added by the owner ({inviter.name}). No action taken.")
                    return # Exit after finding the relevant audit log entry
            print(f"Could not find audit log entry for bot {member.name} ({member.id}). No action taken.")
        except discord.Forbidden:
            print(f"Failed to access audit logs for guild {guild.name}. Make sure the bot has 'View Audit Log' permission.")
        except Exception as e:
            print(f"An error occurred while checking audit logs for {member.name}: {e}")

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    try:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if entry.target.id == channel.id:
                deleter = entry.user
                if not deleter.bot and deleter.id != OWNER_ID:
                    # Nuke prevention: Track channel deletions
                    if deleter.id not in channel_delete_counts:
                        channel_delete_counts[deleter.id] = {"count": 1, "last_deleted": discord.utils.utcnow()}
                    else:
                        # Check if the last deletion was recent (e.g., within 5 seconds)
                        time_diff = (discord.utils.utcnow() - channel_delete_counts[deleter.id]["last_deleted"]).total_seconds()
                        if time_diff < 5:
                            channel_delete_counts[deleter.id]["count"] += 1
                        else:
                            channel_delete_counts[deleter.id] = {"count": 1, "last_deleted": discord.utils.utcnow()}

                    # If a user deletes 2 or more channels within 5 seconds, ban them
                    if channel_delete_counts[deleter.id]["count"] >= 2:
                        print(f"User {deleter.name} ({deleter.id}) deleted multiple channels rapidly. Banning for suspected nuke attempt...")
                        try:
                            await guild.ban(deleter, reason="Suspected nuke attempt: Rapid channel deletion")
                            print(f"Successfully banned {deleter.name}.")
                        except discord.Forbidden:
                            print(f"Failed to ban {deleter.name}. Missing permissions. Make sure the bot has 'Ban Members' permission.")
                        except Exception as e:
                            print(f"An error occurred while banning {deleter.name}: {e}")
                        # Reset count after banning
                        del channel_delete_counts[deleter.id]
                        return

                    print(f"User {deleter.name} ({deleter.id}) deleted channel {channel.name}. Current deletion count: {channel_delete_counts[deleter.id]['count']}")

                else:
                    print(f"Channel {channel.name} deleted by bot or owner. No action taken.")
                return
    except discord.Forbidden:
        print(f"Failed to access audit logs for guild {guild.name}. Make sure the bot has 'View Audit Log' permission.")
    except Exception as e:
        print(f"An error occurred while checking audit logs for channel deletion: {e}")

@bot.event
async def on_message(message):
    if message.author.bot or message.author.id == OWNER_ID: # Ignore bots and owner
        await bot.process_commands(message)
        return

    # Bad words prevention
    for word in BAD_WORDS:
        if word.lower() in message.content.lower():
            print(f"Deleting message from {message.author.name} due to bad word: {word}")
            try:
                await message.delete()
                await message.channel.send(f"{message.author.mention}, لا يُسمح باستخدام الكلمات البذيئة هنا.", delete_after=5)
            except discord.Forbidden:
                print(f"Failed to delete message or send warning. Missing permissions.")
            await bot.process_commands(message)
            return

    # Link prevention
    if re.search(INVITE_REGEX, message.content):
        print(f"Deleting invite link from {message.author.name} in {message.channel.name}")
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, لا يُسمح بنشر روابط الدعوة هنا.", delete_after=5)
        except discord.Forbidden:
            print(f"Failed to delete message or send warning. Missing permissions.")
        await bot.process_commands(message)
        return

    # Spam prevention (mass messages)
    user_id = message.author.id
    current_time = discord.utils.utcnow()

    if user_message_counts[user_id]['last_message_time'] is None:
        user_message_counts[user_id]['last_message_time'] = current_time

    time_diff = (current_time - user_message_counts[user_id]['last_message_time']).total_seconds()

    if time_diff < 3: # If messages are sent within 3 seconds
        user_message_counts[user_id]['count'] += 1
    else:
        user_message_counts[user_id]['count'] = 1
        user_message_counts[user_id]['last_message_time'] = current_time

    if user_message_counts[user_id]['count'] >= 5: # 5 messages in 3 seconds
        print(f"User {message.author.name} is spamming messages. Kicking...")
        try:
            await message.author.kick(reason="Spamming messages")
            await message.channel.send(f"{message.author.mention} تم طردك بسبب إرسال رسائل متكررة.")
            del user_message_counts[user_id] # Reset count after action
        except discord.Forbidden:
            print(f"Failed to kick {message.author.name}. Missing permissions.")
        except Exception as e:
            print(f"An error occurred while kicking {message.author.name}: {e}")
        await bot.process_commands(message)
        return

    # Spam prevention (mass mentions)
    if len(message.mentions) > 5: # More than 5 mentions in one message
        print(f"User {message.author.name} is mass mentioning. Kicking...")
        try:
            await message.author.kick(reason="Mass mentioning")
            await message.channel.send(f"{message.author.mention} تم طردك بسبب الإشارة الجماعية.")
        except discord.Forbidden:
            print(f"Failed to kick {message.author.name}. Missing permissions.")
        except Exception as e:
            print(f"An error occurred while kicking {message.author.name}: {e}")
        await bot.process_commands(message)
        return

    # Duplicate message prevention
    user_last_messages = last_messages[user_id]
    user_last_messages["content"].append(message.content)
    user_last_messages["time"].append(current_time)

    # Keep only messages from the last 10 seconds
    while user_last_messages["time"] and (current_time - user_last_messages["time"][0]).total_seconds() > 10:
        user_last_messages["content"].pop(0)
        user_last_messages["time"].pop(0)

    # Check for duplicate messages (e.g., 3 identical messages in 10 seconds)
    if user_last_messages["content"].count(message.content) >= 3:
        print(f"User {message.author.name} is sending duplicate messages. Kicking...")
        try:
            await message.author.kick(reason="Sending duplicate messages")
            await message.channel.send(f"{message.author.mention} تم طردك بسبب إرسال رسائل مكررة.")
            del last_messages[user_id]
        except discord.Forbidden:
            print(f"Failed to kick {message.author.name}. Missing permissions.")
        except Exception as e:
            print(f"An error occurred while kicking {message.author.name}: {e}")
        await bot.process_commands(message)
        return

    await bot.process_commands(message)

@bot.command()
@commands.is_owner()
async def setactivity(ctx, type: str, *, name: str):
    """Sets the bot's activity (e.g., !setactivity playing Protecting Server)"""
    activity_type = None
    if type.lower() == "playing":
        activity_type = discord.ActivityType.playing
    elif type.lower() == "streaming":
        activity_type = discord.ActivityType.streaming
    elif type.lower() == "listening":
        activity_type = discord.ActivityType.listening
    elif type.lower() == "watching":
        activity_type = discord.ActivityType.watching
    else:
        await ctx.send("نوع النشاط غير صالح. الأنواع المدعومة: playing, streaming, listening, watching.")
        return

    activity = discord.Activity(type=activity_type, name=name)
    await bot.change_presence(activity=activity)
    await ctx.send(f"تم تغيير النشاط إلى {type}: {name}")

@bot.command()
@commands.is_owner()
async def setstatus(ctx, status: str):
    """Sets the bot's status (e.g., !setstatus online)"""
    discord_status = None
    if status.lower() == "online":
        discord_status = discord.Status.online
    elif status.lower() == "idle":
        discord_status = discord.Status.idle
    elif status.lower() == "dnd":
        discord_status = discord.Status.dnd
    elif status.lower() == "invisible":
        discord_status = discord.Status.invisible
    else:
        await ctx.send("حالة غير صالحة. الحالات المدعومة: online, idle, dnd, invisible.")
        return

    await bot.change_presence(status=discord_status)
    await ctx.send(f"تم تغيير الحالة إلى {status}")

# Run the bot
if TOKEN is None:
    print("Error: DISCORD_BOT_TOKEN environment variable not set.")
    exit(1)
bot.run(TOKEN)


