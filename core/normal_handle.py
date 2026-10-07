from astrbot.core.message.components import Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..config import PluginConfig
from ..data import QQAdminDB
from ..utils import extract_image_url, get_ats, get_nickname


class NormalHandle:
    def __init__(self, config: PluginConfig, db: QQAdminDB):
        self.cfg = config
        self.db = db

    async def set_group_ban(
        self,
        event: AiocqhttpMessageEvent,
        ban_time: int | None = None,
        target_id: str | int = "",
    ):
        group_config = self.db.get_group_snapshot(event.get_group_id())
        try:
            ban_time = int(ban_time) if ban_time is not None else None
        except (ValueError, TypeError):
            ban_time = None

        if ban_time is None:
            ban_time = self.cfg.get_ban_time_with_range(
                group_config.get("random_ban_time"), None
            )
        tids = [target_id] if target_id else get_ats(event)
        results = []
        for tid in tids:
            try:
                await event.bot.set_group_ban(
                    group_id=int(event.get_group_id()),
                    user_id=int(tid),
                    duration=ban_time,
                )
                results.append(f"用户[{tid}]已被禁言{ban_time}秒")
            except Exception:
                results.append(f"用户[{tid}]禁言失败")
        event.stop_event()
        return "\n".join(results) if results else "未指定要禁言的用户"

    async def set_group_whole_ban(self, event: AiocqhttpMessageEvent, enable: bool):
        await event.bot.set_group_whole_ban(
            group_id=int(event.get_group_id()), enable=enable
        )
        return "已开启全体禁言" if enable else "已关闭全体禁言"

    async def set_group_card(
        self,
        event: AiocqhttpMessageEvent,
        target_id: str | int = "",
        target_card: str | int = "",
    ):
        tids = ([target_id] if target_id else get_ats(event)) or [event.get_sender_id()]
        results = []
        for tid in tids:
            target_name = await get_nickname(event, user_id=tid)
            results.append(
                f"已修改{target_name}的群昵称为【{target_card}】"
                if target_card
                else f"已清除{target_name}的群昵称"
            )
            await event.bot.set_group_card(
                group_id=int(event.get_group_id()),
                user_id=int(tid),
                card=str(target_card),
            )
        return "\n".join(results) if results else "未指定要设置群昵称的用户"

    async def set_group_special_title(
        self,
        event: AiocqhttpMessageEvent,
        target_id: str | int = "",
        special_title: str | int = "",
    ):
        tids = ([target_id] if target_id else get_ats(event)) or [event.get_sender_id()]
        results = []
        for tid in tids:
            target_name = await get_nickname(event, user_id=tid)
            results.append(
                f"已修改{target_name}的头衔为【{special_title}】"
                if special_title
                else f"已清除{target_name}的头衔"
            )
            await event.bot.set_group_special_title(
                group_id=int(event.get_group_id()),
                user_id=int(tid),
                special_title=str(special_title),
                duration=-1,
            )
        return "\n".join(results) if results else "未指定要设置头衔的用户"

    async def set_group_kick(
        self, event: AiocqhttpMessageEvent, target_id: str | int = ""
    ):
        tids = [target_id] if target_id else get_ats(event)
        results = []
        for tid in tids:
            target_name = await get_nickname(event, user_id=tid)
            await event.bot.set_group_kick(
                group_id=int(event.get_group_id()),
                user_id=int(tid),
                reject_add_request=False,
            )
            results.append(f"已将【{tid}-{target_name}】踢出本群")
        return "\n".join(results) if results else "未指定要踢出的用户"

    async def set_group_block(
        self, event: AiocqhttpMessageEvent, target_id: str | int = ""
    ):
        gid = event.get_group_id()
        tids = [target_id] if target_id else get_ats(event)
        results = []
        for tid in tids:
            target_name = await get_nickname(event, user_id=tid)
            await event.bot.set_group_kick(
                group_id=int(gid),
                user_id=int(tid),
                reject_add_request=True,
            )
            await self.db.add(gid, "block_ids", str(tid))
            results.append(f"已将【{tid}-{target_name}】踢出本群并拉黑!")
        return "\n".join(results) if results else "未指定要拉黑的用户"

    async def set_group_admin(self, event: AiocqhttpMessageEvent, enable: bool):
        results = []
        for tid in get_ats(event):
            target_name = await get_nickname(event, user_id=tid)
            await event.bot.set_group_admin(
                group_id=int(event.get_group_id()), user_id=int(tid), enable=enable
            )
            msg = (
                f"{target_name}已被设为管理员"
                if enable
                else f"{target_name}的管理员身份已被取消"
            )
            results.append(msg)
        return "\n".join(results) if results else "未指定要操作的用户"

    async def set_essence_msg(
        self,
        event: AiocqhttpMessageEvent,
        enable: bool,
        message_id: str | int = "",
    ):
        if not message_id:
            chain = event.get_messages()
            first_seg = chain[0] if chain else None
            if not isinstance(first_seg, Reply):
                return "未指定要设置精华的消息"
            message_id = first_seg.id
        if enable:
            await event.bot.set_essence_msg(message_id=int(message_id))
            return "已设为精华消息"
        else:
            await event.bot.delete_essence_msg(message_id=int(message_id))
            return "已取消精华消息"

    async def get_essence_msg_list(self, event: AiocqhttpMessageEvent):
        """查看群精华"""
        essence_data = await event.bot.get_essence_msg_list(
            group_id=int(event.get_group_id())
        )
        if not essence_data:
            return "没有群精华消息"
        return f"{essence_data}"

    async def set_group_portrait(
        self, event: AiocqhttpMessageEvent, image_url: str | None = None
    ):
        image_url = image_url or extract_image_url(chain=event.get_messages())
        if not image_url:
            return "未获取到新头像"
        await event.bot.set_group_portrait(
            group_id=int(event.get_group_id()),
            file=image_url,
        )
        return "群头像已更新"

    async def set_group_name(
        self, event: AiocqhttpMessageEvent, group_name: str | int | None = None
    ):
        if not group_name:
            return "未输入新群名"
        await event.bot.set_group_name(
            group_id=int(event.get_group_id()), group_name=str(group_name)
        )
        return f"本群群名更新为：{group_name}"
