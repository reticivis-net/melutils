import math
import sys
import typing

import aiosqlite
import nextcord as discord
from nextcord.ext import commands
from nextcord.ext.commands import BucketType
import si_prefix

import moderation
from clogs import logger
import database


def progress_bar(n: typing.Union[int, float], tot: typing.Union[int, float], cols: int = 20, border: str = "") -> str:
    """
    make UTF progress bar
    adapted from https://github.com/tqdm/tqdm/blob/fc69d5dcf578f7c7986fa76841a6b793f813df35/tqdm/std.py#L188-L213
    :param n: number of finished iterations
    :param tot: number of total iterations
    :param cols: width of progress bar not including border
    :param border: str at beginning and end of bar
    :return: string of
    """
    frac = n / tot
    charset = u" " + u''.join(map(chr, range(0x258F, 0x2587, -1)))
    nsyms = len(charset) - 1
    bar_length, frac_bar_length = divmod(int(frac * cols * nsyms), nsyms)

    res = charset[-1] * bar_length
    if bar_length < cols:  # whitespace padding
        res = f"{border}{res}{charset[frac_bar_length]}{charset[0] * (cols - bar_length - 1)}{border}"
    return res


def level_to_xp(level: int, xp_per_level: float):
    # https://www.wolframalpha.com/input/?i=sum+from+0+to+x+yx
    return 1 / 2 * level * (level + 1) * xp_per_level


def xp_to_level(xp: float, xp_per_level: float):
    # https://www.wolframalpha.com/input/?i=inverse+1%2F2+x+%281+%2B+x%29+y
    # yes sqrts are inefficient as hell but this command is not run often, cope about it frfr
    return math.floor(-1 / 2 + math.sqrt(8 * xp + xp_per_level) / (2 * math.sqrt(xp_per_level))
                      # fix float imprecision so like 3.999999999999 doesnt floor to 3
                      # theoretically possible for it to fuck up like at level 100000000000 but i do not care
                      + sys.float_info.epsilon)


