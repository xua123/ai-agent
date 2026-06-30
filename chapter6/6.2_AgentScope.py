import os
import asyncio
from dotenv import load_dotenv
from typing import Optional, List, Type, Dict, Any
from pydantic import BaseModel, Field
import shortuuid

import agentscope
from agentscope.message import Msg
from agentscope.agent import AgentBase
from agentscope.pipeline import MsgHub, fanout_pipeline
from agentscope.model import OpenAIChatModel

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ==========================================
# 1. 数据模型定义 (Structured Output Models)
# ==========================================

class DiscussionModelCN(BaseModel):
    """讨论阶段的输出格式"""
    reach_agreement: bool = Field(
        description="是否已达成一致意见",
        default=False
    )
    confidence_level: int = Field(
        description="对当前推理的信心程度(1-10)",
        ge=1, le=10,
        default=5
    )
    key_evidence: Optional[str] = Field(
        description="支持你观点的关键证据",
        default=None
    )
    thought: str = Field(
        description="你的内部推理和策略思考过程",
        default=""
    )
    speak: str = Field(
        description="你在讨论中公开发表的言论（必须符合你角色的三国人物性格和口吻）",
        default=""
    )

class WerewolfKillModelCN(BaseModel):
    """狼人杀人阶段的输出格式"""
    target_name: str = Field(
        description="选择今晚要击杀的玩家姓名"
    )
    thought: str = Field(
        description="选择击杀该玩家的深层逻辑和战术考虑"
    )

class ProphetCheckModelCN(BaseModel):
    """预言家查验阶段的输出格式"""
    target_name: str = Field(
        description="选择要查验的存活玩家姓名"
    )
    thought: str = Field(
        description="为什么选择查验该玩家"
    )

class WitchActionModelCN(BaseModel):
    """女巫行动的输出格式"""
    use_antidote: bool = Field(
        description="是否使用解药救活今晚被杀的人"
    )
    use_poison: bool = Field(
        description="是否使用毒药毒杀一名玩家"
    )
    target_name: Optional[str] = Field(
        description="如果要使用毒药，请提供毒杀玩家的姓名（否则写为 null 或空字符串）",
        default=None
    )
    thought: str = Field(
        description="你使用解药或毒药的判断和推理依据"
    )

class VoteModelCN(BaseModel):
    """投票阶段的输出格式"""
    target_name: str = Field(
        description="你要投票投出局的玩家姓名"
    )
    thought: str = Field(
        description="你投票给该玩家的理由"
    )

# ==========================================
# 2. 三国角色默认兜底回复 (防止 API 额度耗尽导致游戏中断)
# ==========================================

DEFAULT_PEOPLE_SP_DISCUSS = {
    "孙权": "曹操势大，周瑜多谋，孤以为当徐徐图之，勿要自乱阵脚。",
    "周瑜": "公瑾在此，何惧老贼！曹操狼子野心，若不尽早除去，恐对我们所有人都不利。",
    "曹操": "顺我者昌，逆我者亡！孤昨夜窥见天机，某些人表面忠义，实则是隐藏的叛逆。",
    "张飞": "俺老张行事粗鲁，但眼里容不得沙子！哪个是狼人，出来与俺大战三百回合！",
    "司马懿": "世事如棋，乾坤莫测。仲达静观其变，诸位且先行试探，狐狸尾巴终会露出来。",
    "赵云": "子龙奉命护卫，必当秉公执法，坚守正道！若有作恶者，云枪下绝不留情。"
}

# ==========================================
# 3. 智能体定义
# ==========================================

