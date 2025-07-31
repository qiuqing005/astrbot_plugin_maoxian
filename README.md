# astrbot_plugin_textadventure
支持暂停恢复的动态文字冒险游戏插件，让玩家享受AI驱动的沉浸式冒险体验

# 文字冒险游戏 AstrBot 插件

<div align="center">

[![Version](https://img.shields.io/badge/version-0.0.1-blue.svg)](https://github.com/xSapientia/astrbot_plugin_textadventure)
[![AstrBot](https://img.shields.io/badge/AstrBot-%3E%3D3.4.0-green.svg)](https://github.com/Soulter/AstrBot)
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

一个支持暂停恢复功能的AI驱动文字冒险游戏插件，让你的 AstrBot 成为专业的游戏主持人！

</div>

## ✨ 功能特性

- 🎲 **AI驱动故事生成** - 由大语言模型实时生成独特的冒险情节
- ⏸️ **暂停恢复机制** - 随时暂停游戏，不影响其他Bot功能使用
- 💾 **智能缓存系统** - 自动保存游戏进度，断线重连不丢失
- 🎭 **自定义主题** - 支持玩家自定义冒险世界主题
- ⏰ **智能超时管理** - 超时自动暂停，保护游戏进度
- 🔄 **多用户支持** - 每个用户独立的游戏会话
- 🛡️ **数据安全** - 完善的数据管理和备份机制

## 🎯 使用方法

### 基础指令

| 指令 | 别名 | 说明 | 权限 |
|------|------|------|------|
| `/开始冒险 [主题]` | `start_adventure`, `开始游戏` | 开始新的冒险游戏 | 所有人 |
| `/暂停冒险` | `pause_adventure`, `暂停游戏` | 暂停当前游戏 | 所有人 |
| `/恢复冒险` | `resume_adventure`, `继续游戏` | 恢复暂停的游戏 | 所有人 |
| `/冒险状态` | `adventure_status`, `游戏状态` | 查看当前游戏状态 | 所有人 |
| `/删除冒险` | `delete_adventure`, `清除游戏` | 删除当前冒险数据 | 所有人 |
| `/冒险帮助` | `adventure_help`, `游戏帮助` | 显示帮助信息 | 所有人 |

### 管理员指令

| 指令 | 别名 | 说明 | 权限 |
|------|------|------|------|
| `/admin_clear_adventures` | `管理员清理冒险` | 清理所有冒险数据 | 管理员 |

## ⚙️ 配置说明

插件支持在 AstrBot 管理面板中进行可视化配置：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `default_adventure_theme` | string | 奇幻世界 | 默认冒险主题 |
| `session_timeout` | int | 300 | 会话超时时间（秒） |
| `max_cache_days` | int | 7 | 缓存保留天数 |
| `auto_save_interval` | int | 60 | 自动保存间隔（秒） |
| `system_prompt_template` | text | 见配置文件 | 系统提示词模板 |
| `delete_cache_on_uninstall` | bool | false | 卸载时删除缓存 |

### 系统提示词模板

默认模板支持 `{game_theme}` 占位符，会自动替换为游戏主题：

