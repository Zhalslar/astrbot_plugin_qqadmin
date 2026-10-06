from __future__ import annotations

import textwrap
from datetime import datetime
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..config import PluginConfig
from ..utils import download_file, extract_image_url

if TYPE_CHECKING:
    from ..main import QQAdminPlugin


class NoticeHandle:
    def __init__(self, plugin: QQAdminPlugin, config: PluginConfig):
        self.plugin = plugin
        self.cfg = config

    async def send_group_notice(
        self,
        event: AiocqhttpMessageEvent,
        content: str = "",
        image_url: str | None = None,
    ):
        """(引用图片)发布群公告 xxx"""
        content = content or event.message_str.partition(" ")[2]
        if not content:
            return "未指定群公告内容"
        gid = event.get_group_id()
        kwargs = {"group_id": int(gid), "content": content}
        if image_url := (image_url or extract_image_url(chain=event.get_messages())):
            img_name = f"{gid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            temp_path = self.cfg.group_notice_dir / img_name

            logger.debug(f"Group notice image temp path: {temp_path}")
            image_path = await download_file(image_url, temp_path)
            if not image_path:
                return "图片获取失败"
            kwargs["image"] = str(image_path)

        await event.bot._send_group_notice(**kwargs)
        return "群公告已发布"

    async def get_group_notice(self, event: AiocqhttpMessageEvent):
        """查看群公告"""
        notices = await event.bot._get_group_notice(group_id=int(event.get_group_id()))

        formatted_messages = []
        for notice in notices:
            sender_id = notice["sender_id"]
            publish_time = datetime.fromtimestamp(notice["publish_time"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            message_text = notice["message"]["text"].replace("&#10;", "\n\n")

            formatted_message = (
                f"【{publish_time}-{sender_id}】\n\n"
                f"{textwrap.indent(message_text, '    ')}"
            )
            formatted_messages.append(formatted_message)

        notices_str = "\n\n\n".join(formatted_messages)
        return notices_str or "当前群没有群公告"
