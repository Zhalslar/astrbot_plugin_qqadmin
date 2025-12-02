import copy
import json
from pathlib import Path

from aiocqhttp import CQHttp

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..utils import get_nickname, get_reply_message_str


class GroupJoinData:
    def __init__(self, path: Path, config: dict):
        self.path = path
        # 总数据
        self._cfg: dict[str, dict] = {}
        # 默认配置
        self.default_cfg = {
            "switch": config["default_switch"],
            "accept_keywords": [],
            "reject_keywords": [],
            "min_level": config["default_min_level"],
            "max_time": config["default_max_time"],
            "block_ids": [],
        }
        self._load()

    # ---------- 私有工具 ----------
    def _load(self):
        if not self.path.exists():
            self.save()
            return
        try:
            with self.path.open(encoding="utf-8") as f:
                self._cfg = json.load(f)
        except Exception as e:
            logger.error(f"加载失败: {e}")
            self.save()

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(self._cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存失败: {e}")

    def ensure_group(self, group_id: str) -> None:
        """群聊没有配置时创建默认配置并落盘"""
        if group_id not in self._cfg:
            self._cfg[group_id] = copy.deepcopy(self.default_cfg)
            self.save()

    # ---------- 对外接口 ----------
    def get(self, group_id: str) -> dict:
        """返回该群配置（无则返回空 dict）"""
        return self._cfg.get(group_id, {})

    def set(self, group_id: str, **kwargs) -> None:
        """直接覆写给定字段"""
        self.ensure_group(group_id)
        self._cfg.setdefault(group_id, {}).update(kwargs)
        self.save()

    def remove(self, group_id: str) -> None:
        """删除整个群配置"""
        self._cfg.pop(group_id, None)
        self.save()

    # ---------- 快捷只读访问 ----------
    def get_switch(self, group_id: str) -> bool:
        return self.get(group_id).get("switch", False)

    def get_accept_keywords(self, group_id: str) -> list[str]:
        return self.get(group_id).get("accept_keywords", [])

    def get_reject_keywords(self, group_id: str) -> list[str]:
        return self.get(group_id).get("reject_keywords", [])

    def get_min_level(self, group_id: str) -> int:
        return self.get(group_id).get("min_level", 0)

    def get_max_time(self, group_id: str) -> int:
        return self.get(group_id).get("max_time", 0)

    def get_block_ids(self, group_id: str) -> list[str]:
        return self.get(group_id).get("block_ids", [])

    # ---------- 快捷覆写 ----------
    def set_switch(self, group_id: str, on: bool) -> None:
        self.set(group_id, switch=on)

    def set_accept_keywords(self, group_id: str, kws: list[str]) -> None:
        self.set(group_id, accept_keywords=kws)

    def set_reject_keywords(self, group_id: str, kws: list[str]) -> None:
        self.set(group_id, reject_keywords=kws)

    def set_min_level(self, group_id: str, level: int) -> None:
        self.set(group_id, min_level=level)

    def set_max_time(self, group_id: str, times: int) -> None:
        self.set(group_id, max_time=times)

    def set_block_ids(self, group_id: str, uids: list[str]) -> None:
        self.set(group_id, block_ids=uids)

    # ---------- 快捷增删 ----------
    def add_block_id(self, group_id: str, uid: str) -> None:
        self.set_block_ids(group_id, [*self.get_block_ids(group_id), uid])

    def remove_block_id(self, group_id: str, uid: str) -> None:
        self.set_block_ids(
            group_id, [i for i in self.get_block_ids(group_id) if i != uid]
        )


class JoinHandle:
    DB_VERSION = 2

    def __init__(self, config: AstrBotConfig, data_dir: Path, admin_ids: list[str]):
        self.jconf = config["join_config"]
        self.admin_ids: list[str] = admin_ids
        json_file = data_dir / f"group_join_data_v{self.DB_VERSION}.json"
        self.db = GroupJoinData(json_file, self.jconf)
        # 加群失败次数缓存（key 用 f"{group_id}_{user_id}"）
        self._fail: dict[str, int] = {}

    async def _send_admin(self, client: CQHttp, message: str):
        """向bot管理员发送私聊消息"""
        for admin_id in self.admin_ids:
            if admin_id.isdigit():
                try:
                    await client.send_private_msg(
                        user_id=int(admin_id), message=message
                    )
                except Exception as e:
                    logger.error(f"无法发送消息给bot管理员：{e}")

    @staticmethod
    def _parse_mode(mode: str | bool | None):
        """解析模式"""
        mode = str(mode).strip().lower()
        match mode:
            case "开" | "开启" | "on" | "true" | "1":
                return True
            case "关" | "关闭" | "off" | "false" | "0":
                return False
            case _:
                return None

    # -----------修改配置-----------------

    async def handle_join_review(
        self, event: AiocqhttpMessageEvent, mode_str: str | bool | None
    ):
        """设置/查看本群进群审核开关"""
        print(repr(mode_str))
        gid = event.get_group_id()
        mode = self._parse_mode(mode_str)
        print(mode)
        if isinstance(mode, bool):
            self.db.set_switch(gid, mode)
            await event.send(event.plain_result(f"本群进群审核：{mode}"))
        else:
            status = self.db.get_switch(gid)
            await event.send(event.plain_result(f"本群进群审核：{status}"))

    async def handle_accept_keyword(self, event: AiocqhttpMessageEvent):
        """设置/查看自动批准进群的关键词"""
        gid = event.get_group_id()
        if keywords := event.message_str.removeprefix("进群白词").strip().split():
            self.db.set_accept_keywords(gid, keywords)
            await event.send(event.plain_result(f"本群进群白词已设为：{keywords}"))
        else:
            keywords = self.db.get_accept_keywords(gid)
            await event.send(event.plain_result(f"本群进群白词：{keywords}"))

    async def handle_reject_keywords(self, event: AiocqhttpMessageEvent):
        """设置/查看进群黑名单关键词"""
        gid = event.get_group_id()
        if keywords := event.message_str.removeprefix("进群黑词").strip().split():
            self.db.set_reject_keywords(gid, keywords)
            await event.send(event.plain_result(f"本群进群黑词已设为：{keywords}"))
        else:
            keywords = self.db.get_reject_keywords(gid)
            await event.send(event.plain_result(f"本群进群黑词：{keywords}"))

    async def handle_level_threshold(
        self, event: AiocqhttpMessageEvent, level: int | None
    ):
        """设置进群等级门槛"""
        gid = event.get_group_id()
        if isinstance(level, int):
            self.db.set_min_level(gid, level)
            msg = (
                f"本群进群等级门槛已设为：{level} 级"
                if level > 0
                else "已解除本群的进群等级限制"
            )
            await event.send(event.plain_result(msg))
        else:
            level = self.db.get_min_level(gid)
            await event.send(event.plain_result(f"本群进群等级门槛: {level} 级"))

    async def handle_join_time(self, event: AiocqhttpMessageEvent, time: int | None):
        """设置最大进群次数"""
        gid = event.get_group_id()
        if isinstance(time, int):
            self.db.set_max_time(gid, time)
            msg = (
                f"本群进群次数已限制为：{time} 次"
                if time > 0
                else "已解除本群的进群次数限制"
            )
            await event.send(event.plain_result(msg))
        else:
            time = self.db.get_max_time(gid)
            await event.send(event.plain_result(f"本群进群可尝试次数：{time} 次"))

    async def handle_block_ids(self, event: AiocqhttpMessageEvent):
        """设置/查看进群黑名单（支持 +id 增加、-id 删除，纯数字覆写）"""
        gid = event.get_group_id()
        raw = event.message_str.removeprefix("进群黑名单").strip()

        # 仅查询
        if not raw:
            ids = self.db.get_block_ids(gid)
            await event.send(event.plain_result(f"本群进群黑名单：{ids}"))
            return

        # 覆写模式：全部是数字（可空格分隔）
        if all(tok.isdigit() for tok in raw.split()):
            new_ids = raw.split()
            self.db.set_block_ids(gid, new_ids)
            await event.send(event.plain_result(f"黑名单已覆写为：{' '.join(new_ids)}"))
            return

        # 增减模式
        curr = set(self.db.get_block_ids(gid))
        added, removed = [], []
        for tok in raw.split():
            if tok.startswith("+") and tok[1:].isdigit():
                uid = tok[1:]
                if uid not in curr:
                    curr.add(uid)
                    added.append(uid)
            elif tok.startswith("-") and tok[1:].isdigit():
                uid = tok[1:]
                if uid in curr:
                    curr.discard(uid)
                    removed.append(uid)
        self.db.set_block_ids(gid, list(curr))

        # 只反馈实际变动的
        reply = ["本群进群黑名单"]
        if added:
            reply.append(f"新增：{'、'.join(added)}")
        if removed:
            reply.append(f"移除：{'、'.join(removed)}")
        if not added and not removed:
            reply.append("无变动")
        await event.send(event.plain_result("\n".join(reply)))

    # ---------辅助函数-----------------
    def should_approve(
        self,
        group_id: str,
        user_id: str,
        comment: str | None = None,
        user_level: int | None = None,
    ) -> tuple[bool | None, str]:
        """判断是否让该用户入群，返回原因"""
        # 1.黑名单用户
        if user_id in self.db.get_block_ids(group_id):
            return False, "黑名单用户"

        # 2.QQ等级过低
        min_level = self.db.get_min_level(group_id)
        if min_level > 0 and user_level is not None and user_level < min_level:
            return False, f"QQ等级过低({user_level}<{min_level})"

        if comment:
            lower_comment = comment.lower()
            # 3.命中进群黑词
            rkws = self.db.get_reject_keywords(group_id)
            if any(rk.lower() in lower_comment for rk in rkws):
                self.db.add_block_id(group_id, user_id)
                return False, "命中进群黑词，已拉黑"

            # 4.命中进群白词
            akws = self.db.get_accept_keywords(group_id)
            if akws and any(ak.lower() in lower_comment for ak in akws):
                return True, "命中进群白词"

        # 5.最大失败次数（考虑到只是防爆破，存内存里足矣，重启清零）
        max_fail = self.db.get_max_time(group_id)
        if max_fail > 0:
            key = f"{group_id}_{user_id}"
            self._fail[key] = self._fail.get(key, 0) + 1
            if self._fail[key] >= max_fail:
                self.db.add_block_id(group_id, user_id)
                return False, f"进群尝试次数已达上限({max_fail}次)，已拉黑"

        # 6.未命中白词时,自动驳回
        if self.jconf["no_match_reject"]:
            return False, "未命中进群关键词"

        # 7.未命中进群关键词, 人工审核
        return None, "未命中进群关键词"

    # ---------处理事件-----------------

    async def event_monitoring(self, event: AiocqhttpMessageEvent):
        """监听进群/退群事件"""
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict):
            return

        group_id: str = str(raw.get("group_id", ""))

        # 进群审核总开关
        self.db.ensure_group(group_id)
        if not self.db.get_switch(group_id):
            return

        client = event.bot
        user_id: str = str(raw.get("user_id", ""))

        # 进群申请事件
        if (
            raw.get("post_type") == "request"
            and raw.get("request_type") == "group"
            and raw.get("sub_type") == "add"
        ):
            comment = raw.get("comment")
            flag = raw.get("flag", "")
            info = await client.get_stranger_info(user_id=int(user_id))
            nickname = info.get("nickname") or "未知昵称"
            if info.get("isHideQQLevel"):
                level = None
            else:
                level = info.get("qqLevel") or info.get("level")

            # 生成并发送通知
            notice = f"【进群申请】批准/驳回：\n昵称：{nickname}\nQQ：{user_id}\nflag：{flag}"
            if level is not None:
                notice += f"\n等级：{level}"
            if comment:
                notice += f"\n{comment}"
            if self.jconf["admin_audit"]:
                await self._send_admin(client, notice)
            else:
                await event.send(event.plain_result(notice))

            # 判断是否通过
            approve, reason = self.should_approve(
                group_id, user_id, comment, level
            )
            # 清理缓存
            if approve is True:
                self._fail.pop(f"{group_id}_{user_id}", None)
            # 人工审核
            if approve is None:
                return
            # 自动审核
            try:
                await client.set_group_add_request(
                    flag=flag,
                    sub_type="add",
                    approve=approve,
                    reason="" if approve else reason,
                )
                msg = f"自动{'批准' if approve else '驳回'}: {reason}"
                if self.jconf["admin_audit"]:
                    await self._send_admin(client, msg)
                else:
                    await event.send(event.plain_result(msg))
            except Exception as e:
                logger.warning(f"set_group_add_request failed: {e}")
                return

        # 主动退群事件
        elif (
            self.jconf["leave_notify"]
            and raw.get("post_type") == "notice"
            and raw.get("notice_type") == "group_decrease"
            and raw.get("sub_type") == "leave"
        ):
            nickname = await get_nickname(event, user_id)
            msg = f"{nickname}({user_id}) 主动退群了"
            if self.jconf["leave_block"]:
                self.db.add_block_id(group_id, user_id)
                msg += "，已拉黑"
            await event.send(event.plain_result(msg))

        # 进群欢迎、禁言
        elif (
            raw.get("notice_type") == "group_increase"
            and str(user_id) != event.get_self_id()
        ):
            # 进群欢迎
            if self.jconf["welcome_template"]:
                welcome_template: str = self.jconf["welcome_template"]
                nickname = await get_nickname(event, user_id)
                welcome = welcome_template.format(nickname=nickname)
                await event.send(event.plain_result(welcome))
            # 进群禁言
            if self.jconf["ban_time"] > 0:
                try:
                    await client.set_group_ban(
                        group_id=int(group_id),
                        user_id=int(user_id),
                        duration=self.jconf["ban_time"],
                    )
                except Exception:
                    pass

    async def set_approve(
        self, event: AiocqhttpMessageEvent, extra: str = "", approve: bool = True
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
            except Exception as e:
                logger.error(f"处理进群申请失败: {e}")
                return "这条申请处理过了或者格式不对"

    async def agree_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        """批准进群申请"""
        reply = await self.set_approve(event=event, extra=extra, approve=True)
        if reply:
            await event.send(event.plain_result(reply))

    async def refuse_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        """驳回进群申请"""
        reply = await self.set_approve(event=event, extra=extra, approve=False)
        if reply:
            await event.send(event.plain_result(reply))