class ThreeKingdomsAgent(AgentBase):
    def __init__(self, name: str, role: str, character: str, sys_prompt: str, model):
        super().__init__()
        self.name = name
        self.role = role
        self.character = character
        self.sys_prompt = sys_prompt
        self.model = model
        self.memory = [
            {"role": "system", "content": sys_prompt}
        ]

    async def observe(self, msg: Msg | list[Msg] | None) -> None:
        if msg is None:
            return
        if isinstance(msg, list):
            for m in msg:
                await self.observe(m)
            return
        
        # 排除系统主持人通知自己的私人身份信息等
        if msg.name == "游戏主持人" and "扮演" in msg.content and self.name not in msg.content:
            return

        role = "assistant" if msg.name == self.name else "user"
        self.memory.append({"role": role, "content": f"【{msg.name}】说: {msg.content}"})

    async def reply(self, x: Msg | None = None, structured_model: Optional[Type[BaseModel]] = None) -> Msg:
        if x is not None:
            await self.observe(x)

        parsed_obj = None
        content_text = ""

        try:
            # 调用大语言模型，并传递结构化模型定义
            response = await self.model(
                self.memory, 
                structured_model=structured_model
            )

            # 提取文本
            if response.content:
                texts = []
                for block in response.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif hasattr(block, "text"):
                        texts.append(block.text)
                content_text = "\n".join(texts)

            # 尝试解析 structured_model
            if structured_model is not None:
                # 尝试从 metadata 中读取已解析字段
                if response.metadata:
                    try:
                        fields = structured_model.__fields__.keys()
                        data = {k: response.metadata[k] for k in fields if k in response.metadata}
                        if data:
                            parsed_obj = structured_model(**data)
                    except Exception:
                        pass
                
                # 兜底从文本中寻找 JSON
                if parsed_obj is None and content_text:
                    try:
                        import json
                        from json_repair import repair_json
                        start = content_text.find("{")
                        end = content_text.rfind("}")
                        if start != -1 and end != -1:
                            json_str = content_text[start:end+1]
                            repaired = repair_json(json_str)
                            data = json.loads(repaired)
                            parsed_obj = structured_model(**data)
                    except Exception:
                        pass

        except Exception as e:
            # 记录 API 调用异常，生成兜底应答
            pass

        # 如果没有成功解析出 Pydantic 对象，则进行硬编码逻辑兜底
        if structured_model is not None and parsed_obj is None:
            parsed_obj = self._get_fallback_response(structured_model)
            # 将兜底的发言或思考内容拼回 content_text
            if hasattr(parsed_obj, "speak"):
                content_text = parsed_obj.speak
            elif hasattr(parsed_obj, "target_name"):
                content_text = f"我选择行动目标：{parsed_obj.target_name}。"

        msg = Msg(name=self.name, content=content_text, role="assistant")
        if parsed_obj is not None:
            # 在 metadata 中保存解析后的对象，以供外部程序分析使用
            msg.metadata["parsed"] = parsed_obj

        # 写入自己的记忆
        self.memory.append({"role": "assistant", "content": content_text})
        return msg

    def _get_fallback_response(self, model_cls: Type[BaseModel]) -> BaseModel:
        """根据当前类，生成角色的兜底 Pydantic 对象"""
        if model_cls == DiscussionModelCN:
            speak_text = DEFAULT_PEOPLE_SP_DISCUSS.get(self.name, "诸位，局势不明，我且静观其言。")
            return DiscussionModelCN(
                reach_agreement=False,
                confidence_level=5,
                key_evidence="API失效，转为默认发言",
                thought="API失效，使用保底三国性格台词发言",
                speak=speak_text
            )
        elif model_cls == WerewolfKillModelCN:
            # 狼人优先击杀曹操（预言家）
            return WerewolfKillModelCN(
                target_name="曹操",
                thought="曹操足智多谋，且有枭雄之才，若不除之，必为大患。"
            )
        elif model_cls == ProphetCheckModelCN:
            # 预言家优先查验孙权
            return ProphetCheckModelCN(
                target_name="孙权",
                thought="孙权坐拥江东，行事稳重，孤需查明其是敌是友。"
            )
        elif model_cls == WitchActionModelCN:
            # 女巫救曹操，不毒人
            return WitchActionModelCN(
                use_antidote=True,
                use_poison=False,
                target_name=None,
                thought="曹操被袭击，先用解药救下他以图后效。"
            )
        elif model_cls == VoteModelCN:
            # 投票阶段，狼人投曹操，好人投孙权，村民投孙权
            target = "孙权" if self.role != "狼人" else "曹操"
            return VoteModelCN(
                target_name=target,
                thought="根据目前大家的发言和嫌疑，此人最可疑。"
            )
        return model_cls()

# ==========================================
# 4. 游戏管理器类 (Game Control Layer)
# ==========================================

