"""Live2D 模型加载测试 - 尝试不同模型"""
import sys, os, ctypes

# 尝试不同模型
for model_name in ['hiyori_vts', 'akari_vts', 'hijiki_vts']:
    model_dir = os.path.abspath(f'下载物象/{model_name}')
    if not os.path.exists(model_dir):
        print(f'{model_name}: not found')
        continue
    
    print(f'\n=== Testing {model_name} ===')
    json_files = list(os.listdir(model_dir))
    json3 = [f for f in json_files if f.endswith('.model3.json')]
    print(f'  model3.json: {json3}')
    moc3 = [f for f in json_files if f.endswith('.moc3')]
    print(f'  moc3: {moc3}')
    # Check file sizes
    for f in json3 + moc3:
        path = os.path.join(model_dir, f)
        size = os.path.getsize(path)
        print(f'  {f}: {size} bytes')