import asyncio
import json

import aiosqlite

from astrbot.api import logger

from .utils import parse_bool
from .config import PluginConfig

class QQAdminDB:
    """
    群管插件数据库（极简 API + 动态字段 + 自动补齐）
    """

    # ====================== 字段中英文映射 ======================
    FIELD_MAP = {
        "join_switch": "进群审核",
        "join_min_level": "进群等级门槛",
        "join_max_time": "进群尝试次数",
        "join_accept_words": "进群白词",
        "join_reject_words": "进群黑词",
        "join_no_match_reject": "未中白词拒绝",
        "reject_word_block": "命中黑词拉黑",
        "block_ids": "进群黑名单",
        "join_welcome": "进群欢迎词",
        "join_ban_time": "进群禁言时长",
        "leave_notify": "主动退群通知",
        "leave_block": "主动退群拉黑",
        "builtin_ban": "启用内置禁词",
        "custom_ban_words": "自定义违禁词",
        "word_ban_time": "禁词禁言时长",
        "spamming_ban_time": "刷屏禁言时长",
    }

    REVERSE_FIELD_MAP = {v: k for k, v in FIELD_MAP.items()}

    # ================================================================

    def __init__(self, config: PluginConfig):
        self.db_path = config.db_path

        # 默认字段（动态配置核心）
        self.default_cfg: dict = config.default

        self._conn = None
        self._cache = {}
        self._initialized = False
        self._init_lock = asyncio.Lock()

    # ============================== 初始化 ==============================

    async def init(self):
        async with self._init_lock:
            if self._initialized:
                return

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(str(self.db_path))
            self._conn.row_factory = aiosqlite.Row

            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    group_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
            """)
            await self._conn.commit()

            # 加载缓存
            async with self._conn.execute("SELECT group_id, data FROM groups;") as cur:
                async for row in cur:
                    try:
                        self._cache[row["group_id"]] = json.loads(row["data"])
                    except Exception:
                        logger.exception("解析 group 数据失败: %s", row["group_id"])

            self._initialized = True
            logger.info("QQAdminDB initialized (%d groups)", len(self._cache))

    async def _save_to_db(self, gid: str, data):
        if not self._conn:
            raise RuntimeError("请先 init()")

        await self._conn.execute(
            """
            INSERT INTO groups(group_id, data)
            VALUES (?, ?)
            ON CONFLICT(group_id) DO UPDATE SET data=excluded.data;
            """,
            (gid, json.dumps(data, ensure_ascii=False)),
        )
        await self._conn.commit()

    # ============================== 基础：确保配置存在 ==============================

    async def ensure_group(self, gid: str):
        """确保存在群配置，若没有则按 default_cfg 初始化"""
        if gid not in self._cache:
            self._cache[gid] = json.loads(json.dumps(self.default_cfg))
            await self._save_to_db(gid, self._cache[gid])

    # ============================== 🔥 极简 API ==============================

    async def all(self, gid: str) -> dict:
        """
        获取整个配置，并自动补齐 default_cfg 的字段
        """
        await self.ensure_group(gid)
        data = self._cache[gid]

        changed = False
        for k, v in self.default_cfg.items():
            if k not in data:
                data[k] = json.loads(json.dumps(v))
                changed = True

        if changed:
            await self._save_to_db(gid, data)

        return data

    async def get(self, gid: str, field: str, default=None):
        """
        读字段，不存在则补齐 default
        """
        await self.ensure_group(gid)
        data = self._cache[gid]

        if field not in data:
            data[field] = json.loads(json.dumps(default))
            await self._save_to_db(gid, data)

        return data[field]

    async def set(self, gid: str, field: str, value):
        """
        写入字段
        """
        await self.ensure_group(gid)
        self._cache[gid][field] = value
        await self._save_to_db(gid, self._cache[gid])

    async def add(self, gid: str, field: str, value):
        """
        列表字段追加（自动创建列表）
        """
        lst = list(await self.get(gid, field, []))
        if value not in lst:
            lst.append(value)
            await self.set(gid, field, lst)

    async def remove(self, gid: str, field: str, value):
        """
        列表字段删除（自动创建列表）
        """
        lst = [i for i in await self.get(gid, field, []) if i != value]
        await self.set(gid, field, lst)

    # ============================== 删除群配置 ==============================

    async def delete_group(self, gid: str):
        """彻底删除群配置"""
        if self._conn:
            await self._conn.execute("DELETE FROM groups WHERE group_id = ?", (gid,))
            await self._conn.commit()
        self._cache.pop(gid, None)

    # ============================== 关闭 ==============================

    async def close(self):
        if self._conn:
            await self._conn.close()
            self._conn = None
            self._initialized = False


    # ====================== 中文展示、读回 ======================

    async def export_cn_lines(self, gid: str) -> str:
        """
        以中文键名 + 多行文本形式输出群配置。
        - 列表字段：用空格分隔
        - 布尔：开 / 关
        - 其它类型按原样输出
        """
        data = await self.all(gid)
        lines = []

        for eng_key, value in data.items():
            cn_key = self.FIELD_MAP.get(eng_key, eng_key)

            # 列表字段 => 用空格分隔
            if isinstance(value, list):
                val_str = " ".join(map(str, value))

            # 布尔字段 => 显示 为“开 / 关”
            elif isinstance(value, bool):
                val_str = "开" if value else "关"

            # 其他字段 => 按原样
            else:
                val_str = str(value)

            lines.append(f"{cn_key}: {val_str}")

        return "\n".join(lines)

    async def import_cn_lines(self, gid: str, text: str) -> dict:
        """
        解析用户提交的中文多行文本并写回 DB
        - 列表字段：空格分隔
        - 布尔：开/关/开启/on/off/true/false/1/0
        - 数字：自动转 int
        - 字符串：原样保存
        """
        await self.ensure_group(gid)
        data = self._cache[gid]

        for line in text.splitlines():
            if ":" not in line:
                continue

            cn_key, raw_v = line.split(":", 1)
            cn_key = cn_key.strip()
            raw_v = raw_v.strip()

            eng_key = self.REVERSE_FIELD_MAP.get(cn_key)
            if not eng_key:
                continue

            old_val = data.get(eng_key)

            # 如果原字段是 bool，则优先进行布尔解析
            if isinstance(old_val, bool):
                parsed = parse_bool(raw_v)
                if parsed is not None:
                    data[eng_key] = parsed
                    continue
                # 若解析失败，退回默认字面处理（防错）

            # 列表字段：按空格拆
            if isinstance(old_val, list):
                value = [x for x in raw_v.split() if x]

            # 数字字段：自动转 int
            elif isinstance(old_val, int):
                try:
                    value = int(raw_v)
                except ValueError:
                    value = old_val  # 防错保底

            # 字符串字段
            else:
                value = raw_v

            data[eng_key] = value

        await self._save_to_db(gid, data)
        return data


    async def reset_to_default(self, gid: str | None = None):
        """把指定群（或全部群）配置恢复成 default_cfg"""
        targets = [gid] if gid else list(self._cache.keys())
        for g in targets:
            self._cache[g] = json.loads(json.dumps(self.default_cfg))
            await self._save_to_db(g, self._cache[g])

        logger.info(f"群聊{gid}的群管配置已重置为默认值")
