#!/usr/bin/env python3
"""抓取 Teltonika 新闻首页最新动态。
安装：python -m pip install playwright
      python -m playwright install chromium
运行：python scrape_teltonika_news.py --limit 10
默认输出到本脚本所在的仓库根目录。--input-json 可导入已核实的离线数据。
"""
import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

NEWSROOM = 'https://www.teltonika-networks.com/newsroom'


def parse_date(text):
    for pattern, fmt in [
        (r'\b\d{4}-\d{2}-\d{2}\b', '%Y-%m-%d'),
        (r'\b\d{1,2}/\d{1,2}/\d{4}\b', '%m/%d/%Y'),
        (r'\b\d{1,2} [A-Za-z]+ \d{4}\b', '%d %B %Y'),
    ]:
        for match in re.finditer(pattern, text):
            try:
                return datetime.strptime(match.group(), fmt).date().isoformat()
            except ValueError:
                continue
    raise ValueError('没有找到可识别的发布日期')


def scrape(limit):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale='en-US')
            page.goto(NEWSROOM, wait_until='domcontentloaded', timeout=60000)
            page.wait_for_selector('a[href*="/newsroom/"]', timeout=30000)
            links = page.locator('a[href*="/newsroom/"]').evaluate_all(
                '(nodes) => nodes.map(a => a.href)')
            links = list(dict.fromkeys(
                u.split('#')[0].split('?')[0] for u in links
                if re.match(r'^https://(?:www\.)?teltonika-networks\.com/newsroom/[^/]+/?$', u)
            ))
            rows = []
            for url in links:
                page.goto(url, wait_until='domcontentloaded', timeout=60000)
                heading = page.locator('h1').first
                heading.wait_for(timeout=30000)
                title = heading.inner_text().strip()
                # 优先取结构化数据的 datePublished，避免误用 dateModified。
                published = None
                def visit(obj):
                    nonlocal published
                    if isinstance(obj, dict):
                        if obj.get('datePublished'):
                            published = parse_date(str(obj['datePublished']))
                        for value in obj.values():
                            visit(value)
                    elif isinstance(obj, list):
                        for value in obj:
                            visit(value)
                for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
                    try:
                        visit(json.loads(raw))
                    except (ValueError, TypeError):
                        continue
                if not published:
                    # 只检查文章标题之后的正文，排除导航栏推荐新闻的日期。
                    text = page.locator('body').inner_text()
                    pos = text.find(title)
                    published = parse_date(text[pos + len(title):][:1500])
                if not title:
                    raise RuntimeError(f'新闻标题为空：{url}')
                rows.append({'title': title, 'published_date': published, 'link': url})
                page.wait_for_timeout(500)
            if not rows:
                raise RuntimeError('未提取到新闻，请检查网页结构或访问限制')
            return sorted(rows, key=lambda r: r['published_date'], reverse=True)[:limit]
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=10, help='新闻首页中最多保留的条数')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'teltonika_news.csv')
    parser.add_argument('--input-json', type=Path, help='导入已核实的数据；此模式不访问网站')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit 必须大于零')
    if args.input_json:
        print('模式：导入已核实的离线数据（非实时联网抓取）')
        rows = json.loads(args.input_json.read_text(encoding='utf-8'))
        for row in rows:
            row['published_date'] = parse_date(row['published_date'])
            if not row['title'] or not row['link'].startswith(NEWSROOM + '/'):
                raise ValueError('离线新闻数据不完整')
        rows = sorted(rows, key=lambda r: r['published_date'], reverse=True)[:args.limit]
    else:
        rows = scrape(args.limit)
    if not rows:
        raise RuntimeError('没有新闻数据，不覆盖输出文件')
    with args.output.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['title', 'published_date', 'link'])
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(f"{row['published_date']} | {row['title']}\n{row['link']}\n")
    print(f'共 {len(rows)} 条，已保存至 {args.output.resolve()}')


if __name__ == '__main__':
    main()
