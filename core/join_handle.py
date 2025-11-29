
import json
import os
from pathlib import Path

from aiocqhttp import CQHttp

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..utils import get_reply_message_str


class GroupJoinData:
    def __init__(self, path: str = "group_join_data.json"):
        self.path = path
        self.accept_keywords: dict[str, list[str]] = {}
        self.reject_keywords: dict[str, list[str]] = {}
        self.reject_ids: dict[str, list[str]] = {}
        self.reject_below_level: dict[str, int] = {}
        self.auto_reject_without_keyword: dict[str, bool] = {}
        self.auto_blacklist_on_reject_keyword: dict[str, bool] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            self._save()
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.accept_keywords = data.get("accept_keywords", {})
            self.reject_keywords = data.get("reject_keywords", {})
            self.reject_ids = data.get("reject_ids", {})
            self.reject_below_level = data.get("reject_below_level", {})
            self.auto_reject_without_keyword = data.get("auto_reject_without_keyword", {})
            self.auto_blacklist_on_reject_keyword = data.get("auto_blacklist_on_reject_keyword", {})
        except Exception as e:
            print(f"加载 group_join_data 失败: {e}")
            self._save()

    def _save(self):
        data = {
            "accept_keywords": self.accept_keywords,
            "reject_keywords": self.reject_keywords,
            "reject_ids": self.reject_ids,
            "reject_below_level": self.reject_below_level,
            "auto_reject_without_keyword": self.auto_reject_without_keyword,
            "auto_blacklist_on_reject_keyword": self.auto_blacklist_on_reject_keyword,
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self):
        self._save()



