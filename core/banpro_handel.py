import asyncio
import json
import random
import re
import time
from collections import defaultdict, deque
from pathlib import Path

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..data import QQAdminDB
from ..utils import get_ats, get_nickname, parse_bool


class BanproHandle:
    # 匹配链接的正则表达式
    URL_PATTERN = re.compile(
        r'https?://([a-zA-Z0-9][-a-zA-Z0-9]*\.)+[a-zA-Z]{2,}[-a-zA-Z0-9@:%._+~#=/?&]*|'
        r'([a-zA-Z0-9][-a-zA-Z0-9]*\.)+[a-zA-Z]{2,}[-a-zA-Z0-9@:%._+~#=/?&]*',
        re.IGNORECASE
    )

    def __init__(self, config: AstrBotConfig, db: QQAdminDB, ban_lexicon_path: Path):
        self.conf = config
        self.db = db
        self.builtin_ban_words = json.loads(
            ban_lexicon_path.read_text(encoding="utf-8")
        )["words"]
        self.spamming_count = 5
        self.spamming_interval = 0.5
        self.msg_timestamps: dict[str, dict[str, deque[float]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=self.spamming_count))
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

        # 设置违禁词
        if words := event.message_str.partition(" ")[2].split():
            await self.db.set(gid, "custom_ban_words", words)
            await event.send(event.plain_result(f"本群违禁词已设为：{words}"))
        else:
            # 查看违禁词
            words = await self.db.get(gid, "custom_ban_words", [])
            await event.send(event.plain_result(f"本群违禁词：{words}"))

    async def handle_add_ban_words(self, event: AiocqhttpMessageEvent):
        """增加违禁词（在原有基础上添加）"""
        gid = event.get_group_id()

        if new_words := event.message_str.partition(" ")[2].split():
            # 获取现有违禁词
            existing = await self.db.get(gid, "custom_ban_words", [])
            # 合并并去重
            merged = list(dict.fromkeys(existing + new_words))
            await self.db.set(gid, "custom_ban_words", merged)
            await event.send(event.plain_result(f"已添加违禁词：{new_words}\n当前违禁词：{merged}"))
        else:
            await event.send(event.plain_result("请指定要添加的违禁词，用空格分隔"))

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
        ban_words = await self.db.get(gid, "custom_ban_words", [])
        builtin_enabled = await self.db.get(gid, "builtin_ban", False)

        # 如果两个都没启用，直接返回
        if not ban_words and not builtin_enabled:
            return

        # 检测自定义的违禁词
        if ban_words:
            if await self.check_ban_words(event, ban_words):
                return

        # 检测内置违禁词
        if builtin_enabled:
            if await self.check_ban_words(event, self.builtin_ban_words):
                return

    async def check_ban_words(
        self, event: AiocqhttpMessageEvent, ban_words: list[str]
    ) -> bool:
        """检测内置违禁词并撤回消息"""
        gid = event.get_group_id()
        for word in ban_words:
            if word in event.message_str:
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
        count = self.spamming_count
        if len(timestamps) >= count:
            recent = list(timestamps)[-count:]
            intervals = [recent[i + 1] - recent[i] for i in range(count - 1)]
            if all(interval < self.spamming_interval for interval in intervals):
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
        if not ban_time or not isinstance(ban_time, int):
            ban_time = random.randint(
                *map(int, self.conf["random_ban_time"].split("~"))
            )
        group_id = event.get_group_id()

        if group_id in self.vote_cache:
            await event.send(event.plain_result("群内已有正在进行的禁言投票"))
            return

        expire_at = time.time() + self.conf["vote_ban"]["ttl"]
        self.vote_cache[group_id] = {
            "target": target_id,
            "votes": {},
            "ban_time": ban_time,
            "expire": expire_at,
            "threshold": self.conf["vote_ban"]["threshold"],
        }

        nickname = await get_nickname(event, target_id)
        await event.send(
            event.plain_result(
                f"已发起对 {nickname} 的禁言投票(禁言{ban_time}秒)，输入“赞同禁言/反对禁言”进行表态，{self.conf['vote_ban']['ttl']}秒后结算"
            )
        )

        # ===== 新增：定时结算逻辑 =====
        async def settle_vote():
            await asyncio.sleep(self.conf["vote_ban"]["ttl"])
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

    # ==================== 链接撤回功能 ====================

    async def handle_link_recall(
        self, event: AiocqhttpMessageEvent, mode_str: str | bool | None
    ):
        """启用/停用链接撤回"""
        gid = event.get_group_id()
        mode = parse_bool(mode_str)

        if isinstance(mode, bool):
            await self.db.set(gid, "link_recall", mode)
            status = "开启" if mode else "关闭"
            await event.send(event.plain_result(f"本群链接撤回已{status}"))
        else:
            status = await self.db.get(gid, "link_recall", False)
            await event.send(event.plain_result(f"本群链接撤回：{'开启' if status else '关闭'}"))

    async def handle_link_whitelist(self, event: AiocqhttpMessageEvent):
        """设置/查看链接白名单"""
        gid = event.get_group_id()

        # 设置白名单
        if domains := event.message_str.partition(" ")[2].split():
            await self.db.set(gid, "link_whitelist", domains)
            await event.send(event.plain_result(f"本群链接白名单已设为：{domains}"))
        else:
            # 查看白名单
            domains = await self.db.get(gid, "link_whitelist", [])
            if domains:
                await event.send(event.plain_result(f"本群链接白名单：{domains}"))
            else:
                await event.send(event.plain_result("本群链接白名单为空"))

    async def on_link_recall(self, event: AiocqhttpMessageEvent):
        """检测链接并撤回（不禁言）"""
        gid = event.get_group_id()

        # 检查是否开启链接撤回
        link_recall_enabled = await self.db.get(gid, "link_recall", False)
        if not link_recall_enabled:
            return

        # 查找消息中的链接
        url_matches = list(self.URL_PATTERN.finditer(event.message_str))
        if not url_matches:
            return

        # 获取白名单
        whitelist = await self.db.get(gid, "link_whitelist", [])

        # 检查是否有非白名单链接
        for url_match in url_matches:
            url = url_match.group(0)
            # 检查是否在白名单中
            if not self._is_url_whitelisted(url, whitelist):
                # 撤回消息
                try:
                    message_id = event.message_obj.message_id
                    await event.bot.delete_msg(message_id=int(message_id))
                    logger.info(f"已撤回群{gid}中用户{event.get_sender_id()}的链接消息")
                except Exception:
                    logger.error(f"bot在群{gid}权限不足，撤回链接消息失败")
                return

    def _is_url_whitelisted(self, url: str, whitelist: list[str]) -> bool:
        """检查链接是否在白名单中"""
        # 提取域名
        url_lower = url.lower()
        # 移除协议前缀
        if url_lower.startswith("http://"):
            url_lower = url_lower[7:]
        elif url_lower.startswith("https://"):
            url_lower = url_lower[8:]

        # 获取域名部分（去除路径）
        domain = url_lower.split("/")[0]

        # 检查域名是否匹配白名单
        for white_domain in whitelist:
            white_domain_lower = white_domain.lower()
            # 精确匹配或子域名匹配
            if domain == white_domain_lower or domain.endswith("." + white_domain_lower):
                return True
        return False
