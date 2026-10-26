#!/usr/bin/env python3
"""おおさかeコレクション IIIF v3 マニフェストの直接画像URLを修正。"""
import argparse
import copy
import datetime as dt
import email.utils
import json
import os
from pathlib import Path
import random
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = 'da.library.pref.osaka.jp'
URL_RE = re.compile(r'https://da\.library\.pref\.osaka\.jp/api/items/([A-Za-z0-9_-]+)/manifest\.json$')
SERVICE_RE = re.compile(r'https://da\.library\.pref\.osaka\.jp/api/contents/([A-Za-z0-9_-]+\.jp2)$')
MARKER = {'ja': ['非公式修正版の情報']}


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def fix_manifest(original, source_url):
    match = URL_RE.fullmatch(source_url)
    if not match:
        raise ValueError('未対応のマニフェストURL')
    if original.get('type') != 'Manifest' or original.get('@context') != 'http://iiif.io/api/presentation/3/context.json':
        raise ValueError('IIIF Presentation API v3 Manifestではありません')
    if not isinstance(original.get('items'), list) or not original['items']:
        raise ValueError('Canvas一覧がありません')
    result = copy.deepcopy(original)
    changes, warnings = [], []
    item_id = match.group(1)
    image_count = 0
    for ci, canvas in enumerate(result['items'], 1):
        if canvas.get('type') != 'Canvas':
            raise ValueError(f'items[{ci}]がCanvasではありません')
        for page in canvas.get('items', []):
            for annotation in page.get('items', []):
                if annotation.get('motivation') != 'painting':
                    continue
                body = annotation.get('body')
                if not isinstance(body, dict) or body.get('type') != 'Image':
                    raise ValueError(f'Canvas {ci}: 未対応の画像body構造（部分修正版は出力しません）')
                image_count += 1
                services = body.get('service', [])
                if isinstance(services, dict):
                    services = [services]
                bases = set()
                for service in services:
                    if isinstance(service, dict):
                        base = service.get('@id', service.get('id', ''))
                        if isinstance(base, str) and SERVICE_RE.fullmatch(base):
                            bases.add(base)
                if len(bases) != 1:
                    raise ValueError(f'Canvas {ci}: 対応する画像サービスを一意に判定できません')
                base = bases.pop()
                good = base + '/full/full/0/default.jpg'
                filename = SERVICE_RE.fullmatch(base).group(1)
                bad = f'https://{HOST}/api/items/{item_id}/contents/{filename}/full/full/0/default.jpg'
                before = body.get('id')
                if before == bad:
                    body['id'] = good
                    changes.append({'canvas': ci, 'before': before, 'after': good})
                elif before != good:
                    raise ValueError(f'Canvas {ci}: 未知の画像URL形式（変更せず資料全体をスキップ）: {before}')
    if image_count == 0:
        raise ValueError('対象の画像がありません')
    if changes:
        metadata = result.setdefault('metadata', [])
        if not isinstance(metadata, list):
            raise ValueError('metadataが配列ではありません')
        metadata.append({'label': MARKER, 'value': {'ja': [
            '大阪府立図書館提供のIIIFマニフェストを元に、画像の直接参照URL（body.id）を修正した非公式版です。'
            '画像サービス・画像提供元・既存の識別子は変更していません。'
            f' 元マニフェスト: {source_url} 修正画像数: {len(changes)}'
        ]}})
    return result, changes, warnings


class Downloader:
    def __init__(self, minimum, maximum, timeout):
        self.minimum, self.maximum, self.timeout = minimum, maximum, timeout
        self.last = None

    def get(self, url):
        for attempt in range(3):
            if self.last is not None:
                time.sleep(max(0, random.uniform(self.minimum, self.maximum) - (time.monotonic() - self.last)))
            try:
                request = urllib.request.Request(url, headers={'User-Agent': 'OsakaManifestFix/1.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if not URL_RE.fullmatch(response.url):
                        raise ValueError('未対応のリダイレクト先')
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                retry = exc.headers.get('Retry-After')
                delay = 5 * 2 ** attempt
                if retry:
                    try:
                        delay = max(delay, float(retry))
                    except ValueError:
                        try:
                            delay = max(delay, (email.utils.parsedate_to_datetime(retry) - dt.datetime.now(dt.timezone.utc)).total_seconds())
                        except (ValueError, TypeError):
                            pass
                print(f'再試行待機: {delay:.0f}秒', flush=True)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(5 * 2 ** attempt)
            finally:
                self.last = time.monotonic()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('url_list', nargs='?', default='urls.txt', help='1行1マニフェストURLのUTF-8ファイル')
    p.add_argument('--output', default='output', help='出力ディレクトリ')
    p.add_argument('--refresh', action='store_true', help='既存の完了出力も再取得・再生成')
    p.add_argument('--min-wait', type=float, default=5)
    p.add_argument('--max-wait', type=float, default=10)
    p.add_argument('--timeout', type=float, default=60)
    args = p.parse_args()
    if not 0 <= args.min_wait <= args.max_wait or args.timeout <= 0:
        p.error('待機時間・タイムアウトの指定が不正です')
    root = Path(args.output)
    download = Downloader(args.min_wait, args.max_wait, args.timeout)
    failed = 0
    seen = set()
    for line_number, line in enumerate(Path(args.url_list).read_text(encoding='utf-8-sig').splitlines(), 1):
        url = line.strip()
        if not url or url.startswith('#') or url in seen:
            continue
        seen.add(url)
        try:
            match = URL_RE.fullmatch(url)
            if not match:
                raise ValueError('未対応のURL。公式マニフェストのhttps URLを指定してください')
            item_id = match.group(1)
            dest = root / 'manifests' / (item_id + '.json')
            record = root / 'reports' / (item_id + '.json')
            if dest.exists() and record.exists() and not args.refresh:
                current = json.loads(dest.read_text(encoding='utf-8'))
                report = json.loads(record.read_text(encoding='utf-8'))
                if report.get('source_url') == url and current == report.get('output_snapshot'):
                    print(f'SKIP {item_id}: 完了済み', flush=True)
                    continue
            original = download.get(url)
            fixed, changes, warnings = fix_manifest(original, url)
            stamp = dt.datetime.now(dt.timezone.utc).isoformat()
            atomic_json(root / 'originals' / (item_id + '.json'), original)
            atomic_json(dest, fixed)
            # 完了記録は最後に保存。中断時は次回再処理する。
            atomic_json(record, {'source_url': url, 'retrieved_at': stamp, 'changes': changes,
                                 'warnings': warnings, 'output_snapshot': fixed})
            print(f'OK {item_id}: {len(changes)}画像を修正 → {dest}', flush=True)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            failed += 1
            message = {'line': line_number, 'url': url, 'error': str(exc), 'time': dt.datetime.now(dt.timezone.utc).isoformat()}
            root.mkdir(parents=True, exist_ok=True)
            with (root / 'errors.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(message, ensure_ascii=False) + '\n')
            print(f'ERROR {url}: {exc}', file=sys.stderr, flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n中断しました。同じコマンドで再開できます。', file=sys.stderr)
        sys.exit(130)
