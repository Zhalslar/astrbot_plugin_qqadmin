import asyncio
import random

from astrbot.core.message.components import At, Plain, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..utils import BAN_ME_QUOTES, extract_image_url, get_ats, get_nickname
from ..config import PluginConfig


class NormalHandle:
    def __init__(self, config: PluginConfig):
        self.cfg = config

    async def set_group_ban(
        self,
        event: AiocqhttpMessageEvent,
        ban_time: int | None = None,
    ):
        """禁言 60 @user"""
        ban_time = self.cfg.get_ban_time(ban_time)

        for tid in get_ats(event):
            try:
                await event.bot.set_group_ban(
                    group_id=int(event.get_group_id()),
                    user_id=int(tid),
                    duration=ban_time,
                )
            except:  # noqa: E722
                pass
        event.stop_event()

    async def set_group_ban_me(
        self, event: AiocqhttpMessageEvent, ban_time: int | None = None
    ):
        """禁我 60"""
        ban_time = self.cfg.get_ban_time(ban_time)
        try:
            await event.bot.set_group_ban(
                group_id=int(event.get_group_id()),
                user_id=int(event.get_sender_id()),
                duration=ban_time,
            )
            await event.send(event.plain_result(random.choice(BAN_ME_QUOTES)))
        except Exception:
            await event.send(event.plain_result("我可禁言不了你"))
        event.stop_event()

    async def cancel_group_ban(self, event: AiocqhttpMessageEvent):
        """解禁@user"""
        for tid in get_ats(event):
            await event.bot.set_group_ban(
                group_id=int(event.get_group_id()), user_id=int(tid), duration=0
            )
        event.stop_event()

    async def set_group_whole_ban(self, event: AiocqhttpMessageEvent):
        """全员禁言"""
        await event.bot.set_group_whole_ban(
            group_id=int(event.get_group_id()), enable=True
        )
        await event.send(event.plain_result("已开启全体禁言"))

    async def cancel_group_whole_ban(self, event: AiocqhttpMessageEvent):
        """关闭全员禁言"""
        await event.bot.set_group_whole_ban(
            group_id=int(event.get_group_id()), enable=False
        )
        await event.send(event.plain_result("已关闭全员禁言"))

    async def set_group_card(
        self, event: AiocqhttpMessageEvent, target_card: str | int | None = None
    ):
        """改名 xxx @user"""
        target_card = str(target_card) if target_card else ""
        tids = get_ats(event) or [event.get_sender_id()]
        for tid in tids:
            target_name = await get_nickname(event, user_id=tid)
            msg = (
                f"已修改{target_name}的群昵称为【{target_card}】"
                if target_card
                else f"已清除{target_name}的群昵称"
            )
            await event.send(event.plain_result(msg))
            await event.bot.set_group_card(
                group_id=int(event.get_group_id()),
                user_id=int(tid),
                card=str(target_card),
            )

    async def set_group_card_me(
        self, event: AiocqhttpMessageEvent, target_card: str | int | None = None
    ):
        """改我 xxx"""
        target_card = str(target_card) if target_card else ""
        msg = (
            f"已修改你的群昵称为【{target_card}】"
            if target_card
            else "已清除你的群昵称"
        )
        await event.send(event.plain_result(msg))
        await event.bot.set_group_card(
            group_id=int(event.get_group_id()),
            user_id=int(event.get_sender_id()),
            card=str(target_card),
        )

    async def set_group_special_title(
        self, event: AiocqhttpMessageEvent, new_title: str | int | None = None
    ):
        """头衔 xxx @user"""
        new_title = str(new_title) if new_title else ""
        tids = get_ats(event) or [event.get_sender_id()]
        for tid in tids:
            target_name = await get_nickname(event, user_id=tid)
            msg = (
                f"已修改{target_name}的头衔为【{new_title}】"
                if new_title
                else f"已清除{target_name}的头衔"
            )
            await event.send(event.plain_result(msg))
            await event.bot.set_group_special_title(
                group_id=int(event.get_group_id()),
                user_id=int(tid),
                special_title=new_title,
                duration=-1,
            )

    async def set_group_special_title_me(
        self, event: AiocqhttpMessageEvent, new_title: str | int | None = None
    ):
        """申请头衔 xxx"""
        new_title = str(new_title) if new_title else ""
        msg = f"已将你的头衔改为【{new_title}】" if new_title else "已清除你的头衔"
        await event.send(event.plain_result(msg))
        await event.bot.set_group_special_title(
            group_id=int(event.get_group_id()),
            user_id=int(event.get_sender_id()),
            special_title=new_title,
            duration=-1,
        )

    async def set_group_kick(self, event: AiocqhttpMessageEvent):
        """踢了@user"""
        for tid in get_ats(event):
            target_name = await get_nickname(event, user_id=tid)
            await event.bot.set_group_kick(
                group_id=int(event.get_group_id()),
                user_id=int(tid),
                reject_add_request=False,
            )
            await event.send(event.plain_result(f"已将【{tid}-{target_name}】踢出本群"))

    async def set_group_block(self, event: AiocqhttpMessageEvent):
        """拉黑 @user"""
        for tid in get_ats(event):
            target_name = await get_nickname(event, user_id=tid)
            await event.bot.set_group_kick(
                group_id=int(event.get_group_id()),
                user_id=int(tid),
                reject_add_request=True,
            )
            await event.send(
                event.plain_result(f"已将【{tid}-{target_name}】踢出本群并拉黑!")
            )

    async def set_group_admin(self, event: AiocqhttpMessageEvent):
        """设置管理员@user"""
        for tid in get_ats(event):
            await event.bot.set_group_admin(
                group_id=int(event.get_group_id()), user_id=int(tid), enable=True
            )
            chain = [At(qq=tid), Plain(text="你已被设为管理员")]
            await event.send(event.chain_result(chain))

    async def cancel_group_admin(self, event: AiocqhttpMessageEvent):
        """取消管理员@user"""
        for tid in get_ats(event):
            await event.bot.set_group_admin(
                group_id=int(event.get_group_id()), user_id=int(tid), enable=False
            )
            chain = [At(qq=tid), Plain(text="你的管理员身份已被取消")]
            await event.send(event.chain_result(chain))

    async def set_essence_msg(self, event: AiocqhttpMessageEvent):
        """将引用消息添加到群精华"""
        first_seg = event.get_messages()[0]
        if isinstance(first_seg, Reply):
            await event.bot.set_essence_msg(message_id=int(first_seg.id))
            await event.send(event.plain_result("已设为精华消息"))
            event.stop_event()

    async def delete_essence_msg(self, event: AiocqhttpMessageEvent):
        """将引用消息移出群精华"""
        first_seg = event.get_messages()[0]
        if isinstance(first_seg, Reply):
            await event.bot.delete_essence_msg(message_id=int(first_seg.id))
            await event.send(event.plain_result("已移除精华消息"))
            event.stop_event()

    async def get_essence_msg_list(self, event: AiocqhttpMessageEvent):
        """查看群精华"""
        essence_data = await event.bot.get_essence_msg_list(
            group_id=int(event.get_group_id())
        )
        await event.send(event.plain_result(f"{essence_data}"))
        event.stop_event()
        # TODO 做张好看的图片来展示

    async def set_group_portrait(self, event: AiocqhttpMessageEvent):
        """(引用图片)设置群头像"""
        image_url = extract_image_url(chain=event.get_messages())
        if not image_url:
            await event.send(event.plain_result("未获取到新头像"))
            return
        await event.bot.set_group_portrait(
            group_id=int(event.get_group_id()),
            file=image_url,
        )
        await event.send(event.plain_result("群头像更新啦>v<"))

    async def set_group_name(
        self, event: AiocqhttpMessageEvent, group_name: str | int | None = None
    ):
        """设置群名 xxx"""
        if not group_name:
            await event.send(event.plain_result("未输入新群名"))
            return
        await event.bot.set_group_name(
            group_id=int(event.get_group_id()), group_name=str(group_name)
        )
        await event.send(event.plain_result(f"本群群名更新为：{group_name}"))

    async def delete_msg(self, event: AiocqhttpMessageEvent):
        """(引用消息)撤回 | 撤回 @某人(默认bot) 数量(默认10)"""
        client = event.bot
        chain = event.get_messages()
        first_seg = chain[0]
        if isinstance(first_seg, Reply):
            try:
                await client.delete_msg(message_id=int(first_seg.id))
            except Exception:
                await event.send(event.plain_result("我无权撤回这条消息"))
            finally:
                event.stop_event()
        elif any(isinstance(seg, At) for seg in chain):
            target_ids = get_ats(event) or [event.get_self_id()]
            target_ids = {str(uid) for uid in target_ids}

            end_arg = event.message_str.split()[-1]
            count = int(end_arg) if end_arg.isdigit() else 10

            payloads = {
                "group_id": int(event.get_group_id()),
                "message_seq": 0,
                "count": count,
                "reverseOrder": True,
            }
            result: dict = await client.api.call_action(
                "get_group_msg_history", **payloads
            )

            messages = list(reversed(result.get("messages", [])))
            delete_count = 0
            sem = asyncio.Semaphore(10)

            # 撤回消息
            async def try_delete(message: dict):
                nonlocal delete_count
                if str(message["sender"]["user_id"]) not in target_ids:
                    return
                async with sem:
                    try:
                        await client.delete_msg(message_id=message["message_id"])
                        delete_count += 1
                    except Exception:
                        pass

            # 并发撤回
            tasks = [try_delete(msg) for msg in messages]
            await asyncio.gather(*tasks)

            await event.send(
                event.plain_result(f"已从{count}条消息中撤回{delete_count}条")
            )
