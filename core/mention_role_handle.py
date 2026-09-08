import re
import time

from astrbot.api import logger
from astrbot.core.message.components import At, Plain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..data import QQAdminDB
from ..utils import get_ats, get_nickname


class MentionRoleHandle:
    FIELD = "mention_roles"
    MAX_ROLE_MEMBERS = 50
    MAX_MENTION_PER_CALL = 20
    CALL_COOLDOWN_SECONDS = 60
    COMMAND_TOKENS = {
        "身份组创建",
        "身份组删除",
        "身份组删组",
        "身份组加",
        "身份组删",
        "身份组列表",
        "身份组",
        "呼叫",
        "召唤",
        "呼叫身份组",
    }

    def __init__(self, db: QQAdminDB):
        self.db = db
        self._last_calls: dict[str, float] = {}

    @staticmethod
    def _normalize_role_name(role_name: str | int | None) -> str:
        return str(role_name or "").strip()

    @staticmethod
    def _parse_role_and_tail(event: AiocqhttpMessageEvent, command_name: str):
        raw = str(event.message_str or "").strip()
        if not raw:
            rest = ""
        elif raw == command_name or raw.startswith(f"{command_name} "):
            rest = raw[len(command_name) :].strip()
        elif raw.split(maxsplit=1)[0] in MentionRoleHandle.COMMAND_TOKENS:
            parts = raw.split(maxsplit=1)
            rest = parts[1] if len(parts) > 1 else ""
        else:
            rest = raw
        role_name, _, tail = rest.partition(" ")
        return role_name.strip(), tail.strip()

    def get_call_role_name(
        self, event: AiocqhttpMessageEvent, command_name: str = "呼叫"
    ) -> str:
        role_name, _ = self._parse_role_and_tail(event, command_name)
        return self._normalize_role_name(role_name)

    @staticmethod
    def _validate_role_name(role_name: str) -> str | None:
        if not role_name:
            return "请输入身份组名"
        if len(role_name) > 20:
            return "身份组名不能超过20个字符"
        if re.search(r"\s", role_name):
            return "身份组名不能包含空格"
        return None

    @staticmethod
    def _extract_ids(event: AiocqhttpMessageEvent, tail: str = "") -> list[str]:
        ids = get_ats(event)
        ids.extend(re.findall(r"(?<!\d)(\d{5,12})(?!\d)", tail or ""))
        result = []
        seen = set()
        self_id = str(event.get_self_id())
        for uid in ids:
            uid = str(uid).strip()
            if not uid or uid == self_id or uid in seen:
                continue
            seen.add(uid)
            result.append(uid)
        return result

    async def _get_roles(self, gid: str) -> dict[str, list[str]]:
        raw = await self.db.get(gid, self.FIELD, {})
        if not isinstance(raw, dict):
            return {}
        roles: dict[str, list[str]] = {}
        for name, members in raw.items():
            if not isinstance(name, str) or not isinstance(members, list):
                continue
            clean_members = []
            seen = set()
            for uid in members:
                uid = str(uid).strip()
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                clean_members.append(uid)
            roles[name] = clean_members
        return roles

    async def _save_roles(self, gid: str, roles: dict[str, list[str]]):
        await self.db.set(gid, self.FIELD, roles)

    async def _send_call_chain(
        self, event: AiocqhttpMessageEvent, members: list[str], tail: str
    ):
        """Send role mentions as raw OneBot segments for LLOneBot compatibility."""
        if event.platform_meta.name == "aiocqhttp" and not event.is_private_chat():
            gid = event.get_group_id()
            try:
                group_id = int(gid)
                message = []
                for uid in members:
                    message.append(
                        {"type": "at", "data": {"qq": str(uid)}}
                    )
                    message.append({"type": "text", "data": {"text": " "}})
                if tail:
                    message.append({"type": "text", "data": {"text": tail}})

                routing_params = {}
                if getattr(event.message_obj, "self_id", None):
                    routing_params["self_id"] = event.message_obj.self_id

                await event.bot.send_group_msg(
                    group_id=group_id,
                    message=message,
                    **routing_params,
                )
                return
            except Exception as e:
                logger.warning(f"身份组直接发送 OneBot at 失败，回退消息链发送: {e}")

        chain = []
        for uid in members:
            chain.append(At(qq=uid))
            chain.append(Plain(" "))
        if tail:
            chain.append(Plain(tail))
        await event.send(event.chain_result(chain))

    async def is_sender_in_role(
        self, event: AiocqhttpMessageEvent, role_name: str | int
    ) -> bool:
        role_name = self._normalize_role_name(role_name)
        if not role_name:
            return False
        roles = await self._get_roles(event.get_group_id())
        return str(event.get_sender_id()) in set(roles.get(role_name, []))

    async def create_role(self, event: AiocqhttpMessageEvent, role_name: str | int = ""):
        gid = event.get_group_id()
        role_name = self._normalize_role_name(role_name)
        if error := self._validate_role_name(role_name):
            return error

        roles = await self._get_roles(gid)
        if role_name in roles:
            return f"身份组【{role_name}】已存在"

        roles[role_name] = []
        await self._save_roles(gid, roles)
        return f"已创建身份组【{role_name}】"

    async def delete_role(self, event: AiocqhttpMessageEvent, role_name: str | int = ""):
        gid = event.get_group_id()
        role_name = self._normalize_role_name(role_name)
        if error := self._validate_role_name(role_name):
            return error

        roles = await self._get_roles(gid)
        if role_name not in roles:
            return f"身份组【{role_name}】不存在"

        roles.pop(role_name, None)
        await self._save_roles(gid, roles)
        return f"已删除身份组【{role_name}】"

    async def add_members(self, event: AiocqhttpMessageEvent):
        gid = event.get_group_id()
        role_name, tail = self._parse_role_and_tail(event, "身份组加")
        if error := self._validate_role_name(role_name):
            return error

        new_ids = self._extract_ids(event, tail)
        if not new_ids:
            return "请 @ 要加入身份组的成员，或输入QQ号"

        roles = await self._get_roles(gid)
        if role_name not in roles:
            return f"身份组【{role_name}】不存在"
        members = roles[role_name]
        before = set(members)
        added = []
        for uid in new_ids:
            if uid in before:
                continue
            if len(members) >= self.MAX_ROLE_MEMBERS:
                break
            members.append(uid)
            before.add(uid)
            added.append(uid)

        await self._save_roles(gid, roles)
        if not added:
            return f"身份组【{role_name}】没有新增成员"
        return f"已向【{role_name}】加入 {len(added)} 人，当前共 {len(members)} 人"

    async def remove_members(self, event: AiocqhttpMessageEvent):
        gid = event.get_group_id()
        role_name, tail = self._parse_role_and_tail(event, "身份组删")
        if error := self._validate_role_name(role_name):
            return error

        remove_ids = set(self._extract_ids(event, tail))
        if not remove_ids:
            return "请 @ 要移出身份组的成员，或输入QQ号"

        roles = await self._get_roles(gid)
        if role_name not in roles:
            return f"身份组【{role_name}】不存在"

        old_members = roles[role_name]
        roles[role_name] = [uid for uid in old_members if uid not in remove_ids]
        await self._save_roles(gid, roles)
        removed = len(old_members) - len(roles[role_name])
        return f"已从【{role_name}】移出 {removed} 人，当前共 {len(roles[role_name])} 人"

    async def list_roles(self, event: AiocqhttpMessageEvent, role_name: str | int = ""):
        gid = event.get_group_id()
        role_name = self._normalize_role_name(role_name)
        roles = await self._get_roles(gid)
        if not roles:
            return "本群还没有身份组"

        if role_name:
            if role_name not in roles:
                return f"身份组【{role_name}】不存在"
            lines = [f"【{role_name}】共 {len(roles[role_name])} 人"]
            for uid in roles[role_name]:
                nickname = await get_nickname(event, uid)
                lines.append(f"- {uid}｜{nickname}")
            return "\n".join(lines)

        return "\n".join(
            f"【{name}】{len(members)}人" for name, members in sorted(roles.items())
        )

    async def call_role(self, event: AiocqhttpMessageEvent, command_name: str = "呼叫"):
        gid = event.get_group_id()
        role_name, tail = self._parse_role_and_tail(event, command_name)
        if error := self._validate_role_name(role_name):
            return error

        roles = await self._get_roles(gid)
        members = roles.get(role_name, [])
        if not members:
            return f"身份组【{role_name}】不存在或没有成员"

        cooldown_key = f"{gid}:{role_name}"
        now = time.monotonic()
        last_called = self._last_calls.get(cooldown_key, 0)
        wait = int(self.CALL_COOLDOWN_SECONDS - (now - last_called))
        if wait > 0:
            return f"身份组【{role_name}】冷却中，还需 {wait} 秒"
        call_members = members[: self.MAX_MENTION_PER_CALL]
        send_tail = tail
        if len(members) > len(call_members):
            extra_tail = (
                f"\n身份组【{role_name}】共 {len(members)} 人，"
                f"本次仅 @ 前 {len(call_members)} 人"
            )
            send_tail = f"{send_tail}{extra_tail}" if send_tail else extra_tail

        await self._send_call_chain(event, call_members, send_tail)
        self._last_calls[cooldown_key] = now
        event.stop_event()
        return None
