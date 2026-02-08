from __future__ import annotations

import asyncio
import json
import zoneinfo
from datetime import datetime, timedelta
from pathlib import Path

from aiocqhttp import CQHttp, Event
from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_platform_adapter import (
    AiocqhttpAdapter,
)
from astrbot.core.star.context import Context

from ..config import PluginConfig


class CurfewStore:
    """负责宵禁任务数据的统一持久化"""

    def __init__(self, file: Path):
        self.file = file
        # {"bot_id": {"group_id": {"start_time", "end_time"}}
        self.data: dict[str, dict[str, dict[str, str]]] = {}

    def load(self) -> dict[str, dict]:
        if not self.file.exists():
            return {}
        try:
            with self.file.open("r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception as e:
            logger.error(f"加载宵禁任务数据失败: {e}", exc_info=True)
            self.data = {}
        return self.data

    def save(self):
        try:
            with self.file.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            logger.debug("宵禁任务数据已保存")
        except Exception as e:
            logger.error(f"保存宵禁任务数据失败: {e}", exc_info=True)


class GroupCurfew:
    """单群宵禁任务，维护两个 job（开始/结束）"""

    def __init__(
        self,
        bot: CQHttp,
        group_id: str,
        start_time: str,
        end_time: str,
        scheduler: AsyncIOScheduler,
        manager: BotCurfewManager | None = None,
    ):
        self.bot = bot
        self.group_id = group_id
        self._start_time_str = start_time
        self._end_time_str = end_time
        self.scheduler = scheduler
        self.manager = manager
        self.start_job: Job | None = None
        self.end_job: Job | None = None
        self.whole_ban_status = False
        self._lock = asyncio.Lock()

    async def _enable_curfew(self):
        """开启宵禁"""
        async with self._lock:
            if self.whole_ban_status:
                return
            self.whole_ban_status = True
        try:
            await self.bot.send_group_msg(
                group_id=int(self.group_id),
                message=f"【{self._start_time_str}】本群宵禁开始！",
            )
            await self.bot.set_group_whole_ban(group_id=int(self.group_id), enable=True)
            logger.info(f"群 {self.group_id} 已开启全体禁言")
        except Exception as e:
            logger.error(f"群 {self.group_id} 宵禁开启失败: {e}", exc_info=True)
            async with self._lock:
                self.whole_ban_status = False
            # 异常时移除群
            if hasattr(self, "manager") and self.manager:
                await self.manager.remove_group_on_error(self.group_id)

    async def _disable_curfew(self):
        """关闭宵禁"""
        async with self._lock:
            if not self.whole_ban_status:
                return
            self.whole_ban_status = False
        try:
            await self.bot.send_group_msg(
                group_id=int(self.group_id),
                message=f"【{self._end_time_str}】本群宵禁结束！",
            )
            await self.bot.set_group_whole_ban(
                group_id=int(self.group_id), enable=False
            )
            logger.info(f"群 {self.group_id} 已解除全体禁言")
        except Exception as e:
            logger.error(f"群 {self.group_id} 宵禁解除失败: {e}", exc_info=True)
            async with self._lock:
                self.whole_ban_status = True


    async def start_curfew_task(self):
        """注册 APScheduler 定时任务"""
        hour_s, minute_s = map(int, self._start_time_str.split(":"))
        hour_e, minute_e = map(int, self._end_time_str.split(":"))

        self.start_job = self.scheduler.add_job(
            self._enable_curfew,
            trigger=CronTrigger(hour=hour_s, minute=minute_s),
            name=f"curfew_start_{self.group_id}",
            misfire_grace_time=60,  # 如果错过 60 秒内仍执行
        )
        self.end_job = self.scheduler.add_job(
            self._disable_curfew,
            trigger=CronTrigger(hour=hour_e, minute=minute_e),
            name=f"curfew_end_{self.group_id}",
            misfire_grace_time=60,
        )
        # 立即检查是否跨天在宵禁时间段
        now = datetime.now(self.scheduler.timezone)
        start_dt = now.replace(hour=hour_s, minute=minute_s, second=0, microsecond=0)
        end_dt = now.replace(hour=hour_e, minute=minute_e, second=0, microsecond=0)
        if start_dt >= end_dt:  # 跨天
            end_dt += timedelta(days=1)
        if start_dt <= now < end_dt:
            logger.debug(f"当前时间群 {self.group_id} 在宵禁时间段，立即启用禁言")
            await self._enable_curfew()


    def stop_curfew_task(self):
        """移除 APScheduler 任务（同步即可）"""
        if self.start_job:
            self.start_job.remove()
            self.start_job = None
        if self.end_job:
            self.end_job.remove()
            self.end_job = None
        logger.info(f"群 {self.group_id} 宵禁任务已移除")


class BotCurfewManager:
    """单 Bot 宵禁调度，统一管理多群"""

    def __init__(
        self, bot: CQHttp, bot_id: str, store: CurfewStore, scheduler: AsyncIOScheduler
    ):
        self.bot = bot
        self.bot_id = bot_id
        self.store = store
        self.scheduler = scheduler
        self.store.data.setdefault(bot_id, {})
        self.bot_data = self.store.data[bot_id]
        self.tasks: dict[str, GroupCurfew] = {}

    async def restore_from_store(self):
        """恢复群聊禁言任务"""
        for group_id, times in self.bot_data.items():
            try:
                cw = GroupCurfew(
                    self.bot,
                    group_id,
                    times["start_time"],
                    times["end_time"],
                    self.scheduler,
                )
                await cw.start_curfew_task()
                self.tasks[group_id] = cw
            except Exception as e:
                logger.error(f"恢复群 {group_id} 宵禁失败: {e}")

    def _save(self):
        self.bot_data.clear()
        self.bot_data.update(
            {
                gid: {"start_time": cw._start_time_str, "end_time": cw._end_time_str}
                for gid, cw in self.tasks.items()
            }
        )
        self.store.save()

    async def remove_group_on_error(self, group_id: str):
        """当群无法操作时自动移除"""
        if group_id in self.tasks:
            cw = self.tasks.pop(group_id)
            cw.stop_curfew_task()
        if group_id in self.bot_data:
            self.bot_data.pop(group_id)
        self._save()
        logger.info(f"群 {group_id} 因操作失败已从宵禁任务中移除")

    async def enable_curfew(self, group_id: str, start_time: str, end_time: str):
        """创建群聊的宵禁任务"""
        if group_id in self.tasks:
            self.tasks[group_id].stop_curfew_task()
        cw = GroupCurfew(
            self.bot, group_id, start_time, end_time, self.scheduler, manager=self
        )

        await cw.start_curfew_task()
        self.tasks[group_id] = cw
        self._save()

    async def disable_curfew(self, group_id: str) -> bool:
        """关闭群聊的宵禁任务"""
        cw = self.tasks.pop(group_id, None)
        if cw:
            cw.stop_curfew_task()
            self.bot_data.pop(group_id, None)
            self._save()
            return True
        return False


class CurfewHandle:
    """多 Bot 宵禁处理类"""

    def __init__(self, context: Context, config: PluginConfig):
        self.context = context
        tz = self.context.get_config().get("timezone")
        self.timezone = (
            zoneinfo.ZoneInfo(tz) if tz else zoneinfo.ZoneInfo("Asia/Shanghai")
        )
        self.scheduler = AsyncIOScheduler(timezone=self.timezone)
        self.scheduler.start()
        self.store = CurfewStore(config.curfew_file)
        self.store.load()
        self.curfew_managers: dict[str, BotCurfewManager] = {}

    async def _initialize_aiocqhttp_adapter(self, inst: AiocqhttpAdapter):
        """初始化单个 AiocqhttpAdapter 的宵禁管理器"""
        bot_id = None

        # client直接获取 bot_id
        if client := inst.get_client():
            try:
                login_data = await client.get_login_info()
                bot_id = str(login_data.get("user_id"))
            except Exception:
                pass

        # client 在 ws 连接成功时获取
        if not bot_id:
            bot_id_future = asyncio.get_event_loop().create_future()

            @client.on_websocket_connection
            async def on_ws_connect(event_: Event):
                if not bot_id_future.done():
                    bot_id_future.set_result(str(event_.self_id))

            try:
                bot_id = await asyncio.wait_for(bot_id_future, timeout=25)
            except asyncio.TimeoutError:
                logger.warning(f"{inst.metadata.id} 等待 WebSocket 连接超时")
                return

        # 宵禁初始化
        try:
            self.store.data.setdefault(bot_id, {})
            curfew_mgr = BotCurfewManager(client, bot_id, self.store, self.scheduler)
            self.curfew_managers[bot_id] = curfew_mgr
            await curfew_mgr.restore_from_store()
            logger.debug(f"{inst.metadata.id}({bot_id}) 宵禁初始化完成")
        except Exception as e:
            logger.error(f"{inst.metadata.id} 宵禁初始化失败: {e}")

    async def initialize(self):
        tasks = [
            self._initialize_aiocqhttp_adapter(inst)
            for inst in self.context.platform_manager.platform_insts
            if isinstance(inst, AiocqhttpAdapter)
        ]
        if tasks:
            await asyncio.gather(*tasks)


    @staticmethod
    def parse_time(time_str: str) -> tuple[str, int, int] | None:
        """
        统一处理时间格式
        输入: "HH:MM" 或带中文冒号 "HH：MM"
        返回: (原始字符串, hour:int, minute:int)
        出错返回 None
        """
        try:
            time_str_clean = time_str.strip().replace("：", ":")
            hour, minute = map(int, time_str_clean.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            return time_str_clean, hour, minute
        except Exception:
            return None

    async def start_curfew(
        self,
        event: AiocqhttpMessageEvent,
        input_start_time: str | None = None,
        input_end_time: str | None = None,
    ):
        if not input_start_time or not input_end_time:
            await event.send(event.plain_result("未输入范围 HH:MM HH:MM"))
            return

        start_parsed = self.parse_time(input_start_time)
        end_parsed = self.parse_time(input_end_time)

        if not start_parsed or not end_parsed:
            await event.send(event.plain_result("时间格式错误，应为 HH:MM"))
            return

        start_str, start_h, start_m = start_parsed
        end_str, end_h, end_m = end_parsed

        if start_h == end_h and start_m == end_m:
            await event.send(event.plain_result("开始时间和结束时间不能相同"))
            return

        curfew_mgr = self.curfew_managers.get(event.get_self_id())
        if not curfew_mgr:
            await event.send(event.plain_result("宵禁管理器未初始化"))
            return

        await curfew_mgr.enable_curfew(event.get_group_id(), start_str, end_str)
        await event.send(event.plain_result(f"宵禁任务已创建：{start_str}~{end_str}"))

    async def stop_curfew(self, event: AiocqhttpMessageEvent):
        curfew_mgr = self.curfew_managers.get(event.get_self_id())
        if not curfew_mgr:
            await event.send(event.plain_result("宵禁管理器未初始化"))
            return
        if await curfew_mgr.disable_curfew(event.get_group_id()):
            await event.send(event.plain_result("本群宵禁任务已取消"))
        else:
            await event.send(event.plain_result("本群没有宵禁任务"))

    async def stop_all_tasks(self):
        for _, curfew_mgr in self.curfew_managers.items():
            for cw in list(curfew_mgr.tasks.values()):
                cw.stop_curfew_task()
            curfew_mgr.tasks.clear()
        self.store.save()
