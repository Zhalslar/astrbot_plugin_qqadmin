import os
from datetime import datetime
from pathlib import Path

from aiohttp import ClientSession

from astrbot import logger
from astrbot.core.message.components import At, BaseMessageComponent, Image, Reply
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

BAN_ME_QUOTES: list[str] = [
    "还真有人有这种奇怪的要求",
    "满足你",
    "静一会也挺好的",
    "是你自己要求的哈！",
    "行，你去静静",
    "好好好，禁了",
    "主人你没事吧？",
]


ADMIN_HELP = (
    "#【群管帮助】(指令前缀以bot配置为准)\n\n"
    "## NormalHandle 群管理\n"
    "- 禁言 <秒数> @用户：对指定成员禁言\n"
    "- 禁我 <秒数>：对自己禁言\n"
    "- 解禁 @用户：解除指定成员的禁言\n"
    "- 开启全禁 / 关闭全禁：控制全群是否可发言\n"
    "- 改名 <新昵称> @用户 / 改我 <新昵称>：修改群名片\n"
    "- 头衔 <头衔> @用户 / 申请头衔 <头衔>：设置群头衔（需群主权限）\n"
    "- 踢了 @用户：将指定成员移出群聊\n"
    "- 拉黑 @用户：踢出并拉黑指定成员\n"
    "- 上管 @用户：设置管理员（需群主权限）\n"
    "- 下管 @用户：取消管理员（需群主权限）\n"
    "- 撤回 (引用消息) / 撤回 @用户 数量：撤回消息，默认10条\n"
    "- 设置群头像 (引用图片)：修改群头像\n"
    "- 设置群名 <新群名>：修改群名称\n"
    "- 设精 (引用消息) / 移精 (引用消息)：管理精华消息\n"
    "- 查看精华：查看精华消息列表\n\n"
    "## NoticeHandle 公告管理\n"
    "- 发布群公告 <内容> (可引用图片)：发布群公告\n"
    "- 查看群公告：查看群公告\n\n"
    "## EnhanceHandle 增强功能\n"
    "- 投票禁言 <秒数> @用户：发起禁言投票\n"
    "- 赞同禁言 / 反对禁言：投票同意或反对禁言\n"
    "- 设置禁词 <词1 词2...>：设置或查看自定义违禁词\n"
    "- 内置禁词 开/关：开启或关闭内置违禁词检测\n"
    "- 刷屏禁言 <秒数>：设置刷屏触发的禁言时长（0 关闭）\n"
    "- （自动）违禁词检测：检测违禁词并自动撤回并禁言\n"
    "- （自动）刷屏检测：检测刷屏行为并自动处理\n\n"
    "## CurfewHandle 宵禁功能\n"
    "- 开启宵禁 HH:MM HH:MM：设置宵禁时间段\n"
    "- 关闭宵禁：关闭宵禁任务\n\n"
    "## JoinHandle 进群管理\n"
    "- 进群审核 开/关：开启或关闭进群审核功能\n"
    "- 进群白词 <关键词...>：设置自动批准进群的关键词\n"
    "- 进群黑词 <关键词...>：设置自动拒绝进群的关键词\n"
    "- 未命中驳回 开/关：设置是否拒绝未命中白词的进群申请\n"
    "- 进群等级 <等级>：设置进群等级门槛\n"
    "- 进群次数 <次数>：设置最大进群尝试次数\n"
    "- 进群黑名单 +QQ号 / -QQ号：添加或移除进群黑名单\n"
    "- 进群禁言 <秒数>：设置新进成员的禁言时长（0 表示不启用）\n"
    "- 进群欢迎：开启/关闭进群欢迎消息\n"
    "- 退群通知 开/关：开启或关闭退群通知\n"
    "- 退群拉黑 开/关：开启或关闭退群后自动拉黑（拉黑后下次进群自动拒绝）\n"
    "- 批准 / 驳回 <理由>：审批进群申请\n"
    "- （自动）监听进群/退群事件：记录群员变动\n\n"
    "## MemberHandle 群成员工具\n"
    "- 群友信息：查看群成员活跃情况\n"
    "- 清理群友 <未发言天数> <群等级>：移除不活跃或低等级成员\n\n"
    "## FileHandle 群文件管理\n"
    "- 上传群文件 <文件夹名/文件名>：引用文件并上传\n"
    "- 删除群文件 <文件夹名或序号> <文件名或序号>：删除群文件或文件夹\n"
    "- 查看群文件 <文件夹名或序号> <文件名或序号>：查看文件夹或文件详情\n\n"
    "## LLMHandle LLM功能\n"
    "- 取名 @用户 <抽取消息轮数>：根据聊天记录取个群昵称\n"
    "## 配置管理\n"
    "- 群管配置：修改/查看本群群管配置（直接跟配置文本）\n"
    "- 群管重置 <群号 | all>：重置本群或全部群的群管配置\n\n"
)


