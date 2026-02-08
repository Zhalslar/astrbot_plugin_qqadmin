
import inspect
from collections.abc import AsyncGenerator, Awaitable, Callable
from enum import IntEnum
from functools import wraps
from typing import Any, Optional, cast

from astrbot import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .utils import get_ats


class PermLevel(IntEnum):
    """
    定义用户的权限等级。数字越小，权限越高。
    """

    SUPERUSER = 0
    OWNER = 1
    ADMIN = 2
    HIGH = 3
    MEMBER = 4
    UNKNOWN = 5

    def __str__(self):
        return {
            PermLevel.SUPERUSER: "超管",
            PermLevel.OWNER: "群主",
            PermLevel.ADMIN: "管理员",
            PermLevel.HIGH: "高等级成员",
            PermLevel.MEMBER: "成员",
            PermLevel.UNKNOWN: "未知/无权限",
        }.get(self, "未知/无权限")

    @classmethod
    def from_str(cls, perm_str: str):
        mapping = {
            "超管": cls.SUPERUSER,
            "群主": cls.OWNER,
            "管理员": cls.ADMIN,
            "高等级成员": cls.HIGH,
            "成员": cls.MEMBER,
            "未知": cls.UNKNOWN,
            "无权限": cls.UNKNOWN,
        }
        return mapping.get(perm_str, cls.UNKNOWN)



class PermissionManager:
    _instance: Optional["PermissionManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        superusers: list[str] | None = None,
        perms: dict[str, str] | None = None,
        level_threshold: int = 10,
    ):
        if self._initialized:
            return
        self.superusers = superusers or []
        if perms is None:
            raise ValueError("初始化必须传入 perms")
        self.perms: dict[str, PermLevel] = {
            k: PermLevel.from_str(v) for k, v in perms.items()
        }
        self.level_threshold = level_threshold
        self._initialized = True

    @classmethod
    def get_instance(
        cls,
        superusers: list[str] | None = None,
        perms: dict[str, str] | None = None,
        level_threshold: int = 50,
    ) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = cls(
                superusers=superusers,
                perms=perms,
                level_threshold=level_threshold,
            )
        return cls._instance

    async def get_perm_level(
        self, event: AiocqhttpMessageEvent, user_id: str | int
    ) -> PermLevel:
        group_id = event.get_group_id()
        if int(group_id) == 0 or int(user_id) == 0:
            return PermLevel.UNKNOWN
        if str(user_id) in self.superusers:
            return PermLevel.SUPERUSER
        try:
            info = await event.bot.get_group_member_info(
                group_id=int(group_id), user_id=int(user_id), no_cache=True
            )
        except Exception:
            return PermLevel.UNKNOWN
        role = info.get("role", "unknown")
        level = int(info.get("level", 0))
        match role:
            case "owner":
                return PermLevel.OWNER
            case "admin":
                return PermLevel.ADMIN
            case "member":
                return (
                    PermLevel.HIGH
                    if level >= self.level_threshold
                    else PermLevel.MEMBER
                )
            case _:
                return PermLevel.UNKNOWN

    async def perm_block(
        self,
        event: AiocqhttpMessageEvent,
        bot_perm: PermLevel,
        perm_key: str,
        check_at: bool = True,
    ) -> str | None:
        user_level = await self.get_perm_level(event, user_id=event.get_sender_id())

        # 未指定权限，则默认至少需要管理员权限
        required_level = self.perms.get(perm_key) or PermLevel.ADMIN

        if user_level > required_level:
            return f"你没{required_level}权限"

        bot_level = await self.get_perm_level(event, user_id=event.get_self_id())
        if bot_level > bot_perm:
            return f"我没{bot_perm}权限"

        if check_at:
            for at_id in get_ats(event):
                at_level = await self.get_perm_level(event, user_id=at_id)
                if bot_level >= at_level:
                    return f"我动不了{at_level}"

        return None


def perm_required(
    bot_perm: PermLevel = PermLevel.ADMIN,
    perm_key: str | None = None,
    check_at: bool = True,
):
    """
    权限检查装饰器。
    :param perm_key: 可选。用户执行命令所需的最低权限键名，默认使用被装饰函数的函数名。
    :param bot_perm: Bot 执行此命令所需的最低权限等级。
    :param check_at: 是否检查“是否有权对被@者实施操作”。
    """

    def decorator(
        func: Callable[..., AsyncGenerator[Any, Any] | Awaitable[Any]],
    ) -> Callable[..., AsyncGenerator[Any, Any]]:
        actual_perm_key = perm_key or func.__name__
        @wraps(func)
        async def wrapper(
            plugin_instance: Any,
            event: AiocqhttpMessageEvent,
            *args: Any,
            **kwargs: Any,
        ) -> AsyncGenerator[Any, Any]:
            perm_manager = PermissionManager.get_instance()

            # 仅限aiocqhttp
            if event.platform_meta.name != "aiocqhttp":
                return

            # 仅限群聊
            if event.is_private_chat():
                return

            # 权限管理未初始化
            if not perm_manager._initialized:
                logger.error(f"PermissionManager 未初始化（尝试访问权限项：{perm_key}）")
                yield event.plain_result("内部错误：权限系统未正确加载")
                event.stop_event()
                return

            # 判断权限
            result = await perm_manager.perm_block(
                event, bot_perm=bot_perm, perm_key=actual_perm_key, check_at=check_at
            )
            if result:
                yield event.plain_result(result)
                event.stop_event()
                return

            # 执行原始方法
            if inspect.isasyncgenfunction(func):
                async for item in func(plugin_instance, event, *args, **kwargs):
                    yield item
            else:
                await cast(
                    Awaitable[Any], func(plugin_instance, event, *args, **kwargs)
                )

        return wrapper

    return decorator


