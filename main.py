import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, List

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register


@register("astrbot_plugin_textadventure", "xSapientia", "支持历史记录的动态文字冒险游戏插件", "0.1.0", "https://github.com/xSapientia/astrbot_plugin_textadventure")
class TextAdventurePlugin(Star):
    """
    一个由LLM驱动的文字冒险游戏插件，支持游戏暂停、恢复、历史记录和多冒险管理功能。
    玩家可以同时拥有多个冒险，随时切换和查看历史记录。
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        
        # 缓存目录
        self.cache_dir = os.path.join("data", "plugin_data", "astrbot_plugin_textadventure")
        self.history_dir = os.path.join(self.cache_dir, "history")
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.history_dir, exist_ok=True)
        
        # 当前活跃游戏会话：{user_id: game_state}
        self.active_game_sessions: Dict[str, dict] = {}
        
        # 用户的所有冒险记录：{user_id: [game_list]}
        self.user_adventures: Dict[str, List[dict]] = {}
        
        # 用户当前选中的冒险ID：{user_id: adventure_id}
        self.user_current_adventure: Dict[str, str] = {}
        
        # 加载所有用户数据
        self._load_all_user_data()
        
        # 启动自动保存任务
        asyncio.create_task(self._auto_save_task())
        
        logger.info("--- TextAdventurePlugin 初始化完成 ---")
        logger.info(f"缓存目录: {self.cache_dir}")
        logger.info(f"加载了 {len(self.user_adventures)} 个用户的冒险数据")
        total_adventures = sum(len(adventures) for adventures in self.user_adventures.values())
        logger.info(f"总冒险数: {total_adventures}")

    async def initialize(self):
        """异步初始化方法"""
        logger.info("TextAdventurePlugin 异步初始化完成")

    def _get_user_data_file_path(self, user_id: str) -> str:
        """获取用户数据文件路径"""
        return os.path.join(self.cache_dir, f"user_{user_id}.json")

    def _get_adventure_history_file_path(self, user_id: str, adventure_id: str) -> str:
        """获取冒险历史文件路径"""
        return os.path.join(self.history_dir, f"adventure_{user_id}_{adventure_id}.json")

    def _generate_adventure_id(self) -> str:
        """生成唯一的冒险ID"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _save_user_data(self, user_id: str):
        """保存用户数据（冒险列表和当前选中）"""
        try:
            user_data = {
                "adventures": self.user_adventures.get(user_id, []),
                "current_adventure": self.user_current_adventure.get(user_id, ""),
                "last_update": datetime.now().isoformat()
            }
            
            user_file = self._get_user_data_file_path(user_id)
            with open(user_file, 'w', encoding='utf-8') as f:
                json.dump(user_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存用户 {user_id} 的数据")
        except Exception as e:
            logger.error(f"保存用户数据失败 [{user_id}]: {e}")

    def _save_adventure_details(self, user_id: str, adventure_id: str, game_state: dict):
        """保存冒险详细数据"""
        try:
            history_file = self._get_adventure_history_file_path(user_id, adventure_id)
            save_state = game_state.copy()
            save_state["last_update"] = datetime.now().isoformat()
            
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(save_state, f, ensure_ascii=False, indent=2)
            logger.debug(f"已保存冒险 {adventure_id} 的详细数据")
        except Exception as e:
            logger.error(f"保存冒险详细数据失败 [{user_id}/{adventure_id}]: {e}")

    def _load_user_data(self, user_id: str) -> bool:
        """加载用户数据"""
        try:
            user_file = self._get_user_data_file_path(user_id)
            if not os.path.exists(user_file):
                return False
                
            with open(user_file, 'r', encoding='utf-8') as f:
                user_data = json.load(f)
            
            self.user_adventures[user_id] = user_data.get("adventures", [])
            self.user_current_adventure[user_id] = user_data.get("current_adventure", "")
            
            return True
        except Exception as e:
            logger.error(f"加载用户数据失败 [{user_id}]: {e}")
            return False

    def _load_adventure_details(self, user_id: str, adventure_id: str) -> Optional[dict]:
        """加载冒险详细数据"""
        try:
            history_file = self._get_adventure_history_file_path(user_id, adventure_id)
            if not os.path.exists(history_file):
                return None
                
            with open(history_file, 'r', encoding='utf-8') as f:
                game_state = json.load(f)
            
            # 检查数据完整性
            required_fields = ["theme", "llm_conversation_context", "turn_count", "adventure_id"]
            if not all(field in game_state for field in required_fields):
                logger.warning(f"冒险数据不完整 [{user_id}/{adventure_id}]")
                return None
                
            return game_state
        except Exception as e:
            logger.error(f"加载冒险详细数据失败 [{user_id}/{adventure_id}]: {e}")
            return None

    def _load_all_user_data(self):
        """启动时加载所有用户数据"""
        if not os.path.exists(self.cache_dir):
            return
            
        try:
            for filename in os.listdir(self.cache_dir):
                if filename.startswith("user_") and filename.endswith(".json"):
                    user_id = filename[5:-5]  # 去掉 "user_" 前缀和 ".json" 后缀
                    self._load_user_data(user_id)
                    logger.debug(f"加载用户 {user_id} 的数据: {len(self.user_adventures.get(user_id, []))} 个冒险")
        except Exception as e:
            logger.error(f"加载所有用户数据失败: {e}")

    async def _auto_save_task(self):
        """自动保存任务"""
        while True:
            try:
                auto_save_interval = self.config.get("auto_save_interval", 60)
                await asyncio.sleep(auto_save_interval)
                
                # 保存活跃游戏
                for user_id, game_state in self.active_game_sessions.items():
                    adventure_id = game_state.get("adventure_id", "")
                    if adventure_id:
                        self._save_adventure_details(user_id, adventure_id, game_state)
                        self._save_user_data(user_id)
                
                if self.active_game_sessions:
                    logger.debug(f"自动保存完成: {len(self.active_game_sessions)} 个活跃冒险")
                    
            except Exception as e:
                logger.error(f"自动保存任务错误: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟再重试

    def _create_game_state(self, theme: str, system_prompt: str, adventure_id: str) -> dict:
        """创建新的游戏状态"""
        return {
            "adventure_id": adventure_id,
            "theme": theme,
            "llm_conversation_context": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "故事开始了，我的第一个场景是什么？"}
            ],
            "created_time": datetime.now().isoformat(),
            "last_action_time": datetime.now().isoformat(),
            "is_active": False,
            "is_completed": False,
            "completion_reason": "",
            "turn_count": 0,
            "total_actions": 0
        }

    def _add_adventure_to_user(self, user_id: str, game_state: dict):
        """将冒险添加到用户的冒险列表"""
        if user_id not in self.user_adventures:
            self.user_adventures[user_id] = []
        
        # 创建冒险摘要信息
        adventure_summary = {
            "adventure_id": game_state["adventure_id"],
            "theme": game_state["theme"],
            "created_time": game_state["created_time"],
            "last_action_time": game_state["last_action_time"],
            "is_active": game_state["is_active"],
            "is_completed": game_state.get("is_completed", False),
            "completion_reason": game_state.get("completion_reason", ""),
            "turn_count": game_state["turn_count"],
            "total_actions": game_state.get("total_actions", 0)
        }
        
        # 检查是否已存在，如果存在则更新
        existing_index = -1
        for i, adventure in enumerate(self.user_adventures[user_id]):
            if adventure["adventure_id"] == game_state["adventure_id"]:
                existing_index = i
                break
        
        if existing_index >= 0:
            self.user_adventures[user_id][existing_index] = adventure_summary
        else:
            self.user_adventures[user_id].append(adventure_summary)
        
        # 设置为当前冒险
        self.user_current_adventure[user_id] = game_state["adventure_id"]

    def _get_current_adventure_state(self, user_id: str) -> Optional[dict]:
        """获取用户当前选中的冒险状态"""
        if user_id in self.active_game_sessions:
            return self.active_game_sessions[user_id]
        
        current_adventure_id = self.user_current_adventure.get(user_id, "")
        if not current_adventure_id:
            return None
            
        return self._load_adventure_details(user_id, current_adventure_id)

    async def _pause_current_game(self, user_id: str):
        """暂停当前游戏"""
        if user_id in self.active_game_sessions:
            game_state = self.active_game_sessions.pop(user_id)
            game_state["is_active"] = False
            game_state["pause_time"] = datetime.now().isoformat()
            
            # 保存详细数据和更新摘要
            adventure_id = game_state["adventure_id"]
            self._save_adventure_details(user_id, adventure_id, game_state)
            self._add_adventure_to_user(user_id, game_state)
            self._save_user_data(user_id)
            
            logger.info(f"用户 {user_id} 的冒险 {adventure_id} 已暂停")

    async def _resume_adventure(self, user_id: str, adventure_id: str = "") -> bool:
        """恢复指定的冒险"""
        # 如果没有指定adventure_id，使用当前选中的
        if not adventure_id:
            adventure_id = self.user_current_adventure.get(user_id, "")
            if not adventure_id:
                return False
        
        # 先暂停当前活跃的游戏
        if user_id in self.active_game_sessions:
            await self._pause_current_game(user_id)
        
        # 加载要恢复的冒险
        game_state = self._load_adventure_details(user_id, adventure_id)
        if not game_state:
            return False
        
        # 检查是否已完成
        if game_state.get("is_completed", False):
            return False
        
        # 恢复游戏
        game_state["is_active"] = True
        game_state["last_action_time"] = datetime.now().isoformat()
        game_state["resume_time"] = datetime.now().isoformat()
        
        self.active_game_sessions[user_id] = game_state
        self.user_current_adventure[user_id] = adventure_id
        
        # 保存状态
        self._save_adventure_details(user_id, adventure_id, game_state)
        self._add_adventure_to_user(user_id, game_state)
        self._save_user_data(user_id)
        
        logger.info(f"用户 {user_id} 的冒险 {adventure_id} 已恢复")
        return True

    def _is_game_timeout(self, game_state: dict) -> bool:
        """检查游戏是否超时"""
        try:
            session_timeout = self.config.get("session_timeout", 300)
            last_action_time = datetime.fromisoformat(game_state["last_action_time"])
            return datetime.now() - last_action_time > timedelta(seconds=session_timeout)
        except (ValueError, KeyError):
            return True

    def _check_game_completion(self, story_text: str) -> tuple[bool, str]:
        """检查游戏是否应该结束（基于LLM输出的特殊标记）"""
        # 检查常见的结束标记
        completion_patterns = [
            r"故事结束",
            r"游戏结束",
            r"冒险结束",
            r"THE END",
            r"完",
            r"\[END\]",
            r"\[GAME_OVER\]",
            r"你的冒险到此结束",
            r"这次冒险就到这里",
            r"故事告一段落"
        ]
        
        for pattern in completion_patterns:
            if re.search(pattern, story_text, re.IGNORECASE):
                return True, "story_end"
        
        # 检查死亡或失败标记
        death_patterns = [
            r"你死了",
            r"你倒下了",
            r"游戏失败",
            r"任务失败",
            r"GAME OVER",
            r"你已经无法继续",
            r"冒险失败"
        ]
        
        for pattern in death_patterns:
            if re.search(pattern, story_text, re.IGNORECASE):
                return True, "death"
        
        # 检查胜利标记
        victory_patterns = [
            r"你胜利了",
            r"任务完成",
            r"成功完成",
            r"胜利",
            r"大获全胜",
            r"你成功了"
        ]
        
        for pattern in victory_patterns:
            if re.search(pattern, story_text, re.IGNORECASE):
                return True, "victory"
        
        return False, ""

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
                f"你的冒险《{game_state['theme']}》已自动暂停。\n"
                f"使用 `/恢复冒险` 可以继续你的旅程！"
            )
            await self._pause_current_game(user_id)
            event.stop_event()
            return
            
        # 处理游戏行动
        try:
            async for result in self._handle_game_action(event, game_state):
                yield result
        except Exception as e:
            logger.error(f"处理游戏消息时发生异常 [{user_id}]: {e}")
            yield event.plain_result("抱歉，处理你的行动时出现了问题。游戏已自动暂停。")
            await self._pause_current_game(user_id)
        
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
            
            # 更新对话上下文和状态
            game_state["llm_conversation_context"].append({"role": "user", "content": player_action})
            game_state["last_action_time"] = datetime.now().isoformat()
            game_state["turn_count"] += 1
            game_state["total_actions"] = game_state.get("total_actions", 0) + 1

            llm_provider = self.context.get_using_provider()
            if not llm_provider:
                yield event.plain_result("抱歉，当前没有可用的LLM服务。游戏暂停中...")
                await self._pause_current_game(user_id)
                return

            # 调用LLM生成故事
            llm_response: LLMResponse = await llm_provider.text_chat(
                prompt="",
                session_id=event.get_session_id(),
                contexts=game_state["llm_conversation_context"],
            )
            
            if not llm_response or not llm_response.completion_text:
                yield event.plain_result("抱歉，AI暂时无法回应。游戏已暂停，请稍后使用 `/恢复冒险` 继续。")
                await self._pause_current_game(user_id)
                return
            
            story_text = llm_response.completion_text.strip()
            game_state["llm_conversation_context"].append({"role": "assistant", "content": story_text})

            # 检查游戏是否结束
            is_completed, completion_reason = self._check_game_completion(story_text)
            
            if is_completed:
                game_state["is_completed"] = True
                game_state["completion_reason"] = completion_reason
                game_state["completion_time"] = datetime.now().isoformat()
                
                # 根据结束原因显示不同的消息
                completion_messages = {
                    "story_end": "📚 **故事完结**",
                    "death": "💀 **冒险结束**", 
                    "victory": "🏆 **胜利完成**"
                }
                completion_msg = completion_messages.get(completion_reason, "🔚 **冒险完成**")
                
                response_text = (
                    f"📖 **第 {game_state['turn_count']} 回合**\n\n"
                    f"{story_text}\n\n"
                    f"{completion_msg}\n"
                    f"这次冒险共进行了 {game_state['turn_count']} 回合。\n"
                    f"冒险记录已保存到历史中，你可以使用 `/冒险历史` 查看。\n\n"
                    f"**[💡 提示: 使用 /开始冒险 开始新的冒险！]**"
                )
                
                # 从活跃会话中移除并保存
                self.active_game_sessions.pop(user_id, None)
                adventure_id = game_state["adventure_id"]
                self._save_adventure_details(user_id, adventure_id, game_state)
                self._add_adventure_to_user(user_id, game_state)
                self._save_user_data(user_id)
                
                logger.info(f"用户 {user_id} 的冒险 {adventure_id} 已完成: {completion_reason}")
                
            else:
                # 正常的故事回合
                response_text = (
                    f"📖 **第 {game_state['turn_count']} 回合**\n\n"
                    f"{story_text}\n\n"
                    f"**[💡 提示: 输入行动继续冒险，或发送 /暂停冒险 暂停游戏]**"
                )
                
                # 保存游戏状态
                adventure_id = game_state["adventure_id"]
                self._save_adventure_details(user_id, adventure_id, game_state)
                self._add_adventure_to_user(user_id, game_state)
                
            yield event.plain_result(response_text)
            logger.debug(f"用户 {user_id} 完成第 {game_state['turn_count']} 回合")

        except Exception as e:
            logger.error(f"处理游戏行动失败 [{user_id}]: {e}")
            yield event.plain_result(f"抱歉，AI遇到了问题。游戏已自动暂停，你可以稍后使用 `/恢复冒险` 继续。")
            await self._pause_current_game(user_id)

    @filter.command("开始冒险", alias={"start_adventure", "开始游戏", "新冒险"})
    async def start_adventure(self, event: AstrMessageEvent, theme: str = ""):
        """
        开始一场新的动态文字冒险游戏。
        用法: /开始冒险 [可选的主题]
        例如: /开始冒险 在一个赛博朋克城市
        """
        user_id = event.get_sender_id()
        
        # 如果有活跃游戏，先暂停
        if user_id in self.active_game_sessions:
            current_game = self.active_game_sessions[user_id]
            yield event.plain_result(
                f"🎮 **检测到正在进行的冒险**\n"
                f"当前冒险: {current_game['theme']} (第{current_game['turn_count']}回合)\n"
                f"开始新冒险将自动暂停当前游戏。\n\n"
                f"确认开始新冒险吗？请再次发送指令确认，或发送其他消息取消。"
            )
            # 这里可以添加确认机制，为了简化先直接暂停
            await self._pause_current_game(user_id)
            yield event.plain_result(f"当前冒险《{current_game['theme']}》已暂停并保存。")

        default_theme = self.config.get("default_adventure_theme", "奇幻世界")
        game_theme = theme.strip() if theme else default_theme
        adventure_id = self._generate_adventure_id()

        # 游戏介绍
        session_timeout = self.config.get("session_timeout", 300)
        user_adventure_count = len(self.user_adventures.get(user_id, []))
        
        intro_message = (
            "🏰 **动态文字冒险游戏** 🏰\n\n"
            f"🎭 **主题**: {game_theme}\n"
            f"🆔 **冒险ID**: {adventure_id}\n"
            f"⏰ **超时设置**: {session_timeout}秒无操作自动暂停\n"
            f"📚 **你的冒险数**: {user_adventure_count}\n\n"
            "📜 **游戏说明**:\n"
            "• 直接输入你的行动来推进故事\n"
            "• 使用 `/暂停冒险` 可随时暂停游戏\n"
            "• 暂停后可正常使用其他功能\n"
            "• 使用 `/恢复冒险` 继续游戏\n"
            "• 使用 `/冒险历史` 查看所有冒险\n\n"
            "🎲 正在为你生成专属冒险..."
        )
        yield event.plain_result(intro_message)

        # 构建系统提示词
        system_prompt_template = self.config.get(
            "system_prompt_template",
            "你是一位经验丰富的文字冒险游戏主持人(Game Master)。你将在一个'{game_theme}'主题下，根据玩家的行动实时生成独特且逻辑连贯的故事情节。如果故事应该结束（玩家死亡、任务完成、故事自然结束等），请在回复的最后加上适当的结束标记，如'故事结束'、'游戏结束'、'你死了'、'任务完成'等。"
        )
        
        try:
            system_prompt = system_prompt_template.format(game_theme=game_theme)
        except KeyError:
            logger.error("系统提示词模板格式错误！缺少{game_theme}占位符")
            system_prompt = f"你是一位文字冒险游戏主持人，主题是'{game_theme}'。根据玩家行动生成有趣的故事情节。"

        # 创建游戏状态
        game_state = self._create_game_state(game_theme, system_prompt, adventure_id)

        # 生成开场故事
        try:
            llm_provider = self.context.get_using_provider()
            if not llm_provider:
                yield event.plain_result("❌ 抱歉，当前没有可用的LLM服务来开始冒险。请联系管理员配置。")
                return

            llm_response: LLMResponse = await llm_provider.text_chat(
                prompt="",
                session_id=event.get_session_id(),
                contexts=game_state["llm_conversation_context"],
            )
            
            if not llm_response or not llm_response.completion_text:
                yield event.plain_result("❌ 抱歉，AI无法生成开场故事。请稍后重试。")
                return
            
            story_text = llm_response.completion_text.strip()
            game_state["llm_conversation_context"].append({"role": "assistant", "content": story_text})
            game_state["is_active"] = True
            game_state["turn_count"] = 1

            # 启动游戏
            self.active_game_sessions[user_id] = game_state
            
            # 保存到用户冒险列表和详细数据
            self._add_adventure_to_user(user_id, game_state)
            self._save_adventure_details(user_id, adventure_id, game_state)
            self._save_user_data(user_id)

            response_text = (
                f"✨ **冒险开始！** ✨\n\n"
                f"{story_text}\n\n"
                f"**[💡 提示: 直接输入你的行动来继续冒险！]**"
            )
            yield event.plain_result(response_text)
            
            logger.info(f"用户 {user_id} 开始了新冒险 {adventure_id}: {game_theme}")

        except Exception as e:
            logger.error(f"开始冒险时LLM调用失败 [{user_id}]: {e}")
            yield event.plain_result(f"❌ 抱歉，无法开始冒险，LLM服务出现问题: {str(e)[:100]}")

    @filter.command("暂停冒险", alias={"pause_adventure", "暂停游戏"})
    async def pause_adventure(self, event: AstrMessageEvent):
        """暂停当前的冒险游戏"""
        user_id = event.get_sender_id()
        
        if user_id not in self.active_game_sessions:
            # 检查是否有任何冒险
            user_adventures = self.user_adventures.get(user_id, [])
            if not user_adventures:
                yield event.plain_result("❌ 你还没有任何冒险。使用 `/开始冒险` 开始新游戏。")
            else:
                active_adventures = [adv for adv in user_adventures if not adv.get("is_completed", False)]
                if not active_adventures:
                    yield event.plain_result("❌ 你没有正在进行的冒险。所有冒险都已完成。使用 `/开始冒险` 开始新游戏。")
                else:
                    yield event.plain_result("❌ 你当前没有活跃的冒险。使用 `/恢复冒险` 恢复之前暂停的游戏。")
            return

        game_state = self.active_game_sessions[user_id]
        await self._pause_current_game(user_id)
        
        yield event.plain_result(
            f"⏸️ **冒险已暂停**\n"
            f"冒险: {game_state['theme']}\n"
            f"ID: {game_state['adventure_id']}\n"
            f"回合数: {game_state['turn_count']}\n"
            f"你可以正常使用其他功能，使用 `/恢复冒险` 继续游戏。"
        )

    @filter.command("恢复冒险", alias={"resume_adventure", "继续游戏", "继续冒险"})
    async def resume_adventure(self, event: AstrMessageEvent, adventure_id: str = ""):
        """恢复暂停的冒险游戏"""
        user_id = event.get_sender_id()
        
        # 检查用户是否有冒险
        user_adventures = self.user_adventures.get(user_id, [])
        if not user_adventures:
            yield event.plain_result("❌ 你还没有任何冒险。使用 `/开始冒险` 开始新游戏。")
            return
        
        # 如果已有活跃游戏
        if user_id in self.active_game_sessions:
            current_game = self.active_game_sessions[user_id]
            if not adventure_id or current_game["adventure_id"] == adventure_id:
                yield event.plain_result(
                    f"🎮 **你的冒险已经在进行中！**\n"
                    f"冒险: {current_game['theme']}\n"
                    f"ID: {current_game['adventure_id']}\n"
                    f"回合数: {current_game['turn_count']}\n"
                    f"直接输入行动继续游戏。"
                )
                return
            else:
                # 用户想切换到不同的冒险
                yield event.plain_result(f"正在切换冒险，当前游戏《{current_game['theme']}》将被暂停...")
                await self._pause_current_game(user_id)

        # 找到可恢复的冒险
        available_adventures = [adv for adv in user_adventures if not adv.get("is_completed", False)]
        if not available_adventures:
            completed_count = len([adv for adv in user_adventures if adv.get("is_completed", False)])
            yield event.plain_result(
                f"❌ 你没有可以恢复的冒险。\n"
                f"所有 {completed_count} 个冒险都已完成。\n"
                f"使用 `/开始冒险` 开始新游戏，或使用 `/冒险历史` 查看历史记录。"
            )
            return

        # 确定要恢复的冒险ID
        target_adventure_id = adventure_id
        if not target_adventure_id:
            # 如果没有指定，使用当前选中的或最近的
            target_adventure_id = self.user_current_adventure.get(user_id, "")
            if not target_adventure_id or not any(adv["adventure_id"] == target_adventure_id for adv in available_adventures):
                # 使用最近的可用冒险
                available_adventures.sort(key=lambda x: x["last_action_time"], reverse=True)
                target_adventure_id = available_adventures[0]["adventure_id"]

        # 检查指定的冒险是否存在且可恢复
        target_adventure = None
        for adv in available_adventures:
            if adv["adventure_id"] == target_adventure_id:
                target_adventure = adv
                break
        
        if not target_adventure:
            if adventure_id:  # 用户指定了ID但没找到
                yield event.plain_result(
                    f"❌ 找不到ID为 {adventure_id} 的可恢复冒险。\n"
                    f"使用 `/冒险历史` 查看所有冒险，或使用 `/恢复冒险` 恢复最近的冒险。"
                )
            else:
                yield event.plain_result("❌ 没有找到可以恢复的冒险。")
            return

        # 恢复游戏
        if await self._resume_adventure(user_id, target_adventure_id):
            game_state = self.active_game_sessions[user_id]
            
            # 获取最后的故事内容
            last_story = "冒险继续..."
            for msg in reversed(game_state["llm_conversation_context"]):
                if msg["role"] == "assistant" and msg["content"].strip():
                    last_story = msg["content"]
                    break

            response_text = (
                f"▶️ **冒险恢复！**\n"
                f"冒险: {game_state['theme']}\n"
                f"ID: {game_state['adventure_id']}\n"
                f"回合数: {game_state['turn_count']}\n\n"
                f"📖 **当前情况**:\n{last_story}\n\n"
                f"**[💡 提示: 直接输入你的行动继续冒险！]**"
            )
            yield event.plain_result(response_text)
        else:
            yield event.plain_result("❌ 恢复游戏失败，冒险数据可能已损坏。请尝试开始新游戏。")

    @filter.command("冒险历史", alias={"adventure_history", "历史记录", "我的冒险"})
    async def adventure_history(self, event: AstrMessageEvent, page: str = "1"):
        """查看冒险历史记录"""
        user_id = event.get_sender_id()
        
        user_adventures = self.user_adventures.get(user_id, [])
        if not user_adventures:
            yield event.plain_result(
                "📚 **冒险历史**\n\n"
                "你还没有任何冒险记录。\n"
                "使用 `/开始冒险` 开始你的第一次冒险！"
            )
            return

        # 分页处理
        try:
            page_num = max(1, int(page))
        except (ValueError, TypeError):
            page_num = 1
            
        items_per_page = 10
        total_adventures = len(user_adventures)
        total_pages = (total_adventures + items_per_page - 1) // items_per_page
        page_num = min(page_num, total_pages)
        
        start_idx = (page_num - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_adventures)
        
        # 按时间排序（最新的在前）
        sorted_adventures = sorted(user_adventures, key=lambda x: x["last_action_time"], reverse=True)
        page_adventures = sorted_adventures[start_idx:end_idx]
        
        # 统计信息
        active_count = len([adv for adv in user_adventures if not adv.get("is_completed", False)])
        completed_count = len([adv for adv in user_adventures if adv.get("is_completed", False)])
        current_adventure_id = self.user_current_adventure.get(user_id, "")
        
        # 构建历史列表
        history_text = f"📚 **冒险历史** (第{page_num}/{total_pages}页)\n\n"
        history_text += f"📊 **统计**: 总计{total_adventures} | 进行中{active_count} | 已完成{completed_count}\n\n"
        
        for i, adventure in enumerate(page_adventures, start_idx + 1):
            # 状态标记
            status_icon = ""
            if adventure["adventure_id"] == current_adventure_id:
                if user_id in self.active_game_sessions:
                    status_icon = "🎮"  # 当前活跃
                else:
                    status_icon = "👆"  # 当前选中但暂停
            elif adventure.get("is_completed", False):
                completion_reason = adventure.get("completion_reason", "")
                if completion_reason == "victory":
                    status_icon = "🏆"
                elif completion_reason == "death":
                    status_icon = "💀"
                else:
                    status_icon = "📚"
            else:
                status_icon = "⏸️"
            
            # 时间格式化
            try:
                last_time = datetime.fromisoformat(adventure["last_action_time"])
                time_str = last_time.strftime("%m-%d %H:%M")
            except:
                time_str = "未知"
            
            # 主题截断
            theme = adventure["theme"]
            if len(theme) > 20:
                theme = theme[:20] + "..."
            
            history_text += (
                f"{status_icon} **{i}.** {theme}\n"
                f"   🆔 {adventure['adventure_id']} | "
                f"🎲 {adventure['turn_count']}回合 | "
                f"⏰ {time_str}\n"
            )
            
            # 完成状态说明
            if adventure.get("is_completed", False):
                completion_reason = adventure.get("completion_reason", "")
                reason_text = {
                    "victory": "胜利完成",
                    "death": "冒险失败", 
                    "story_end": "故事完结"
                }.get(completion_reason, "已完成")
                history_text += f"   ✅ {reason_text}\n"
            
            history_text += "\n"
        
        # 操作提示
        history_text += "**💡 操作提示**:\n"
        history_text += "• `/恢复冒险 [ID]` - 恢复指定冒险\n"
        history_text += "• `/冒险详情 [ID]` - 查看冒险详情\n"
        history_text += "• `/删除冒险 [ID]` - 删除指定冒险\n"
        
        if total_pages > 1:
            history_text += f"• `/冒险历史 [页码]` - 查看其他页 (1-{total_pages})\n"
        
        history_text += "\n📖 直接输入行动继续当前冒险，或开始新冒险！"
        
        yield event.plain_result(history_text)

    @filter.command("冒险详情", alias={"adventure_detail", "冒险信息"})
    async def adventure_detail(self, event: AstrMessageEvent, adventure_id: str = ""):
        """查看指定冒险的详细信息"""
        user_id = event.get_sender_id()
        
        user_adventures = self.user_adventures.get(user_id, [])
        if not user_adventures:
            yield event.plain_result("❌ 你还没有任何冒险记录。")
            return
        
        # 确定要查看的冒险ID
        target_adventure_id = adventure_id
        if not target_adventure_id:
            # 使用当前选中的冒险
            target_adventure_id = self.user_current_adventure.get(user_id, "")
            if not target_adventure_id:
                # 使用最新的冒险
                sorted_adventures = sorted(user_adventures, key=lambda x: x["last_action_time"], reverse=True)
                target_adventure_id = sorted_adventures[0]["adventure_id"]
        
        # 查找冒险摘要
        target_adventure = None
        for adv in user_adventures:
            if adv["adventure_id"] == target_adventure_id:
                target_adventure = adv
                break
        
        if not target_adventure:
            yield event.plain_result(f"❌ 找不到ID为 {adventure_id} 的冒险记录。使用 `/冒险历史` 查看所有冒险。")
            return
        
        # 加载详细数据
        game_state = self._load_adventure_details(user_id, target_adventure_id)
        if not game_state:
            yield event.plain_result(f"❌ 无法加载冒险 {target_adventure_id} 的详细数据。")
            return
        
        # 构建详情文本
        try:
            created_time = datetime.fromisoformat(target_adventure["created_time"])
            last_time = datetime.fromisoformat(target_adventure["last_action_time"])
            
            detail_text = f"🎭 **冒险详情**\n\n"
            detail_text += f"**基本信息**:\n"
            detail_text += f"🆔 ID: {target_adventure_id}\n"
            detail_text += f"🎯 主题: {target_adventure['theme']}\n"
            detail_text += f"📅 创建: {created_time.strftime('%Y-%m-%d %H:%M')}\n"
            detail_text += f"⏰ 最后活动: {last_time.strftime('%Y-%m-%d %H:%M')}\n"
            
            # 状态信息
            if target_adventure_id == self.user_current_adventure.get(user_id, ""):
                if user_id in self.active_game_sessions:
                    status = "🎮 当前活跃"
                else:
                    status = "👆 当前选中(暂停中)"
            elif target_adventure.get("is_completed", False):
                completion_reason = target_adventure.get("completion_reason", "")
                status_map = {
                    "victory": "🏆 胜利完成",
                    "death": "💀 冒险失败",
                    "story_end": "📚 故事完结"
                }
                status = status_map.get(completion_reason, "✅ 已完成")
                if "completion_time" in game_state:
                    try:
                        comp_time = datetime.fromisoformat(game_state["completion_time"])
                        status += f" ({comp_time.strftime('%m-%d %H:%M')})"
                    except:
                        pass
            else:
                status = "⏸️ 暂停中"
            
            detail_text += f"🎲 状态: {status}\n\n"
            
            # 游戏统计
            detail_text += f"**游戏统计**:\n"
            detail_text += f"🎯 回合数: {target_adventure['turn_count']}\n"
            detail_text += f"⚡ 行动数: {target_adventure.get('total_actions', target_adventure['turn_count'])}\n"
            
            # 获取最后几轮对话
            contexts = game_state.get("llm_conversation_context", [])
            if len(contexts) > 1:
                # 跳过系统提示词，显示最后的对话
                recent_contexts = []
                for ctx in reversed(contexts):
                    if ctx["role"] in ["user", "assistant"]:
                        recent_contexts.append(ctx)
                        if len(recent_contexts) >= 4:  # 最多显示2轮对话
                            break
                
                if recent_contexts:
                    detail_text += f"\n**最近对话**:\n"
                    for ctx in reversed(recent_contexts[-4:]):  # 按正确顺序显示
                        if ctx["role"] == "user" and ctx["content"] != "故事开始了，我的第一个场景是什么？":
                            content = ctx["content"][:100] + ("..." if len(ctx["content"]) > 100 else "")
                            detail_text += f"👤 你: {content}\n"
                        elif ctx["role"] == "assistant":
                            content = ctx["content"][:150] + ("..." if len(ctx["content"]) > 150 else "")
                            detail_text += f"🎭 GM: {content}\n"
            
            # 操作提示
            detail_text += f"\n**💡 可用操作**:\n"
            if not target_adventure.get("is_completed", False):
                detail_text += f"• `/恢复冒险 {target_adventure_id}` - 恢复这个冒险\n"
            detail_text += f"• `/删除冒险 {target_adventure_id}` - 删除这个冒险\n"
            detail_text += f"• `/冒险历史` - 返回历史列表\n"
            
            yield event.plain_result(detail_text)
            
        except Exception as e:
            logger.error(f"显示冒险详情失败 [{user_id}/{target_adventure_id}]: {e}")
            yield event.plain_result("❌ 显示冒险详情时出现错误。")

    @filter.command("删除冒险", alias={"delete_adventure", "清除冒险"})
    async def delete_adventure(self, event: AstrMessageEvent, adventure_id: str = ""):
        """删除指定的冒险记录"""
        user_id = event.get_sender_id()
        
        user_adventures = self.user_adventures.get(user_id, [])
        if not user_adventures:
            yield event.plain_result("❌ 你还没有任何冒险记录。")
            return
        
        # 确定要删除的冒险ID
        target_adventure_id = adventure_id
        if not target_adventure_id:
            # 如果在活跃游戏中，删除当前游戏
            if user_id in self.active_game_sessions:
                target_adventure_id = self.active_game_sessions[user_id]["adventure_id"]
            else:
                # 删除当前选中的冒险
                target_adventure_id = self.user_current_adventure.get(user_id, "")
                if not target_adventure_id:
                    yield event.plain_result("❌ 请指定要删除的冒险ID。使用 `/冒险历史` 查看所有冒险。")
                    return
        
        # 查找要删除的冒险
        target_adventure = None
        target_index = -1
        for i, adv in enumerate(user_adventures):
            if adv["adventure_id"] == target_adventure_id:
                target_adventure = adv
                target_index = i
                break
        
        if not target_adventure:
            yield event.plain_result(f"❌ 找不到ID为 {target_adventure_id} 的冒险记录。")
            return
        
        # 如果是活跃游戏，先从活跃会话中移除
        if user_id in self.active_game_sessions and self.active_game_sessions[user_id]["adventure_id"] == target_adventure_id:
            self.active_game_sessions.pop(user_id)
        
        # 从用户冒险列表中移除
        self.user_adventures[user_id].pop(target_index)
        
        # 如果是当前选中的冒险，更新选中状态
        if self.user_current_adventure.get(user_id) == target_adventure_id:
            remaining_adventures = [adv for adv in self.user_adventures[user_id] if not adv.get("is_completed", False)]
            if remaining_adventures:
                # 选择最新的未完成冒险
                remaining_adventures.sort(key=lambda x: x["last_action_time"], reverse=True)
                self.user_current_adventure[user_id] = remaining_adventures[0]["adventure_id"]
            else:
                self.user_current_adventure.pop(user_id, None)
        
        # 删除详细数据文件
        try:
            history_file = self._get_adventure_history_file_path(user_id, target_adventure_id)
            if os.path.exists(history_file):
                os.remove(history_file)
        except Exception as e:
            logger.error(f"删除冒险文件失败 [{user_id}/{target_adventure_id}]: {e}")
        
        # 保存用户数据
        self._save_user_data(user_id)
        
        # 状态描述
        status_desc = ""
        if target_adventure.get("is_completed", False):
            status_desc = "(已完成)"
        elif target_adventure_id in [adv["adventure_id"] for adv in self.active_game_sessions.values() if "adventure_id" in adv]:
            status_desc = "(活跃中)"
        else:
            status_desc = "(暂停中)"
        
        yield event.plain_result(
            f"🗑️ **冒险已删除**\n"
            f"冒险: {target_adventure['theme']} {status_desc}\n"
            f"ID: {target_adventure_id}\n"
            f"回合数: {target_adventure['turn_count']}\n\n"
            f"剩余冒险: {len(self.user_adventures.get(user_id, []))} 个\n"
            f"使用 `/冒险历史` 查看剩余冒险，或 `/开始冒险` 开始新游戏。"
        )
        
        logger.info(f"用户 {user_id} 删除了冒险 {target_adventure_id}: {target_adventure['theme']}")

    @filter.command("冒险状态", alias={"adventure_status", "游戏状态", "当前状态"})
    async def adventure_status(self, event: AstrMessageEvent):
        """查看当前冒险状态和总体统计"""
        user_id = event.get_sender_id()
        
        user_adventures = self.user_adventures.get(user_id, [])
        
        # 基本统计
        total_count = len(user_adventures)
        active_adventures = [adv for adv in user_adventures if not adv.get("is_completed", False)]
        completed_adventures = [adv for adv in user_adventures if adv.get("is_completed", False)]
        active_count = len(active_adventures)
        completed_count = len(completed_adventures)
        
        status_text = f"📊 **冒险状态总览**\n\n"
        status_text += f"**统计信息**:\n"
        status_text += f"📚 总冒险数: {total_count}\n"
        status_text += f"🎮 进行中: {active_count}\n"
        status_text += f"✅ 已完成: {completed_count}\n"
        
        if completed_count > 0:
            # 完成情况统计
            victory_count = len([adv for adv in completed_adventures if adv.get("completion_reason") == "victory"])
            death_count = len([adv for adv in completed_adventures if adv.get("completion_reason") == "death"])
            story_end_count = len([adv for adv in completed_adventures if adv.get("completion_reason") == "story_end"])
            other_count = completed_count - victory_count - death_count - story_end_count
            
            status_text += f"  └─ 🏆 胜利: {victory_count} | 💀 失败: {death_count} | 📚 完结: {story_end_count}"
            if other_count > 0:
                status_text += f" | 📝 其他: {other_count}"
            status_text += "\n"
        
        # 当前活跃游戏
        if user_id in self.active_game_sessions:
            current_game = self.active_game_sessions[user_id]
            try:
                last_action_time = datetime.fromisoformat(current_game["last_action_time"])
                session_timeout = self.config.get("session_timeout", 300)
                time_left = session_timeout - (datetime.now() - last_action_time).seconds
                time_left = max(0, time_left)
                
                status_text += f"\n**🎮 当前活跃冒险**:\n"
                status_text += f"🎭 主题: {current_game['theme']}\n"
                status_text += f"🆔 ID: {current_game['adventure_id']}\n"
                status_text += f"🎲 回合数: {current_game['turn_count']}\n"
                status_text += f"⚡ 行动数: {current_game.get('total_actions', current_game['turn_count'])}\n"
                status_text += f"⏰ 剩余时间: {time_left}秒\n"
                
                status_text += f"\n💡 直接输入行动继续游戏，或使用 `/暂停冒险` 暂停。"
                
            except Exception as e:
                logger.error(f"获取活跃游戏状态失败 [{user_id}]: {e}")
                status_text += f"\n**🎮 当前活跃冒险**: {current_game.get('theme', '未知')}\n"
                status_text += f"❌ 状态信息获取失败，建议重新开始游戏。"
        
        # 当前选中的冒险（如果不是活跃的）
        elif self.user_current_adventure.get(user_id):
            current_id = self.user_current_adventure[user_id]
            current_adventure = None
            for adv in user_adventures:
                if adv["adventure_id"] == current_id:
                    current_adventure = adv
                    break
            
            if current_adventure and not current_adventure.get("is_completed", False):
                try:
                    last_time = datetime.fromisoformat(current_adventure["last_action_time"])
                    status_text += f"\n**👆 当前选中冒险** (暂停中):\n"
                    status_text += f"🎭 主题: {current_adventure['theme']}\n"
                    status_text += f"🆔 ID: {current_adventure['adventure_id']}\n"
                    status_text += f"🎲 回合数: {current_adventure['turn_count']}\n"
                    status_text += f"⏰ 最后活动: {last_time.strftime('%m-%d %H:%M')}\n"
                    
                    status_text += f"\n💡 使用 `/恢复冒险` 继续这个冒险。"
                except:
                    status_text += f"\n**👆 当前选中冒险**: {current_adventure.get('theme', '未知')}"
        
        # 最近的冒险
        if not user_id in self.active_game_sessions and active_count > 0:
            recent_adventures = sorted(active_adventures, key=lambda x: x["last_action_time"], reverse=True)[:3]
            status_text += f"\n**📅 最近的冒险**:\n"
            for i, adv in enumerate(recent_adventures, 1):
                try:
                    last_time = datetime.fromisoformat(adv["last_action_time"])
                    time_str = last_time.strftime("%m-%d %H:%M")
                except:
                    time_str = "未知"
                
                theme = adv["theme"][:15] + ("..." if len(adv["theme"]) > 15 else "")
                status_text += f"  {i}. {theme} (第{adv['turn_count']}回合, {time_str})\n"
        
        # 操作提示
        status_text += f"\n**💡 可用操作**:\n"
        
        if user_id in self.active_game_sessions:
            status_text += "• 直接输入行动继续当前冒险\n"
            status_text += "• `/暂停冒险` - 暂停当前游戏\n"
        elif active_count > 0:
            status_text += "• `/恢复冒险` - 恢复最近的冒险\n"
            status_text += "• `/恢复冒险 [ID]` - 恢复指定冒险\n"
        
        status_text += "• `/开始冒险` - 开始新冒险\n"
        status_text += "• `/冒险历史` - 查看所有冒险\n"
        
        if total_count == 0:
            yield event.plain_result(
                "📊 **冒险状态总览**\n\n"
                "你还没有任何冒险记录。\n"
                "使用 `/开始冒险` 开始你的第一次冒险！\n\n"
                "💡 文字冒险游戏支持暂停恢复、多冒险管理等功能。"
            )
        else:
            yield event.plain_result(status_text)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("admin_clear_adventures", alias={"管理员清理冒险"})
    async def admin_clear_adventures(self, event: AstrMessageEvent, target_user: str = ""):
        """管理员命令：清理冒险数据"""
        if target_user:
            # 清理指定用户
            user_adventures_count = len(self.user_adventures.get(target_user, []))
            active_count = 1 if target_user in self.active_game_sessions else 0
            
            # 清理内存数据
            self.user_adventures.pop(target_user, None)
            self.user_current_adventure.pop(target_user, None)
            self.active_game_sessions.pop(target_user, None)
            
            # 清理文件
            file_count = 0
            try:
                user_file = self._get_user_data_file_path(target_user)
                if os.path.exists(user_file):
                    os.remove(user_file)
                    file_count += 1
                
                # 删除该用户的所有冒险历史文件
                if os.path.exists(self.history_dir):
                    for filename in os.listdir(self.history_dir):
                        if filename.startswith(f"adventure_{target_user}_"):
                            os.remove(os.path.join(self.history_dir, filename))
                            file_count += 1
            except Exception as e:
                logger.error(f"清理用户 {target_user} 的文件失败: {e}")
            
            yield event.plain_result(
                f"🧹 **管理员清理完成** (用户: {target_user})\n"
                f"已清理 {user_adventures_count} 个冒险记录\n"
                f"已清理 {active_count} 个活跃游戏\n"
                f"已删除 {file_count} 个文件"
            )
            logger.info(f"管理员 {event.get_sender_id()} 清理了用户 {target_user} 的冒险数据")
            
        else:
            # 清理所有数据
            total_adventures = sum(len(adventures) for adventures in self.user_adventures.values())
            total_users = len(self.user_adventures)
            active_count = len(self.active_game_sessions)
            
            # 清理内存中的数据
            self.active_game_sessions.clear()
            self.user_adventures.clear()
            self.user_current_adventure.clear()
            
            # 清理缓存文件
            file_count = 0
            try:
                # 删除用户数据文件
                if os.path.exists(self.cache_dir):
                    for filename in os.listdir(self.cache_dir):
                        if filename.startswith("user_") and filename.endswith(".json"):
                            os.remove(os.path.join(self.cache_dir, filename))
                            file_count += 1
                
                # 删除冒险历史文件
                if os.path.exists(self.history_dir):
                    for filename in os.listdir(self.history_dir):
                        if filename.startswith("adventure_") and filename.endswith(".json"):
                            os.remove(os.path.join(self.history_dir, filename))
                            file_count += 1
            except Exception as e:
                logger.error(f"清理缓存文件失败: {e}")
            
            yield event.plain_result(
                f"🧹 **管理员全面清理完成**\n"
                f"已清理 {total_users} 个用户\n"
                f"已清理 {total_adventures} 个冒险记录\n"
                f"已清理 {active_count} 个活跃游戏\n"
                f"已删除 {file_count} 个文件"
            )
            logger.info(f"管理员 {event.get_sender_id()} 清理了所有冒险数据: {total_users}用户, {total_adventures}冒险, {active_count}活跃")

    @filter.command("冒险帮助", alias={"adventure_help", "游戏帮助", "帮助"})
    async def adventure_help(self, event: AstrMessageEvent):
        """显示冒险游戏帮助信息"""
        help_text = (
            "🏰 **文字冒险游戏帮助** 🏰\n\n"
            "**🎮 基本指令**:\n"
            "• `/开始冒险 [主题]` - 开始新冒险\n"
            "• `/暂停冒险` - 暂停当前游戏\n"
            "• `/恢复冒险 [ID]` - 恢复冒险\n"
            "• `/冒险状态` - 查看当前状态\n"
            "• `/冒险历史 [页码]` - 查看所有冒险\n"
            "• `/冒险详情 [ID]` - 查看冒险详情\n"
            "• `/删除冒险 [ID]` - 删除冒险\n\n"
            "**✨ 游戏特色**:\n"
            "• 🎲 AI驱动的动态故事生成\n"
            "• ⏸️ 支持暂停/恢复，不影响其他功能\n"
            "• 📚 多冒险管理，同时进行多个故事\n"
            "• 💾 完整的历史记录和进度保存\n"
            "• 🏆 智能的游戏结束检测\n"
            "• ⏰ 智能超时管理\n\n"
            "**💡 使用技巧**:\n"
            "• 游戏中直接输入行动（不需要加/）\n"
            "• 可以随时暂停去使用其他功能\n"
            "• 支持多个冒险同时存在，随时切换\n"
            "• 超时会自动暂停，不会丢失进度\n"
            "• 支持自定义主题创建独特冒险\n"
            "• LLM会在合适时机自动结束故事\n\n"
            "**🎯 游戏状态**:\n"
            "• 🎮 活跃中 - 正在进行的冒险\n"
            "• ⏸️ 暂停中 - 可恢复的冒险\n"
            "• 🏆 胜利完成 - 成功完成任务\n"
            "• 💀 冒险失败 - 死亡或失败\n"
            "• 📚 故事完结 - 自然结束\n\n"
            f"**⚙️ 当前设置**:\n"
            f"• 超时时间: {self.config.get('session_timeout', 300)}秒\n"
            f"• 默认主题: {self.config.get('default_adventure_theme', '奇幻世界')}\n"
            f"• 自动保存: {self.config.get('auto_save_interval', 60)}秒\n\n"
            "**👑 管理员指令**:\n"
            "• `/admin_clear_adventures [用户ID]` - 清理冒险数据\n\n"
            "📖 开始你的文字冒险之旅吧！"
        )
        yield event.plain_result(help_text)

    async def terminate(self):
        """插件终止时保存所有数据并清理资源"""
        logger.info("正在终止 TextAdventurePlugin...")
        
        try:
            # 保存所有活跃游戏
            for user_id, game_state in self.active_game_sessions.items():
                game_state["is_active"] = False
                game_state["pause_time"] = datetime.now().isoformat()
                
                adventure_id = game_state["adventure_id"]
                self._save_adventure_details(user_id, adventure_id, game_state)
                self._add_adventure_to_user(user_id, game_state)
                self._save_user_data(user_id)
                logger.debug(f"保存活跃游戏: {user_id}/{adventure_id}")
            
            # 保存所有用户数据
            for user_id in self.user_adventures:
                self._save_user_data(user_id)
                logger.debug(f"保存用户数据: {user_id}")
        
        except Exception as e:
            logger.error(f"保存游戏数据时出错: {e}")
        
        # 清理内存
        active_count = len(self.active_game_sessions)
        total_users = len(self.user_adventures)
        total_adventures = sum(len(adventures) for adventures in self.user_adventures.values())
        
        self.active_game_sessions.clear()
        self.user_adventures.clear()
        self.user_current_adventure.clear()
        
        # 根据配置决定是否删除缓存文件
        if self.config.get("delete_cache_on_uninstall", False):
            try:
                if os.path.exists(self.cache_dir):
                    import shutil
                    shutil.rmtree(self.cache_dir)
                    logger.info("已删除所有游戏缓存文件")
            except Exception as e:
                logger.error(f"删除缓存目录失败: {e}")
        else:
            logger.info("保留游戏缓存文件（可通过配置修改此行为）")
        
        logger.info(f"TextAdventurePlugin 已终止 - 处理了 {total_users} 个用户, {total_adventures} 个冒险, {active_count} 个活跃游戏")