class GroupJoinManager:
    def __init__(self, json_path: str):
        self.data = GroupJoinData(json_path)
        self.reject_below_level: int = 0
        self.auto_reject_without_keyword: bool = False
        self.auto_blacklist_on_reject_keyword: bool = False

    def reject_reason(
        self, group_id: str, user_id: str, comment: str | None = None, user_level: int | None = None
    ) -> str | None:
        """返回拒绝原因标识：
        黑名单用户: 在用户ID黑名单中
        命中黑名单关键词: 触发黑名单关键词
        未包含进群关键词: 已配置自动同意关键词但未命中且开启自动拒绝
        QQ等级过低: QQ等级低于设定阈值
        None: 不拒绝
        """
        # 用户ID黑名单
        if (
            group_id in self.data.reject_ids
            and user_id in self.data.reject_ids[group_id]
        ):
            return "黑名单用户"

        # QQ等级过低（优先使用群独立配置，否则使用全局配置）
        level_threshold = self.data.reject_below_level.get(group_id, self.reject_below_level)
        if (
            level_threshold > 0
            and user_level is not None
            and user_level < level_threshold
        ):
            return f"QQ等级过低({user_level}<{level_threshold})"

        if comment:
            lower_comment = comment.lower()
            # 黑名单关键词
            if group_id in self.data.reject_keywords and any(
                rk.lower() in lower_comment for rk in self.data.reject_keywords[group_id]
            ):
                return "命中黑名单关键词"
            # 未包含任何自动同意关键词（需开启开关 & 已设置白名单关键词）
            # 优先使用群独立配置，否则使用全局配置
            if (
                self.should_auto_reject_without_keyword(group_id)
                and group_id in self.data.accept_keywords
                and self.data.accept_keywords[group_id]
                and not any(
                    ak.lower() in lower_comment
                    for ak in self.data.accept_keywords[group_id]
                )
            ):
                return "未包含进群关键词"
        return None

    def should_reject(
        self, group_id: str, user_id: str, comment: str | None = None, user_level: int | None = None
    ) -> bool:
        return self.reject_reason(group_id, user_id, comment, user_level) is not None

    def should_approve(self, group_id: str, comment: str) -> bool:
        if group_id not in self.data.accept_keywords:
            return False
        return any(
            kw.lower() in comment.lower() for kw in self.data.accept_keywords[group_id]
        )

    def add_keyword(self, group_id: str, keywords: list[str]):
        self.data.accept_keywords.setdefault(group_id, []).extend(keywords)
        self.data.accept_keywords[group_id] = list(
            set(self.data.accept_keywords[group_id])
        )
        self.data.save()

    def remove_keyword(self, group_id: str, keywords: list[str]):
        if group_id in self.data.accept_keywords:
            for k in keywords:
                if k in self.data.accept_keywords[group_id]:
                    self.data.accept_keywords[group_id].remove(k)
            self.data.save()

    def get_keywords(self, group_id: str) -> list[str]:
        return self.data.accept_keywords.get(group_id, [])

    def add_reject_keyword(self, group_id: str, keywords: list[str]):
        self.data.reject_keywords.setdefault(group_id, []).extend(keywords)
        self.data.reject_keywords[group_id] = list(
            set(self.data.reject_keywords[group_id])
        )
        self.data.save()

    def remove_reject_keyword(self, group_id: str, keywords: list[str]):
        if group_id in self.data.reject_keywords:
            for k in keywords:
                if k in self.data.reject_keywords[group_id]:
                    self.data.reject_keywords[group_id].remove(k)
            self.data.save()

    def get_reject_keywords(self, group_id: str) -> list[str]:
        return self.data.reject_keywords.get(group_id, [])

    def add_reject_id(self, group_id: str, ids: list[str]):
        self.data.reject_ids.setdefault(group_id, []).extend(ids)
        self.data.reject_ids[group_id] = list(set(self.data.reject_ids[group_id]))
        self.data.save()

    def remove_reject_id(self, group_id: str, ids: list[str]):
        if group_id in self.data.reject_ids:
            for uid in ids:
                if uid in self.data.reject_ids[group_id]:
                    self.data.reject_ids[group_id].remove(uid)
            self.data.save()

    def get_reject_ids(self, group_id: str) -> list[str]:
        return self.data.reject_ids.get(group_id, [])

    def blacklist_on_leave(self, group_id: str, user_id: str) -> None:
        self.data.reject_ids.setdefault(group_id, []).append(user_id)
        self.data.save()

    def set_level_threshold(self, group_id: str, level: int) -> None:
        """设置群的进群等级门槛"""
        if level <= 0:
            # 删除群配置，回退到全局配置
            self.data.reject_below_level.pop(group_id, None)
        else:
            self.data.reject_below_level[group_id] = level
        self.data.save()

    def get_level_threshold(self, group_id: str) -> int | None:
        """获取群的进群等级门槛，返回 None 表示未设置（使用全局配置）"""
        return self.data.reject_below_level.get(group_id)

    def set_auto_reject_without_keyword(self, group_id: str, enabled: bool | None) -> None:
        """设置群的未命中关键词自动拒绝开关，None 表示删除群配置（使用全局配置）"""
        if enabled is None:
            self.data.auto_reject_without_keyword.pop(group_id, None)
        else:
            self.data.auto_reject_without_keyword[group_id] = enabled
        self.data.save()

    def get_auto_reject_without_keyword(self, group_id: str) -> bool | None:
        """获取群的未命中关键词自动拒绝开关，返回 None 表示未设置（使用全局配置）"""
        return self.data.auto_reject_without_keyword.get(group_id)

    def should_auto_reject_without_keyword(self, group_id: str) -> bool:
        """判断是否应该在未命中关键词时自动拒绝（优先使用群配置，否则使用全局配置）"""
        group_setting = self.data.auto_reject_without_keyword.get(group_id)
        if group_setting is not None:
            return group_setting
        return self.auto_reject_without_keyword

    def set_auto_blacklist_on_reject_keyword(self, group_id: str, enabled: bool | None) -> None:
        """设置群的命中黑词自动拉黑开关，None 表示删除群配置（使用全局配置）"""
        if enabled is None:
            self.data.auto_blacklist_on_reject_keyword.pop(group_id, None)
        else:
            self.data.auto_blacklist_on_reject_keyword[group_id] = enabled
        self.data.save()

    def get_auto_blacklist_on_reject_keyword(self, group_id: str) -> bool | None:
        """获取群的命中黑词自动拉黑开关，返回 None 表示未设置（使用全局配置）"""
        return self.data.auto_blacklist_on_reject_keyword.get(group_id)

    def should_auto_blacklist_on_reject_keyword(self, group_id: str) -> bool:
        """判断是否应该在命中黑词时自动拉黑（优先使用群配置，否则使用全局配置）"""
        group_setting = self.data.auto_blacklist_on_reject_keyword.get(group_id)
        if group_setting is not None:
            return group_setting
        return self.auto_blacklist_on_reject_keyword


