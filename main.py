import asyncio
import random

from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.event_message_type import EventMessageType

from .core import (
    CurfewHandle,
    EnhanceHandle,
    FileHandle,
    JoinHandle,
    LLMHandle,
    MemberHandle,
    NormalHandle,
    NoticeHandle,
)
from .permission import (
    PermissionManager,
    PermLevel,
    perm_required,
)
from .utils import ADMIN_HELP, print_logo


@register("astrbot_plugin_qqadmin", "Zhalslar", "...", "...")
class QQAdminPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.conf = config
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_qqadmin")
        self.admins_id: list[str] = context.get_config().get("admins_id", [])

    async def initialize(self):
        # 实例化各个处理类
        self.normal = NormalHandle(self.conf)
        self.notice = NoticeHandle(self, self.plugin_data_dir)
        self.enhance = EnhanceHandle(self.conf)
        self.join = JoinHandle(self.conf, self.plugin_data_dir, self.admins_id)
        self.member = MemberHandle(self)
        self.file = FileHandle(self.plugin_data_dir)
        self.curfew = CurfewHandle(self.context, self.plugin_data_dir)
        self.llm = LLMHandle(self.context, self.conf)
        asyncio.create_task(self.curfew.initialize())

        # 初始化权限管理器
        PermissionManager.get_instance(
            superusers=self.admins_id,
            perms=self.conf["perms"],
            level_threshold=self.conf["level_threshold"],
        )
        # 概率打印LOGO（qwq）
        if random.random() < 0.01:
            print_logo()

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        """平台加载完成时"""
        if not self.curfew.curfew_managers:
            asyncio.create_task(self.curfew.initialize())

    @filter.command("禁言", desc="禁言 <秒数> @群友")
    @perm_required(PermLevel.ADMIN)
    async def set_group_ban(self, event: AiocqhttpMessageEvent, ban_time=None):
        await self.normal.set_group_ban(event, ban_time)

    @filter.command("禁我", desc="禁我 <秒数>")
    @perm_required(PermLevel.ADMIN)
    async def set_group_ban_me(
        self, event: AiocqhttpMessageEvent, ban_time: int | None = None
    ):
        await self.normal.set_group_ban_me(event, ban_time)

    @filter.command("解禁", desc="解禁 @群友")
    @perm_required(PermLevel.ADMIN)
    async def cancel_group_ban(self, event: AiocqhttpMessageEvent):
        await self.normal.cancel_group_ban(event)

    @filter.command("开启全禁", alias={"全员禁言", "开启全员禁言"})
    @perm_required(PermLevel.ADMIN)
    async def set_group_whole_ban(self, event: AiocqhttpMessageEvent):
        await self.normal.set_group_whole_ban(event)

    @filter.command("关闭全禁", alias={"关闭全禁", "关闭全员禁言"})
    @perm_required(PermLevel.ADMIN)
    async def cancel_group_whole_ban(self, event: AiocqhttpMessageEvent):
        await self.normal.cancel_group_whole_ban(event)

    @filter.command("改名", desc="改名 xxx @user")
    @perm_required(PermLevel.ADMIN)
    async def set_group_card(
        self, event: AiocqhttpMessageEvent, target_card: str | int | None = None
    ):
        """改名 xxx @user"""
        await self.normal.set_group_card(event, target_card)

    @filter.command("改我", desc="改我 xxx")
    @perm_required(PermLevel.ADMIN)
    async def set_group_card_me(
        self, event: AiocqhttpMessageEvent, target_card: str | int | None = None
    ):
        await self.normal.set_group_card_me(event, target_card)

    @filter.command("头衔", desc="改头衔 xxx @群友")
    @perm_required(PermLevel.OWNER)
    async def set_group_special_title(
        self, event: AiocqhttpMessageEvent, new_title: str | int | None = None
    ):
        await self.normal.set_group_special_title(event, new_title)

    @filter.command("申请头衔", desc="申请头衔 xxx", alias={"我要头衔"})
    @perm_required(PermLevel.OWNER)
    async def set_group_special_title_me(
        self, event: AiocqhttpMessageEvent, new_title: str | int | None = None
    ):
        await self.normal.set_group_special_title(event, new_title)

    @filter.command("踢了", desc="踢了@群友")
    @perm_required(PermLevel.ADMIN)
    async def set_group_kick(self, event: AiocqhttpMessageEvent):
        await self.normal.set_group_kick(event)

    @filter.command("拉黑", desc="拉黑@群友")
    @perm_required(PermLevel.ADMIN)
    async def set_group_block(self, event: AiocqhttpMessageEvent):
        await self.normal.set_group_block(event)

    @filter.command(
        "上管", alias={"设置管理员", "添加管理员", "设为管理员"}, desc="上管@群友"
    )
    @perm_required(PermLevel.OWNER, check_at=False)
    async def set_group_admin(self, event: AiocqhttpMessageEvent):
        await self.normal.set_group_admin(event)

    @filter.command("下管", alias={"取消管理员"}, desc="下管@群友")
    @perm_required(PermLevel.OWNER)
    async def cancel_group_admin(self, event: AiocqhttpMessageEvent):
        await self.normal.cancel_group_admin(event)

    @filter.command("设精", desc="(引用消息)设精", alias={"设为精华"})
    @perm_required(PermLevel.ADMIN)
    async def set_essence_msg(self, event: AiocqhttpMessageEvent):
        await self.normal.set_essence_msg(event)

    @filter.command("移精", desc="(引用消息)移精", alias={"移除精华"})
    @perm_required(PermLevel.ADMIN)
    async def delete_essence_msg(self, event: AiocqhttpMessageEvent):
        await self.normal.delete_essence_msg(event)

    @filter.command("查看精华", alias={"群精华"})
    @perm_required(PermLevel.ADMIN)
    async def get_essence_msg_list(self, event: AiocqhttpMessageEvent):
        await self.normal.get_essence_msg_list(event)

    @filter.command("设置群头像", desc="(引用图片)设置群头像")
    @perm_required(PermLevel.ADMIN)
    async def set_group_portrait(self, event: AiocqhttpMessageEvent):
        await self.normal.set_group_portrait(event)

    @filter.command("设置群名", desc="设置群名 xxx")
    @perm_required(PermLevel.ADMIN)
    async def set_group_name(
        self, event: AiocqhttpMessageEvent, group_name: str | int | None = None
    ):
        await self.normal.set_group_name(event, group_name)

    @filter.command("撤回", desc="(引用消息)撤回 | 撤回 @某人(默认bot) 数量(默认10)")
    @perm_required(PermLevel.MEMBER)
    async def delete_msg(self, event: AiocqhttpMessageEvent):
        await self.normal.delete_msg(event)

    @filter.command("发布群公告", desc="(引用图片)发布群公告 xxx")
    @perm_required(PermLevel.ADMIN)
    async def send_group_notice(self, event: AiocqhttpMessageEvent):
        await self.notice.send_group_notice(event)

    @filter.command("查看群公告")
    @perm_required(PermLevel.MEMBER)
    async def get_group_notice(self, event: AiocqhttpMessageEvent):
        await self.notice.get_group_notice(event)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def check_forbidden_words(self, event: AiocqhttpMessageEvent):
        """自动检测违禁词，撤回并禁言"""
        await self.enhance.check_forbidden_words(event)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def spamming_ban(self, event: AiocqhttpMessageEvent):
        """刷屏检测与禁言"""
        await self.enhance.spamming_ban(event)

    @filter.command("投票禁言", desc="投票禁言 <秒数> @群友")
    @perm_required(PermLevel.ADMIN)
    async def start_vote_mute(
        self, event: AiocqhttpMessageEvent, ban_time: int | None = None
    ):
        await self.enhance.start_vote_mute(event, ban_time)

    @filter.command("赞同禁言", desc="同意执行当前禁言投票")
    @perm_required(PermLevel.ADMIN)
    async def agree_vote_mute(self, event: AiocqhttpMessageEvent):
        await self.enhance.vote_mute(event, agree=True)

    @filter.command("反对禁言", desc="反对执行当前禁言投票")
    @perm_required(PermLevel.ADMIN)
    async def disagree_vote_mute(self, event: AiocqhttpMessageEvent):
        await self.enhance.vote_mute(event, agree=False)

    @filter.command("开启宵禁", desc="开启宵禁 HH:MM HH:MM")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @perm_required(PermLevel.ADMIN)
    async def start_curfew(
        self,
        event: AiocqhttpMessageEvent,
        start_time: str | None = None,
        end_time: str | None = None,
    ):
        await self.curfew.start_curfew(event, start_time, end_time)

    @filter.command("关闭宵禁", desc="关闭本群的宵禁任务")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @perm_required(PermLevel.ADMIN)
    async def stop_curfew(self, event: AiocqhttpMessageEvent):
        await self.curfew.stop_curfew(event)

    @filter.command("进群审核", desc="进群审核 开/关，所有进群审核功能的总开关")
    @perm_required(PermLevel.ADMIN)
    async def handle_join_review(
        self, event: AiocqhttpMessageEvent, mode: str | bool | None = None
    ):
        await self.join.handle_join_review(event, mode)

    @filter.command("进群白词")
    @perm_required(PermLevel.ADMIN)
    async def handle_accept_keyword(self, event: AiocqhttpMessageEvent):
        "设置/查看自动批准进群的关键词（空格隔开，无参数表示查看）"
        await self.join.handle_accept_keyword(event)

    @filter.command("进群黑词")
    @perm_required(PermLevel.ADMIN)
    async def handle_reject_keywords(self, event: AiocqhttpMessageEvent):
        "设置/查看进群黑名单关键词（空格隔开，无参数表示查看）"
        await self.join.handle_reject_keywords(event)

    @filter.command("进群等级")
    @perm_required(PermLevel.ADMIN)
    async def handle_level_threshold(
        self, event: AiocqhttpMessageEvent, level: int | None = None
    ):
        "设置/查看本群进群等级门槛，（0表示不限制，无参数表示查看）"
        await self.join.handle_level_threshold(event, level)

    @filter.command("进群次数")
    @perm_required(PermLevel.ADMIN)
    async def handle_join_time(
        self, event: AiocqhttpMessageEvent, time: int | None = None
    ):
        "设置/查看未命中进群关键词多少次后拉黑（0表示不限制，无参数表示查看）"
        await self.join.handle_join_time(event, time)

    @filter.command("进群黑名单", desc="查看进群黑名单", alias={"进群黑名单"})
    @perm_required(PermLevel.ADMIN)
    async def handle_reject_ids(self, event: AiocqhttpMessageEvent):
        "进群黑名单 <None/id/+id/-id>"
        await self.join.handle_block_ids(event)

    @filter.command("批准", alias={"同意进群"}, desc="批准进群申请")
    @perm_required(PermLevel.ADMIN)
    async def agree_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        await self.join.agree_add_group(event, extra)

    @filter.command("驳回", alias={"拒绝进群", "不批准"}, desc="驳回进群申请")
    @perm_required(PermLevel.ADMIN)
    async def refuse_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        await self.join.refuse_add_group(event, extra)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def event_monitoring(self, event: AiocqhttpMessageEvent):
        """监听进群/退群事件"""
        await self.join.event_monitoring(event)

    @filter.command("群友信息", desc="查看群友信息")
    @perm_required(PermLevel.MEMBER)
    async def get_group_member_list(self, event: AiocqhttpMessageEvent):
        await self.member.get_group_member_list(event)

    @filter.command("清理群友", desc="清理群友 未发言天数 群等级")
    @perm_required(PermLevel.MEMBER)
    async def clear_group_member(
        self,
        event: AiocqhttpMessageEvent,
        inactive_days: int = 30,
        under_level: int = 10,
    ):
        await self.member.clear_group_member(event, inactive_days, under_level)

    @filter.command("上传群文件", desc="上传群文件 <文件夹名/文件名 | 文件名>")
    @perm_required(PermLevel.ADMIN)
    async def upload_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str | int | None = None,
    ):
        await self.file.upload_group_file(event, str(path))

    @filter.command("删除群文件", desc="删除群文件 <文件夹名/序号> <文件名/序号>")
    @perm_required(PermLevel.ADMIN)
    async def delete_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str | int | None = None,
    ):
        await self.file.delete_group_file(event, str(path))

    @filter.command("查看群文件", desc="查看群文件 <文件夹名/序号> <文件名/序号>")
    @perm_required(PermLevel.MEMBER)
    async def view_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str | int | None = None,
    ):
        async for r in self.file.view_group_file(event, path):
            yield r

    @filter.command("取名", desc="取名@群友", alias={"取昵称"})
    @perm_required(PermLevel.ADMIN, check_at=False)
    async def ai_set_card(self, event: AiocqhttpMessageEvent):
        await self.llm.ai_set_card(event)

    @filter.llm_tool()  # type: ignore
    async def llm_set_group_ban(
        self, event: AiocqhttpMessageEvent, user_id: str, duration: int
    ):
        """
        在群聊中禁言某用户。被禁言的用户在禁言期间将无法发送消息。
        Args:
            user_id(string): 要禁言的用户的QQ账号，必定为一串数字，如(12345678)
            duration(number): 禁言持续时间（以秒为单位），范围为30~86400。
        """
        try:
            await event.bot.set_group_ban(
                group_id=int(event.get_group_id()),
                user_id=int(user_id),
                duration=duration,
            )
            logger.info(
                f"用户：{user_id}在群聊中被：{event.get_sender_name()}执行禁言{duration}秒"
            )
            event.stop_event()
            yield
        except Exception as e:
            logger.error(f"禁言用户 {user_id} 失败: {e}")
            yield

    @filter.command("群管帮助")
    async def qq_admin_help(self, event: AiocqhttpMessageEvent):
        """查看群管帮助"""
        url = await self.text_to_image(ADMIN_HELP)
        yield event.image_result(url)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        await self.curfew.stop_all_tasks()
        logger.info("插件 astrbot_plugin_QQAdmin 已优雅关闭")
