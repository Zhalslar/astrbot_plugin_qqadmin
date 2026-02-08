from aiocqhttp import CQHttp

from astrbot.api import logger
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..data import QQAdminDB
from ..utils import get_nickname, get_reply_message_str, parse_bool
from ..config import PluginConfig


class JoinHandle:
    def __init__(self, config: PluginConfig, db: QQAdminDB):
        self.cfg = config
        self.db = db
        self._fail: dict[str, int] = {}

    async def _send_admin(self, client: CQHttp, message: str):
        for admin_id in self.cfg.admins_id:
            try:
                await client.send_private_msg(
                    user_id=int(admin_id), message=message
                )
            except Exception as e:
                logger.error(f"无法发送消息给bot管理员：{e}")

    # -----------修改配置-----------------

    async def handle_join_review(
        self, event: AiocqhttpMessageEvent, mode_str: str | bool | None
    ):
        gid = event.get_group_id()
        mode = parse_bool(mode_str)
        if isinstance(mode, bool):
            await self.db.set(gid, "join_switch", mode)
            await event.send(event.plain_result(f"本群进群审核：{mode}"))
        else:
            status = await self.db.get(gid, "join_switch")
            await event.send(event.plain_result(f"本群进群审核：{status}"))

    async def handle_accept_words(self, event: AiocqhttpMessageEvent):
        gid = event.get_group_id()
        raw = event.message_str.partition(" ")[2]
        if raw:
            words = raw.split()
            await self.db.set(gid, "join_accept_words", words)
            await event.send(event.plain_result(f"本群进群白词已设为：{words}"))
        else:
            words = await self.db.get(gid, "join_accept_words", [])
            await event.send(event.plain_result(f"本群进群白词：{words}"))

    async def handle_reject_words(self, event: AiocqhttpMessageEvent):
        gid = event.get_group_id()
        raw = event.message_str.partition(" ")[2]
        if raw:
            words = raw.split()
            await self.db.set(gid, "join_reject_words", words)
            await event.send(event.plain_result(f"本群进群黑词已设为：{words}"))
        else:
            words = await self.db.get(gid, "join_reject_words", [])
            await event.send(event.plain_result(f"本群进群黑词：{words}"))

    async def handle_no_match_reject(
        self, event: AiocqhttpMessageEvent, mode_str: str | bool | None
    ):
        gid = event.get_group_id()
        mode = parse_bool(mode_str)
        if isinstance(mode, bool):
            await self.db.set(gid, "join_no_match_reject", mode)
            await event.send(event.plain_result(f"本群未命中白词驳回已设为：{mode}"))
        else:
            status = await self.db.get(gid, "join_no_match_reject")
            await event.send(event.plain_result(f"本群未命中白词驳回：{status}"))

    async def handle_join_min_level(
        self, event: AiocqhttpMessageEvent, level: int | None
    ):
        gid = event.get_group_id()
        if isinstance(level, int):
            await self.db.set(gid, "join_min_level", level)
            msg = (
                f"本群进群等级门槛已设为：{level} 级"
                if level > 0
                else "已解除本群的进群等级限制"
            )
            await event.send(event.plain_result(msg))
        else:
            level = await self.db.get(gid, "join_min_level")
            await event.send(event.plain_result(f"本群进群等级门槛: {level} 级"))

    async def handle_join_max_time(
        self, event: AiocqhttpMessageEvent, time: int | None
    ):
        gid = event.get_group_id()
        if isinstance(time, int):
            await self.db.set(gid, "join_max_time", time)
            msg = (
                f"本群进群次数已限制为：{time} 次"
                if time > 0
                else "已解除本群的进群次数限制"
            )
            await event.send(event.plain_result(msg))
        else:
            time = await self.db.get(gid, "join_max_time")
            await event.send(event.plain_result(f"本群进群可尝试次数：{time} 次"))

    async def handle_block_ids(self, event: AiocqhttpMessageEvent):
        gid = event.get_group_id()
        raw = event.message_str.partition(" ")[2]

        if not raw:
            ids = await self.db.get(gid, "block_ids", [])
            await event.send(event.plain_result(f"本群进群黑名单：{ids}"))
            return

        if all(tok.isdigit() for tok in raw.split()):
            new_ids = raw.split()
            await self.db.set(gid, "block_ids", new_ids)
            await event.send(event.plain_result(f"黑名单已覆写为：{' '.join(new_ids)}"))
            return

        curr = set(await self.db.get(gid, "block_ids", []))
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

        await self.db.set(gid, "block_ids", list(curr))

        reply = ["本群进群黑名单"]
        if added:
            reply.append(f"新增：{'、'.join(added)}")
        if removed:
            reply.append(f"移除：{'、'.join(removed)}")
        if not added and not removed:
            reply.append("无变动")
        await event.send(event.plain_result("\n".join(reply)))

    async def handle_join_ban(self, event: AiocqhttpMessageEvent, time: int | None):
        gid = event.get_group_id()
        if isinstance(time, int):
            await self.db.set(gid, "join_ban_time", time)
            msg = f"本群进群禁言已设为：{time} 秒" if time > 0 else "已关闭本群进群禁言"
            await event.send(event.plain_result(msg))
        else:
            t = await self.db.get(gid, "join_ban_time", 0)
            await event.send(event.plain_result(f"本群进群禁言设置：{t} 秒"))

    async def handle_join_welcome(self, event: AiocqhttpMessageEvent):
        gid = event.get_group_id()
        raw = event.message_str.partition(" ")[2]

        if raw:
            await self.db.set(gid, "join_welcome", raw)
            await event.send(event.plain_result(f"本群进群欢迎语已设为：\n{raw}"))
        else:
            text = await self.db.get(gid, "join_welcome", "")
            await event.send(
                event.plain_result(f"本群进群欢迎语：\n{text or '（未设置）'}")
            )

    async def handle_leave_notify(self, event: AiocqhttpMessageEvent, mode_str):
        gid = event.get_group_id()
        mode = parse_bool(mode_str)
        if isinstance(mode, bool):
            await self.db.set(gid, "leave_notify", mode)
            await event.send(event.plain_result(f"本群退群通知已设为：{mode}"))
        else:
            status = await self.db.get(gid, "leave_notify")
            await event.send(event.plain_result(f"本群退群通知：{status}"))

    async def handle_leave_block(self, event: AiocqhttpMessageEvent, mode_str):
        gid = event.get_group_id()
        mode = parse_bool(mode_str)
        if isinstance(mode, bool):
            await self.db.set(gid, "leave_block", mode)
            await event.send(event.plain_result(f"本群退群拉黑已设为：{mode}"))
        else:
            status = await self.db.get(gid, "leave_block")
            await event.send(event.plain_result(f"本群退群拉黑：{status}"))

    # ---------辅助函数-----------------
    async def should_approve(
        self,
        gid: str,
        uid: str,
        comment: str | None = None,
        user_level: int | None = None,
    ) -> tuple[bool | None, str]:
        """判断是否让该用户入群，返回原因"""
        # 1.黑名单用户
        block_ids = await self.db.get(gid, "block_ids", [])
        if uid in block_ids:
            return False, "黑名单用户"

        # 2.QQ等级过低
        min_level = await self.db.get(gid, "join_min_level")
        if min_level > 0 and user_level is not None and user_level < min_level:
            return False, f"QQ等级过低({user_level}<{min_level})"

        if comment:
            # 提取答案部分
            keyword = "\n答案："
            if keyword in comment:
                comment = comment.split(keyword, 1)[1]

            lower_comment = comment.lower()
            # 3.命中进群黑词
            rkws = await self.db.get(gid, "join_reject_words", [])
            if any(rk.lower() in lower_comment for rk in rkws):
                if await self.db.get(gid, "reject_word_block", False):
                    await self.db.add(gid, "block_ids", uid)
                    return False, "命中进群黑词，已拉黑"
                return False, "命中进群黑词"

            # 4.命中进群白词
            akws = await self.db.get(gid, "join_accept_words", [])
            if akws and any(ak.lower() in lower_comment for ak in akws):
                return True, "命中进群白词"

        # 5.最大失败次数（考虑到只是防爆破，存内存里足矣，重启清零）
        max_fail = await self.db.get(gid, "join_max_time", 3)
        if max_fail > 0:
            key = f"{gid}_{uid}"
            self._fail[key] = self._fail.get(key, 0) + 1
            if self._fail[key] >= max_fail:
                await self.db.add(gid, "block_ids", uid)
                return False, f"进群尝试次数已达上限({max_fail}次)，已拉黑"

        # 6.未命中白词时, 自动驳回
        if await self.db.get(gid, "join_no_match_reject"):
            return False, "未命中进群关键词"

        # 7.未命中进群关键词, 人工审核
        return None, "人工审核"

    # ---------处理事件-----------------

    async def event_monitoring(self, event: AiocqhttpMessageEvent):
        """监听进群/退群事件"""
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict):
            return

        gid: str = str(raw.get("group_id", ""))
        client = event.bot
        uid: str = str(raw.get("user_id", ""))

        # 进群申请事件
        if (
            raw.get("post_type") == "request"
            and raw.get("request_type") == "group"
            and raw.get("sub_type") == "add"
        ):
            # 进群审核总开关
            if not await self.db.get(gid, "join_switch"):
                return
            comment = raw.get("comment")
            flag = raw.get("flag", "")
            info = await client.get_stranger_info(user_id=int(uid))
            nickname = info.get("nickname") or "未知昵称"
            if info.get("isHideQQLevel"):
                level = None
            else:
                level = info.get("qqLevel") or info.get("level")

            # 判断是否通过
            approve, reason = await self.should_approve(gid, uid, comment, level)
            # 清理缓存
            if approve is True:
                self._fail.pop(f"{gid}_{uid}", None)

            # 自动审核
            if approve is not None:
                try:
                    await client.set_group_add_request(
                        flag=flag,
                        sub_type="add",
                        approve=approve,
                        reason="" if approve else reason,
                    )
                    approve_msg = f"自动{'批准' if approve else '驳回'}：{reason}"
                except Exception as e:
                    logger.warning(f"set_group_add_request failed: {e}")
                    return
            else:
                approve_msg = ""

            # 生成并发送通知
            tip = "批准/驳回：" if not approve_msg else ""
            notice = f"【进群申请】{tip}\n昵称：{nickname}\nQQ：{uid}\nflag：{flag}"
            if level is not None:
                notice += f"\n等级：{level}"
            if comment:
                notice += f"\n{comment}"
            if approve_msg:
                notice += f"\n\n{approve_msg}"

            if self.cfg.admin_audit:
                await self._send_admin(client, notice)
            else:
                await event.send(event.plain_result(notice))

        # 主动退群事件
        elif (
            raw.get("post_type") == "notice"
            and raw.get("notice_type") == "group_decrease"
            and raw.get("sub_type") == "leave"
        ):
            if await self.db.get(gid, "leave_notify", False):
                nickname = await get_nickname(event, uid)
                msg = f"{nickname}({uid}) 主动退群了"
                # 退群拉黑
                if await self.db.get(gid, "leave_block", False):
                    await self.db.add(gid, "block_ids", uid)
                    msg += "，已拉黑"
                await event.send(event.plain_result(msg))


        # 进群欢迎、禁言
        elif (
            raw.get("notice_type") == "group_increase"
            and uid != event.get_self_id()
        ):
            # 进群欢迎
            join_welcome = await self.db.get(gid, "join_welcome")
            if join_welcome:
                nickname = await get_nickname(event, uid)
                welcome = join_welcome.format(nickname=nickname)
                await event.send(event.plain_result(welcome))
            # 进群禁言
            join_ban_time = await self.db.get(gid, "join_ban_time")
            if join_ban_time > 0:
                try:
                    await client.set_group_ban(
                        group_id=int(gid),
                        user_id=int(uid),
                        duration=join_ban_time,
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
