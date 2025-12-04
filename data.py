import asyncio
import json
from pathlib import Path

import aiosqlite

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig


class QQAdminDB:
    """
    群管插件数据库（简化版）
    - 无锁：asyncio 单线程天然无并发风险
    - 启动时加载所有群数据到缓存
    """

    def __init__(self, config: AstrBotConfig, db_path: Path):
        self.db_path = db_path
        jconf = config["join_config"]

        self.default_cfg = {
            "switch": jconf["default_switch"],
            "accept_words": [],
            "reject_words": [],
            "no_match_reject": jconf["default_no_match_reject"],
            "min_level": jconf["default_min_level"],
            "max_time": jconf["default_max_time"],
            "block_ids": [],
            "ban_words": [],
        }

        self._conn: aiosqlite.Connection | None = None
        self._cache: dict[str, dict] = {}
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def init(self):
        """初始化数据库连接并加载所有群组数据（仅调用一次）"""
        async with self._init_lock:
            if self._initialized:
                return

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(self.db_path))
            self._conn.row_factory = aiosqlite.Row

            await self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                """
            )
            await self._conn.commit()

            # -------- 一次性加载全部 group --------
            async with self._conn.execute("SELECT group_id, data FROM groups;") as cur:
                async for row in cur:
                    try:
                        self._cache[row["group_id"]] = json.loads(row["data"])
                    except Exception:
                        logger.exception("解析 group 数据失败: %s", row["group_id"])

            self._initialized = True
            logger.info("QQAdminDB initialized, loaded %d groups.", len(self._cache))

    # -------- 工具方法 --------
    async def _save_to_db(self, group_id: str, data: dict):
        """写入数据库（串行，不需要锁）"""
        if not self._conn:
            raise RuntimeError("DB 未初始化，请先 init()")

        j = json.dumps(data, ensure_ascii=False)
        await self._conn.execute(
            """
            INSERT INTO groups(group_id, data)
            VALUES (?, ?)
            ON CONFLICT(group_id)
            DO UPDATE SET data=excluded.data;
            """,
            (group_id, j),
        )
        await self._conn.commit()

    # -------- 核心接口 --------
    async def ensure_group(self, group_id: str):
        """确保 group 在缓存内，若无则创建默认配置"""
        if group_id not in self._cache:
            data = json.loads(json.dumps(self.default_cfg))
            self._cache[group_id] = data
            await self._save_to_db(group_id, data)

    async def get(self, group_id: str) -> dict:
        await self.ensure_group(group_id)
        return self._cache[group_id]

    async def set(self, group_id: str, **kwargs):
        await self.ensure_group(group_id)
        data = self._cache[group_id]

        data.update(kwargs)
        self._cache[group_id] = data

        await self._save_to_db(group_id, data)

    async def remove(self, group_id: str):
        if not self._conn:
            raise RuntimeError("DB 未初始化，请先 init()")

        await self._conn.execute("DELETE FROM groups WHERE group_id = ?;", (group_id,))
        await self._conn.commit()

        self._cache.pop(group_id, None)

    # -------- 便捷只读方法 --------
    async def get_switch(self, group_id: str) -> bool:
        return bool((await self.get(group_id)).get("switch", False))

    async def get_accept_words(self, group_id: str) -> list[str]:
        return list((await self.get(group_id)).get("accept_words", []))

    async def get_reject_words(self, group_id: str) -> list[str]:
        return list((await self.get(group_id)).get("reject_words", []))

    async def get_no_match_reject(self, group_id: str):
        return bool((await self.get(group_id)).get("no_match_reject", False))

    async def get_min_level(self, group_id: str) -> int:
        return int((await self.get(group_id)).get("min_level", 0))

    async def get_max_time(self, group_id: str) -> int:
        return int((await self.get(group_id)).get("max_time", 0))

    async def get_block_ids(self, group_id: str) -> list[str]:
        return list((await self.get(group_id)).get("block_ids", []))

    async def get_ban_words(self, group_id: str) -> list[str]:
        return list((await self.get(group_id)).get("ban_words", []))

    # -------- 便捷写方法 --------
    async def set_switch(self, group_id: str, on: bool):
        await self.set(group_id, switch=bool(on))

    async def set_accept_words(self, group_id: str, kws: list[str]):
        await self.set(group_id, accept_words=kws)

    async def set_reject_words(self, group_id: str, kws: list[str]):
        await self.set(group_id, reject_words=kws)

    async def set_no_match_reject(self, group_id: str, reject: bool):
        await self.set(group_id, no_match_reject=bool(reject))

    async def set_min_level(self, group_id: str, level: int):
        await self.set(group_id, min_level=level)

    async def set_max_time(self, group_id: str, times: int):
        await self.set(group_id, max_time=times)

    async def set_block_ids(self, group_id: str, uids: list[str]):
        await self.set(group_id, block_ids=uids)

    async def set_ban_words(self, group_id: str, words: list[str]):
        await self.set(group_id, ban_words=words)

    # -------- 增删 --------
    async def add_block_id(self, group_id: str, uid: str):
        ids = set(await self.get_block_ids(group_id))
        if uid not in ids:
            ids.add(uid)
            await self.set_block_ids(group_id, list(ids))

    async def remove_block_id(self, group_id: str, uid: str):
        ids = [i for i in await self.get_block_ids(group_id) if i != uid]
        await self.set_block_ids(group_id, ids)

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._initialized = False