class ExperienceCog(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
        # var and not db for performance and cause it doesnt really matter if its lost
        self.last_message_in_guild = {
            "user.guild": "datetime object"
        }
        # suspend XP gain for recalculation
        self.suspended_guild = []

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots and myself (which should be a bot but lets check anyways)
        if message.author.bot or message.author == self.bot.user:
            return
        # guilds only frfr
        if not message.guild:
            return
        if message.guild.id in self.suspended_guild:
            return

        # we dont care how long the timeout is if there is no entry for last message
        if f"{message.author.id}.{message.guild.id}" in self.last_message_in_guild:
            # get timeout between message for this guild
            async with database.db.execute("SELECT time_between_xp FROM server_config WHERE guild=?",
                                           (message.guild.id,)) as cur:
                cur: aiosqlite.Cursor
                timeout = await cur.fetchone()
            # error for now
            if timeout is None:
                return
            # make sure the minimum timeout has passed
            sincelastmsg = discord.utils.utcnow() - self.last_message_in_guild[f"{message.author.id}."
                                                                               f"{message.guild.id}"]
            if sincelastmsg.total_seconds() < timeout[0]:
                logger.debug(f"{message.author} has to wait {timeout[0] - sincelastmsg.total_seconds()} before "
                             f"gaining XP again in {message.guild}.")
                return
        # check if user or channel is excluded from gaining XP
        async with database.db.execute("SELECT userorchannel FROM guild_xp_exclusions WHERE guild=?",
                                       (message.guild.id,)) as cur:
            cur: aiosqlite.Cursor
            async for row in cur:
                excl = row[0]
                if message.channel.id == excl or message.author.id == excl:
                    logger.debug(f"{message.author} tried to gain XP as an excluded user or in an excluded channel"
                                 f" in {message.guild}. Exclusion is {excl}.")
                    return
        # create new record of 1 xp or update by 1
        await database.db.execute("""INSERT INTO experience(user, guild, experience) VALUES (?,?,1)
                            ON CONFLICT(user, guild) DO UPDATE SET experience = experience + 1;""",
                                  (message.author.id, message.guild.id))
        await database.db.commit()
        self.last_message_in_guild[f"{message.author.id}.{message.guild.id}"] = message.created_at
        logger.debug(f"{message.author} gained XP in {message.guild}")

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 60 * 60 * 24 * 7, BucketType.guild)
    async def recalculateguildxp(self, ctx: commands.Context):
        """
        recalculate guild's XP from message history
        """
        # TODO: implement
        raise NotImplementedError

    # TODO: add option to exclude all child threads
    @moderation.mod_only()
    @commands.command()
    async def excludefromxp(self, ctx: commands.Context,
                            userorchannel: typing.Union[discord.User, discord.TextChannel, discord.Thread]):
        """
        exclude user or channel from gaining XP

        :param ctx: discord context
        :param userorchannel: user or channel to disallow gaining XP.
        """
        async with database.db.execute("SELECT 1 FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                                       (ctx.guild.id, ctx.author.id)) as cur:
            if await cur.fetchone() is not None:
                exists = True
                await database.db.execute("DELETE FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                                          (ctx.guild.id, ctx.author.id))
            else:
                exists = False
                await database.db.execute(
                    "INSERT INTO guild_xp_exclusions(guild, userorchannel, mod_set) VALUES (?,?,true)",
                    (ctx.guild.id, userorchannel.id))
            await database.db.commit()
        await ctx.reply(f"✔️ {'Unexcluded' if exists else 'Excluded'} {userorchannel.mention} from XP.")

    @commands.command()
    async def togglemyxp(self, ctx: commands.Context):
        """
        enable or disable yourself from getting XP.
        """
        async with database.db.execute("SELECT mod_set FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                                       (ctx.guild.id, ctx.author.id)) as cur:
            res = await cur.fetchone()
            # user is not excluded from guild
            if res is None:
                result = "Disabled"
                await database.db.execute(
                    "INSERT INTO guild_xp_exclusions(guild, userorchannel, mod_set) VALUES (?,?,false)",
                    (ctx.guild.id, ctx.author.id))
                await database.db.commit()
            # user is excluded but not by a mod
            elif not res[0]:
                result = "Enabled"
                await database.db.execute("DELETE FROM guild_xp_exclusions WHERE guild=? AND userorchannel=?",
                                          (ctx.guild.id, ctx.author.id))
                await database.db.commit()
            # user is excluded by a mod, dont let them reenable xp on their own
            else:
                result = "Blocked"
        if result == "Blocked":
            await ctx.reply(f"❌ Your XP has been disabled by a moderator. Contact a moderator to get your XP "
                            f"re-enabled.\nIf you are a moderator, use `m.excludefromxp`.")
        else:
            # enabled or disabled
            await ctx.reply(f"✔️ {result} your XP.")

    @commands.command()
    async def rank(self, ctx: commands.Context, user: typing.Optional[discord.User] = None):
        # https://www.wolframalpha.com/input/?i=sum+from+0+to+x+yx
        if user is None:
            user = ctx.author
        async with database.db.execute("SELECT experience, experience_rank FROM (SELECT experience, RANK() OVER "
                                       "(ORDER BY experience DESC) experience_rank, user FROM experience "
                                       "WHERE guild = ?) WHERE user=?",
                                       (ctx.guild.id, user.id)) as cur:
            exp = await cur.fetchone()
        if exp is None:
            exp = 0
            rank = None
        else:
            exp, rank = exp
        async with database.db.execute("SELECT xp_change_per_level FROM server_config WHERE guild=?",
                                       (ctx.guild.id,)) as cur:
            change_per_level = await cur.fetchone()
        if change_per_level is None:
            # default
            change_per_level = 30
        else:
            change_per_level = change_per_level[0]
        level = xp_to_level(exp, change_per_level)
        xp_for_current_level = level_to_xp(level, change_per_level)
        xp_for_next_level = level_to_xp(level + 1, change_per_level)
        bar = progress_bar(exp - xp_for_current_level, xp_for_next_level - xp_for_current_level)

        embed = discord.Embed(color=discord.Color(0x15fe02))
        embed.set_author(name=user.display_name, icon_url=user.avatar.url)
        embed.set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url)
        embed.add_field(name="XP", value=f"{exp:,}", inline=True)
        embed.add_field(name="Level", value=f"{level}", inline=True)
        embed.add_field(name="Rank", value=f"{rank}", inline=True)
        embed.add_field(name="Progress To Next Level", value=f"{si_prefix.si_format(xp_for_current_level)} `{bar}` "
                                                             f"{si_prefix.si_format(xp_for_next_level)}",
                        inline=False)

        await ctx.reply(embed=embed)
    # TODO: leaderboard command
    # TODO: serverwide disable or enable
    # TODO: serverwide reset
    # TODO: user reset?
    # TODO: xp info command


'''
Steps to convert:
@bot.command() -> @commands.command()
@bot.listen() -> @commands.Cog.listener()
function(ctx): -> function(self, ctx)
bot -> self.bot
'''