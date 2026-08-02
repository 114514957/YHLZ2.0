from backend.plugin_sdk import NekoPluginBase, neko_plugin, plugin_entry, Ok, Err
from pathlib import Path


@neko_plugin
class FileToolsPlugin(NekoPluginBase):

    @plugin_entry(
        id="read_file",
        name="读取文件",
        description="读取指定文件内容",
        metadata={"category": "file"},
        parameters={"file_path": {"type": "str", "description": "文件路径"}}
    )
    def read_file(self, file_path: str = "", **_):
        if not file_path:
            return Err("文件路径不能为空")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            if len(content) > 1000:
                return Ok({"result": content[:1000] + "\n...（内容过长，已截断）"})

            return Ok({"result": content})
        except FileNotFoundError:
            return Err(f"文件不存在: {file_path}")
        except PermissionError:
            return Err(f"无权限读取文件: {file_path}")
        except Exception as e:
            return Err(f"读取文件失败: {e}")

    @plugin_entry(
        id="write_file",
        name="写入文件",
        description="将内容写入指定文件",
        metadata={"category": "file"},
        parameters={
            "file_path": {"type": "str", "description": "文件路径"},
            "content": {"type": "str", "description": "要写入的内容"},
            "append": {"type": "bool", "description": "是否追加模式（默认False，覆盖写入）"}
        }
    )
    def write_file(self, file_path: str = "", content: str = "", append: bool = False, **_):
        if not file_path:
            return Err("文件路径不能为空")

        try:
            mode = 'a' if append else 'w'
            with open(file_path, mode, encoding='utf-8') as f:
                f.write(content)

            return Ok({"result": f"文件写入成功: {file_path}"})
        except PermissionError:
            return Err(f"无权限写入文件: {file_path}")
        except Exception as e:
            return Err(f"写入文件失败: {e}")

    @plugin_entry(
        id="list_files",
        name="列出文件",
        description="列出指定目录下的文件",
        metadata={"category": "file"},
        parameters={"directory": {"type": "str", "description": "目录路径，默认为当前目录 \".\""}}
    )
    def list_files(self, directory: str = ".", **_):
        try:
            path = Path(directory)

            if not path.exists():
                return Err(f"目录不存在: {directory}")

            if not path.is_dir():
                return Err(f"不是目录: {directory}")

            files = []
            for item in path.iterdir():
                if item.is_file():
                    files.append(f"📄 {item.name}")
                elif item.is_dir():
                    files.append(f"📁 {item.name}/")

            if not files:
                return Ok({"result": "目录为空"})

            return Ok({"result": "\n".join(files)})
        except PermissionError:
            return Err(f"无权限访问目录: {directory}")
        except Exception as e:
            return Err(f"列出文件失败: {e}")