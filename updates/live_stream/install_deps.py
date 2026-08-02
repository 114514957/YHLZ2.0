import subprocess
import sys


def install_package(package_name, version=None):
    if version:
        package = f"{package_name}=={version}"
    else:
        package = package_name
    
    print(f"安装 {package}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✓ {package} 安装成功")
    except subprocess.CalledProcessError:
        print(f"✗ {package} 安装失败")
        return False
    return True


def main():
    print("=" * 60)
    print("YHLZ 直播功能依赖安装")
    print("=" * 60)
    print()
    
    packages = [
        ("websockets", None),
        ("requests", None),
        ("pyvts", None),
        ("numpy", None),
        ("scipy", None),
        ("pyaudio", None),
        ("aiohttp", None),
        ("pydub", None),
        ("bilibili-api-python", None),
        ("blivedm", None),
    ]
    
    print("安装核心依赖...")
    print("-" * 40)
    
    success_count = 0
    for package, version in packages:
        if install_package(package, version):
            success_count += 1
    
    print()
    print("=" * 60)
    print(f"安装完成: {success_count}/{len(packages)} 个包安装成功")
    print("=" * 60)
    print()
    
    print("可选依赖（推荐安装）:")
    print("  pymouth - 专业口型同步")
    print("  bilibili-api-python - B站API")
    print("  blivedm - B站弹幕监听")
    print()
    print("安装可选依赖:")
    print("  pip install pymouth")
    print("  pip install bilibili-api-python")
    print("  pip install blivedm")


if __name__ == "__main__":
    main()