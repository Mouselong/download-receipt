"""Small built-in English and Simplified Chinese translation table."""

from __future__ import annotations

import locale
from collections.abc import Callable


ZH_CN = {
    "Ready": "就绪",
    "Download Receipt": "下载收据",
    "Local history for the files you download": "记录下载文件的本地档案",
    "File": "文件",
    "Add file...": "添加文件...",
    "Choose watch folder...": "选择监控文件夹...",
    "Export...": "导出...",
    "Settings...": "设置...",
    "Exit": "退出",
    "Help": "帮助",
    "About": "关于",
    "Add file": "添加文件",
    "Scan now": "立即扫描",
    "Watch folder": "监控文件夹",
    "Search": "搜索",
    "All receipts": "全部收据",
    "With source": "有来源",
    "Needs a note": "待添加备注",
    "Duplicates": "重复文件",
    "Missing files": "已丢失文件",
    "Replaced versions": "历史版本",
    "Download inbox": "待整理",
    "Marked for removal": "待删除",
    "Source": "来源",
    "Saved": "记录时间",
    "Size": "大小",
    "Note": "备注",
    "Receipt details": "收据详情",
    "FILE": "文件",
    "STATUS": "状态",
    "SOURCE": "来源",
    "FIRST SAVED": "首次记录",
    "LOCAL PATH": "本地路径",
    "SOURCE URL": "来源网址",
    "SHA-256": "SHA-256",
    "NOTE": "备注",
    "ORGANIZE": "整理状态",
    "Inbox": "待整理",
    "Keep": "保留",
    "Later": "稍后处理",
    "Remove": "待删除",
    "Select a receipt": "请选择一条收据",
    "Not available": "不可用",
    "Active": "当前文件",
    "Missing": "文件已移动或删除",
    "Replaced": "已被同路径的新文件替换",
    "Unknown": "未知",
    "Save note": "保存备注",
    "Open source": "打开来源",
    "Open file": "打开文件",
    "Show in folder": "在文件夹中显示",
    "Relocate": "重新定位",
    "Remove receipt": "删除收据",
    "Scanning...": "扫描中...",
    "Receipt saved": "收据已保存",
    "Note saved": "备注已保存",
    "Watch folder updated": "监控文件夹已更新",
    "Scan failed": "扫描失败",
    "Could not read file": "无法读取文件",
    "Folder not found": "找不到文件夹",
    "File not found": "找不到文件",
    "No source URL": "没有来源网址",
    "Unsafe source URL": "来源网址不安全",
    "Settings": "设置",
    "Scan automatically": "自动扫描",
    "Include subfolders": "包含子文件夹",
    "Minimize to system tray when closing": "关闭窗口时最小化到系统托盘",
    "Start with Windows": "Windows 启动时运行",
    "Scan interval (seconds)": "扫描间隔（秒）",
    "Language": "语言",
    "Automatic": "跟随系统",
    "English": "English",
    "Simplified Chinese": "简体中文",
    "Save": "保存",
    "Cancel": "取消",
    "Restart required": "需要重启",
    "Settings saved": "设置已保存",
    "Export receipts": "导出收据",
    "Export complete": "导出完成",
    "Welcome to Download Receipt": "欢迎使用下载收据",
    "Your Downloads folder will be scanned locally. No data is uploaded.": "程序会在本机扫描下载文件夹，不会上传任何数据。",
    "You can change the folder and scan options at any time in Settings.": "你可以随时在设置中更改文件夹和扫描选项。",
    "Get started": "开始使用",
    "Show Download Receipt": "显示下载收据",
    "Quit Download Receipt": "退出下载收据",
    "Not calculated for files over 200 MB": "超过 200 MB，未计算指纹",
    "duplicate found": "发现重复文件",
    "Not stored by the browser": "浏览器未保存来源",
}


def resolve_language(preference: str) -> str:
    if preference in {"en", "zh_CN"}:
        return preference
    system_language = (locale.getlocale()[0] or "").lower()
    return "zh_CN" if system_language.startswith("zh") else "en"


def translator(preference: str) -> Callable[[str], str]:
    language = resolve_language(preference)
    if language == "zh_CN":
        return lambda text: ZH_CN.get(text, text)
    return lambda text: text
