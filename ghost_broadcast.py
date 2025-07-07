#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Discord Broadcast Bot - All-in-One Version
------------------------------------------
بوت Discord للبث يرسل رسائل خاصة لجميع أعضاء سيرفر معين
باستثناء الأعضاء الذين كتبوا رسائل في آخر 10 أيام.

المؤلف: Manus AI
الإصدار: 2.1 (All-in-One with Termux Keep-Alive)
"""

import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime, timedelta
import os
import sys
import json
import threading
import time
import subprocess

# ===== إعدادات البوت =====
# يمكنك تعديل هذه الإعدادات حسب احتياجاتك

# توكن البوت (يمكن تعيينه أيضاً كمتغير بيئة DISCORD_TOKEN)
BOT_TOKEN = "MTM5MTgzMTQxMjY3MTUxMjczNw.GH7oEV.ZWxxiPQuRL746CaCmyyfBPtnb4b53-a2iQQL_U"

# بادئة الأوامر
COMMAND_PREFIX = "!"

# عدد الأيام للتحقق من نشاط الأعضاء
ACTIVITY_DAYS = 5

# التأخير بين إرسال الرسائل (بالثواني) لتجنب Rate Limiting
# قيمة أقل = إرسال أسرع (0.2 ثانية هي الحد الأدنى الآمن)
RATE_LIMIT_DELAY = 0.2

# الفاصل الزمني لإرسال إشارات إلى Termux (بالثواني)
TERMUX_PING_INTERVAL = 180  # 3 دقائق

# عدد الرسائل المرسلة قبل تحديث شريط التقدم
PROGRESS_UPDATE_INTERVAL = 10

# الصلاحيات المطلوبة لاستخدام أوامر البث
REQUIRED_PERMISSIONS = ["administrator", "manage_guild"]

# إعدادات التسجيل
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR
LOG_FILE = "bot.log"

# رسائل مخصصة
MESSAGES = {
    "no_permission": "❌ ليس لديك الصلاحيات الكافية لاستخدام هذا الأمر.",
    "no_message": "❌ يرجى تحديد رسالة للإرسال.",
    "confirm_broadcast": "⚠️ هل أنت متأكد من أنك تريد إرسال هذه الرسالة؟",
    "broadcast_started": "🚀 بدء عملية البث...",
    "broadcast_cancelled": "❌ تم إلغاء عملية البث.",
    "timeout": "❌ انتهت مهلة التأكيد. تم إلغاء عملية البث."
}

# ===== نهاية الإعدادات =====

# إعداد التسجيل
log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("BroadcastBot")

# إعداد البوت مع Intents
intents = discord.Intents.default()
intents.members = True  # مطلوب للوصول إلى قائمة الأعضاء
intents.message_content = True  # مطلوب للوصول إلى محتوى الرسائل

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# متغير للتحكم في حلقة إرسال الإشارات إلى Termux
termux_ping_active = True

def ping_termux():
    """
    وظيفة لإرسال إشارات إلى Termux بشكل دوري لمنع إغلاق البرنامج
    تعمل في خلفية البرنامج كخيط منفصل
    """
    logger.info(f"بدء خيط إرسال الإشارات إلى Termux كل {TERMUX_PING_INTERVAL} ثانية")
    
    while termux_ping_active:
        try:
            # طباعة رسالة في وحدة التحكم لإبقاء Termux نشطاً
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[TERMUX KEEP-ALIVE] {current_time} - إشارة للحفاظ على نشاط Termux")
            sys.stdout.flush()  # إجبار طباعة الرسالة فوراً
            
            # محاولة تنفيذ أمر في Termux (إذا كان متاحاً)
            try:
                subprocess.run(["termux-wake-lock"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass  # تجاهل الأخطاء إذا لم يكن الأمر متاحاً
                
            # انتظار الفاصل الزمني المحدد
            time.sleep(TERMUX_PING_INTERVAL)
        except Exception as e:
            logger.error(f"خطأ في خيط إرسال الإشارات إلى Termux: {e}")
            time.sleep(60)  # انتظار دقيقة واحدة في حالة حدوث خطأ

class BroadcastStats:
    """فئة لتتبع إحصائيات البث"""
    def __init__(self):
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.total = 0
        self.start_time = None
        self.end_time = None
    
    def start(self, total_members):
        self.total = total_members
        self.start_time = datetime.now()
    
    def finish(self):
        self.end_time = datetime.now()
    
    def get_duration(self):
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None
    
    def to_dict(self):
        return {
            'success': self.success,
            'failed': self.failed,
            'skipped': self.skipped,
            'total': self.total,
            'duration': str(self.get_duration()) if self.get_duration() else None
        }

def check_permissions(ctx):
    """التحقق من صلاحيات المستخدم لتنفيذ أوامر البث"""
    if ctx.author.guild_permissions.administrator:
        return True
    
    for permission in REQUIRED_PERMISSIONS:
        if getattr(ctx.author.guild_permissions, permission, False):
            return True
    
    return False

async def check_member_activity(member, days=ACTIVITY_DAYS):
    """
    التحقق مما إذا كان العضو نشطاً في آخر X أيام
    
    المعلمات:
        member (discord.Member): عضو Discord للتحقق من نشاطه
        days (int): عدد الأيام للتحقق
        
    العائد:
        bool: True إذا كان العضو نشطاً، False إذا لم يكن نشطاً
    """
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # التحقق من جميع القنوات النصية في السيرفر
    for channel in member.guild.text_channels:
        try:
            # محاولة الوصول إلى القناة والبحث في تاريخها
            async for message in channel.history(after=cutoff_date, limit=100):
                if message.author.id == member.id:
                    logger.debug(f"العضو {member.name} نشط (آخر رسالة في {message.created_at})")
                    return True
        except discord.Forbidden:
            # تخطي القنوات التي لا يمكن الوصول إليها
            logger.debug(f"لا يمكن الوصول إلى القناة {channel.name}")
            continue
        except Exception as e:
            logger.error(f"خطأ أثناء التحقق من نشاط {member.name} في {channel.name}: {e}")
    
    logger.debug(f"العضو {member.name} غير نشط في آخر {days} أيام")
    return False

async def send_broadcast_message(ctx, message_content, exclude_active=True):
    """
    إرسال رسالة بث لجميع الأعضاء
    
    المعلمات:
        ctx (commands.Context): سياق الأمر
        message_content (str): محتوى الرسالة للإرسال
        exclude_active (bool): استثناء الأعضاء النشطين
        
    العائد:
        BroadcastStats: إحصائيات الإرسال
    """
    stats = BroadcastStats()
    members = [m for m in ctx.guild.members if not m.bot]
    stats.start(len(members))
    
    # إرسال رسالة بدء العملية
    status_message = await ctx.send(f"بدء إرسال الرسائل إلى {len(members)} عضو...")
    
    # إنشاء شريط تقدم
    progress = 0
    last_update_time = datetime.now()
    
    for member in members:
        progress += 1
        
        # التحقق من نشاط العضو إذا كان exclude_active صحيحاً
        if exclude_active:
            is_active = await check_member_activity(member)
            if is_active:
                stats.skipped += 1
                logger.info(f"تم تخطي العضو النشط: {member.name}")
                continue
        
        # محاولة إرسال الرسالة
        try:
            await member.send(message_content)
            stats.success += 1
            logger.info(f"تم إرسال الرسالة بنجاح إلى {member.name}")
        except discord.Forbidden:
            stats.failed += 1
            logger.warning(f"لا يمكن إرسال رسالة إلى {member.name} (إعدادات الخصوصية)")
        except Exception as e:
            stats.failed += 1
            logger.error(f"فشل في إرسال الرسالة إلى {member.name}: {e}")
        
        # تحديث شريط التقدم بشكل أقل تكراراً لتسريع العملية
        current_time = datetime.now()
        time_since_update = (current_time - last_update_time).total_seconds()
        
        if progress % PROGRESS_UPDATE_INTERVAL == 0 or progress == len(members) or time_since_update >= 5:
            percentage = (progress / len(members)) * 100
            await status_message.edit(
                content=f"جارٍ الإرسال: {progress}/{len(members)} ({percentage:.1f}%)\n"
                       f"✅ نجاح: {stats.success} | ❌ فشل: {stats.failed} | ⏭️ تخطي: {stats.skipped}"
            )
            last_update_time = current_time
        
        # تأخير لتجنب Rate Limiting (تم تقليله لتسريع العملية)
        await asyncio.sleep(RATE_LIMIT_DELAY)
    
    stats.finish()
    
    # إرسال تقرير نهائي
    duration = stats.get_duration()
    duration_str = f" في {duration}" if duration else ""
    
    final_report = f"""
