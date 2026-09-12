import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class ExpressionController:
    def __init__(self):
        self.expressions = {
            "happy": {
                "name": "happy",
                "hotkey": "happy_expression",
                "keywords": ["开心", "高兴", "好棒", "赞", "厉害", "太好了", "太棒了", "不错", "喜欢", "爱你", "谢谢", "感谢"],
                "emojis": ["😊", "😄", "😆", "🤩", "😎", "🥰", "😍", "👍", "👏", "🎉"],
                "color": "#FFD700"
            },
            "sad": {
                "name": "sad",
                "hotkey": "sad_expression",
                "keywords": ["难过", "伤心", "糟糕", "遗憾", "可惜", "失望", "失落", "沮丧", "哭"],
                "emojis": ["😢", "😭", "😔", "😞", "😓", "💔"],
                "color": "#4169E1"
            },
            "surprised": {
                "name": "surprised",
                "hotkey": "surprised_expression",
                "keywords": ["惊讶", "哇", "厉害", "没想到", "居然", "竟然", "震惊", "不可思议", "神奇"],
                "emojis": ["😲", "😳", "🤯", "😱", "😨", "🙀", "👀"],
                "color": "#FF69B4"
            },
            "neutral": {
                "name": "neutral",
                "hotkey": "neutral_expression",
                "keywords": [],
                "emojis": ["😐", "😶", "😌"],
                "color": "#808080"
            },
            "angry": {
                "name": "angry",
                "hotkey": "angry_expression",
                "keywords": ["生气", "愤怒", "可恶", "讨厌", "烦", "气死", "过分", "不满"],
                "emojis": ["😠", "😡", "🤬", "😤", "💢"],
                "color": "#FF4500"
            },
            "shy": {
                "name": "shy",
                "hotkey": "shy_expression",
                "keywords": ["害羞", "脸红", "不好意思", "尴尬", "难为情"],
                "emojis": ["😳", "🥺", "🙈", "😖", "😣"],
                "color": "#FFB6C1"
            },
            "excited": {
                "name": "excited",
                "hotkey": "excited_expression",
                "keywords": ["激动", "兴奋", "期待", "开心", "冲", "加油", "冲冲冲", "太棒了"],
                "emojis": ["🤩", "😆", "🎉", "🎊", "🔥", "💪"],
                "color": "#FF6347"
            },
            "sleepy": {
                "name": "sleepy",
                "hotkey": "sleepy_expression",
                "keywords": ["困", "累", "睡觉", "休息", "晚安", "熬夜"],
                "emojis": ["😴", "🥱", "😪", "😌", "💤"],
                "color": "#9370DB"
            },
            "confused": {
                "name": "confused",
                "hotkey": "confused_expression",
                "keywords": ["疑惑", "不懂", "什么", "怎么", "为什么", "啥", "蒙了", "懵"],
                "emojis": ["😕", "🤔", "😟", "🙄", "😧"],
                "color": "#98FB98"
            },
            "laugh": {
                "name": "laugh",
                "hotkey": "laugh_expression",
                "keywords": ["哈哈", "笑死", "搞笑", "好玩", "有趣", "滑稽"],
                "emojis": ["😂", "🤣", "😆", "😹", "🤪"],
                "color": "#FFD700"
            },
            "cry": {
                "name": "cry",
                "hotkey": "cry_expression",
                "keywords": ["哭", "流泪", "感动", "伤心", "难过", "泪目"],
                "emojis": ["😭", "😢", "🥺", "😿", "💧"],
                "color": "#1E90FF"
            }
        }
        
        self._current_expression = "neutral"
        self._expression_history = []
        self._max_history_length = 20

    def analyze_expression(self, text: str) -> str:
        if not text:
            return "neutral"
        
        scores = {expr: 0 for expr in self.expressions}
        
        for expr_name, expr_data in self.expressions.items():
            for keyword in expr_data["keywords"]:
                if keyword in text:
                    scores[expr_name] += 1
            
            for emoji in expr_data["emojis"]:
                if emoji in text:
                    scores[expr_name] += 2
        
        max_score = max(scores.values())
        
        if max_score == 0:
            return "neutral"
        
        best_expr = max(scores, key=scores.get)
        
        self._expression_history.append((text, best_expr))
        if len(self._expression_history) > self._max_history_length:
            self._expression_history.pop(0)
        
        self._current_expression = best_expr
        
        return best_expr

    def analyze_with_confidence(self, text: str) -> Dict:
        if not text:
            return {"expression": "neutral", "confidence": 0.0, "reasons": []}
        
        scores = {expr: 0 for expr in self.expressions}
        reasons = []
        
        for expr_name, expr_data in self.expressions.items():
            for keyword in expr_data["keywords"]:
                if keyword in text:
                    scores[expr_name] += 1
                    reasons.append(f"包含关键词 '{keyword}'")
            
            for emoji in expr_data["emojis"]:
                if emoji in text:
                    scores[expr_name] += 2
                    reasons.append(f"包含表情 '{emoji}'")
        
        max_score = max(scores.values())
        total_score = sum(scores.values())
        
        if max_score == 0:
            return {"expression": "neutral", "confidence": 0.0, "reasons": []}
        
        best_expr = max(scores, key=scores.get)
        confidence = max_score / max(total_score, 1)
        
        return {
            "expression": best_expr,
            "confidence": round(confidence, 2),
            "reasons": reasons[:3]
        }

    def get_expression_info(self, expression_name: str) -> Dict:
        return self.expressions.get(expression_name, self.expressions["neutral"])

    def get_all_expressions(self) -> List[Dict]:
        return [self.expressions[name] for name in self.expressions]

    def get_current_expression(self) -> str:
        return self._current_expression

    def get_expression_history(self) -> List:
        return self._expression_history

    def set_expression(self, expression_name: str):
        if expression_name in self.expressions:
            self._current_expression = expression_name
            return True
        return False

    def reset(self):
        self._current_expression = "neutral"
        self._expression_history = []


