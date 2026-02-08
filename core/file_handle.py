import os
import re
from datetime import datetime

from astrbot.api import logger
from astrbot.core.message.components import File, Image, Reply, Video
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from ..utils import download_file
from ..config import PluginConfig


class FileHandle:
    def __init__(self, config: PluginConfig):
        self.data_dir = config.file_dir

    async def _parse_path(
        self, event: AiocqhttpMessageEvent, path: str
    ) -> tuple[str | None, str | None]:
        """
        解析路径，返回 (folder_name, file_name)
        支持：
        - "文件夹名" -> (folder_name, None)
        - "文件.zip" -> (None, file_name)
        - "文件夹名/文件.zip" -> (folder_name, file_name)
        - "数字" -> 用缓存解析 (folder or file)
        - "数字/数字" -> 用缓存解析 (folder序号/文件序号)
        """
        path = path.strip()
        response = await event.bot.get_group_root_files(group_id=int(event.get_group_id()))
        _, mapping = self._get_folder_info(response, "")

        def resolve_index(
            index: str, kind_filter: str | None = None
        ) -> tuple[str | None, str | None]:
            """根据序号解析文件夹名或文件名，可选过滤类型，返回(kind, name)"""
            if not index.isdigit():
                return None, None
            idx = int(index)
            if idx not in mapping:
                return None, None
            kind, name = mapping[idx]
            if kind_filter and kind != kind_filter:
                return None, None
            return kind, name

        if "/" in path:
            left, right = path.split("/", 1)

            # 先解析左边文件夹
            folder_kind, folder_name = resolve_index(left, "folder")
            folder_name = folder_name or left  # 左边不是数字就直接当字符串用

            # 如果右边是数字，需要进入对应文件夹再解析
            if right.isdigit() and folder_name:
                target_folder = await self._get_folder(event, folder_name)
                if target_folder:
                    folder_files = await event.bot.get_group_files_by_folder(
                        group_id=int(event.get_group_id()),
                        folder_id=target_folder["folder_id"],
                    )
                    _, file_mapping = self._get_folder_info(folder_files, "")
                    idx = int(right)
                    if idx in file_mapping and file_mapping[idx][0] == "file":
                        file_name = file_mapping[idx][1]
                        return folder_name, file_name

            # 如果右边不是纯数字或者没解析到，就直接当文件名
            return folder_name, right

        elif "." in path:
            return None, path

        else:
            if path.isdigit():
                idx = int(path)
                if idx in mapping:
                    kind, name = mapping[idx]
                    return (name, None) if kind == "folder" else (None, name)
                return None, None
            return path, None

    async def _get_folder(
        self, event: AiocqhttpMessageEvent, folder_name: str
    ) -> dict | None:
        """从根目录下找到指定文件夹, 返回文件夹数据"""
        response = await event.bot.get_group_root_files(
            group_id=int(event.get_group_id())
        )
        return next(
            (
                folder
                for folder in response["folders"]
                if folder_name == folder["folder_name"]
            ),
            None,
        )

    def _get_folder_info(self, data: dict, title: str) -> tuple[str, dict[int, str]]:
        """从响应数据里提取文件夹和文件，每个文件夹下文件序号从 1 开始"""
        info = [title]
        mapping = {}

        idx = 1
        for folder in data["folders"]:
            info.append(f"▶{idx}. {folder['folder_name']}")
            mapping[idx] = ("folder", folder["folder_name"])
            idx += 1

        for file in data["files"]:
            info.append(f"📄{idx}. {file['file_name']}")
            mapping[idx] = ("file", file["file_name"])
            idx += 1

        return "\n".join(info), mapping

    def _format_file_info(self, file: dict) -> str:
        """格式化文件信息"""
        lines = [f"【📄 {file.get('file_name', '未知')}】"]
        size = int(file.get("size", "0"))
        if size < 1024**2:
            lines.append(f"文件大小: {size / 1024:.2f} KB")
        else:
            lines.append(f"文件大小: {size / (1024**2):.2f} MB")

        lines.append(
            f"上传者：{file.get('uploader_name', '未知')}({file.get('uploader', '未知')})"
        )
        lines.append(f"下载次数：{file.get('download_times', '未知')}")

        if upload_time := file.get("upload_time", 0):
            lines.append(
                f"上传时间：{datetime.fromtimestamp(upload_time).strftime('%Y-%m-%d %H:%M:%S')}"
            )
        dead_time = file.get("dead_time", 0)
        lines.append(
            f"过期时间：{'永久有效' if dead_time == 0 else datetime.fromtimestamp(dead_time).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        if modify_time := file.get("modify_time", 0):
            lines.append(
                f"修改时间：{datetime.fromtimestamp(modify_time).strftime('%Y-%m-%d %H:%M:%S')}"
            )
        logger.debug(f"文件ID：{file.get('file_id', '未知')}")
        return "\n".join(lines)

    async def _get_file_in_folder(
        self, event: AiocqhttpMessageEvent, folder_name: str, file_name: str
    ):
        """返回目标文件夹和文件对象"""
        if not folder_name:
            return None, None
        target_folder = await self._get_folder(event, folder_name=folder_name)
        if not target_folder:
            return None, None
        response = await event.bot.get_group_files_by_folder(
            group_id=int(event.get_group_id()), folder_id=target_folder["folder_id"]
        )
        file = next((f for f in response["files"] if f["file_name"] == file_name), None)
        return target_folder, file

    async def _save_temp_file(self, event: AiocqhttpMessageEvent, file_name: str):
        """获取文件URL并下载，返回保存路径"""
        chain = event.message_obj.message
        reply_chain = chain[0].chain if chain and isinstance(chain[0], Reply) else None
        seg = reply_chain[0] if reply_chain else None
        if seg and isinstance(seg, File | Image | Video):
            if url := getattr(seg, "url", None) or getattr(seg, "file", None):
                logger.info(f"正在从URL下载文件：{url}")
                file_path = self.data_dir / file_name
                await download_file(url, file_path)
                if os.path.exists(file_path):
                    return file_path
                logger.error(f"下载文件失败：{url}")
            else:
                await event.send(event.plain_result("请引用一个文件"))

    async def _ensure_folder(self, event: AiocqhttpMessageEvent, folder_name: str):
        """
        确保群文件夹存在，如果不存在则创建，返回目标文件夹数据
        """
        group_id = int(event.get_group_id())
        client = event.bot

        target_folder = await self._get_folder(event, folder_name)
        if target_folder:
            return target_folder

        # 清理非法字符
        safe_name = re.sub(r"[\\/:*?\"<>|]", "", folder_name)[:30]
        await client.create_group_file_folder(
            group_id=group_id,
            folder_name=safe_name,
            parent_id="/",
        )
        await event.send(event.plain_result(f"新建群文件夹：▶ {safe_name}"))

        # 再次获取，确保拿到 folder_id
        return await self._get_folder(event, safe_name)

    async def upload_group_file(self, event: AiocqhttpMessageEvent, path: str):
        """上传群文件"""
        folder_name, file_name = await self._parse_path(event, path)
        if not file_name:
            await event.send(event.plain_result("路径未包含文件名，无法上传"))
            return

        group_id = int(event.get_group_id())
        client = event.bot

        # 拼接本地缓存路径
        file_path = await self._save_temp_file(event, file_name)
        if not file_path or not file_path.exists():
            return

        folder_id = None
        if folder_name:
            if target_folder := await self._ensure_folder(event, folder_name):
                folder_id = target_folder["folder_id"]

        try:
            await client.upload_group_file(
                group_id=group_id,
                file=str(file_path),
                name=file_name,
                folder_id=folder_id,
            )
        except Exception as e:
            logger.error(f"上传群文件失败：{e}")
            await event.send(event.plain_result(f"上传失败：{e}"))

    async def delete_group_file(self, event: AiocqhttpMessageEvent, path: str):
        """删除群文件夹或群文件"""
        folder_name, file_name = await self._parse_path(event, path)
        if not folder_name and not file_name:
            await event.send(event.plain_result("请指定要删除的文件夹或文件"))
            return
        group_id = int(event.get_group_id())

        # 删除文件
        if file_name:
            file = None
            if folder_name:
                target_folder, file = await self._get_file_in_folder(
                    event, folder_name, file_name
                )
                if not target_folder or not file:
                    await event.send(event.plain_result(f"{path} 不存在"))
                    return
            else:
                response = await event.bot.get_group_root_files(group_id=group_id)
                file = next(
                    (f for f in response["files"] if file_name == f["file_name"]),
                    None,
                )
            if file:
                await event.bot.delete_group_file(
                    group_id=group_id, file_id=file["file_id"]
                )
                await event.send(event.plain_result(f"已删除群文件：📄{file_name}"))

        # 删除文件夹
        elif folder_name and not file_name:
            if target_folder := await self._get_folder(event, folder_name):
                await event.bot.delete_group_folder(
                    group_id=group_id, folder_id=target_folder["folder_id"]
                )
                await event.send(
                    event.plain_result(f"已删除群文件夹：▶{folder_name}")
                )
            else:
                await event.send(event.plain_result(f"群文件夹【{folder_name}】不存在"))

    async def view_group_file(self, event: AiocqhttpMessageEvent, path):
        """查看群文件/目录，path 可以是 文件夹名、文件名 或 文件夹名/文件名"""
        group_id = int(event.get_group_id())
        client = event.bot
        if not path:
            # 查看根目录
            response = await client.get_group_root_files(group_id=group_id)
            text, _ = self._get_folder_info(response, "【群文件根目录】")
            yield event.plain_result(text)
            return

        folder_name, file_name = await self._parse_path(event, str(path))

        if folder_name and file_name:
            target_folder, file = await self._get_file_in_folder(
                event, folder_name, file_name
            )
            if not file:
                yield event.plain_result(f"未能找到群文件：📄{file_name}")
                return
            yield event.plain_result(self._format_file_info(file))
            return

        if folder_name and not file_name:
            target_folder = await self._get_folder(event, folder_name)
            if target_folder:
                response = await client.get_group_files_by_folder(
                    group_id=group_id, folder_id=target_folder["folder_id"]
                )
                text, _ = self._get_folder_info(response, f"【{folder_name}】")
                yield event.plain_result(text)
            else:
                # 根目录单文件
                response = await client.get_group_root_files(group_id=group_id)
                if file := next(
                    (f for f in response["files"] if folder_name == f["file_name"]),
                    None,
                ):
                    yield event.plain_result(
                        self._format_file_info(file)
                    )
                else:
                    yield event.plain_result(f"未能找到【{folder_name}】")
        elif not folder_name and file_name:
            # 根目录文件
            response = await client.get_group_root_files(group_id=group_id)
            if file := next(
                (f for f in response["files"] if file_name == f["file_name"]),
                None,
            ):
                yield event.plain_result(
                    self._format_file_info(file)
                )

            else:
                yield event.plain_result(f"未能找到群文件：📄{file_name}")
