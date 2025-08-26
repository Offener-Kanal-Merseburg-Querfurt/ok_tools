#!/usr/bin/env python3
"""
Restore working Rental links across templates and remove "Coming Soon" modal/script/CSS.

Usage:
  python scripts/restore_rental_links.py
"""
from __future__ import annotations
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]

def replace_in_file(path: pathlib.Path, replacements: list[tuple[str, str]]) -> None:
    content = path.read_text(encoding='utf-8')
    original = content
    for old, new in replacements:
        content = content.replace(old, new)
    if content != original:
        path.write_text(content, encoding='utf-8')

def remove_between_markers(content: str, start_marker: str, end_marker: str) -> str:
    while True:
        start = content.find(start_marker)
        if start == -1:
            break
        end = content.find(end_marker, start)
        if end == -1:
            break
        content = content[:start] + content[end + len(end_marker):]
    return content

def restore_base_html() -> None:
    path = ROOT / 'ok_tools' / 'templates' / 'base.html'
    content = path.read_text(encoding='utf-8')

    # 1) Sidebar: replace button with anchor using our commented snippet marker
    content = content.replace(
        '<button type="button" class="sidebar-link btn btn-link coming-soon-btn" data-feature="rental">',
        '<a href="{% url \"rental_dashboard\" %}" class="sidebar-link">'
    )
    content = content.replace('</button>', '</a>')

    # 2) Remove Coming Soon modal block by markers
    content = remove_between_markers(content, '<!-- COMING_SOON_MODAL_START', '<!-- COMING_SOON_MODAL_END -->')

    # 3) Remove Coming Soon script block by markers
    content = remove_between_markers(content, '<!-- COMING_SOON_SCRIPT_START', '<!-- COMING_SOON_SCRIPT_END -->')

    path.write_text(content, encoding='utf-8')

def restore_dashboard_html() -> None:
    path = ROOT / 'ok_tools' / 'templates' / 'dashboard.html'
    content = path.read_text(encoding='utf-8')

    # Replace the Coming Soon button with link using the commented template above it
    content = content.replace(
        '<button type="button" class="btn btn-outline-primary coming-soon-btn" data-feature="rental">',
        '<a href="{% url \"rental_dashboard\" %}" class="btn btn-outline-primary">'
    )
    content = content.replace('</button>', '</a>')

    path.write_text(content, encoding='utf-8')

def clean_css() -> None:
    path = ROOT / 'ok_tools' / 'static' / 'css' / 'dashboard.css'
    content = path.read_text(encoding='utf-8')
    content = remove_between_markers(content, '/* COMING_SOON_CSS_START', '/* COMING_SOON_CSS_END */')
    path.write_text(content, encoding='utf-8')

def main() -> None:
    restore_base_html()
    restore_dashboard_html()
    clean_css()
    print('Rental links restored. Remove unused imports/translations if any. ✅')

if __name__ == '__main__':
    main()
