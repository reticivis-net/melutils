import asyncio
import io
import typing

import discord
from discord.ext import commands

import database
from clogs import logger
from moderation import mod_only
from modlog import modlog


class AutoReactionCog(commands.Cog, name="AutoReaction"):
    """
    commands for setting up auto-reactions
    """

    def __init__(self, bot):
        self.bot = bot

    @mod_only()
    @commands.command(aliases=["addautoreactionrule", "createautoreaction", "createautoreactionrule", "addar", "aar",
                               "createar"])
    @commands.guild_only()
    async def addautoreaction(self, ctx: commands.Context,
                              channel: typing.Union[discord.TextChannel, discord.Thread, discord.ForumChannel],
                              emoji: discord.Emoji, react_to_threads: bool = False):
        """
        create a new autoreaction rule
        :param ctx: discord context
        :param channel: channel to react in
        :param emoji: emoji to react with
        :param react_to_threads: should I react to threads of the channel?
        """
        await database.db.execute(
            "REPLACE INTO auto_reactions(guild,channel,emoji,react_to_threads) VALUES (?,?,?,?)",
            (ctx.guild.id, channel.id, emoji.id, react_to_threads))
        await database.db.commit()
        await ctx.reply(f"✔️ I will now react to all messages in {channel.mention} with {emoji}.")
        await modlog(
            f"{ctx.author.mention} (`{ctx.author}`) added new autoreaction rule ({emoji} in {channel.mention})",
            ctx.guild.id, modid=ctx.author.id)

    @mod_only()
    @commands.command(
        aliases=["deleteautoreaction", "deleteautoreactionrule", "removeautoreactionrule", "removear", "deletear",
                 "delar", "rar", "dar"])
    @commands.guild_only()
    async def removeautoreaction(self, ctx: commands.Context,
                                 channel: typing.Union[discord.TextChannel, discord.Thread, discord.ForumChannel],
                                 emoji: discord.Emoji):
        """
        remove an autoreaction rule

        :param ctx: discord context
        :param channel: channel of reactions
        :param emoji: emoji to no longer react with
        """
        cur = await database.db.execute(
            "DELETE FROM auto_reactions WHERE channel=? AND emoji=?",
            (channel.id, emoji.id))
        await database.db.commit()
        if cur.rowcount > 0:
            await ctx.reply(f"✔️ Removed autoreaction rule for {channel.mention}.")
            await modlog(f"{ctx.author.mention} (`{ctx.author}`) removed autoreaction rule "
                         f"({emoji} in {channel.mention}).", ctx.guild.id, modid=ctx.author.id)
        else:
            await ctx.reply("⚠️ No matching autoreaction rule found!")

    @commands.command(aliases=["autoreactions", "ars", "ar"])
    @commands.guild_only()
    async def autoreactionrules(self, ctx: commands.Context):
        """
        list all autoreaction rules
        """
        async with database.db.execute("SELECT * FROM auto_reactions WHERE guild=?",
                                       (ctx.guild.id,)) as cursor:
            arrules = await cursor.fetchall()
        outstr = f"{len(arrules)} autoreaction rule{'' if len(arrules) == 1 else 's'}:\n"
        for rule in arrules:
            outstr += f"<#{rule[1]}>: {discord.utils.get(ctx.guild.emojis, id=rule[2])}" \
                      f"{' (applies to threads)' if rule[3] else ''}\n"
        if len(outstr) < 2000:
            await ctx.reply(outstr, )
        else:
            with io.StringIO() as buf:
                buf.write(outstr)
                buf.seek(0)
                await ctx.reply(f"{len(arrules)} autoreaction rule{'' if len(arrules) == 1 else 's'}.",
                                file=discord.File(buf, filename="arrules.txt"))
        logger.debug(arrules)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        parentid = message.channel.parent_id if isinstance(message.channel, discord.Thread) else -1
        async with database.db.execute("SELECT * FROM auto_reactions WHERE channel=? "
                                       "OR (react_to_threads=true AND channel=?)",
                                       (message.channel.id, parentid)) as cursor:
            async for emid in cursor:
                emoji = discord.utils.get(message.guild.emojis, id=emid[2])
                if emoji is None:
                    await database.db.execute("DELETE FROM auto_reactions WHERE channel=? AND emoji=?",
                                              (emid[1], emid[2]))
                    await database.db.commit()
                    await modlog(f"Removed autoreaction rule from {message.channel.mention} because emoji with id "
                                 f"`{emid[2]}` no longer exists.", message.guild.id)
                else:
                    asyncio.create_task(message.add_reaction(emoji))

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if isinstance(thread.parent, discord.ForumChannel):
            message = [message async for message in thread.history(limit=1, oldest_first=True)][0]
            async with database.db.execute("SELECT * FROM auto_reactions WHERE channel=? ",
                                           (thread.parent_id,)) as cursor:
                async for emid in cursor:
                    emoji = discord.utils.get(message.guild.emojis, id=emid[2])
                    if emoji is None:
                        await database.db.execute("DELETE FROM auto_reactions WHERE channel=? AND emoji=?",
                                                  (emid[1], emid[2]))
                        await database.db.commit()
                        await modlog(f"Removed autoreaction rule from {message.channel.mention} because emoji with id "
                                     f"`{emid[2]}` no longer exists.", message.guild.id)
                    else:
                        asyncio.create_task(message.add_reaction(emoji))
