"""Save bounded public previews in an isolated research cache, never SFT."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATASETS = [
    'Moemu/Muice-Dataset',
    'MemorialSummer/chinese-adorable-high-emotional-intelligence-chat',
    'zhcompanion/companion-roleplay-sft',
    'LooksJuicy/Chinese-Emotional-Intelligence',
    'bai-roleplay/evol-character-200',
    'shibing624/roleplay-zh-sharegpt-gpt4-data',
    'LooksJuicy/Chinese-Roleplay-Novel',
    'silver/lccc',
]
PROJECTS = {
    'Character-LLM': 'https://raw.githubusercontent.com/choosewhatulike/trainable-agents/main/README.md',
    'BaiJia': 'https://raw.githubusercontent.com/BAI-LAB/BaiJia/main/README.md',
    'pippa-zh': 'https://raw.githubusercontent.com/snake-aabb-wtf/pippa-zh/main/README.md',
    'TreeHoleEcho': 'https://modelscope.cn/api/v1/datasets/catbohe/TreeHoleEcho/repo?Revision=master&FilePath=README.md',
    'HANA': 'https://modelscope.cn/api/v1/datasets/xuanxixue/HANA/repo?Revision=master&FilePath=README.md',
}
ROUND2_DATASETS = [
    'xywang1/NaturalConv',
    'VITA-MLLM/Emotion_NaturalConv_FunctionCall',
    'proj-persona/PersonaHub',
    'markyfsun/chinese-enthusiastic-dpo',
    'raincandy-u/chinese-roleplay',
]
ROUND2_PROJECTS = {
    'NaturalConv-official': 'https://raw.githubusercontent.com/naturalconv/NaturalConvDataSet/main/README.md',
    'NaturalConv-license': 'https://huggingface.co/datasets/xywang1/NaturalConv/raw/adb38574e8014ada1d8404247167582e76b22d05/LICENSE',
    'DuLeMon': 'https://raw.githubusercontent.com/PaddlePaddle/Research/master/NLP/ACL2022-DuLeMon/README.md',
    'DuLeMon-download': 'https://raw.githubusercontent.com/PaddlePaddle/Research/master/NLP/ACL2022-DuLeMon/data/download_dulemon.sh',
    'MOOM': 'https://raw.githubusercontent.com/cows21/MOOM-Roleplay-Dialogue/main/README.md',
    'MOOM-data-directory': 'https://github.com/cows21/MOOM-Roleplay-Dialogue/tree/main/data',
    'MOOM-download': 'https://raw.githubusercontent.com/cows21/MOOM-Roleplay-Dialogue/main/download.sh',
    'PersonaHub-official': 'https://raw.githubusercontent.com/tencent-ailab/persona-hub/main/README.md',
    'CharacterEval': 'https://raw.githubusercontent.com/morecry/CharacterEval/main/README.md',
    'Arya-ModelScope': 'https://modelscope.cn/api/v1/datasets/newcjh/Arya/repo?Revision=master&FilePath=README.md',
    'nover-airp-ModelScope': 'https://modelscope.cn/api/v1/datasets/tianyuan888/gemini-3.1-pro-nover-airp/repo?Revision=master&FilePath=README.md',
    'lmsys-ModelScope': 'https://modelscope.cn/api/v1/datasets/AI-ModelScope/lmsys_chat_1m_clean/repo?Revision=master&FilePath=README.md',
}


def get(url, as_json=True):
    try:
        req = Request(url, headers={'User-Agent': 'YHLZ-materials-review/1.0'})
        with urlopen(req, timeout=20) as response:
            raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise ValueError('Response exceeds the 3 MB preview bound')
        text = raw.decode('utf-8')
        return {'url': url, 'ok': True, 'data': json.loads(text) if as_json else text}
    except Exception as exc:
        return {'url': url, 'ok': False, 'error': str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--round', choices=(1, 2), type=int, default=1)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    datasets = ROUND2_DATASETS if args.round == 2 else DATASETS
    projects = ROUND2_PROJECTS if args.round == 2 else PROJECTS
    index = []
    for repo in datasets:
        meta = get('https://huggingface.co/api/datasets/' + repo)
        ev = {'repo': repo, 'purpose': 'reference_only_not_training', 'metadata': meta}
        if meta['ok']:
            sha = meta['data']['sha']
            ev['revision'] = sha
            ev['readme'] = get(f'https://huggingface.co/datasets/{repo}/raw/{sha}/README.md', False)
            splits = get('https://datasets-server.huggingface.co/splits?' + urlencode({'dataset': repo}))
            ev['splits'] = splits
            options = splits.get('data', {}).get('splits', [])
            desired_config = 'persona' if repo == 'proj-persona/PersonaHub' else None
            compatible = [s for s in options if desired_config is None or s['config'] == desired_config]
            chosen = next((s for s in compatible if s['split'] == 'train'), compatible[0] if compatible else None)
            if chosen:
                params = {'dataset': repo, 'config': chosen['config'], 'split': chosen['split'], 'offset': 0, 'length': 8}
                ev['preview'] = get('https://datasets-server.huggingface.co/rows?' + urlencode(params))
                total = ev['preview'].get('data', {}).get('num_rows_total', 0)
                ev['additional_previews'] = []
                if total > 24:
                    for offset in sorted({total // 2, max(0, total - 8)}):
                        params['offset'] = offset
                        ev['additional_previews'].append(get('https://datasets-server.huggingface.co/rows?' + urlencode(params)))
        filename = repo.replace('/', '__') + '.json'
        (args.out / filename).write_text(json.dumps(ev, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        card = meta.get('data', {}).get('cardData') or {}
        previews = [ev.get('preview', {})] + ev.get('additional_previews', [])
        row = {'repo': repo, 'revision': ev.get('revision'), 'license': card.get('license'), 'preview_rows': sum(len(p.get('data', {}).get('rows', [])) for p in previews), 'total': ev.get('preview', {}).get('data', {}).get('num_rows_total'), 'evidence': filename}
        index.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    for name, url in projects.items():
        ev = get(url, False)
        (args.out / (name + '.json')).write_text(json.dumps(ev, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'project': name, 'ok': ev['ok'], 'error': ev.get('error')}), flush=True)
    (args.out / 'index.json').write_text(json.dumps({'purpose': 'reference_only_not_training', 'sampling': 'first/middle/last up to 8 rows each, not random or exhaustive; viewer revision is not assumed pinned', 'datasets': index}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
