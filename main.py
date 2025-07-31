import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register


@register("astrbot_plugin_textadventure", "xSapientia", "支持暂停恢复的动态文字冒险游戏插件", "0.0.1", "https://github.com/xSapientia/astrbot_plugin_textadventure")
class TextAdventurePlugin(Star):
    """
    一个由LLM驱动的文字冒险游戏插件，支持游戏暂停、恢复和缓存功能。
    玩家可以随时暂停游戏去进行其他对话，之后再恢复游戏继续冒险。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        
        # 缓存目录
        self.cache_dir = os.path.join("data", "plugin_data", "astrbot_plugin_textadventure")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 活跃游戏会话：{user_id: game_state}
        self.active_game_sessions: Dict[str, dict] = {}
        
        # 暂停的游戏会话：{user_id: game_state}
        self.paused_game_sessions: Dict[str, dict] = {}
        
        # 加载缓存的游戏
        self._load_cached_games()
        
        # 启动自动保存任务
        asyncio.create_task(self._auto_save_task())
        
        logger.info("--- TextAdventurePlugin 初始化完成 ---")
        logger.info(f"缓存目录: {self.cache_dir}")
        logger.info(f"加载了 {len(self.paused_game_sessions)} 个暂停的游戏")

    async def initialize(self):
        """异步初始化方法"""
        pass

    def _get_cache_file_path(self, user_id: str) -> str:
        """获取用户缓存文件路径"""
        return os.path.join(self.cache_dir, f"game_{user_id}.json")

    def _save_game_cache(self, user_id: str, game_state: dict):
        """保存游戏状态到缓存"""
        try:
            cache_file = self._get_cache_file_path(user_id)
            game_state["last_update"] = datetime.now().isoformat()
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(game_state, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存用户 {user_id} 的游戏缓存")
        except Exception as e:
            logger.error(f"保存游戏缓存失败: {e}")

    def _load_game_cache(self, user_id: str) -> Optional[dict]:
        """从缓存加载游戏状态"""
        try:
            cache_file = self._get_cache_file_path(user_id)
            if os.path.exists(cache_file):
                with open(cache_file, 'r', encoding='utf-8') as f:
                    game_state = json.load(f)
                    
                # 检查缓存是否过期
                max_cache_days = self.config.get("max_cache_days", 7)
                last_update = datetime.fromisoformat(game_state.get("last_update", "2000-01-01T00:00:00"))
                if datetime.now() - last_update > timedelta(days=max_cache_days):
                    logger.info(f"用户 {user_id} 的游戏缓存已过期，删除")
                    os.remove(cache_file)
                    return None
                    
                return game_state
        except Exception as e:
            logger.error(f"加载游戏缓存失败: {e}")
        return None

    def _delete_game_cache(self, user_id: str):
        """删除游戏缓存"""
        try:
            cache_file = self._get_cache_file_path(user_id)
            if os.path.exists(cache_file):
                os.remove(cache_file)
                logger.debug(f"已删除用户 {user_id} 的游戏缓存")
        except Exception as e:
            logger.error(f"删除游戏缓存失败: {e}")

    def _load_cached_games(self):
        """启动时加载所有缓存的游戏"""
        if not os.path.exists(self.cache_dir):
            return
            
        for filename in os.listdir(self.cache_dir):
            if filename.startswith("game_") and filename.endswith(".json"):
                user_id = filename[5:-5]  # 去掉 "game_" 前缀和 ".json" 后缀
                game_state = self._load_game_cache(user_id)
                if game_state:
                    self.paused_game_sessions[user_id] = game_state

    async def _auto_save_task(self):
        """自动保存任务"""
        while True:
            try:
                auto_save_interval = self.config.get("auto_save_interval", 60)
                await asyncio.sleep(auto_save_interval)
                # 保存活跃游戏
                for user_id, game_state in self.active_game_sessions.items():
                    self._save_game_cache(user_id, game_state)
                # 保存暂停游戏
                for user_id, game_state in self.paused_game_sessions.items():
                    self._save_game_cache(user_id, game_state)
            except Exception as e:
                logger.error(f"自动保存任务错误: {e}")

    def _create_game_state(self, theme: str, system_prompt: str) -> dict:
        """创建新的游戏状态"""
        return {
            "theme": theme,
            "llm_conversation_context": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "故事开始了，我的第一个场景是什么？"}
            ],
            "created_time": datetime.now().isoformat(),
            "last_action_time": datetime.now().isoformat(),
            "is_active": False,
            "turn_count": 0
        }

    async def _pause_game(self, user_id: str):
        """暂停游戏"""
        if user_id in self.active_game_sessions:
            game_state = self.active_game_sessions.pop(user_id)
            game_state["is_active"] = False
            self.paused_game_sessions[user_id] = game_state
            self._save_game_cache(user_id, game_state)
            logger.info(f"用户 {user_id} 的游戏已暂停")

    async def _resume_game(self, user_id: str) -> bool:
        """恢复游戏"""
        if user_id in self.paused_game_sessions:
            game_state = self.paused_game_sessions.pop(user_id)
            game_state["is_active"] = True
            game_state["last_action_time"] = datetime.now().isoformat()
            self.active_game_sessions[user_id] = game_state
            logger.info(f"用户 {user_id} 的游戏已恢复")
            return True
        return False

    def _is_game_timeout(self, game_state: dict) -> bool:
        """检查游戏是否超时"""
        session_timeout = self.config.get("session_timeout", 300)
        last_action_time = datetime.fromisoformat(game_state["last_action_time"])
        return datetime.now() - last_action_time > timedelta(seconds=session_timeout)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听所有消息，处理游戏中的用户输入"""
        user_id = event.get_sender_id()
        
        # 只处理活跃游戏中的用户消息
        if user_id not in self.active_game_sessions:
            return
            
        # 跳过指令消息，让其他指令正常处理
        message_text = event.message_str.strip()
        if message_text.startswith('/') or message_text.startswith('\\'):
            return
            
        # 检查是否超时
        game_state = self.active_game_sessions[user_id]
        if self._is_game_timeout(game_state):
            yield event.plain_result(
                f"⏱️ **游戏超时暂停**\n"
                f"你的冒险已自动暂停。使用 `/恢复冒险` 可以继续你的旅程！"
            )
            await self._pause_game(user_id)
            event.stop_event()
            return
            
        # 处理游戏行动
        await self._handle_game_action(event, game_state)
        
        # 阻止事件继续传播，避免触发其他功能
        event.stop_event()

    async def _handle_game_action(self, event: AstrMessageEvent, game_state: dict):
        """处理游戏行动"""
        user_id = event.get_sender_id()
        player_action = event.message_str.strip()
        
        if not player_action:
            yield event.plain_result("你静静地站着，什么也没做。要继续冒险，请输入你的行动。")
            return

        try:
            yield event.plain_result("🎲 AI正在构思下一幕...请稍等片刻...")
            
            # 更新对话上下文
            game_state["llm_conversation_context"].append({"role": "user", "content": player_action})
            game_state["last_action_time"] = datetime.now().isoformat()
            game_state["turn_count"] += 1

            llm_provider = self.context.get_using_provider()
            if not llm_provider:
                yield event.plain_result("抱歉，当前没有可用的LLM服务。游戏暂停中...")
                await self._pause_game(user_id)
                return

            # 调用LLM生成故事
            llm_response: LLMResponse = await llm_provider.text_chat(
                prompt="",
                session_id=event.get_session_id(),
                contexts=game_state["llm_conversation_context"],
            )
            
            story_text = llm_response.completion_text
            game_state["llm_conversation_context"].append({"role": "assistant", "content": story_text})

            # 发送故事内容
            response_text = (
                f"📖 **第 {game_state['turn_count']} 回合**\n\n"
                f"{story_text}\n\n"
                f"**[💡 提示: 输入行动继续冒险，或发送 /暂停冒险 暂停游戏]**"
            )
            yield event.plain_result(response_text)
            
            # 保存游戏状态
            self._save_game_cache(user_id, game_state)

        except Exception as e:
            logger.error(f"处理游戏行动失败: {e}")
            yield event.plain_result(f"抱歉，AI遇到了问题。游戏已自动暂停，你可以稍后使用 /恢复冒险 继续。")
            await self._pause_game(user_id)

    @filter.command("开始冒险", alias={"start_adventure", "开始游戏"})
    async def start_adventure(self, event: AstrMessageEvent, theme: str = ""):
        """
        开始一场动态文字冒险游戏。
        用法: /开始冒险 [可选的主题]
        例如: /开始冒险 在一个赛博朋克城市
        """
        user_id = event.get_sender_id()
        
        # 检查是否已有活跃游戏
        if user_id in self.active_game_sessions:
            game_state = self.active_game_sessions[user_id]
            yield event.plain_result(
                f"🎮 **你已经有一个正在进行的冒险！**\n"
                f"主题: {game_state['theme']}\n"
                f"回合数: {game_state['turn_count']}\n"
                f"直接输入行动继续游戏，或使用 `/暂停冒险` 暂停。"
            )
            return

        # 检查是否有暂停的游戏
        if user_id in self.paused_game_sessions:
            paused_game = self.paused_game_sessions[user_id]
            yield event.plain_result(
                f"📚 **检测到暂停的冒险**\n"
                f"主题: {paused_game['theme']}\n"
                f"回合数: {paused_game['turn_count']}\n"
                f"使用 `/恢复冒险` 继续之前的游戏，或使用 `/删除冒险` 开始新游戏。"
            )
            return

        default_theme = self.config.get("default_adventure_theme", "奇幻世界")
        game_theme = theme.strip() if theme else default_theme

        # 游戏介绍
        session_timeout = self.config.get("session_timeout", 300)
        intro_message = (
            "🏰 **动态文字冒险游戏** 🏰\n\n"
            f"🎭 **主题**: {game_theme}\n"
            f"⏰ **超时设置**: {session_timeout}秒无操作自动暂停\n\n"
            "📜 **游戏说明**:\n"
            "• 直接输入你的行动来推进故事\n"
            "• 使用 `/暂停冒险` 可随时暂停游戏\n"
            "• 暂停后可正常使用其他功能\n"
            "• 使用 `/恢复冒险` 继续游戏\n\n"
            "🎲 正在为你生成专属冒险..."
        )
        yield event.plain_result(intro_message)

        # 构建系统提示词
        system_prompt_template = self.config.get(
            "system_prompt_template",
            "你是一位经验丰富的文字冒险游戏主持人(Game Master)。你将在一个'{game_theme}'主题下，根据玩家的行动实时生成独特且逻辑连贯的故事情节。"
        )
        
        try:
            system_prompt = system_prompt_template.format(game_theme=game_theme)
        except KeyError:
            logger.error("系统提示词模板格式错误！")
            system_prompt = f"你是一位文字冒险游戏主持人，主题是'{game_theme}'。"

        # 创建游戏状态
        game_state = self._create_game_state(game_theme, system_prompt)

        # 生成开场故事
        try:
            llm_provider = self.context.get_using_provider()
            if not llm_provider:
                yield event.plain_result("❌ 抱歉，当前没有可用的LLM服务来开始冒险。")
                return

            llm_response: LLMResponse = await llm_provider.text_chat(
                prompt="",
                session_id=event.get_session_id(),
                contexts=game_state["llm_conversation_context"],
            )
            
            story_text = llm_response.completion_text
            game_state["llm_conversation_context"].append({"role": "assistant", "content": story_text})
            game_state["is_active"] = True
            game_state["turn_count"] = 1

            # 启动游戏
            self.active_game_sessions[user_id] = game_state
            self._save_game_cache(user_id, game_state)

            response_text = (
                f"✨ **冒险开始！** ✨\n\n"
                f"{story_text}\n\n"
                f"**[💡 提示: 直接输入你的行动来继续冒险！]**"
            )
            yield event.plain_result(response_text)

        except Exception as e:
            logger.error(f"开始冒险时LLM调用失败: {e}")
            yield event.plain_result("❌ 抱歉，无法开始冒险，LLM服务出现问题。")

    @filter.command("暂停冒险", alias={"pause_adventure", "暂停游戏"})
    async def pause_adventure(self, event: AstrMessageEvent):
        """暂停当前的冒险游戏"""
        user_id = event.get_sender_id()
        
        if user_id not in self.active_game_sessions:
            yield event.plain_result("❌ 你当前没有正在进行的冒险。")
            return

        game_state = self.active_game_sessions[user_id]
        await self._pause_game(user_id)
        
        yield event.plain_result(
            f"⏸️ **冒险已暂停**\n"
            f"主题: {game_state['theme']}\n"
            f"回合数: {game_state['turn_count']}\n"
            f"你可以正常使用其他功能，使用 `/恢复冒险` 继续游戏。"
        )

    @filter.command("恢复冒险", alias={"resume_adventure", "继续游戏"})
    async def resume_adventure(self, event: AstrMessageEvent):
        """恢复暂停的冒险游戏"""
        user_id = event.get_sender_id()
        
        if user_id in self.active_game_sessions:
            game_state = self.active_game_sessions[user_id]
            yield event.plain_result(
                f"🎮 你的冒险已经在进行中！\n"
                f"主题: {game_state['theme']}\n"
                f"直接输入行动继续游戏。"
            )
            return

        if user_id not in self.paused_game_sessions:
            yield event.plain_result("❌ 你没有暂停的冒险可以恢复。使用 `/开始冒险` 开始新游戏。")
            return

        # 恢复游戏
        if await self._resume_game(user_id):
            game_state = self.active_game_sessions[user_id]
            
            # 获取最后的故事内容
            last_story = ""
            for msg in reversed(game_state["llm_conversation_context"]):
                if msg["role"] == "assistant":
                    last_story = msg["content"]
                    break

            response_text = (
                f"▶️ **冒险恢复！**\n"
                f"主题: {game_state['theme']}\n"
                f"回合数: {game_state['turn_count']}\n\n"
                f"📖 **当前情况**:\n{last_story}\n\n"
                f"**[💡 提示: 直接输入你的行动继续冒险！]**"
            )
            yield event.plain_result(response_text)
        else:
            yield event.plain_result("❌ 恢复游戏失败，请稍后重试。")

    @filter.command("冒险状态", alias={"adventure_status", "游戏状态"})
    async def adventure_status(self, event: AstrMessageEvent):
        """查看当前冒险状态"""
        user_id = event.get_sender_id()
        
        if user_id in self.active_game_sessions:
            game_state = self.active_game_sessions[user_id]
            created_time = datetime.fromisoformat(game_state["created_time"])
            last_action_time = datetime.fromisoformat(game_state["last_action_time"])
            
            status_text = (
                f"🎮 **活跃冒险状态**\n"
                f"主题: {game_state['theme']}\n"
                f"回合数: {game_state['turn_count']}\n"
                f"开始时间: {created_time.strftime('%Y-%m-%d %H:%M')}\n"
                f"最后行动: {last_action_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"直接输入行动继续游戏，或使用 `/暂停冒险` 暂停。"
            )
            yield event.plain_result(status_text)
            
        elif user_id in self.paused_game_sessions:
            game_state = self.paused_game_sessions[user_id]
            created_time = datetime.fromisoformat(game_state["created_time"])
            
            status_text = (
                f"⏸️ **暂停冒险状态**\n"
                f"主题: {game_state['theme']}\n"
                f"回合数: {game_state['turn_count']}\n"
                f"开始时间: {created_time.strftime('%Y-%m-%d %H:%M')}\n\n"
                f"使用 `/恢复冒险` 继续游戏。"
            )
            yield event.plain_result(status_text)
            
        else:
            yield event.plain_result("❌ 你当前没有任何冒险。使用 `/开始冒险` 开始新游戏。")

    @filter.command("删除冒险", alias={"delete_adventure", "清除游戏"})
    async def delete_adventure(self, event: AstrMessageEvent):
        """删除当前的冒险（活跃或暂停的）"""
        user_id = event.get_sender_id()
        
        deleted = False
        
        if user_id in self.active_game_sessions:
            del self.active_game_sessions[user_id]
            deleted = True
            
        if user_id in self.paused_game_sessions:
            del self.paused_game_sessions[user_id]
            deleted = True
            
        if deleted:
            self._delete_game_cache(user_id)
            yield event.plain_result(
                f"🗑️ **冒险已删除**\n"
                f"你的冒险数据已清除，可以使用 `/开始冒险` 开始新的冒险。"
            )
        else:
            yield event.plain_result("❌ 你没有需要删除的冒险。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("admin_clear_adventures", alias={"管理员清理冒险"})
    async def admin_clear_adventures(self, event: AstrMessageEvent):
        """管理员命令：清理所有冒险数据"""
        active_count = len(self.active_game_sessions)
        paused_count = len(self.paused_game_sessions)
        
        # 清理内存中的数据
        self.active_game_sessions.clear()
        self.paused_game_sessions.clear()
        
        # 清理缓存文件
        try:
            if os.path.exists(self.cache_dir):
                for filename in os.listdir(self.cache_dir):
                    if filename.startswith("game_") and filename.endswith(".json"):
                        os.remove(os.path.join(self.cache_dir, filename))
        except Exception as e:
            logger.error(f"清理缓存文件失败: {e}")
        
        yield event.plain_result(
            f"🧹 **管理员清理完成**\n"
            f"已清理 {active_count} 个活跃游戏\n"
            f"已清理 {paused_count} 个暂停游戏\n"
            f"所有缓存文件已删除"
        )
        logger.info(f"管理员 {event.get_sender_id()} 清理了所有冒险数据")

    @filter.command("冒险帮助", alias={"adventure_help", "游戏帮助"})
    async def adventure_help(self, event: AstrMessageEvent):
        """显示冒险游戏帮助信息"""
        help_text = (
            "🏰 **文字冒险游戏帮助** 🏰\n\n"
            "**基本指令**:\n"
            "• `/开始冒险 [主题]` - 开始新冒险\n"
            "• `/暂停冒险` - 暂停当前游戏\n"
            "• `/恢复冒险` - 恢复暂停的游戏\n"
            "• `/冒险状态` - 查看游戏状态\n"
            "• `/删除冒险` - 删除当前冒险\n\n"
            "**游戏特色**:\n"
            "• 🎲 AI驱动的动态故事生成\n"
            "• ⏸️ 支持暂停/恢复，不影响其他功能\n"
            "• 💾 自动保存，断线重连不丢失\n"
            "• ⏰ 智能超时管理\n\n"
            "**使用技巧**:\n"
            "• 游戏中直接输入行动（不需要加/）\n"
            "• 可以随时暂停去使用其他功能\n"
            "• 超时会自动暂停，不会丢失进度\n"
            "• 支持自定义主题创建独特冒险\n\n"
            "**管理员指令**:\n"
            "• `/admin_clear_adventures` - 清理所有冒险数据"
        )
        yield event.plain_result(help_text)

    async def terminate(self):
        """插件终止时保存所有数据并清理资源"""
        logger.info("正在终止 TextAdventurePlugin...")
        
        # 保存所有活跃游戏
        for user_id, game_state in self.active_game_sessions.items():
            game_state["is_active"] = False
            self.paused_game_sessions[user_id] = game_state
            self._save_game_cache(user_id, game_state)
        
        # 保存所有暂停游戏
        for user_id, game_state in self.paused_game_sessions.items():
            self._save_game_cache(user_id, game_state)
        
        # 清理内存
        self.active_game_sessions.clear()
        self.paused_game_sessions.clear()
        
        # 根据配置决定是否删除缓存文件
        if self.config.get("delete_cache_on_uninstall", False):
            try:
                if os.path.exists(self.cache_dir):
                    import shutil
                    shutil.rmtree(self.cache_dir)
                    logger.info("已删除所有游戏缓存文件")
            except Exception as e:
                logger.error(f"删除缓存目录失败: {e}")
        
        logger.info("TextAdventurePlugin 已终止")
