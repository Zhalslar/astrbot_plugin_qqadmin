import asyncio
import re

from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core import AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.event_message_type import EventMessageType

from .config import PluginConfig
from .core import (
    BanproHandle,
    CurfewHandle,
    FileHandle,
    JoinHandle,
    MemberHandle,
    MentionRoleHandle,
    NormalHandle,
    NoticeHandle,
    RecallHandle,
)
from .data import QQAdminDB
from .group_info_cache import QQGroupInfoCache
from .permission import (
    PermLevel,
    perm_manager,
    perm_required,
)
from .utils import parse_bool
from .web import QQAdminWebController


class QQAdminPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.cfg = PluginConfig(config, context)
        self.db = QQAdminDB(self.cfg)
        self.db.default_cfg = self.cfg.build_group_default_config()
        self.group_cache = QQGroupInfoCache(context, self.db)
        self.normal = NormalHandle(self.cfg, self.db)
        self.recall = RecallHandle(self.cfg, self.db)
        self.notice = NoticeHandle(self, self.cfg)
        self.banpro = BanproHandle(self.cfg, self.db)
        self.join = JoinHandle(self.cfg, self.db)
        self.member = MemberHandle(self)
        self.mention_role = MentionRoleHandle(self.db)
        self.file = FileHandle(self.cfg)
        self.curfew = CurfewHandle(self.context, self.cfg)
        self.web = QQAdminWebController(context, self.cfg, self.db, self.group_cache)
        self.web.register_routes()

    async def initialize(self):
        await self.db.init()
        asyncio.create_task(self.curfew.initialize())
        perm_manager.lazy_init(self.cfg, self.db)

    async def terminate(self):
        await self.curfew.stop_all_tasks()
        await self.db.close()

    @filter.on_platform_loaded()
    async def on_platform_loaded(self):
        """平台加载完成时"""
        if not self.curfew.curfew_managers:
            asyncio.create_task(self.curfew.initialize())

    @filter.command("群管配置", alias={"群管设置"})
    @perm_required(PermLevel.MEMBER, check_at=False)
    async def set_config(self, event: AiocqhttpMessageEvent):
        """群管配置 <群号 | 留空> <配置串>"""
        raw: str = event.message_str.partition(" ")[2].strip()
        if not raw:
            gid = event.get_group_id()
            config_str = await self.db.export_cn_lines(gid)
            yield event.plain_result(f"【群管配置】\n{config_str}")
            return
        m = re.match(r"(\d+)\s+(.+)", raw)
        if m:
            gid = str(m.group(1))
            arg = m.group(2)
        else:
            gid = event.get_group_id()
            arg = raw
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

    @filter.command("身份组创建")
    @perm_required(PermLevel.ADMIN, perm_key="mention_role_manage", check_at=False)
    async def create_mention_role(
        self, event: AiocqhttpMessageEvent, role_name: str | int = ""
    ):
        """身份组创建 <组名>"""
        if result := await self.mention_role.create_role(event, role_name):
            yield event.plain_result(result)

    @filter.command("身份组删除", alias={"身份组删组"})
    @perm_required(PermLevel.ADMIN, perm_key="mention_role_manage", check_at=False)
    async def delete_mention_role(
        self, event: AiocqhttpMessageEvent, role_name: str | int = ""
    ):
        """身份组删除 <组名>"""
        if result := await self.mention_role.delete_role(event, role_name):
            yield event.plain_result(result)

    @filter.command("身份组加")
    @perm_required(PermLevel.ADMIN, perm_key="mention_role_manage", check_at=False)
    async def add_mention_role_members(self, event: AiocqhttpMessageEvent):
        """身份组加 <组名> @群友..."""
        if result := await self.mention_role.add_members(event):
            yield event.plain_result(result)

    @filter.command("身份组删")
    @perm_required(PermLevel.ADMIN, perm_key="mention_role_manage", check_at=False)
    async def remove_mention_role_members(self, event: AiocqhttpMessageEvent):
        """身份组删 <组名> @群友..."""
        if result := await self.mention_role.remove_members(event):
            yield event.plain_result(result)

    @filter.command("身份组列表", alias={"身份组"})
    @perm_required(PermLevel.MEMBER, perm_key="mention_role_list", check_at=False)
    async def list_mention_roles(
        self, event: AiocqhttpMessageEvent, role_name: str | int = ""
    ):
        """身份组列表 <组名 | 留空>"""
        if result := await self.mention_role.list_roles(event, role_name):
            yield event.plain_result(result)

    @filter.command("呼叫", alias={"召唤", "呼叫身份组"})
    async def call_mention_role(self, event: AiocqhttpMessageEvent):
        """呼叫 <组名> <附加消息>"""
        if event.platform_meta.name != "aiocqhttp" or event.is_private_chat():
            return
        if not perm_manager._initialized:
            yield event.plain_result("内部错误：权限系统未正确加载")
            event.stop_event()
            return
        role_name = self.mention_role.get_call_role_name(event)
        if not await self.mention_role.is_sender_in_role(event, role_name):
            if result := await perm_manager.perm_block(
                event,
                bot_perm=PermLevel.MEMBER,
                perm_key="mention_role_call",
                check_at=False,
            ):
                yield event.plain_result(result)
                event.stop_event()
                return
        if result := await self.mention_role.call_role(event):
            yield event.plain_result(result)

    @filter.command("禁言")
    @perm_required(PermLevel.ADMIN, perm_key="set_group_card")
    async def set_group_ban(self, event: AiocqhttpMessageEvent, ban_time=None):
        """禁言 <秒数> @群友"""
        await self.normal.set_group_ban(event, ban_time)

    @filter.command("解禁")
    @perm_required(PermLevel.ADMIN, perm_key="set_group_card")
    async def cancel_group_ban(self, event: AiocqhttpMessageEvent):
        """解禁 @群友"""
        await self.normal.set_group_ban(event, ban_time=0)

    @filter.command("全禁", alias={"全员禁言", "全员禁言"})
    @perm_required(PermLevel.ADMIN, perm_key="whole_ban")
    async def set_group_whole_ban(
        self, event: AiocqhttpMessageEvent, enable: bool | str = True
    ):
        """全禁 开/关, 开启或关闭群全员禁言"""
        enable = parse_bool(enable, default=True)
        await self.normal.set_group_whole_ban(event, enable)

    @filter.command("改名")
    @perm_required(PermLevel.ADMIN, perm_key="set_group_card")
    async def set_group_card(
        self, event: AiocqhttpMessageEvent, target_card: str | int = ""
    ):
        """改名 <新昵称> @user"""
        if result := await self.normal.set_group_card(event, target_id=target_card):
            yield event.plain_result(result)

    @filter.command("改头衔", alias={"头衔"})
    @perm_required(PermLevel.OWNER, perm_key="set_group_special_title")
    async def set_group_special_title(
        self, event: AiocqhttpMessageEvent, special_title: str | int = ""
    ):
        """改头衔 <新头衔> @群友"""
        if result := await self.normal.set_group_special_title(
            event, special_title=special_title
        ):
            yield event.plain_result(result)

    @filter.command("申请头衔", alias={"我要头衔"})
    @perm_required(PermLevel.OWNER, perm_key="set_group_special_title_me")
    async def set_group_special_title_me(
        self, event: AiocqhttpMessageEvent, special_title: str | int = ""
    ):
        """申请头衔 <新头衔>"""
        if result := await self.normal.set_group_special_title(
            event, special_title=special_title
        ):
            yield event.plain_result(result)

    @filter.command("踢了")
    @perm_required(PermLevel.ADMIN, perm_key="set_group_kick")
    async def set_group_kick(self, event: AiocqhttpMessageEvent):
        """踢了@群友"""
        if result := await self.normal.set_group_kick(event):
            yield event.plain_result(result)

    @filter.command("群拉黑")
    @perm_required(PermLevel.ADMIN, perm_key="set_group_block")
    async def set_group_block(self, event: AiocqhttpMessageEvent):
        """群拉黑@群友"""
        if result := await self.normal.set_group_block(event):
            yield event.plain_result(result)

    @filter.command("上管", alias={"设置管理员"})
    @perm_required(PermLevel.OWNER, perm_key="admin", check_at=False)
    async def set_group_admin(self, event: AiocqhttpMessageEvent):
        """上管@群友，将群友设为管理员"""
        if result := await self.normal.set_group_admin(event, enable=True):
            yield event.plain_result(result)

    @filter.command("下管", alias={"取消管理员"})
    @perm_required(PermLevel.OWNER, perm_key="admin", check_at=False)
    async def cancel_group_admin(self, event: AiocqhttpMessageEvent):
        """下管@群友，取消群友的管理员身份"""
        if result := await self.normal.set_group_admin(event, enable=False):
            yield event.plain_result(result)

    @filter.command("设精", alias={"设为精华"})
    @perm_required(PermLevel.ADMIN, perm_key="essence")
    async def set_essence_msg(self, event: AiocqhttpMessageEvent):
        """(引用消息)设精, 将消息设为群精华"""
        if result := await self.normal.set_essence_msg(event, enable=True):
            yield event.plain_result(result)

    @filter.command("移精", alias={"移除精华"})
    @perm_required(PermLevel.ADMIN, perm_key="essence")
    async def delete_essence_msg(self, event: AiocqhttpMessageEvent):
        """(引用消息)移精，将消息移除群精华"""
        if result := await self.normal.set_essence_msg(event, enable=False):
            yield event.plain_result(result)

    @filter.command("群精华", alias={"查看群精华"})
    @perm_required(PermLevel.ADMIN, perm_key="get_essence_msg_list")
    async def get_essence_msg_list(self, event: AiocqhttpMessageEvent):
        """查看群精华"""
        if result := await self.normal.get_essence_msg_list(event):
            yield event.plain_result(result)

    @filter.command("设置群头像")
    @perm_required(PermLevel.ADMIN, perm_key="set_group_portrait")
    async def set_group_portrait(self, event: AiocqhttpMessageEvent):
        """(引用图片)设置群头像"""
        if result := await self.normal.set_group_portrait(event):
            yield event.plain_result(result)

    @filter.command("设置群名")
    @perm_required(PermLevel.ADMIN, perm_key="set_group_name")
    async def set_group_name(
        self, event: AiocqhttpMessageEvent, group_name: str | int | None = None
    ):
        """设置群名 <新群名>"""
        if result := await self.normal.set_group_name(event, group_name):
            yield event.plain_result(result)

    @filter.command("撤回")
    @perm_required(PermLevel.MEMBER, perm_key="delete_msg")
    async def delete_msg(self, event: AiocqhttpMessageEvent):
        """(引用消息)撤回 | 撤回 <@群友> <消息数量>"""
        await self.recall.delete_msg(event)

    @filter.command("发布群公告")
    @perm_required(PermLevel.ADMIN, perm_key="send_group_notice")
    async def send_group_notice(self, event: AiocqhttpMessageEvent):
        """(引用图片)发布群公告 <文字内容>"""
        if result := await self.notice.send_group_notice(event):
            yield event.plain_result(result)

    @filter.command("群公告", alias={"查看群公告"})
    @perm_required(PermLevel.MEMBER, perm_key="get_group_notice")
    async def get_group_notice(self, event: AiocqhttpMessageEvent):
        """查看群公告"""
        if result := await self.notice.get_group_notice(event):
            yield event.plain_result(result)

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

    @filter.command("投票禁言")
    @perm_required(PermLevel.ADMIN, perm_key="vote")
    async def start_vote_mute(
        self, event: AiocqhttpMessageEvent, ban_time: int | None = None
    ):
        "投票禁言 <秒数> @群友"
        await self.banpro.start_vote_mute(event, ban_time)

    @filter.command("赞同禁言")
    @perm_required(PermLevel.ADMIN, perm_key="vote")
    async def agree_vote_mute(self, event: AiocqhttpMessageEvent):
        """同意执行当前禁言投票"""
        await self.banpro.vote_mute(event, agree=True)

    @filter.command("反对禁言")
    @perm_required(PermLevel.ADMIN, perm_key="vote")
    async def disagree_vote_mute(self, event: AiocqhttpMessageEvent):
        """反对执行当前禁言投票"""
        await self.banpro.vote_mute(event, agree=False)

    @filter.command("开启宵禁")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @perm_required(PermLevel.ADMIN, perm_key="curfew")
    async def start_curfew(
        self,
        event: AiocqhttpMessageEvent,
        start_time: str | None = None,
        end_time: str | None = None,
    ):
        """开启宵禁 HH:MM HH:MM"""
        if result := await self.curfew.start_curfew(event, start_time, end_time):
            yield event.plain_result(result)

    @filter.command("关闭宵禁")
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @perm_required(PermLevel.ADMIN, perm_key="curfew")
    async def stop_curfew(self, event: AiocqhttpMessageEvent):
        """关闭本群的宵禁任务"""
        if result := await self.curfew.stop_curfew(event):
            yield event.plain_result(result)

    @filter.command("进群审核")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_join_review(
        self, event: AiocqhttpMessageEvent, mode: str | bool | None = None
    ):
        "进群审核 开/关，所有进群审核功能的总开关"
        await self.join.handle_join_review(event, mode)

    @filter.command("进群白词")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_accept_words(self, event: AiocqhttpMessageEvent):
        "设置/查看自动批准进群的关键词（空格隔开，无参数表示查看）"
        await self.join.handle_accept_words(event)

    @filter.command("进群黑词")
    @perm_required(PermLevel.ADMIN, perm_key="join")
    async def handle_reject_words(self, event: AiocqhttpMessageEvent):
        "设置/查看进群黑名单关键词（空格隔开，无参数表示查看）"
        await self.join.handle_reject_words(event)

    @filter.command("未命中驳回")
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

    @filter.command("批准", alias={"同意进群"})
    @perm_required(PermLevel.ADMIN, perm_key="approve")
    async def agree_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        "批准进群申请"
        await self.join.agree_add_group(event, extra)

    @filter.command("驳回", alias={"拒绝进群", "不批准"})
    @perm_required(PermLevel.ADMIN, perm_key="approve")
    async def refuse_add_group(self, event: AiocqhttpMessageEvent, extra: str = ""):
        "驳回进群申请"
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
        "进群欢迎 <欢迎语>"
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

    @filter.command("群友信息")
    @perm_required(PermLevel.MEMBER, perm_key="get_group_member_list")
    async def get_group_member_list(self, event: AiocqhttpMessageEvent):
        "查看群友信息"
        await self.member.get_group_member_list(event)

    @filter.command("清理群友")
    @perm_required(PermLevel.MEMBER, perm_key="clear_group_member")
    async def clear_group_member(
        self,
        event: AiocqhttpMessageEvent,
        inactive_days: int = 30,
        under_level: int = 10,
    ):
        "清理群友 <未发言天数> <群等级>"
        await self.member.clear_group_member(event, inactive_days, under_level)

    @filter.command("上传群文件")
    @perm_required(PermLevel.MEMBER, perm_key="upload_group_file")
    async def upload_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str | int | None = None,
    ):
        "上传群文件 <文件夹名/文件名 | 文件名>"
        if result := await self.file.upload_group_file(event, str(path)):
            yield event.plain_result(result)

    @filter.command("删除群文件")
    @perm_required(PermLevel.ADMIN, perm_key="delete_group_file")
    async def delete_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str | int | None = None,
    ):
        "删除群文件 <文件夹名/序号> <文件名/序号>"
        if result := await self.file.delete_group_file(event, str(path)):
            yield event.plain_result(result)

    @filter.command("查看群文件")
    @perm_required(PermLevel.MEMBER, perm_key="view_group_file")
    async def view_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str | int | None = None,
    ):
        "查看群文件 <文件夹名/序号> <文件名/序号>"
        if result := await self.file.view_group_file(event, path):
            yield event.plain_result(result)

    @filter.llm_tool()
    async def llm_set_group_ban(
        self,
        event: AiocqhttpMessageEvent,
        user_id: int,
        duration: int,
        need_auth: bool = True,
    ):
        """
        在群聊中禁言某用户，被禁言的用户在禁言期间将无法发送消息。
        Args:
            user_id(number): 要禁言的用户QQ
            duration(number): 禁言持续时间（秒），范围为0~86400, 0表示取消禁言
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event,
                perm_key="set_group_ban",
                bot_perm=PermLevel.ADMIN,
            ):
                yield error
                return
        if result := await self.normal.set_group_ban(
            event, ban_time=duration, target_id=user_id
        ):
            yield result

    @filter.llm_tool()
    async def llm_set_group_card(
        self,
        event: AiocqhttpMessageEvent,
        target_id: int,
        target_card: str,
        need_auth: bool = True,
    ):
        """
        给群聊中某用户设置群昵称。
        Args:
            target_id(number): 要设置群昵称的用户的QQ
            target_card(string): 要设置的群昵称
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event,
                perm_key="set_group_card",
                bot_perm=PermLevel.ADMIN,
            ):
                yield error
                return
        if result := await self.normal.set_group_card(
            event, target_id=target_id, target_card=target_card
        ):
            yield result

    @filter.llm_tool()
    async def llm_set_group_special_title(
        self,
        event: AiocqhttpMessageEvent,
        target_id: int,
        special_title: str,
        need_auth: bool = True,
    ):
        """
        给群聊中某用户设置专属头衔。
        Args:
            target_id(number): 要设置头衔的用户的QQ
            special_title(string): 要设置的新头衔
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event,
                perm_key="set_group_special_title",
                bot_perm=PermLevel.OWNER,
            ):
                yield error
                return
        if result := await self.normal.set_group_special_title(
            event, target_id=target_id, special_title=special_title
        ):
            yield result

    @filter.llm_tool()
    async def llm_set_group_whole_ban(
        self,
        event: AiocqhttpMessageEvent,
        enable: bool = True,
        need_auth: bool = True,
    ):
        """
        开启或关闭群全员禁言。
        Args:
            enable(boolean): 是否开启全员禁言。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="whole_ban", bot_perm=PermLevel.ADMIN
            ):
                yield error
                return
        if result := await self.normal.set_group_whole_ban(event, enable):
            yield result

    @filter.llm_tool()
    async def llm_set_group_kick(
        self,
        event: AiocqhttpMessageEvent,
        target_id: int,
    ):
        """
        将指定用户踢出当前群聊(危险操作，本工具已强制鉴权)。
        Args:
            target_id(number): 要踢出的用户QQ。
        """
        if error := await perm_manager.llm_perm_block(
            event, perm_key="set_group_kick", bot_perm=PermLevel.ADMIN
        ):
            yield error
            return
        if result := await self.normal.set_group_kick(event, target_id=target_id):
            yield result

    @filter.llm_tool()
    async def llm_set_group_block(
        self,
        event: AiocqhttpMessageEvent,
        target_id: int,
    ):
        """
        将指定用户踢出当前群聊并加入群黑名单(危险操作，本工具已强制鉴权)。
        Args:
            target_id(number): 要踢出并拉黑的用户QQ。
        """
        if error := await perm_manager.llm_perm_block(
            event, perm_key="set_group_block", bot_perm=PermLevel.ADMIN
        ):
            yield error
            return
        if result := await self.normal.set_group_block(event, target_id=target_id):
            yield result

    @filter.llm_tool()
    async def llm_set_essence_msg(
        self,
        event: AiocqhttpMessageEvent,
        message_id: int,
        enable: bool = True,
        need_auth: bool = True,
    ):
        """
        设置或取消指定消息的群精华。
        Args:
            message_id(number): 要操作的消息ID。
            enable(boolean): 是否设置为群精华，False表示取消群精华。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="essence", bot_perm=PermLevel.ADMIN
            ):
                yield error
                return
        if result := await self.normal.set_essence_msg(
            event, enable=enable, message_id=message_id
        ):
            yield result

    @filter.llm_tool()
    async def llm_get_essence_msg_list(
        self,
        event: AiocqhttpMessageEvent,
        need_auth: bool = True,
    ):
        """
        查看当前群的群精华消息列表。
        Args:
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="get_essence_msg_list", bot_perm=PermLevel.ADMIN
            ):
                yield error
                return
        if result := await self.normal.get_essence_msg_list(event):
            yield result

    @filter.llm_tool()
    async def llm_set_group_name(
        self,
        event: AiocqhttpMessageEvent,
        group_name: str,
        need_auth: bool = True,
    ):
        """
        设置当前群的群名称。
        Args:
            group_name(string): 要设置的新群名称。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="set_group_name", bot_perm=PermLevel.ADMIN
            ):
                yield error
                return
        if result := await self.normal.set_group_name(event, group_name):
            yield result

    @filter.llm_tool()
    async def llm_set_group_portrait(
        self,
        event: AiocqhttpMessageEvent,
        image_url: str,
        need_auth: bool = True,
    ):
        """
        设置当前群的群头像。
        Args:
            image_url(string): 群头像图片URL或本地图片路径。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="set_group_portrait", bot_perm=PermLevel.ADMIN
            ):
                yield error
                return
        if result := await self.normal.set_group_portrait(event, image_url=image_url):
            yield result

    @filter.llm_tool()
    async def llm_send_group_notice(
        self,
        event: AiocqhttpMessageEvent,
        content: str,
        image_url: str = "",
        need_auth: bool = True,
    ):
        """
        发布一条群公告。
        Args:
            content(string): 群公告正文。
            image_url(string): 可选的公告图片URL或本地图片路径。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="send_group_notice", bot_perm=PermLevel.ADMIN
            ):
                yield error
                return
        if result := await self.notice.send_group_notice(
            event, content=content, image_url=image_url
        ):
            yield result

    @filter.llm_tool()
    async def llm_get_group_notice(
        self,
        event: AiocqhttpMessageEvent,
        need_auth: bool = True,
    ):
        """
        查看当前群的群公告。
        Args:
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="get_group_notice", bot_perm=PermLevel.MEMBER
            ):
                yield error
                return
        if result := await self.notice.get_group_notice(event):
            yield result

    @filter.llm_tool()
    async def llm_upload_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str,
        need_auth: bool = True,
    ):
        """
        上传本地文件到当前群的群文件。
        Args:
            path(string): 本地文件路径，可包含群文件夹路径。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="upload_group_file", bot_perm=PermLevel.MEMBER
            ):
                yield error
                return
        if result := await self.file.upload_group_file(event, path):
            yield result

    @filter.llm_tool()
    async def llm_delete_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str,
        need_auth: bool = True,
    ):
        """
        删除当前群的群文件或群文件夹。
        Args:
            path(string): 群文件名、文件夹名或文件夹/文件名。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="delete_group_file", bot_perm=PermLevel.ADMIN
            ):
                yield error
                return
        if result := await self.file.delete_group_file(event, path):
            yield result

    @filter.llm_tool()
    async def llm_view_group_file(
        self,
        event: AiocqhttpMessageEvent,
        path: str = "",
        need_auth: bool = True,
    ):
        """
        查看当前群的群文件或群文件夹。
        Args:
            path(string): 可选的文件名、文件夹名或文件夹/文件名，留空查看根目录。
            need_auth(boolean): 是否要进行鉴权，机器人自行发起操作则填False, 当前用户要发起操作则填True。
        """
        if need_auth:
            if error := await perm_manager.llm_perm_block(
                event, perm_key="view_group_file", bot_perm=PermLevel.MEMBER
            ):
                yield error
                return
        if result := await self.file.view_group_file(event, path):
            yield result
