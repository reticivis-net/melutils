import glob
import os
import sqlite3

import nextcord as discord
from nextcord.ext import commands

import config
import errhandler
import scheduler
from admincommands import AdminCommands
from autoreaction import AutoReactionCog
from birthday import BirthdayCog
from bulklog import BulkLog
from clogs import logger
from errhandler import ErrorHandler
from funcommands import FunCommands
from funnybanner import FunnyBanner
from helpcommand import HelpCommand
from macro import MacroCog
from moderation import ModerationCog
from modlog import ModLogInitCog
from nitroroles import NitroRolesCog
from threadutils import ThreadUtilsCog
from utilitycommands import UtilityCommands

if not os.path.exists(config.temp_dir.rstrip("/")):
    os.mkdir(config.temp_dir.rstrip("/"))
for f in glob.glob(f'{config.temp_dir}*'):
    os.remove(f)
# init db if not ready
logger.debug("checking db")
con = sqlite3.connect("database.sqlite")
cur = con.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name != 'sqlite_master' AND name != "
                  "'sqlite_sequence'")
numoftables = cur.fetchone()[0]
if numoftables == 0:
    logger.debug("detected empty database, initializing")
    with open("makedatabase.sql", "r") as f:
        makesql = f.read()
    with con:
        con.executescript(makesql)
    logger.debug("initialized db!")

intents = discord.Intents.default()
intents.members = True
activity = discord.Activity(name=f"you | {config.command_prefix}help", type=discord.ActivityType.watching)
bot = commands.Bot(command_prefix=config.command_prefix, help_command=None, case_insensitive=True, activity=activity,
                   intents=intents, allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=False,
                                                                             replied_user=True))
bot.add_cog(ErrorHandler(bot))
bot.add_cog(HelpCommand(bot))
bot.add_cog(FunCommands(bot))
bot.add_cog(AdminCommands(bot))
bot.add_cog(UtilityCommands(bot))
bot.add_cog(ModerationCog(bot))
bot.add_cog(scheduler.ScheduleInitCog(bot))
bot.add_cog(ModLogInitCog(bot))
bot.add_cog(FunnyBanner(bot))
bot.add_cog(MacroCog(bot))
bot.add_cog(AutoReactionCog(bot))
bot.add_cog(ThreadUtilsCog(bot))
bot.add_cog(BirthdayCog(bot))
bot.add_cog(NitroRolesCog(bot))
bot.add_cog(BulkLog(bot))


def logcommand(cmd):
    cmd = cmd.replace("\n", "\\n")
    if len(cmd) > 100:
        cmd = cmd[:100] + "..."
    return cmd


@bot.listen()
async def on_command(ctx):
    if isinstance(ctx.channel, discord.DMChannel):
        logger.log(25,
                   f"@{ctx.message.author.name}#{ctx.message.author.discriminator} ran "
                   f"'{logcommand(ctx.message.content)}' in DMs")
    else:
        logger.log(25,
                   f"@{ctx.message.author.name}#{ctx.message.author.discriminator}"
                   f" ({ctx.message.author.display_name}) ran '{logcommand(ctx.message.content)}' in channel "
                   f"#{ctx.channel.name} in server {ctx.guild}")


@bot.listen()
async def on_command_completion(ctx):
    logger.log(35,
               f"Command '{logcommand(ctx.message.content)}' by @{ctx.message.author.name}#{ctx.message.author.discriminator} "
               f"is complete!")


@bot.event
async def on_ready():
    scheduler.botcopy = bot
    logger.log(35, f"Logged in as {bot.user.name}!")


@bot.command()
async def testcommand(ctx: commands.Context, someargument: str, color: discord.Color=None):
    await ctx.reply(f"You inputted {someargument} and {color}")




bot.run(config.bot_token)