class ThreeKingdomsWerewolfGame:
    def __init__(self, model):
        self.model = model
        self.players = []
        self.alive_players = []
        self.werewolves = []
        self.prophet = None
        self.witch = None
        self.villagers = []
        self.game_over = False
        self.winner = None
        self.rounds = 0
        self.has_witch_antidote = True
        self.has_witch_poison = True

    async def announce(self, content: str) -> Msg:
        print(f"游戏主持人: 📢 {content}")
        return Msg(name="游戏主持人", content=content, role="user")

    def init_players(self):
        roles_config = [
            {"name": "孙权", "role": "狼人", "character": "孙权", "personality": "沉稳大局观，注重江山，言语有主见，喜欢权衡利弊，防备心重。"},
            {"name": "周瑜", "role": "狼人", "character": "周瑜", "personality": "智谋过人，雄姿英发，言语骄傲自负但极具谋略，重义气，对曹操和司马懿有戒心。"},
            {"name": "曹操", "role": "预言家", "character": "曹操", "personality": "枭雄本色，多疑狡诈，霸气侧漏，喜欢掌控局势，常有豪壮之言。"},
            {"name": "张飞", "role": "女巫", "character": "张飞", "personality": "勇猛粗犷，粗中有细，重情重义，言语豪爽大声，脾气火爆，急性子。"},
            {"name": "司马懿", "role": "村民", "character": "司马懿", "personality": "深谋远虑，隐忍内敛，言语沉稳，喜欢以静制动，暗藏心机，善于洞察人心。"},
            {"name": "赵云", "role": "村民", "character": "赵云", "personality": "忠肝义胆，一身是胆，言语谦逊有礼，行事严谨公正，坚守护卫职责。"}
        ]
        
        self.players = []
        self.werewolves = []
        self.villagers = []
        
        for cfg in roles_config:
            prompt = f"""你是三国时期的{cfg['character']}，在这场三国狼人杀游戏中扮演{cfg['role']}。
你的性格特点是：{cfg['personality']}

【游戏规则及你的策略】：
1. 你必须严格扮演{cfg['character']}，在所有发言中体现你的性格特点和口吻。
2. 你的游戏身份是{cfg['role']}。
   - 如果你是狼人：夜晚可以与队友商量并杀掉一名玩家，白天需要伪装自己，误导好人。
   - 如果你是预言家：夜晚可以查验一名存活玩家的真实身份（好人或狼人）。
   - 如果你是女巫：拥有一瓶解药（可以救活夜晚被杀的人）和一瓶毒药（可以毒杀一名玩家），每瓶药只能使用一次。
   - 如果你是村民：没有任何特异功能，白天需要根据大家的言论认真推理，投出狼人。
3. 请严格按照系统指定的输出格式进行回复。
"""
            agent = ThreeKingdomsAgent(
                name=cfg['name'],
                role=cfg['role'],
                character=cfg['character'],
                sys_prompt=prompt,
                model=self.model
            )
            self.players.append(agent)
            
            if cfg['role'] == "狼人":
                self.werewolves.append(agent)
            elif cfg['role'] == "预言家":
                self.prophet = agent
            elif cfg['role'] == "女巫":
                self.witch = agent
            else:
                self.villagers.append(agent)
                
        self.alive_players = list(self.players)

        # 游戏初始化通告
        for p in self.players:
            role_desc = "夜晚可以击杀一名玩家" if p.role == "狼人" else \
                        "夜晚可以查验一名玩家身份" if p.role == "预言家" else \
                        "拥有一瓶解药和毒药，可在夜晚使用" if p.role == "女巫" else \
                        "没有特殊技能，白天参与讨论与投票"
            print(f"游戏主持人: 📢 【{p.name}】你在这场三国狼人杀中扮演{p.role}，你的角色是{p.character}。{role_desc}")

    async def werewolf_phase(self) -> Optional[str]:
        await self.announce(f"🌙 第 {self.rounds} 夜降临，天黑请闭眼...")
        await self.announce("🐺 狼人请睁眼，选择今晚要击杀的目标...")
        alive_wolves = [w for w in self.werewolves if w in self.alive_players]
        if not alive_wolves:
            await self.announce("没有存活的狼人。")
            return None
            
        alive_names = "、".join([p.name for p in self.alive_players])
        announcement = await self.announce(f"狼人们，请讨论今晚的击杀目标。存活玩家：{alive_names}")
        
        # 狼人建立 MsgHub 沟通频道
        async with MsgHub(
            alive_wolves,
            enable_auto_broadcast=True,
            announcement=announcement
        ) as werewolves_hub:
            # 讨论 2 个轮次
            for _ in range(2):
                for wolf in alive_wolves:
                    msg = Msg(name="游戏主持人", content="狼人队友，请就今晚的击杀目标发表你的分析和意见。", role="user")
                    response = await wolf(msg, structured_model=DiscussionModelCN)
                    speak_text = ""
                    if "parsed" in response.metadata and hasattr(response.metadata["parsed"], "speak"):
                        speak_text = response.metadata["parsed"].speak
                    else:
                        speak_text = response.content
                    print(f"{wolf.name}: {speak_text}")
                    
            # 投票击杀阶段
            werewolves_hub.set_auto_broadcast(False)
            kill_msg = Msg(name="游戏主持人", content="请选择击杀目标", role="user")
            kill_votes = await fanout_pipeline(
                alive_wolves,
                msg=kill_msg,
                structured_model=WerewolfKillModelCN,
                enable_gather=True
            )
            
            vote_counts = {}
            for wolf, res in zip(alive_wolves, kill_votes):
                target = ""
                if "parsed" in res.metadata and hasattr(res.metadata["parsed"], "target_name"):
                    target = res.metadata["parsed"].target_name
                
                if target:
                    target = target.strip()
                    print(f"{wolf.name}: 我选择投票击杀 {target}。")
                    vote_counts[target] = vote_counts.get(target, 0) + 1
                    
            victim_name = None
            if vote_counts:
                victim_name = max(vote_counts, key=vote_counts.get)
                # 验证是否是存活玩家
                alive_names_list = [p.name for p in self.alive_players]
                if victim_name not in alive_names_list:
                    # 默认杀第一个非狼人玩家
                    non_wolves = [p.name for p in self.alive_players if p not in self.werewolves]
                    victim_name = non_wolves[0] if non_wolves else alive_names_list[0]
            else:
                non_wolves = [p.name for p in self.alive_players if p not in self.werewolves]
                victim_name = non_wolves[0] if non_wolves else self.alive_players[0].name
                
            return victim_name

    async def prophet_phase(self):
        await self.announce("🔮 预言家请睁眼，选择要查验的玩家...")
        if self.prophet not in self.alive_players:
            await self.announce("预言家已阵亡。")
            return
            
        alive_names = "、".join([p.name for p in self.alive_players if p != self.prophet])
        msg = Msg(name="游戏主持人", content=f"请选择你要查验的存活玩家姓名。存活玩家：{alive_names}", role="user")
        response = await self.prophet(msg, structured_model=ProphetCheckModelCN)
        
        target = ""
        if "parsed" in response.metadata and hasattr(response.metadata["parsed"], "target_name"):
            target = response.metadata["parsed"].target_name
            
        if target:
            target = target.strip()
            print(f"{self.prophet.name}: 我要查验{target}。")
            target_player = next((p for p in self.players if p.name == target), None)
            is_werewolf = "是狼人" if (target_player and target_player.role == "狼人") else "是好人"
            
            result_msg = f"查验结果：{target}{is_werewolf}"
            await self.announce(result_msg)
            # 存入预言家记忆
            self.prophet.memory.append({"role": "user", "content": f"系统提示：你查验的 【{target}】 {is_werewolf}。"})

    async def witch_phase(self, victim_name: Optional[str]) -> tuple[bool, Optional[str]]:
        await self.announce("🧙‍♀️ 女巫请睁眼...")
        if self.witch not in self.alive_players:
            await self.announce("女巫已阵亡。")
            return False, None
            
        if victim_name:
            await self.announce(f"今晚{victim_name}被狼人击杀")
        else:
            await self.announce("今晚是平安夜，无人被杀。")
            
        prompt_content = f"今晚被杀的人是：{victim_name}。你有解药（剩余: {1 if self.has_witch_antidote else 0}）和毒药（剩余: {1 if self.has_witch_poison else 0}）。请决定你的行动。"
        msg = Msg(name="游戏主持人", content=prompt_content, role="user")
        response = await self.witch(msg, structured_model=WitchActionModelCN)
        
        use_antidote = False
        use_poison = False
        poison_target = None
        
        if "parsed" in response.metadata and hasattr(response.metadata["parsed"], "use_antidote"):
            parsed = response.metadata["parsed"]
            use_antidote = parsed.use_antidote
            use_poison = parsed.use_poison
            poison_target = parsed.target_name
            
        saved = False
        poisoned_name = None
        
        if use_antidote and self.has_witch_antidote and victim_name:
            self.has_witch_antidote = False
            saved = True
            print(f"{self.witch.name}: 我昨晚使用了解药救了{victim_name}，现在解药已经用掉了。")
            await self.announce(f"你使用解药救了{victim_name}")
            
        if use_poison and self.has_witch_poison and poison_target:
            alive_names_list = [p.name for p in self.alive_players]
            if poison_target in alive_names_list:
                self.has_witch_poison = False
                poisoned_name = poison_target
                print(f"{self.witch.name}: 我选择对 {poison_target} 使用毒药。")
                await self.announce(f"你使用毒药毒杀了{poison_target}")
                
        return saved, poisoned_name

    async def day_phase(self, killed_name: Optional[str], poisoned_name: Optional[str]):
        await self.announce(f"☀️ 第 {self.rounds} 天天亮了，请大家睁眼...")
        
        deaths = []
        if killed_name:
            deaths.append(killed_name)
        if poisoned_name:
            deaths.append(poisoned_name)
            
        if not deaths:
            await self.announce("昨夜平安无事，无人死亡。")
        else:
            for d in deaths:
                await self.announce(f"【{d}】今早被发现死在林中。")
                dead_player = next((p for p in self.players if p.name == d), None)
                if dead_player in self.alive_players:
                    self.alive_players.remove(dead_player)
                    
        if self.check_game_over():
            return
            
        # 自由讨论阶段
        alive_names = "、".join([p.name for p in self.alive_players])
        announcement = await self.announce(f"现在开始自由讨论。存活玩家：{alive_names}")
        
        async with MsgHub(
            self.alive_players,
            enable_auto_broadcast=True,
            announcement=announcement
        ) as day_hub:
            for player in self.alive_players:
                msg = Msg(name="游戏主持人", content="请分析当前局势并表达你的观点。", role="user")
                response = await player(msg, structured_model=DiscussionModelCN)
                
                speak_text = ""
                if "parsed" in response.metadata and hasattr(response.metadata["parsed"], "speak"):
                    speak_text = response.metadata["parsed"].speak
                else:
                    speak_text = response.content
                print(f"{player.name}: {speak_text}")
                
        # 投票阶段
        vote_announcement = await self.announce("请投票选择要淘汰的玩家")
        votes = await fanout_pipeline(
            self.alive_players,
            msg=vote_announcement,
            structured_model=VoteModelCN,
            enable_gather=True
        )
        
        vote_counts = {}
        for player, res in zip(self.alive_players, votes):
            target = ""
            if "parsed" in res.metadata and hasattr(res.metadata["parsed"], "target_name"):
                target = res.metadata["parsed"].target_name
                
            if target:
                target = target.strip()
                print(f"{player.name}: 我选择投票给 {target}。")
                vote_counts[target] = vote_counts.get(target, 0) + 1
                
        voted_out_name = None
        if vote_counts:
            voted_out_name = max(vote_counts, key=vote_counts.get)
            alive_names_list = [p.name for p in self.alive_players]
            if voted_out_name not in alive_names_list:
                voted_out_name = None
                
        if voted_out_name:
            await self.announce(f"根据投票结果，【{voted_out_name}】被投出局。")
            voted_player = next((p for p in self.players if p.name == voted_out_name), None)
            if voted_player in self.alive_players:
                self.alive_players.remove(voted_player)
        else:
            await self.announce("投票结果未达成多数，无人出局。")
            
        self.check_game_over()

    def check_game_over(self) -> bool:
        alive_wolves = [p for p in self.alive_players if p.role == "狼人"]
        alive_good = [p for p in self.alive_players if p.role != "狼人"]
        
        if not alive_wolves:
            self.game_over = True
            self.winner = "好人阵营"
            return True
        if len(alive_wolves) >= len(alive_good):
            self.game_over = True
            self.winner = "狼人阵营"
            return True
        return False

    async def start(self):
        await self.announce("三国狼人杀游戏开始！参与者：孙权、周瑜、曹操、张飞、司马懿、赵云")
        self.init_players()
        await self.announce(f"游戏设置完成，共 {len(self.alive_players)} 名玩家")
        
        while not self.game_over and self.rounds < 5:
            self.rounds += 1
            print(f"\n=== 第 {self.rounds} 轮游戏 ===")
            
            # 狼人杀人
            victim_name = await self.werewolf_phase()
            
            # 预言家验人
            await self.prophet_phase()
            
            # 女巫用药
            saved, poisoned_name = await self.witch_phase(victim_name)
            
            # 白天阶段
            killed_name = None if saved else victim_name
            await self.day_phase(killed_name, poisoned_name)
            
        print(f"\n=== 游戏结束 ===")
        if self.winner:
            print(f"🎉 胜利者是：{self.winner}！")
        else:
            print("游戏平局（超出最大轮数）。")

# ==========================================
# 5. 主程序入口
# ==========================================

async def main():
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model_name = os.getenv("LLM_MODEL_ID") or os.getenv("MODEL_NAME") or "gpt-4o"

    # 初始化 Model 实例
    model = OpenAIChatModel(
        model_name=model_name,
        api_key=api_key,
        client_kwargs={"base_url": base_url},
        generate_kwargs={"temperature": 0.3}
    )

    # 初始化 AgentScope 基础配置
    agentscope.init(project="ThreeKingdomsWerewolf", name="WerewolfGame", logging_level="WARNING")

    # 开始游戏
    game = ThreeKingdomsWerewolfGame(model=model)
    await game.start()

if __name__ == "__main__":
    asyncio.run(main())
