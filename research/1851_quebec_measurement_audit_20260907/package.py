from pathlib import Path
import hashlib, json, zipfile
import markdown
from weasyprint import HTML
import fitz

p = Path(__file__).resolve().parent
css = """
@page { size: A4; margin: 19mm 18mm; @bottom-center { content: counter(page); font-size: 9pt; } }
body { font-family: Georgia, serif; font-size: 10.5pt; line-height: 1.42; color: #17212b; }
h1 { font-size: 22pt; line-height: 1.15; color: #173c53; }
h2 { font-size: 13pt; color: #173c53; margin-top: 18pt; }
h1,h2 { break-after: avoid; }
p { orphans: 3; widows: 3; }
a { color: #245d80; text-decoration: none; overflow-wrap: anywhere; }
table { border-collapse: collapse; font-size: 9pt; width: 100%; margin: 12pt 0; }
th,td { border-bottom: 1px solid #bbc6cb; padding: 5pt; text-align: left; vertical-align: top; }
tr { break-inside: avoid; } th { background: #e8eef2; }
code { font-size: 8.5pt; overflow-wrap: anywhere; }
"""
for stem in ['RESEARCH_MEMO','REVIEW_REQUEST']:
    body = markdown.markdown((p/f'{stem}.md').read_text(), extensions=['tables','fenced_code'])
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><style>'+css+'</style><body>'+body+'</body></html>'
    (p/f'{stem}.html').write_text(html)
    HTML(string=html,base_url=str(p)).write_pdf(p/f'{stem}.pdf')
    doc=fitz.open(p/f'{stem}.pdf')
    assert all(page.get_text().strip() for page in doc)
    print(stem,len(doc),'pages')
    if stem == 'RESEARCH_MEMO':
        doc[0].get_pixmap(matrix=fitz.Matrix(1.3,1.3)).save(p/'memo_preview.png')

files=['RESEARCH_MEMO.md','RESEARCH_MEMO.pdf','REVIEW_REQUEST.md','REVIEW_REQUEST.pdf',
       'README.md','audit.py','package.py','validation.json','provenance.json',
       'source_cells.jsonl.gz','county_reconciliation.csv','verified_print_discrepancies.csv',
       'external_sources/census_pdfpage_189.png']
manifest={f: {'bytes':(p/f).stat().st_size,'sha256':hashlib.sha256((p/f).read_bytes()).hexdigest()} for f in files}
(p/'package_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
with zipfile.ZipFile(p/'review_dossier.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in files+['package_manifest.json']: z.write(p/f,arcname=f)
print('Archive bytes',(p/'review_dossier.zip').stat().st_size)
