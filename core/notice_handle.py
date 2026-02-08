from __future__ import annotations

import textwrap
from datetime import datetime
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..utils import download_file, extract_image_url
from ..config import PluginConfig

if TYPE_CHECKING:
    from ..main import QQAdminPlugin

class NoticeHandle:
    def __init__(self, plugin: QQAdminPlugin, config: PluginConfig):
        self.plugin = plugin
        self.cfg = config

    async def send_group_notice(self, event: AiocqhttpMessageEvent):
        """(引用图片)发布群公告 xxx"""
        content = event.message_str.partition(" ")[2]
        if not content:
            await event.send(event.plain_result("你又不说要发什么群公告"))
            return
        gid = event.get_group_id()
        image_path = None
        if image_url := extract_image_url(chain=event.get_messages()):
            img_name = f"{gid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            temp_path = self.cfg.group_notice_dir / img_name

            logger.debug("temp_path:", temp_path)
            image_path = await download_file(image_url, temp_path)
            if not image_path:
                await event.send(event.plain_result("图片获取失败"))
                return
        await event.bot._send_group_notice(
            group_id=int(event.get_group_id()), content=content, image=image_path
        )
        event.stop_event()

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
        url = await self.plugin.text_to_image(notices_str)
        await event.send(event.image_result(url))
        # TODO 做张好看的图片来展示
