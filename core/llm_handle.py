import re
from typing import Any

from astrbot import logger
from astrbot.api.star import Context
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from data.plugins.astrbot_plugin_qqadmin.utils import get_ats, get_nickname


class LLMHandle:
    def __init__(self, context: Context, config: AstrBotConfig):
        self.context = context
        self.conf = config

    def _build_user_context(
        self, round_messages: list[dict[str, Any]], target_id: str
    ) -> list[dict[str, str]]:
        """
        把指定用户在所有回合里的纯文本消息打包成 openai-style 的 user 上下文。
        """
        contexts: list[dict[str, str]] = []

        for msg in round_messages:
            # 1. 过滤发送者
            if msg["sender"]["user_id"] != int(target_id):
                continue
            # 2. 提取并拼接所有 text 片段
            text_segments = [
                seg["data"]["text"] for seg in msg["message"] if seg["type"] == "text"
            ]
            text = "".join(text_segments).strip()
            # 3. 仅当真正说了话才保留
            if text:
                contexts.append({"role": "user", "content": text})
        return contexts

    async def get_msg_contexts(
        self, event: AiocqhttpMessageEvent, target_id: str
    ) -> list[dict]:
        """持续获取群聊历史消息直到达到要求"""
        group_id = event.get_group_id()
        message_seq = 0
        contexts: list[dict] = []
        for _ in range(self.conf["query"]["query_rounds"]):
            payloads = {
                "group_id": group_id,
                "message_seq": message_seq,
                "count": self.conf["query"]["query_counts"],
                "reverseOrder": True,
            }
            result: dict = await event.bot.api.call_action(
                "get_group_msg_history", **payloads
            )
            round_messages = result["messages"]
            message_seq = round_messages[0]["message_id"]

            contexts.extend(self._build_user_context(round_messages, target_id))
        return contexts

    async def get_llm_respond(
        self, system_prompt: str, contexts: list[dict]
    ) -> str | None:
        """调用llm回复"""
        get_using = self.context.get_using_provider()
        if not get_using:
            return None
        try:
            llm_response = await get_using.text_chat(
                system_prompt=system_prompt,
                prompt="这是这位群友的聊天记录",
                contexts=contexts,
            )
            return llm_response.completion_text

        except Exception as e:
            logger.error(f"LLM 调用失败：{e}")
            return None



    async def ai_set_card(self, event: AiocqhttpMessageEvent):
        """让AI设置群友的群名片"""
        at_ids = get_ats(event)
        target_id = at_ids[0] if at_ids else event.get_sender_id()
        raw_card = await get_nickname(event, target_id)

        logger.info(f"正在根据{raw_card}（{target_id}）的聊天记录生成新昵称...")

        contexts = await self.get_msg_contexts(event, target_id)
        if not contexts:
            await event.send(event.plain_result("聊天记录为空"))
            return
        logger.debug(f"获取到{raw_card}（{target_id}）的聊天记录：{contexts}")

        system_prompt = (
            "请你扮演一名起名专家，根据这位群友的聊天记录，生成一个昵称。\n"
            "注意：昵称要简洁且符合这位群友的人格特征。\n"
            "请只返回一个昵称，并用精辟的一句话说明取这个昵称的理由，昵称要用 Markdown 加粗，理由要用英文单引号引出。例如：“新昵称：**白嫖怪** \n理由：'太喜欢白嫖别人的成果'”\n"
            "不要附带任何多余的文字、解释或标点。"
        )

        llm_respond = await self.get_llm_respond(
            system_prompt=system_prompt, contexts=contexts
        )
        if not llm_respond:
            await event.send(event.plain_result("LLM响应为空"))
            return

        # 提取 **加粗** 的内容
        match = re.search(r"\*\*(.+?)\*\*", llm_respond)
        if not match:
            await event.send(
                event.plain_result(f"未能从LLM回复中提取到昵称: {llm_respond}")
            )
            return
        # 保留中英文，最多8个字符
        new_card = re.sub(r"[^a-zA-Z\u4e00-\u9fff]", "", match.group(1))[:8]

        # 提取单引号内的内容（理由）
        reason_match = re.search(r"'([^']*)'", llm_respond)
        if not reason_match:
            await event.send(
                event.plain_result(f"未能从LLM回复中提取到取昵称的理由: {llm_respond}")
            )
            return
        reason = reason_match.group(1)

        await event.bot.set_group_card(
            group_id=int(event.get_group_id()),
            user_id=int(target_id),
            card=new_card,
        )
        await event.send(event.plain_result(f"根据最近的{len(contexts)}条消息给'{raw_card}'取的新昵称：{new_card}"))
        await event.send(event.plain_result(f"理由：{reason}"))
        logger.info(f"已为 {target_id} 设置群昵称: {new_card}, 理由：{reason}")
