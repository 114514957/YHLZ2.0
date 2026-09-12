from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, Ok, Err


@neko_plugin
class APIToolsPlugin(NekoPluginBase):

    @plugin_entry(
        id="get_weather",
        name="天气查询",
        description="获取指定城市的天气信息",
        metadata={"category": "api"},
        parameters={"city": {"type": "str", "description": "城市名称，如 \"Beijing\" 或 \"北京\""}}
    )
    def get_weather(self, city: str = "Beijing", **_):
        try:
            import requests

            url = f"https://wttr.in/{city}?format=%C+%t+%h+%w"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                weather = response.text.strip()
                return Ok({"result": f"{city}天气: {weather}"})
            else:
                return Err(f"获取{city}天气失败")

        except Exception as e:
            return Err(f"天气查询失败: {e}")

    @plugin_entry(
        id="web_search",
        name="网页搜索",
        description="搜索指定关键词",
        metadata={"category": "api"},
        parameters={"query": {"type": "str", "description": "搜索关键词"}}
    )
    def web_search(self, query: str = "", **_):
        if not query:
            return Err("搜索关键词不能为空")

        try:
            import requests

            url = "https://api.duckduckgo.com/"
            params = {
                "q": query,
                "format": "json",
                "no_html": "1",
                "no_redirect": "1"
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()

                results = []

                if "Abstract" in data and data["Abstract"]:
                    results.append(f"摘要: {data['Abstract']}")

                if "RelatedTopics" in data:
                    for topic in data["RelatedTopics"][:5]:
                        if "Text" in topic:
                            results.append(f"- {topic['Text']}")

                if not results:
                    return Ok({"result": f"未找到关于'{query}'的搜索结果"})

                return Ok({"result": "\n".join(results)})
            else:
                return Err("搜索失败")

        except Exception as e:
            return Err(f"搜索失败: {e}")