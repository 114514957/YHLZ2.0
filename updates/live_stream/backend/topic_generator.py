import random
import logging

logger = logging.getLogger(__name__)


class TopicGenerator:
    def __init__(self):
        self.topics = {
            "general": [
                "今天大家过得怎么样？",
                "最近有什么好玩的事情吗？",
                "你们最喜欢的游戏是什么？",
                "最近看了什么好看的电影或动画？",
                "周末打算做什么？",
                "你们平时喜欢听什么音乐？",
                "最喜欢的食物是什么？",
                "如果能去任何地方旅行，你想去哪里？",
                "最喜欢的季节是什么？",
                "有没有什么特别的爱好？"
            ],
            "game": [
                "最近在玩什么游戏？",
                "最喜欢的游戏类型是什么？",
                "有没有什么游戏推荐？",
                "玩游戏的时候最喜欢做什么？",
                "游戏里最难忘的经历是什么？",
                "喜欢单机游戏还是多人游戏？",
                "有没有什么游戏成就很难达成？",
                "游戏中的角色你们最喜欢谁？",
                "最喜欢的游戏配乐是哪首？",
                "有没有什么游戏让你感动过？"
            ],
            "anime": [
                "最近在追什么番？",
                "最喜欢的动画是什么？",
                "有没有什么动画推荐？",
                "最喜欢的动画角色是谁？",
                "动画里最难忘的场景是什么？",
                "喜欢什么类型的动画？",
                "有没有什么动画看了很多遍？",
                "最喜欢的动画主题曲是哪首？",
                "动画里最感人的瞬间是什么？",
                "有没有什么动画让你哭过？"
            ],
            "tech": [
                "最近关注什么科技新闻？",
                "最喜欢的科技产品是什么？",
                "有没有什么新科技让你很期待？",
                "平时用什么手机/电脑？",
                "最喜欢的编程语言是什么？",
                "有没有什么技术想学？",
                "最喜欢的科技公司是哪家？",
                "觉得未来最有前景的技术是什么？",
                "有没有什么科技产品觉得没必要买？",
                "平时喜欢折腾什么数码产品？"
            ],
            "food": [
                "今天吃什么好吃的了？",
                "最喜欢的菜是什么？",
                "有没有什么美食推荐？",
                "会做饭吗？最拿手的菜是什么？",
                "最喜欢的零食是什么？",
                "有没有什么食物不吃的？",
                "最喜欢的饮料是什么？",
                "有没有什么网红美食想试试？",
                "最喜欢的餐厅是哪家？",
                "有没有什么美食让你念念不忘？"
            ],
            "live": [
                "今天直播大家想看什么？",
                "觉得今天的直播怎么样？",
                "有没有什么想让我做的？",
                "喜欢什么类型的直播内容？",
                "有没有什么问题想问我？",
                "觉得直播节奏怎么样？",
                "有没有什么建议？",
                "下次直播想玩什么？",
                "最喜欢直播里的哪个环节？",
                "有没有什么想让我展示的？"
            ]
        }
        
        self.keyword_topic_map = {
            "游戏": "game",
            "动画": "anime",
            "番": "anime",
            "科技": "tech",
            "电脑": "tech",
            "手机": "tech",
            "吃": "food",
            "美食": "food",
            "饭": "food",
            "直播": "live",
            "互动": "live"
        }

    def generate_topic(self, context_history=None, topic_type=None):
        if context_history and not topic_type:
            topic_type = self._infer_topic_type(context_history)
        
        if topic_type and topic_type in self.topics:
            topics = self.topics[topic_type]
        else:
            all_topics = []
            for category in self.topics.values():
                all_topics.extend(category)
            topics = all_topics
        
        return random.choice(topics)

    def generate_multiple_topics(self, count=3, context_history=None, topic_type=None):
        if context_history and not topic_type:
            topic_type = self._infer_topic_type(context_history)
        
        if topic_type and topic_type in self.topics:
            topics = self.topics[topic_type]
        else:
            all_topics = []
            for category in self.topics.values():
                all_topics.extend(category)
            topics = all_topics
        
        return random.sample(topics, min(count, len(topics)))

    def _infer_topic_type(self, context_history):
        if not context_history:
            return None
        
        text = " ".join(str(item.get("content", "") if isinstance(item, dict) else str(item)) for item in context_history)
        
        for keyword, topic_type in self.keyword_topic_map.items():
            if keyword in text:
                return topic_type
        
        return None

    def get_topic_types(self):
        return list(self.topics.keys())


class ChatFlowController:
    def __init__(self):
        self.topic_generator = TopicGenerator()
        self.last_topic_time = 0
        self.topic_interval = 300

    async def check_and_generate_topic(self, danmaku_history, vts_plugin=None):
        if len(danmaku_history) == 0:
            return None
        
        recent_danmaku = danmaku_history[-20:]
        
        recent_text = " ".join(d.get("content", "") for d in recent_danmaku)
        
        if len(recent_text) < 10:
            topic = self.topic_generator.generate_topic(recent_danmaku)
            return topic
        
        return None


topic_generator = TopicGenerator()
chat_flow_controller = ChatFlowController()