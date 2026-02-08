import re
from collections.abc import Callable, Coroutine
from typing import Any

from astrbot import logger
from astrbot.api.star import Context
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..utils import get_ats, get_nickname
from ..config import PluginConfig


class LLMHandle:
    def __init__(self, context: Context, config: PluginConfig):
        self.context = context
        self.cfg = config

    def _build_user_context(
        self, round_messages: list[dict[str, Any]], target_id: str
    ) -> list[str]:
        """把指定用户在所有回合里的纯文本消息提取出来"""
        lines: list[str] = []

        for msg in round_messages:
            if msg["sender"]["user_id"] != int(target_id):
                continue
            text_segments = [
                seg["data"]["text"] for seg in msg["message"] if seg["type"] == "text"
            ]
            text = "".join(text_segments).strip()
            if text:
                lines.append(text)
        return lines

    async def get_msg_contexts(
        self, event: AiocqhttpMessageEvent, target_id: str, query_rounds: int
    ) -> str:
        """持续获取群聊历史消息直到达到要求，返回拼接后的聊天记录文本"""
        group_id = event.get_group_id()
        message_seq = 0
        all_lines: list[str] = []

        for _ in range(query_rounds):
            payloads = {
                "group_id": group_id,
                "message_seq": message_seq,
                "count": 200,
                "reverseOrder": True,
            }
            result: dict = await event.bot.api.call_action(
                "get_group_msg_history", **payloads
            )
            round_messages = result["messages"]
            message_seq = round_messages[0]["message_id"]

            all_lines.extend(self._build_user_context(round_messages, target_id))

        return "\n".join(all_lines)

    async def get_llm_respond(
        self, system_prompt: str, chat_history: str
    ) -> str | None:
        """调用llm回复"""
        get_using = self.context.get_using_provider()
        if not get_using:
            return None
        try:
            llm_response = await get_using.text_chat(
                system_prompt=system_prompt,
                prompt=f"以下是这位群友的聊天记录：\n{chat_history}",
            )
            return llm_response.completion_text

        except Exception as e:
            logger.error(f"LLM 调用失败：{e}")
            return None

    async def get_llm_nick(self, chat_history: str) -> tuple[str | None, str]:
        """调用LLM生成昵称"""
        system_prompt = (
            "请你扮演一名起名专家，根据这位群友的聊天记录，生成一个昵称。\n"
            "注意：昵称要简洁且符合这位群友的人格特征。\n"
            "请只返回一个昵称，并用精辟的一句话说明取这个昵称的理由，昵称要用 Markdown 加粗，理由要用英文单引号引出。例如：“新昵称：**白嫖怪** \n理由：'太喜欢白嫖别人的成果'”\n"
            "不要附带任何多余的文字、解释或标点。"
        )
        llm_respond = await self.get_llm_respond(
            system_prompt=system_prompt, chat_history=chat_history
        )
        if not llm_respond:
            return None, "LLM响应为空"

        match = re.search(r"\*\*(.+?)\*\*", llm_respond)
        if not match:
            return None, "未能从LLM回复中提取到昵称"
        new_card = re.sub(r"[^a-zA-Z\u4e00-\u9fff]", "", match.group(1))[:8]

        reason_match = re.search(r"'([^']*)'", llm_respond)
        reason = reason_match.group(1) if reason_match else ""

        return new_card, reason

    async def parse_args(self, event: AiocqhttpMessageEvent):
        at_ids = get_ats(event)
        target_id = at_ids[0] if at_ids else event.get_sender_id()
        end_arg = event.message_str.split()[-1]
        query_rounds = int(end_arg) if end_arg.isdigit() else self.cfg.llm_get_msg_count
        raw_card = await get_nickname(event, target_id)
        return target_id, raw_card, query_rounds

    async def _ai_set_name(
        self,
        event: AiocqhttpMessageEvent,
        name_type: str,
        set_func: Callable[[int, int, str], Coroutine],
    ):
        """通用的 AI 设置名称方法"""
        target_id, raw_card, query_rounds = await self.parse_args(event)
        logger.info(f"正在根据{raw_card}（{target_id}）的聊天记录生成新{name_type}...")

        chat_history = await self.get_msg_contexts(event, target_id, query_rounds)
        if not chat_history:
            await event.send(event.plain_result("聊天记录为空"))
            return

        logger.debug(f"获取到{raw_card}（{target_id}）的聊天记录：\n{chat_history}")

        nick, reason = await self.get_llm_nick(chat_history)
        if not nick:
            await event.send(event.plain_result(f"生成失败：{reason}"))
            return
        await event.send(event.plain_result(f"给{raw_card}取的新{name_type}：{nick}"))
        await event.send(event.plain_result(f"理由：{reason}"))
        # 实际执行
        try:
            await set_func(int(event.get_group_id()), int(target_id), nick)
        except Exception as e:
            logger.warning(f"设置新{name_type}失败：{e}, 跳过操作")

    async def ai_set_card(self, event: AiocqhttpMessageEvent):
        """接口：设置群昵称"""
        await self._ai_set_name(
            event,
            "昵称",
            lambda gid, uid, name: event.bot.set_group_card(
                group_id=gid, user_id=uid, card=name
            ),
        )

    async def ai_set_title(self, event: AiocqhttpMessageEvent):
        """接口：设置群头衔"""
        await self._ai_set_name(
            event,
            "头衔",
            lambda gid, uid, name: event.bot.set_group_special_title(
                group_id=gid, user_id=uid, special_title=name
            ),
        )
