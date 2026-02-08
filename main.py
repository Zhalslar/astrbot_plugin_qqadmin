import asyncio
import random
import re
from pathlib import Path

from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star, StarTools
from astrbot.core import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.event_message_type import EventMessageType

from .core import (
    BanproHandle,
    CurfewHandle,
    FileHandle,
    JoinHandle,
    LLMHandle,
    MemberHandle,
    NormalHandle,
    NoticeHandle,
)
from .data import QQAdminDB
from .permission import (
    PermissionManager,
    PermLevel,
    perm_required,
)
from .utils import ADMIN_HELP, print_logo


class QQAdminPlugin(Star):
    DB_VERSION = 3

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.conf = config
        self.admins_id: list[str] = context.get_config().get("admins_id", [])
        self.plugin_data_dir = StarTools.get_data_dir("astrbot_plugin_qqadmin")
        self.db_path = self.plugin_data_dir / f"qqadmin_data_v{self.DB_VERSION}.db"
        self.ban_lexicon_path = Path(
            "data/plugins/astrbot_plugin_qqadmin/SensitiveLexicon.json"
        )
        self.divided_manage = config["divided_manage"]

    async def initialize(self):
        # 数据库
        self.db = QQAdminDB(self.conf, self.db_path)
        await self.db.init()
        if not self.divided_manage:
            await self.db.reset_to_default()
        # 实例化各个处理类
        self.normal = NormalHandle(self.conf)
        self.notice = NoticeHandle(self, self.plugin_data_dir)
        self.banpro = BanproHandle(self.conf, self.db, self.ban_lexicon_path)
        self.join = JoinHandle(self.conf, self.db, self.admins_id)
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
    @perm_required(PermLevel.ADMIN, perm_key="whole_ban")
    async def set_group_whole_ban(self, event: AiocqhttpMessageEvent):
        await self.normal.set_group_whole_ban(event)

    @filter.command("关闭全禁", alias={"关闭全禁", "关闭全员禁言"})
    @perm_required(PermLevel.ADMIN, perm_key="whole_ban")
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

    @filter.command("上管", alias={"设置管理员"}, desc="上管@群友")
    @perm_required(PermLevel.OWNER, perm_key="admin", check_at=False)
    async def set_group_admin(self, event: AiocqhttpMessageEvent):
        await self.normal.set_group_admin(event)

    @filter.command("下管", alias={"取消管理员"}, desc="下管@群友")
    @perm_required(PermLevel.OWNER, perm_key="admin", check_at=False)
    async def cancel_group_admin(self, event: AiocqhttpMessageEvent):
        await self.normal.cancel_group_admin(event)

    @filter.command("设精", desc="(引用消息)设精", alias={"设为精华"})
    @perm_required(PermLevel.ADMIN, perm_key="essence")
    async def set_essence_msg(self, event: AiocqhttpMessageEvent):
        await self.normal.set_essence_msg(event)

    @filter.command("移精", desc="(引用消息)移精", alias={"移除精华"})
    @perm_required(PermLevel.ADMIN, perm_key="essence")
    async def delete_essence_msg(self, event: AiocqhttpMessageEvent):
        await self.normal.delete_essence_msg(event)

    @filter.command("查看群精华", alias={"群精华"})
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

    @filter.command("撤回")
    @perm_required(PermLevel.MEMBER)
    async def delete_msg(self, event: AiocqhttpMessageEvent):
        "(引用消息)撤回 | 撤回 <@群友> <消息数量>"
        await self.normal.delete_msg(event)

    @filter.command("发布群公告", desc="(引用图片)发布群公告 xxx")
    @perm_required(PermLevel.ADMIN)
    async def send_group_notice(self, event: AiocqhttpMessageEvent):
        await self.notice.send_group_notice(event)

    @filter.command("查看群公告")
    @perm_required(PermLevel.MEMBER)
    async def get_group_notice(self, event: AiocqhttpMessageEvent):
        await self.notice.get_group_notice(event)

    @filter.command("禁词禁言")
    @perm_required(PermLevel.ADMIN, perm_key="word_ban")
    async def handle_word_ban_time(
        self, event: AiocqhttpMessageEvent, time: int | None = None
    ):
        """禁词禁言 <秒数>, 设为 0 表示关闭禁词检测"""
        await self.banpro.handle_word_ban_time(event, time)

    @filter.command("设置禁词", alias={"禁词", "违禁词"})
    @perm_required(PermLevel.ADMIN, perm_key="word_ban")
    async def handle_builtin_ban_words(self, event: AiocqhttpMessageEvent):
        """禁词 +词1 -词2, 带+-则增删, 不带则覆写"""
        await self.banpro.handle_ban_words(event)

    @filter.command("内置禁词")
    @perm_required(PermLevel.ADMIN, perm_key="word_ban")
    async def handle_ban_words(
        self, event: AiocqhttpMessageEvent, mode: str | bool | None = None
    ):
        """内置禁词 开/关"""
        await self.banpro.handle_builtin_ban_words(event, mode)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    async def on_ban_words(self, event: AiocqhttpMessageEvent):
        """自动检测违禁词，撤回并禁言"""
        if not event.is_admin():
            await self.banpro.on_ban_words(event)

    @filter.command("刷屏禁言")
    @perm_required(PermLevel.ADMIN, perm_key="spamming")
    async def handle_spamming_ban_time(
        self, event: AiocqhttpMessageEvent, time: int | None = None
    ):
        """刷屏禁言 <秒数>, 设为 0 表示关闭禁词检测"""
        await self.banpro.handle_spamming_ban_time(event, time)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def spamming_ban(self, event: AiocqhttpMessageEvent):
        """刷屏检测与禁言"""
        await self.banpro.spamming_ban(event)

    @filter.command("投票禁言", desc="投票禁言 <秒数> @群友")
    @perm_required(PermLevel.ADMIN, perm_key="vote")
    async def start_vote_mute(
        self, event: AiocqhttpMessageEvent, ban_time: int | None = None
    ):
        await self.banpro.start_vote_mute(event, ban_time)

    @filter.command("赞同禁言", desc="同意执行当前禁言投票")
    @perm_required(PermLevel.ADMIN, perm_key="vote")
    async def agree_vote_mute(self, event: AiocqhttpMessageEvent):
        await self.banpro.vote_mute(event, agree=True)

    @filter.command("反对禁言", desc="反对执行当前禁言投票")
    @perm_required(PermLevel.ADMIN, perm_key="vote")
    async def disagree_vote_mute(self, event: AiocqhttpMessageEvent):
        await self.banpro.vote_mute(event, agree=False)

    @filter.command("开启宵禁", desc="开启宵禁 HH:MM HH:MM")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @perm_required(PermLevel.ADMIN, perm_key="curfew")
    async def start_curfew(
        self,
        event: AiocqhttpMessageEvent,
        start_time: str | None = None,
        end_time: str | None = None,
    ):
        await self.curfew.start_curfew(event, start_time, end_time)

    @filter.command("关闭宵禁", desc="关闭本群的宵禁任务")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @perm_required(PermLevel.ADMIN, perm_key="curfew")
    async def stop_curfew(self, event: AiocqhttpMessageEvent):
        await self.curfew.stop_curfew(event)

    @filter.command("进群审核")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_join_review(
        self, event: AiocqhttpMessageEvent, mode: str | bool | None = None
    ):
        "进群审核 开/关，所有进群审核功能的总开关"
        await self.join.handle_join_review(event, mode)

    @filter.command("进群白词", perm_key="join")
    @perm_required(PermLevel.ADMIN)
    async def handle_accept_words(self, event: AiocqhttpMessageEvent):
        "设置/查看自动批准进群的关键词（空格隔开，无参数表示查看）"
        await self.join.handle_accept_words(event)

    @filter.command("进群黑词", perm_key="join")
    @perm_required(PermLevel.ADMIN)
    async def handle_reject_words(self, event: AiocqhttpMessageEvent):
        "设置/查看进群黑名单关键词（空格隔开，无参数表示查看）"
        await self.join.handle_reject_words(event)

    @filter.command("未命中驳回", desc="未命中白词自动驳回 开/关")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_no_match_reject(
        self, event: AiocqhttpMessageEvent, mode: str | bool | None = None
    ):
        "设置/查看是否拒绝无关键词的进群申请（无参数表示查看）"
        await self.join.handle_no_match_reject(event, mode)

    @filter.command("进群等级")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_join_min_level(
        self, event: AiocqhttpMessageEvent, level: int | None = None
    ):
        "设置/查看本群进群等级门槛，（0表示不限制，无参数表示查看）"
        await self.join.handle_join_min_level(event, level)

    @filter.command("进群次数")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_join_max_time(
        self, event: AiocqhttpMessageEvent, time: int | None = None
    ):
        "设置/查看未命中进群关键词多少次后拉黑（0表示不限制，无参数表示查看）"
        await self.join.handle_join_max_time(event, time)

    @filter.command("进群黑名单")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_reject_ids(self, event: AiocqhttpMessageEvent):
        "进群黑名单 +QQ -QQ, 带+-则增删, 不带则覆写"
        await self.join.handle_block_ids(event)

    @filter.command("批准", alias={"同意进群"}, desc="批准进群申请")
    @perm_required(PermLevel.ADMIN, perm_key="approve")
    async def agree_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        await self.join.agree_add_group(event, extra)

    @filter.command("驳回", alias={"拒绝进群", "不批准"}, desc="驳回进群申请")
    @perm_required(PermLevel.ADMIN, perm_key="approve")
    async def refuse_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        await self.join.refuse_add_group(event, extra)

    @filter.command("进群禁言")
    @perm_required(PermLevel.ADMIN, perm_key="welcome")
    async def handle_join_ban(
        self, event: AiocqhttpMessageEvent, time: int | None = None
    ):
        "进群禁言 <秒数>，设为 0 表示本群不启用该功能"
        await self.join.handle_join_ban(event, time)

    @filter.command("进群欢迎")
    @perm_required(PermLevel.MEMBER, perm_key="welcome")
    async def handle_join_welcome(self, event: AiocqhttpMessageEvent):
        await self.join.handle_join_welcome(event)

    @filter.command("退群通知")
    @perm_required(PermLevel.MEMBER, perm_key="leave")
    async def handle_leave_notify(
        self, event: AiocqhttpMessageEvent, mode: str | bool | None = None
    ):
        """退群通知 开/关"""
        await self.join.handle_leave_notify(event, mode)

    @filter.command("退群拉黑")
    @perm_required(PermLevel.ADMIN, perm_key="leave")
    async def handle_leave_block(
        self, event: AiocqhttpMessageEvent, mode: str | bool | None = None
    ):
        "退群拉黑 开/关, 拉黑后下次进群直接自动拒绝"
        await self.join.handle_leave_block(event, mode)

    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def event_monitoring(self, event: AiocqhttpMessageEvent):
        """监听进群/退群事件"""
        await self.join.event_monitoring(event)

    @filter.command("群友信息", desc="查看群友信息")
    @perm_required(PermLevel.MEMBER)
    async def get_group_member_list(self, event: AiocqhttpMessageEvent):
        await self.member.get_group_member_list(event)

    @filter.command("清理群友")
    @perm_required(PermLevel.MEMBER)
    async def clear_group_member(
        self,
        event: AiocqhttpMessageEvent,
        inactive_days: int = 30,
        under_level: int = 10,
    ):
        "清理群友 <未发言天数> <群等级>"
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

    @filter.command("取名")
    @perm_required(
        PermLevel.MEMBER, check_at=False
    )  # 仅要求Bot为成员，实际权限不足时忽略接口报错
    async def ai_set_card(self, event: AiocqhttpMessageEvent):
        """取名@群友 <消息轮数>"""
        await self.llm.ai_set_card(event)

    @filter.command("取头衔")
    @perm_required(
        PermLevel.MEMBER, check_at=False
    )  # 仅要求Bot为成员，实际权限不足时忽略接口报错
    async def ai_set_title(self, event: AiocqhttpMessageEvent):
        """取名@群友 <消息轮数>"""
        await self.llm.ai_set_title(event)

    @filter.llm_tool()  # type: ignore
    async def llm_set_group_ban(
        self, event: AiocqhttpMessageEvent, user_id: str, duration: int
    ):
        """
        在群聊中禁言某用户。被禁言的用户在禁言期间将无法发送消息。
        Args:
            user_id(string): 要禁言的用户的QQ账号，必定为一串数字，如(12345678)
            duration(number): 禁言持续时间（秒），范围为0~86400, 0表示取消禁言
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

    @filter.command("群管配置", alias={"群管设置"})
    @perm_required(PermLevel.MEMBER, check_at=False)
    async def set_config(self, event: AiocqhttpMessageEvent):
        """群管配置 <群号 | 留空> <配置串>"""
        raw: str = event.message_str.partition(" ")[2].strip()
        if not raw:  # 空串，仅查询
            gid = event.get_group_id()
            config_str = await self.db.export_cn_lines(gid)
            yield event.plain_result(f"【群管配置】\n{config_str}")
            return

        # 正则：^(\d+)\s+(.+)  捕获“数字 + 空格 + 剩余串”
        m = re.match(r"(\d+)\s+(.+)", raw)
        if m:
            gid = str(m.group(1))
            arg = m.group(2)
        else:
            gid = event.get_group_id()
            arg = raw

        # 更新配置
        await self.db.import_cn_lines(gid, arg)
        config_str = await self.db.export_cn_lines(gid)
        yield event.plain_result(f"【群管配置】更新:\n{config_str}")

    @filter.command("群管重置")
    @perm_required(PermLevel.MEMBER, check_at=False)
    async def reset_config(
        self, event: AiocqhttpMessageEvent, group_id: str | int | None = None
    ):
        """群管重置 <群号 | all>"""
        gid = group_id or event.get_group_id()
        if gid == "all" and event.is_admin():
            await self.db.reset_to_default()
            yield event.plain_result("已重置所有群的群管配置")
        else:
            await self.db.reset_to_default(str(gid))
            yield event.plain_result("已重置本群的群管配置")

    @filter.command("群管帮助")
    async def qq_admin_help(self, event: AiocqhttpMessageEvent):
        """查看群管帮助"""
        url = await self.text_to_image(ADMIN_HELP)
        yield event.image_result(url)

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        await self.curfew.stop_all_tasks()
        await self.db.close()
        logger.info("插件 astrbot_plugin_QQAdmin 已优雅关闭")
