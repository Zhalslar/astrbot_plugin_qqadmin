import re
import os
from astrbot.core.message.components import Plain, At, Image

def parse_cq_to_chain(text: str) -> list:
    """增强版 CQ 码解析，支持本地绝对路径图片"""
    chain = []
    # 更加健壮的正则，支持参数中带有路径、空格等
    pattern = r'\[CQ:([a-z]+),([^\]]+)\]'
    last_pos = 0
    
    for match in re.finditer(pattern, text):
        # 处理之前的纯文本
        plain_text = text[last_pos:match.start()]
        if plain_text:
            chain.append(Plain(plain_text))
        
        cq_type = match.group(1)
        params_str = match.group(2)
        
        # 解析参数：file=D:\xxx...
        params = {}
        for item in params_str.split(','):
            if '=' in item:
                k, v = item.split('=', 1)
                params[k.strip()] = v.strip()
        
        # 根据类型构造组件
        if cq_type == "at":
            chain.append(At(qq=params.get("qq", ""), name=""))
        elif cq_type == "image":
            file_path = params.get("file") or params.get("url")
            if file_path:
                # 判断是 URL 还是本地路径
                if file_path.startswith("http"):
                    chain.append(Image.fromURL(file_path))
                else:
                    # 确保路径存在
                    if os.path.exists(file_path):
                        chain.append(Image.fromFileSystem(file_path))
                    else:
                        # 如果路径不存在，回退为文本提示，方便调试
                        chain.append(Plain(f"[图片读取失败: {file_path}]"))
        
        last_pos = match.end()
    
    # 处理剩余文本
    rest_text = text[last_pos:]
    if rest_text:
        chain.append(Plain(rest_text))
        
    return chain

# --- 以下仅用于本地脱离 AstrBot 环境测试 ---
# if __name__ == "__main__":
#     class MockComponent:
#         def __repr__(self): 
#             # 这样打印出来能看到具体的属性
#             return f"{self.__class__.__name__}({self.__dict__})"
    
#     class Plain(MockComponent): 
#         def __init__(self, text): self.text = text
        
#     class At(MockComponent): 
#         def __init__(self, qq, name=""): 
#             self.qq = qq
#             self.name = name

#     class Image(MockComponent): 
#         def __init__(self, file=None, url=None):
#             self.file = file
#             self.url = url
#         @staticmethod
#         def fromURL(url): return Image(url=url)
#         @staticmethod
#         def fromFileSystem(path): return Image(file=path)

#     # 测试文本（建议使用 r"" 原始字符串防止路径转义）
#     test_text = r"你好 {nickname}。欢迎！[CQ:at,qq=123456][CQ:image,file=./入群欢迎.jpg]"
    
#     # 假设你脚本里的函数名是 parse_cq_to_chain
#     result = parse_cq_to_chain(test_text)
    
#     print("\n" + "="*30)
#     print("--- 🔍 解析结果验证 ---")
#     for i, item in enumerate(result):
#         print(f"组件 {i}: {item}")
#     print("="*30)