## 📊 تقرير البث النهائي

**النتائج:**
✅ نجاح: {stats.success}
❌ فشل: {stats.failed}
⏭️ تم تخطيه: {stats.skipped}
📈 المجموع: {len(members)}

**الوقت المستغرق:** {duration_str}
**معدل النجاح:** {(stats.success / len(members) * 100):.1f}%
    """
    
    await ctx.send(final_report)
    
    # حفظ الإحصائيات في ملف
    try:
        with open('broadcast_stats.json', 'a', encoding='utf-8') as f:
            stats_data = {
                'timestamp': datetime.now().isoformat(),
                'guild_id': ctx.guild.id,
                'guild_name': ctx.guild.name,
                'user_id': ctx.author.id,
                'user_name': str(ctx.author),
                'exclude_active': exclude_active,
                'stats': stats.to_dict()
            }
            f.write(json.dumps(stats_data, ensure_ascii=False) + '\n')
    except Exception as e:
        logger.error(f"فشل في حفظ الإحصائيات: {e}")
    
    return stats

@bot.event
async def on_ready():
    """يتم تنفيذه عند تشغيل البوت واتصاله بـ Discord"""
    logger.info(f"تم تسجيل الدخول كـ {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"البوت متصل بـ {len(bot.guilds)} سيرفر")
    
    # تعيين حالة البوت
    await bot.change_presence(
        activity=discord.Game(name=f"{COMMAND_PREFIX}help_broadcast للمساعدة")
    )

@bot.event
async def on_command_error(ctx, error):
    """معالجة أخطاء الأوامر"""
    if isinstance(error, commands.CommandNotFound):
        return  # تجاهل الأوامر غير الموجودة
    
    logger.error(f"خطأ في الأمر {ctx.command}: {error}")
    await ctx.send(f"❌ حدث خطأ: {error}")

@bot.command(name="broadcast")
async def broadcast_command(ctx, *, message=None):
    """
    إرسال رسالة بث للأعضاء غير النشطين
    
    الاستخدام: !broadcast <رسالة>
    """
    # التحقق من الصلاحيات
    if not check_permissions(ctx):
        await ctx.send(MESSAGES['no_permission'])
        return
    
    # التحقق من وجود رسالة
    if not message:
        await ctx.send(f"{MESSAGES['no_message']} مثال: `{COMMAND_PREFIX}broadcast مرحباً بكم في السيرفر!`")
        return
    
    # تأكيد العملية
    embed = discord.Embed(
        title="⚠️ تأكيد البث",
        description=f"هل أنت متأكد من أنك تريد إرسال الرسالة التالية إلى جميع الأعضاء غير النشطين في آخر {ACTIVITY_DAYS} أيام؟",
        color=discord.Color.orange()
    )
    embed.add_field(name="الرسالة", value=f"```{message}```", inline=False)
    embed.add_field(name="التأكيد", value="رجاءً قم بالرد بـ `نعم` للتأكيد أو `لا` للإلغاء.", inline=False)
    
    await ctx.send(embed=embed)
    
    # انتظار رد المستخدم
    try:
        response = await bot.wait_for(
            'message',
            check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
            timeout=60.0
        )
        
        if response.content.lower() in ['نعم', 'yes', 'y']:
            await ctx.send(MESSAGES['broadcast_started'])
            await send_broadcast_message(ctx, message, exclude_active=True)
        else:
            await ctx.send(MESSAGES['broadcast_cancelled'])
    
    except asyncio.TimeoutError:
        await ctx.send(MESSAGES['timeout'])

@bot.command(name="broadcast_all")
async def broadcast_all_command(ctx, *, message=None):
    """
    إرسال رسالة بث لجميع الأعضاء (بما في ذلك النشطين)
    
    الاستخدام: !broadcast_all <رسالة>
    """
    # التحقق من الصلاحيات (مدير فقط)
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("❌ هذا الأمر متاح فقط للمدراء.")
        return
    
    # التحقق من وجود رسالة
    if not message:
        await ctx.send(f"{MESSAGES['no_message']} مثال: `{COMMAND_PREFIX}broadcast_all إعلان مهم لجميع الأعضاء`")
        return
    
    # تأكيد العملية
    embed = discord.Embed(
        title="⚠️ تحذير: بث لجميع الأعضاء",
        description="هل أنت متأكد من أنك تريد إرسال الرسالة التالية إلى **جميع** الأعضاء؟",
        color=discord.Color.red()
    )
    embed.add_field(name="الرسالة", value=f"```{message}```", inline=False)
    embed.add_field(name="التأكيد", value="رجاءً قم بالرد بـ `نعم` للتأكيد أو `لا` للإلغاء.", inline=False)
    
    await ctx.send(embed=embed)
    
    # انتظار رد المستخدم
    try:
        response = await bot.wait_for(
            'message',
            check=lambda m: m.author == ctx.author and m.channel == ctx.channel,
            timeout=60.0
        )
        
        if response.content.lower() in ['نعم', 'yes', 'y']:
            await ctx.send("🚀 بدء عملية البث لجميع الأعضاء...")
            await send_broadcast_message(ctx, message, exclude_active=False)
        else:
            await ctx.send(MESSAGES['broadcast_cancelled'])
    
    except asyncio.TimeoutError:
        await ctx.send(MESSAGES['timeout'])

@bot.command(name="stats")
async def stats_command(ctx):
    """عرض إحصائيات السيرفر"""
    if not check_permissions(ctx):
        await ctx.send(MESSAGES['no_permission'])
        return
    
    guild = ctx.guild
    total_members = len(guild.members)
    bots = len([m for m in guild.members if m.bot])
    humans = total_members - bots
    
    # حساب الأعضاء النشطين (تقدير سريع)
    active_count = 0
    try:
        cutoff_date = datetime.now() - timedelta(days=ACTIVITY_DAYS)
        for channel in guild.text_channels[:5]:  # فحص أول 5 قنوات فقط للسرعة
            try:
                async for message in channel.history(after=cutoff_date, limit=100):
                    if not message.author.bot and message.author not in [m.author for m in guild.members if hasattr(m, 'author')]:
                        active_count += 1
                        break
            except:
                continue
    except:
        active_count = "غير متاح"
    
    embed = discord.Embed(
        title=f"📊 إحصائيات {guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="👥 إجمالي الأعضاء", value=total_members, inline=True)
    embed.add_field(name="🤖 البوتات", value=bots, inline=True)
    embed.add_field(name="👤 البشر", value=humans, inline=True)
    embed.add_field(name="📅 تاريخ الإنشاء", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="📝 القنوات النصية", value=len(guild.text_channels), inline=True)
    embed.add_field(name="🔊 القنوات الصوتية", value=len(guild.voice_channels), inline=True)
    
    if isinstance(active_count, int):
        embed.add_field(name=f"✅ نشط في آخر {ACTIVITY_DAYS} أيام", value=f"~{active_count}", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name="help_broadcast")
async def help_broadcast_command(ctx):
    """عرض تعليمات استخدام البوت"""
    embed = discord.Embed(
        title="📢 بوت البث Discord",
        description="بوت لإرسال رسائل بث للأعضاء في السيرفر",
        color=discord.Color.green()
    )
    
    embed.add_field(
        name=f"{COMMAND_PREFIX}broadcast <رسالة>",
        value=f"إرسال رسالة بث للأعضاء غير النشطين في آخر {ACTIVITY_DAYS} أيام.",
        inline=False
    )
    
    embed.add_field(
        name=f"{COMMAND_PREFIX}broadcast_all <رسالة>",
        value="إرسال رسالة بث لجميع الأعضاء (مدراء فقط).",
        inline=False
    )
    
    embed.add_field(
        name=f"{COMMAND_PREFIX}stats",
        value="عرض إحصائيات السيرفر.",
        inline=False
    )
    
    embed.add_field(
        name=f"{COMMAND_PREFIX}config",
        value="عرض الإعدادات الحالية للبوت.",
        inline=False
    )
    
    embed.add_field(
        name=f"{COMMAND_PREFIX}help_broadcast",
        value="عرض هذه الرسالة.",
        inline=False
    )
    
    embed.add_field(
        name="الصلاحيات المطلوبة",
        value="• مدير أو إدارة السيرفر للأوامر العادية\n• مدير فقط لـ broadcast_all",
        inline=False
    )
    
    embed.set_footer(text="تم تطوير البوت بواسطة Manus AI")
    
    await ctx.send(embed=embed)

@bot.command(name="config")
async def config_command(ctx):
    """عرض الإعدادات الحالية للبوت"""
    if not check_permissions(ctx):
        await ctx.send(MESSAGES['no_permission'])
        return
    
    embed = discord.Embed(
        title="⚙️ إعدادات البوت",
        description="الإعدادات الحالية للبوت",
        color=discord.Color.blue()
    )
    
    embed.add_field(name="بادئة الأوامر", value=f"`{COMMAND_PREFIX}`", inline=True)
    embed.add_field(name="أيام النشاط", value=f"{ACTIVITY_DAYS} أيام", inline=True)
    embed.add_field(name="تأخير الإرسال", value=f"{RATE_LIMIT_DELAY} ثانية", inline=True)
    embed.add_field(name="فاصل إشارات Termux", value=f"{TERMUX_PING_INTERVAL} ثانية", inline=True)
    embed.add_field(name="فاصل تحديث التقدم", value=f"كل {PROGRESS_UPDATE_INTERVAL} رسائل", inline=True)
    embed.add_field(name="مستوى التسجيل", value=LOG_LEVEL, inline=True)
    embed.add_field(name="ملف السجل", value=LOG_FILE, inline=True)
    embed.add_field(name="الصلاحيات المطلوبة", value=", ".join(REQUIRED_PERMISSIONS), inline=False)
    
    embed.set_footer(text="لتغيير الإعدادات، قم بتعديل المتغيرات في أعلى الملف")
    
    await ctx.send(embed=embed)

# تشغيل البوت
def main():
    """الدالة الرئيسية لتشغيل البوت"""
    # التحقق من وجود توكن
    token = os.environ.get('DISCORD_TOKEN', BOT_TOKEN)
    
    if token == 'YOUR_BOT_TOKEN_HERE':
        logger.error("يرجى تعيين توكن البوت الخاص بك.")
        print("\n" + "="*60)
        print("تعليمات إعداد البوت:")
        print("1. احصل على توكن البوت من Discord Developer Portal")
        print("2. قم بتعيين متغير البيئة:")
        print("   export DISCORD_TOKEN='your_token_here'")
        print("3. أو قم بتعديل المتغير BOT_TOKEN في أعلى هذا الملف")
        print("="*60)
        return
    
    # بدء خيط إرسال الإشارات إلى Termux
    termux_thread = threading.Thread(target=ping_termux, daemon=True)
    termux_thread.start()
    logger.info("تم بدء خيط إرسال الإشارات إلى Termux")
    
    # تشغيل البوت
    try:
        logger.info("بدء تشغيل البوت...")
        bot.run(token)
    except discord.LoginFailure:
        logger.error("فشل تسجيل الدخول. يرجى التحقق من توكن البوت.")
    except KeyboardInterrupt:
        logger.info("تم إيقاف البوت بواسطة المستخدم.")
    except Exception as e:
        logger.error(f"حدث خطأ أثناء تشغيل البوت: {e}")
    finally:
        # إيقاف خيط إرسال الإشارات إلى Termux
        global termux_ping_active
        termux_ping_active = False
        logger.info("تم إيقاف خيط إرسال الإشارات إلى Termux")

if __name__ == "__main__":
    main()