class SentimentAnalyzer:
    def __init__(self):
        self._positive_words = [
            "开心", "高兴", "好棒", "赞", "厉害", "太好了", "太棒了", "不错", "喜欢", "爱你",
            "谢谢", "感谢", "优秀", "完美", "精彩", "满意", "幸福", "快乐", "愉快", "惊喜",
            "成功", "胜利", "加油", "努力", "坚持", "奋斗", "希望", "美好", "温暖", "感动"
        ]
        
        self._negative_words = [
            "难过", "伤心", "糟糕", "遗憾", "可惜", "失望", "失落", "沮丧", "生气", "愤怒",
            "可恶", "讨厌", "烦", "气死", "过分", "不满", "悲伤", "痛苦", "绝望", "无奈",
            "失败", "放弃", "崩溃", "可怕", "危险", "担心", "焦虑", "紧张", "害怕", "恐惧"
        ]

    def analyze_sentiment(self, text: str) -> Dict:
        if not text:
            return {"sentiment": "neutral", "score": 0.0}
        
        positive_count = sum(1 for word in self._positive_words if word in text)
        negative_count = sum(1 for word in self._negative_words if word in text)
        
        total = positive_count + negative_count
        
        if total == 0:
            return {"sentiment": "neutral", "score": 0.0}
        
        score = (positive_count - negative_count) / total
        
        if score > 0.3:
            sentiment = "positive"
        elif score < -0.3:
            sentiment = "negative"
        else:
            sentiment = "neutral"
        
        return {"sentiment": sentiment, "score": round(score, 2)}

    def get_sentiment_intensity(self, text: str) -> float:
        result = self.analyze_sentiment(text)
        return abs(result["score"])


expression_controller = ExpressionController()
sentiment_analyzer = SentimentAnalyzer()