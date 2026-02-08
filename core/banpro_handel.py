import asyncio
import json
import time
from collections import defaultdict, deque

from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..data import QQAdminDB
from ..utils import get_ats, get_nickname, parse_bool
from ..config import PluginConfig


class BanproHandle:
    def __init__(self, config: PluginConfig, db: QQAdminDB):
        self.cfg = config
        self.db = db
        self.builtin_ban_data = json.loads(
            config.ban_lexicon_path.read_text(encoding="utf-8")
        )
        self.builtin_ban_words = self.builtin_ban_data["words"]
        self.msg_timestamps: dict[str, dict[str, deque[float]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=self.cfg.spamming_count))
        )
        self.last_banned_time: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        # 记录投票 {group_id: {"target": target_id, "votes": {user_id: bool}, "expire": timestamp, "threshold": threshold,}}
        self.vote_cache: dict[str, dict] = {}

    async def handle_word_ban_time(
        self, event: AiocqhttpMessageEvent, time: int | None
    ):
        """设置禁词禁言时长"""
        gid = event.get_group_id()
        if isinstance(time, int):
            await self.db.set(gid, "word_ban_time", time)
            msg = (
                f"本群禁词禁言时长已设为：{time} 秒"
                if time > 0
                else "本群禁词禁言已关闭"
            )
            await event.send(event.plain_result(msg))
        else:
            status = await self.db.get(gid, "word_ban_time", 0)
            await event.send(event.plain_result(f"本群禁词禁言时长：{status} 秒"))

    async def handle_ban_words(self, event: AiocqhttpMessageEvent):
        """设置/查看违禁词"""
        gid = event.get_group_id()
        raw = event.message_str.partition(" ")[2]

        # 1. 空指令：查看
        if not raw:
            words = await self.db.get(gid, "custom_ban_words", [])
            await event.send(event.plain_result(f"本群违禁词：{words}"))
            return

        # 2. 纯单词列表（无 +/-）：整表覆写
        toks = raw.split()
        if all(not tok.startswith(("+", "-")) for tok in toks):
            await self.db.set(gid, "custom_ban_words", toks)
            await event.send(
                event.plain_result(f"本群违禁词已覆写为：{' '.join(toks)}")
            )
            return

        # 3. 增量模式：+word / -word
        curr = set(await self.db.get(gid, "custom_ban_words", []))
        added, removed = [], []

        for tok in toks:
            if tok.startswith("+") and len(tok) > 1:
                w = tok[1:]
                if w not in curr:
                    curr.add(w)
                    added.append(w)
            elif tok.startswith("-") and len(tok) > 1:
                w = tok[1:]
                if w in curr:
                    curr.discard(w)
                    removed.append(w)

        await self.db.set(gid, "custom_ban_words", list(curr))

        reply = ["本群违禁词"]
        if added:
            reply.append(f"新增：{'、'.join(added)}")
        if removed:
            reply.append(f"移除：{'、'.join(removed)}")
        if not added and not removed:
            reply.append("无变动")
        await event.send(event.plain_result("\n".join(reply)))

    async def handle_builtin_ban_words(
        self, event: AiocqhttpMessageEvent, mode_str: str | bool | None
    ):
        """启用/停用内置违禁词"""
        gid = event.get_group_id()
        mode = parse_bool(mode_str)

        if isinstance(mode, bool):
            await self.db.set(gid, "builtin_ban", mode)
            await event.send(event.plain_result(f"本群内置禁词：{mode}"))
        else:
            status = await self.db.get(gid, "builtin_ban", False)
            await event.send(event.plain_result(f"本群内置禁词：{status}"))

    async def on_ban_words(self, event: AiocqhttpMessageEvent):
        """检测禁词并撤回消息、禁言用户"""
        gid = event.get_group_id()

        # 检测自定义的违禁词
        if ban_words := await self.db.get(gid, "custom_ban_words", []):
            if await self.check_ban_words(event, ban_words):
                return

        # 检测内置违禁词
        if await self.db.get(gid, "builtin_ban", False):
            if await self.check_ban_words(event, self.builtin_ban_words):
                return

    async def check_ban_words(
        self, event: AiocqhttpMessageEvent, ban_words: list[str]
    ) -> bool:
        """检测违禁词并撤回消息"""
        gid = event.get_group_id()
        msg = event.message_str.lower()
        for word in ban_words:
            if word in msg:
                # 撤回消息
                try:
                    message_id = event.message_obj.message_id
                    await event.bot.delete_msg(message_id=int(message_id))
                except Exception:
                    pass
                # 禁言发送者
                ban_time = await self.db.get(gid, "word_ban_time", 0)
                if ban_time > 0:
                    try:
                        await event.bot.set_group_ban(
                            group_id=int(event.get_group_id()),
                            user_id=int(event.get_sender_id()),
                            duration=ban_time,
                        )
                    except Exception:
                        logger.error(f"bot在群{event.get_group_id()}权限不足，禁言失败")
                        pass
                return True
        return False

    async def handle_spamming_ban_time(
        self, event: AiocqhttpMessageEvent, time: int | None
    ):
        """设置刷屏禁言时长"""
        gid = event.get_group_id()
        if isinstance(time, int):
            await self.db.set(gid, "word_ban_time", time)
            msg = (
                f"本群刷屏禁言时长已设为：{time} 秒"
                if time > 0
                else "本群刷屏禁言已关闭"
            )
            await event.send(event.plain_result(msg))
        else:
            status = await self.db.get(gid, "word_ban_time", 0)
            await event.send(event.plain_result(f"本群刷屏禁言时长：{status} 秒"))

    async def spamming_ban(self, event: AiocqhttpMessageEvent):
        """刷屏禁言"""
        group_id = event.get_group_id()
        sender_id = event.get_sender_id()
        ban_time = await self.db.get(group_id, "spamming_ban_time", 0)
        if (
            sender_id == event.get_self_id()
            or ban_time <= 0
            or len(event.get_messages()) == 0
        ):
            return

        now = time.time()

        last_time = self.last_banned_time[group_id][sender_id]
        if now - last_time < ban_time:
            return

        timestamps = self.msg_timestamps[group_id][sender_id]
        timestamps.append(now)
        count = self.cfg.spamming_count
        if len(timestamps) >= count:
            recent = list(timestamps)[-count:]
            intervals = [recent[i + 1] - recent[i] for i in range(count - 1)]
            if all(interval < self.cfg.spamming_interval for interval in intervals):
                # 提前写入禁止标记，防止并发重复禁
                self.last_banned_time[group_id][sender_id] = now

                try:
                    await event.bot.set_group_ban(
                        group_id=int(group_id),
                        user_id=int(sender_id),
                        duration=ban_time,
                    )
                    nickname = await get_nickname(event, sender_id)
                    await event.send(
                        event.plain_result(f"检测到{nickname}刷屏，已禁言")
                    )
                except Exception:
                    logger.error(f"bot在群{group_id}权限不足，禁言失败")
                timestamps.clear()

    async def start_vote_mute(self, event, ban_time: int | None = None):
        """
        发起投票禁言：如果已有对该用户的投票，直接提示
        """
        target_ids = get_ats(event)
        if not target_ids:
            return
        target_id = target_ids[0]
        ban_time = self.cfg.get_ban_time(ban_time)
        group_id = event.get_group_id()

        if group_id in self.vote_cache:
            await event.send(event.plain_result("群内已有正在进行的禁言投票"))
            return

        ttl = self.cfg.vote_ban.ttl
        threshold = self.cfg.vote_ban.threshold

        expire_at = time.time() + ttl
        self.vote_cache[group_id] = {
            "target": target_id,
            "votes": {},
            "ban_time": ban_time,
            "expire": expire_at,
            "threshold": threshold,
        }

        nickname = await get_nickname(event, target_id)
        await event.send(
            event.plain_result(
                f"已发起对 {nickname} 的禁言投票(禁言{ban_time}秒)，输入“赞同禁言/反对禁言”进行表态，{ttl}秒后结算"
            )
        )

        # ===== 新增：定时结算逻辑 =====
        async def settle_vote():
            await asyncio.sleep(ttl)
            record = self.vote_cache.get(group_id)
            if not record:
                return  # 已被提前结算
            votes = list(record["votes"].values())
            agree_count = sum(votes)
            disagree_count = len(votes) - agree_count
            nickname2 = await get_nickname(event, record["target"])

            # 到期按多数票决定（平票视为否决）
            if agree_count > disagree_count:
                try:
                    await event.bot.set_group_ban(
                        group_id=int(group_id),
                        user_id=int(record["target"]),
                        duration=record["ban_time"],
                    )
                    await event.send(
                        event.plain_result(f"投票时间到！已禁言{nickname2}")
                    )
                except Exception:
                    logger.error(f"bot在群{group_id}权限不足，禁言失败")
            else:
                await event.send(
                    event.plain_result(f"投票时间到！禁言被否决，{nickname2}安全了")
                )
            # 清理投票记录
            del self.vote_cache[group_id]

        asyncio.create_task(settle_vote())

    async def vote_mute(self, event: AiocqhttpMessageEvent, agree: bool):
        """
        赞同/反对禁言
        agree=True 表示赞同，False 表示反对
        """
        group_id = event.get_group_id()
        voter_id = event.get_sender_id()

        record = self.vote_cache.get(group_id)
        if not record:
            await event.send(event.plain_result("当前没有进行中的禁言投票"))
            return

        threshold = record["threshold"]
        target_id = record["target"]

        # 记录/更新该用户的立场
        record["votes"][voter_id] = agree

        votes = list(record["votes"].values())
        agree_count = sum(votes)
        disagree_count = len(votes) - agree_count
        nickname = await get_nickname(event, target_id)

        # 提前达成赞同阈值 → 立即禁言
        if agree_count >= threshold:
            try:
                await event.bot.set_group_ban(
                    group_id=int(group_id),
                    user_id=int(target_id),
                    duration=record["ban_time"],
                )
                await event.send(event.plain_result(f"投票通过！已禁言{nickname}"))
            except Exception:
                logger.error(f"bot在群{group_id}权限不足，禁言失败")
            finally:
                # 清理记录（定时任务见前面会检测到记录已删除并直接返回）
                del self.vote_cache[group_id]
            return

        # 提前达成反对阈值 → 立即否决
        if disagree_count >= threshold:
            await event.send(event.plain_result(f"禁言投票被否决，{nickname}安全了"))
            del self.vote_cache[group_id]
            return

        # 否则展示当前进度
        await event.send(
            event.plain_result(
                f"禁言【{nickname}】：\n赞同({agree_count}/{threshold})\n反对({disagree_count}/{threshold})"
            )
        )