class JoinHandle:
    def __init__(self, config: AstrBotConfig, data_dir: Path, admins_id: list[str]):
        self.conf = config
        self.admins_id: list[str] = admins_id
        self.group_join_manager = GroupJoinManager(
            str(data_dir / "group_join_data.json")
        )
        self.group_join_manager.reject_below_level = int(
            config.get("reject_below_level", 0)
        )
        self.group_join_manager.auto_reject_without_keyword = bool(
            config.get("auto_reject_without_keyword", False)
        )
        self.group_join_manager.auto_blacklist_on_reject_keyword = bool(
            config.get("auto_blacklist_on_reject_keyword", False)
        )

    async def _send_admin(self, client: CQHttp, message: str):
        """向bot管理员发送私聊消息"""
        for admin_id in self.admins_id:
            if admin_id.isdigit():
                try:
                    await client.send_private_msg(
                        user_id=int(admin_id), message=message
                    )
                except Exception as e:
                    logger.error(f"无法发送消息给bot管理员：{e}")

    async def add_accept_keyword(self, event: AiocqhttpMessageEvent):
        """添加自动批准进群的关键词"""
        if keywords := event.message_str.removeprefix("添加进群关键词").strip().split():
            self.group_join_manager.add_keyword(event.get_group_id(), keywords)
            await event.send(event.plain_result(f"新增进群关键词：{keywords}"))
        else:
            await event.send(event.plain_result("未输入任何关键词"))

    async def remove_accept_keyword(self, event: AiocqhttpMessageEvent):
        """删除自动批准进群的关键词"""
        if keywords := event.message_str.removeprefix("删除进群关键词").strip().split():
            self.group_join_manager.remove_keyword(event.get_group_id(), keywords)
            await event.send(event.plain_result(f"已删进群关键词：{keywords}"))
        else:
            await event.send(event.plain_result("未指定要删除的关键词"))

    async def view_accept_keywords(self, event: AiocqhttpMessageEvent):
        """查看自动批准进群的关键词"""
        keywords = self.group_join_manager.get_keywords(event.get_group_id())
        if not keywords:
            await event.send(event.plain_result("本群没有设置进群关键词"))
            return
        await event.send(event.plain_result(f"本群的进群关键词：{keywords}"))

    async def add_reject_keywords(self, event: AiocqhttpMessageEvent):
        """添加进群黑名单关键词（命中即拒绝）"""
        if keywords := event.message_str.removeprefix("添加进群黑词").strip().split():
            self.group_join_manager.add_reject_keyword(event.get_group_id(), keywords)
            await event.send(event.plain_result(f"新增进群黑名单关键词：{keywords}"))
        else:
            await event.send(event.plain_result("未输入任何关键词"))

    async def remove_reject_keywords(self, event: AiocqhttpMessageEvent):
        """删除进群黑名单关键词"""
        if keywords := event.message_str.removeprefix("删除进群黑词").strip().split():
            self.group_join_manager.remove_reject_keyword(event.get_group_id(), keywords)
            await event.send(event.plain_result(f"已删进群黑名单关键词：{keywords}"))
        else:
            await event.send(event.plain_result("未指定要删除的关键词"))

    async def view_reject_keywords(self, event: AiocqhttpMessageEvent):
        """查看进群黑名单关键词"""
        keywords = self.group_join_manager.get_reject_keywords(event.get_group_id())
        if not keywords:
            await event.send(event.plain_result("本群没有设置进群黑名单关键词"))
            return
        await event.send(event.plain_result(f"本群的进群黑名单关键词：{keywords}"))

    async def add_reject_ids(self, event: AiocqhttpMessageEvent):
        """添加指定ID到进群黑名单"""
        parts = event.message_str.strip().split(" ")
        if len(parts) < 2:
            await event.send(event.plain_result("请提供至少一个用户ID"))
            return
        reject_ids = list(set(parts[1:]))
        self.group_join_manager.add_reject_id(event.get_group_id(), reject_ids)
        await event.send(event.plain_result(f"进群黑名单新增ID：{reject_ids}"))

    async def remove_reject_ids(self, event: AiocqhttpMessageEvent):
        """从进群黑名单中删除指定ID"""
        parts = event.message_str.strip().split(" ")
        if len(parts) < 2:
            await event.send(event.plain_result("请提供至少一个用户ID。"))
            return
        ids = list(set(parts[1:]))
        self.group_join_manager.remove_reject_id(event.get_group_id(), ids)
        await event.send(event.plain_result(f"已从黑名单中删除：{ids}"))


    async def view_reject_ids(self, event: AiocqhttpMessageEvent):
        """查看进群黑名单"""
        ids = self.group_join_manager.get_reject_ids(event.get_group_id())
        if not ids:
            await event.send(event.plain_result("本群没有设置进群黑名单"))
            return
        await event.send(event.plain_result(f"本群的进群黑名单：{ids}"))

    async def set_level_threshold(self, event: AiocqhttpMessageEvent):
        """设置本群进群等级门槛"""
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            await event.send(event.plain_result("请提供等级数值"))
            return
        try:
            level = int(parts[1])
        except ValueError:
            await event.send(event.plain_result("等级必须是整数"))
            return

        group_id = event.get_group_id()
        self.group_join_manager.set_level_threshold(group_id, level)

        if level <= 0:
            global_level = self.group_join_manager.reject_below_level
            if global_level > 0:
                await event.send(event.plain_result(f"已清除本群等级门槛，将使用全局配置（{global_level}级）"))
            else:
                await event.send(event.plain_result("已清除本群等级门槛，当前未启用等级限制"))
        else:
            await event.send(event.plain_result(f"已设置本群进群等级门槛为 {level} 级"))

    async def view_level_threshold(self, event: AiocqhttpMessageEvent):
        """查看本群进群等级门槛"""
        group_id = event.get_group_id()
        group_level = self.group_join_manager.get_level_threshold(group_id)
        global_level = self.group_join_manager.reject_below_level

        if group_level is not None:
            await event.send(event.plain_result(f"本群进群等级门槛：{group_level} 级（群独立配置）"))
        elif global_level > 0:
            await event.send(event.plain_result(f"本群进群等级门槛：{global_level} 级（全局配置）"))
        else:
            await event.send(event.plain_result("本群未设置进群等级门槛"))

    async def set_auto_reject_without_keyword(self, event: AiocqhttpMessageEvent):
        """设置本群未命中关键词自动拒绝开关"""
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            await event.send(event.plain_result("请提供参数：开/关/清除"))
            return
        arg = parts[1]
        group_id = event.get_group_id()

        if arg in ("开", "开启", "on", "true", "1"):
            self.group_join_manager.set_auto_reject_without_keyword(group_id, True)
            await event.send(event.plain_result("已开启本群未命中关键词自动拒绝"))
        elif arg in ("关", "关闭", "off", "false", "0"):
            self.group_join_manager.set_auto_reject_without_keyword(group_id, False)
            await event.send(event.plain_result("已关闭本群未命中关键词自动拒绝"))
        elif arg in ("清除", "删除", "默认", "default", "clear"):
            self.group_join_manager.set_auto_reject_without_keyword(group_id, None)
            global_setting = self.group_join_manager.auto_reject_without_keyword
            status = "开启" if global_setting else "关闭"
            await event.send(event.plain_result(f"已清除本群配置，将使用全局配置（{status}）"))
        else:
            await event.send(event.plain_result("请提供参数：开/关/清除"))

    async def view_auto_reject_without_keyword(self, event: AiocqhttpMessageEvent):
        """查看本群未命中关键词自动拒绝开关状态"""
        group_id = event.get_group_id()
        group_setting = self.group_join_manager.get_auto_reject_without_keyword(group_id)
        global_setting = self.group_join_manager.auto_reject_without_keyword

        if group_setting is not None:
            status = "开启" if group_setting else "关闭"
            await event.send(event.plain_result(f"本群未命中关键词自动拒绝：{status}（群独立配置）"))
        else:
            status = "开启" if global_setting else "关闭"
            await event.send(event.plain_result(f"本群未命中关键词自动拒绝：{status}（全局配置）"))

    async def set_auto_blacklist_on_reject_keyword(self, event: AiocqhttpMessageEvent):
        """设置本群命中黑词自动拉黑开关"""
        parts = event.message_str.strip().split()
        if len(parts) < 2:
            await event.send(event.plain_result("请提供参数：开/关/清除"))
            return
        arg = parts[1]
        group_id = event.get_group_id()

        if arg in ("开", "开启", "on", "true", "1"):
            self.group_join_manager.set_auto_blacklist_on_reject_keyword(group_id, True)
            await event.send(event.plain_result("已开启本群命中黑词自动拉黑"))
        elif arg in ("关", "关闭", "off", "false", "0"):
            self.group_join_manager.set_auto_blacklist_on_reject_keyword(group_id, False)
            await event.send(event.plain_result("已关闭本群命中黑词自动拉黑"))
        elif arg in ("清除", "删除", "默认", "default", "clear"):
            self.group_join_manager.set_auto_blacklist_on_reject_keyword(group_id, None)
            global_setting = self.group_join_manager.auto_blacklist_on_reject_keyword
            status = "开启" if global_setting else "关闭"
            await event.send(event.plain_result(f"已清除本群配置，将使用全局配置（{status}）"))
        else:
            await event.send(event.plain_result("请提供参数：开/关/清除"))

    async def view_auto_blacklist_on_reject_keyword(self, event: AiocqhttpMessageEvent):
        """查看本群命中黑词自动拉黑开关状态"""
        group_id = event.get_group_id()
        group_setting = self.group_join_manager.get_auto_blacklist_on_reject_keyword(group_id)
        global_setting = self.group_join_manager.auto_blacklist_on_reject_keyword

        if group_setting is not None:
            status = "开启" if group_setting else "关闭"
            await event.send(event.plain_result(f"本群命中黑词自动拉黑：{status}（群独立配置）"))
        else:
            status = "开启" if global_setting else "关闭"
            await event.send(event.plain_result(f"本群命中黑词自动拉黑：{status}（全局配置）"))

    async def agree_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        """批准进群申请"""
        reply = await self.approve(event=event, extra=extra, approve=True)
        if reply:
            await event.send(event.plain_result(reply))

    async def refuse_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        """驳回进群申请"""
        reply = await self.approve(event=event, extra=extra, approve=False)
        if reply:
            await event.send(event.plain_result(reply))


    async def event_monitoring(self, event: AiocqhttpMessageEvent):
        """监听进群/退群事件"""
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict):
            return

        client = event.bot
        group_id: int = raw.get("group_id", 0)
        user_id: int = raw.get("user_id", 0)
        # 进群申请事件
        if (
            self.conf["enable_audit"]
            and raw.get("post_type") == "request"
            and raw.get("request_type") == "group"
            and raw.get("sub_type") == "add"
        ):
            comment = raw.get("comment")
            flag = raw.get("flag", "")
            stranger_info = await client.get_stranger_info(user_id=user_id)
            nickname = stranger_info.get("nickname") or "未知昵称"
            napcat_level = stranger_info.get("qqLevel")
            lagrange_level = stranger_info.get("level")
            user_level = napcat_level or lagrange_level
            reply = f"【进群申请】批准/驳回：\n昵称：{nickname}\nQQ：{user_id}\nflag：{flag}"
            if user_level is not None:
                reply += f"\n等级：{user_level}"
            if comment:
                reply += f"\n{comment}"
            if self.conf["admin_audit"]:
                await self._send_admin(client, reply)
            else:
                await event.send(event.plain_result(reply))

            reason = self.group_join_manager.reject_reason(
                str(group_id), str(user_id), comment, user_level
            )
            if reason:
                await client.set_group_add_request(
                    flag=flag, sub_type="add", approve=False, reason=reason,
                )
                reply_msg = f"{reason}，已自动拒绝进群"
                # 命中黑名单词汇时自动拉黑（优先使用群配置，否则使用全局配置）
                if (
                    reason == "命中黑名单关键词"
                    and self.group_join_manager.should_auto_blacklist_on_reject_keyword(str(group_id))
                ):
                    self.group_join_manager.add_reject_id(str(group_id), [str(user_id)])
                    reply_msg += "，并已加入黑名单"
                await event.send(event.plain_result(reply_msg))
            elif comment and self.group_join_manager.should_approve(
                str(group_id), comment
            ):
                await client.set_group_add_request(
                    flag=flag, sub_type="add", approve=True
                )
                await event.send(event.plain_result("验证通过，已自动同意进群"))

        # 主动退群事件
        elif (
            self.conf["enable_black"]
            and raw.get("post_type") == "notice"
            and raw.get("notice_type") == "group_decrease"
            and raw.get("sub_type") == "leave"
        ):
            nickname = (await client.get_stranger_info(user_id=user_id))[
                "nickname"
            ] or "未知昵称"
            reply = f"{nickname}({user_id}) 主动退群了"
            if self.conf["auto_black"]:
                self.group_join_manager.blacklist_on_leave(str(group_id), str(user_id))
                reply += "，已拉进黑名单"
            await event.send(event.plain_result(reply))

        # 进群禁言
        elif (
            raw.get("notice_type") == "group_increase"
            and str(user_id) != event.get_self_id()
        ):
            await event.send(event.plain_result(self.conf["increase"]["welcome"]))
            if self.conf["increase"]["ban_time"] > 0:
                try:
                    await client.set_group_ban(
                        group_id=group_id,
                        user_id=user_id,
                        duration=self.conf["increase"]["ban_time"],
                    )
                except Exception:
                    pass

    @staticmethod
    async def approve(
        event: AiocqhttpMessageEvent, extra: str = "", approve: bool = True
    ) -> str | None:
        """处理进群申请"""
        text = get_reply_message_str(event)
        if not text:
            return "未引用任何【进群申请】"
        lines = text.split("\n")
        if "【进群申请】" in text and len(lines) >= 4:
            nickname = lines[1].split("：")[1]  # 第2行冒号后文本为nickname
            flag = lines[3].split("：")[1]  # 第4行冒号后文本为flag
            try:
                await event.bot.set_group_add_request(
                    flag=flag, sub_type="add", approve=approve, reason=extra
                )
                if approve:
                    reply = f"已同意{nickname}进群"
                else:
                    reply = f"已拒绝{nickname}进群" + (
                        f"\n理由：{extra}" if extra else ""
                    )
                return reply
            except Exception:
                return "这条申请处理过了或者格式不对"