def print_logo():
    """打印欢迎 Logo"""
    logo = r"""
 ________  __                  __            __
|        \|  \                |  \          |  \
 \$$$$$$$$| $$____    ______  | $$  _______ | $$  ______    ______
    /  $$ | $$    \  |      \ | $$ /       \| $$ |      \  /      \
   /  $$  | $$$$$$$\  \$$$$$$\| $$|  $$$$$$$| $$  \$$$$$$\|  $$$$$$\
  /  $$   | $$  | $$ /      $$| $$ \$$    \ | $$ /      $$| $$   \$$
 /  $$___ | $$  | $$|  $$$$$$$| $$ _\$$$$$$\| $$|  $$$$$$$| $$
|  $$    \| $$  | $$ \$$    $$| $$|       $$| $$ \$$    $$| $$
 \$$$$$$$$ \$$   \$$  \$$$$$$$ \$$ \$$$$$$$  \$$  \$$$$$$$ \$$

        """
    print("\033[92m" + logo + "\033[0m")  # 绿色文字
    print("\033[94m欢迎使用群管插件！\033[0m")  # 蓝色文字



async def get_nickname(event: AiocqhttpMessageEvent, user_id: int | str) -> str:
    """获取指定群友的群昵称或 Q 名，群接口失败/空结果自动降级到陌生人资料"""
    user_id = int(user_id)
    client = event.bot
    group_id = event.get_group_id()
    info = {}

    # 在群里就先试群资料，任何异常或空结果都跳过
    if group_id.isdigit():
        try:
            info = (
                await client.get_group_member_info(
                    group_id=int(group_id), user_id=user_id
                )
                or {}
            )
        except Exception:
            pass

    # 群资料没拿到就降级到陌生人资料
    if not info:
        try:
            info = await client.get_stranger_info(user_id=user_id) or {}
        except Exception:
            pass

    # 依次取群名片、QQ 昵称、通用 nick，兜底数字 UID
    return info.get("card") or info.get("nickname") or info.get("nick") or str(user_id)


def get_ats(event: AiocqhttpMessageEvent) -> list[str]:
    """获取被at者们的id列表"""
    return [
        str(seg.qq)
        for seg in event.get_messages()
        if (isinstance(seg, At) and str(seg.qq) != event.get_self_id())
    ]


def get_replyer_id(event: AiocqhttpMessageEvent) -> str | None:
    """获取被引用消息者的id"""
    for seg in event.get_messages():
        if isinstance(seg, Reply):
            return str(seg.sender_id)


def get_reply_message_str(event: AiocqhttpMessageEvent) -> str | None:
    """
    获取被引用的消息解析后的纯文本消息字符串。
    """
    return next(
        (
            seg.message_str
            for seg in event.message_obj.message
            if isinstance(seg, Reply)
        ),
        "",
    )


def format_time(timestamp):
    """格式化时间戳"""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


async def download_file(url: str, save_path: Path) -> Path | None:
    """下载文件并保存到本地"""
    url = url.replace("https://", "http://")
    try:
        async with ClientSession() as client:
            response = await client.get(url)
            file = await response.read()

            os.makedirs(os.path.dirname(save_path), exist_ok=True)

            with open(save_path, "wb") as img_file:
                img_file.write(file)

            logger.info(f"文件已保存: {save_path}")
            return save_path
    except Exception as e:
        logger.error(f"文件下载并保存失败: {e}")
        return None


def extract_image_url(chain: list[BaseMessageComponent]) -> str | None:
    """从消息链中提取图片URL"""
    for seg in chain:
        if isinstance(seg, Image):
            return seg.url
        elif isinstance(seg, Reply) and seg.chain:
            for reply_seg in seg.chain:
                if isinstance(reply_seg, Image):
                    return reply_seg.url
    return None


def parse_bool(mode: str | bool | None):
    """解析布尔值"""
    mode = str(mode).strip().lower()
    match mode:
        case "开" | "开启" | "启用" | "on" | "true" | "1" | "是" | "真" :
            return True
        case "关" | "关闭" | "禁用" | "off" | "false" | "0" | "否" | "假" :
            return False
        case _:
            return None
