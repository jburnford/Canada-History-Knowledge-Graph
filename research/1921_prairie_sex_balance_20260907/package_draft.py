"""Render shareable HTML/PDF drafts and package the review materials."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
import markdown
from weasyprint import HTML

HERE=Path(__file__).resolve().parent
css='''
@page { size:A4; margin:18mm 17mm 19mm; @bottom-center {content:counter(page);font-size:9pt;color:#666} }
body {font-family:Georgia,serif;font-size:10.5pt;line-height:1.43;color:#202b32;max-width:950px;margin:30px auto;padding:0 24px}
h1 {font-size:23pt;line-height:1.15;color:#153e50;margin-bottom:20px}
p {orphans:3;widows:3;margin:0 0 12px}
a {color:#15536f;text-decoration:none;overflow-wrap:anywhere}
table {border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:8.1pt;line-height:1.28;margin:15px 0;break-inside:avoid}
th {background:#edf3f5;text-align:left;border-bottom:1px solid #587985}
th,td {padding:6px 5px;border-bottom:1px solid #d3dce0}
img {display:block;max-width:100%;height:auto;margin:12px auto;break-inside:avoid}
figure {margin:14px 0;break-inside:avoid}
figcaption {font-size:9pt;font-style:italic;margin-bottom:12px}
.table-caption {break-after:avoid}
pre {white-space:pre-wrap;font-size:9pt;padding:10px;background:#f3f5f6}
code {font-size:9pt;overflow-wrap:anywhere}
@media print {body {margin:0;padding:0;max-width:none}h1 {font-size:21pt}a {color:#15536f}}
'''
for name in ['DRAFT','METHODS','REVIEW_REQUEST']:
    body=markdown.markdown((HERE/f'{name}.md').read_text(),extensions=['tables','fenced_code'])
    body=re.sub(r'<p>(<img[^>]*>)</p>\s*<p><em>(Figure .*?)</em></p>',
                r'<figure>\1<figcaption>\2</figcaption></figure>',body,flags=re.S)
    body=re.sub(r'<p><strong>(Table .*?)</strong></p>',
                r'<p class="table-caption"><strong>\1</strong></p>',body)
    html=f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{name}</title><style>{css}</style></head><body>{body}</body></html>'
    (HERE/f'{name}.html').write_text(html)
    HTML(string=html,base_url=str(HERE)).write_pdf(HERE/f'{name}.pdf')
files=[p for p in HERE.iterdir() if p.is_file() and p.suffix in ['.md','.py','.csv','.json','.png','.pdf','.html','.gz'] and p.name!='package_manifest.json']
files += [HERE/f'external_sources/printed_page_{n}.png' for n in [313,320,332,335]]
manifest={str(p.relative_to(HERE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
(HERE/'package_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
with zipfile.ZipFile(HERE/'review_package.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
    for p in files+[HERE/'package_manifest.json']:
        z.write(p,arcname=p.relative_to(HERE))
print(f'Created {HERE / "review_package.zip"} ({(HERE/"review_package.zip").stat().st_size:,} bytes)')
