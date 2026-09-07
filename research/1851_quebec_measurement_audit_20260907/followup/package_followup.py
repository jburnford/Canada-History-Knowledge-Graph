"""Render and package the local correction supplement; no external publication."""
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import fitz
import markdown
from weasyprint import HTML

HERE = Path(__file__).resolve().parent
EXTERNAL = HERE.parent / 'external_sources'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    outputs = ['all_county_cells.csv','arithmetic_discrepancies.csv','printed_localities.csv',
        'manual_print_transcription.json','corrected_interpretations.jsonl','verification.json']
    subprocess.run([sys.executable,str(HERE/'verify.py')],check=True)
    first = {n:digest(HERE/n) for n in outputs}
    subprocess.run([sys.executable,str(HERE/'verify.py')],check=True)
    second = {n:digest(HERE/n) for n in outputs}
    if first != second:
        raise RuntimeError('Output changed between runs')
    (HERE/'reproducibility.json').write_text(json.dumps({
        'two_runs_byte_identical':True, 'outputs':second},indent=2)+'\n')
    ev = HERE/'evidence'
    ev.mkdir(exist_ok=True)
    for page in [188,189]:
        shutil.copy2(EXTERNAL/f'census_pdfpage_{page}.png',ev/f'pdfpage_{page}.png')
    for page in [178,182,183,190,191,192,193]:
        shutil.copy2(EXTERNAL/f'followup_pdfpage_{page}.png',ev/f'pdfpage_{page}.png')
    shutil.copy2(EXTERNAL/'detail_pdfpage_176.png',ev/'pdfpage_176.png')
    shutil.copy2(EXTERNAL/'detail_pdfpage_193.png',ev/'calves_detail_pdfpage_193.png')
    shutil.copy2(EXTERNAL/'stmaurice_cattle_detail.png',ev/'calves_localities_pdfpage_193.png')
    for name in ['bond_2026.html','bond_table4.html','bond_2026_supplement.pdf']:
        shutil.copy2(EXTERNAL/name,ev/name)
    body = markdown.markdown((HERE/'RESPONSE.md').read_text(),extensions=['tables'])
    css = '''@page {size:A4; margin:18mm 17mm;
        @bottom-right {content:counter(page);font-size:9pt;color:#666}}
        body {font-family:DejaVu Sans,sans-serif;font-size:10pt;line-height:1.42;color:#202a34}
        h1 {font-size:20pt;line-height:1.15} h2 {font-size:13pt;margin-top:18pt}
        h1,h2 {break-after:avoid} p,li {orphans:3;widows:3}
        a {color:#18568c;text-decoration:none} code {font-size:8.5pt;overflow-wrap:anywhere}
        table {border-collapse:collapse;width:100%;font-size:8.5pt;break-inside:avoid}
        td,th {border-bottom:1px solid #c9d3db;text-align:left;padding:5pt}
        th {background:#edf3f7} li {margin-bottom:5pt}'''
    html = '<!doctype html><meta charset="utf-8"><title>Response to redesign verdict</title><style>'+css+'</style>'+body
    (HERE/'RESPONSE.html').write_text(html)
    HTML(string=html,base_url=str(HERE)).write_pdf(HERE/'RESPONSE.pdf')
    pdf = fitz.open(HERE/'RESPONSE.pdf')
    outside = []
    for n,page in enumerate(pdf):
        for b in page.get_text('blocks'):
            if b[0]<0 or b[1]<0 or b[2]>page.rect.width+.1 or b[3]>page.rect.height+.1:
                outside.append([n+1,b[:4]])
    if outside:
        raise RuntimeError(f'PDF overflow {outside}')
    pdf[0].get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(HERE/'preview.png')
    pdf.close()
    files = [p for p in HERE.rglob('*') if p.is_file() and p.name not in
        ('manifest.json','preview.png') and '__pycache__' not in p.parts]
    for p in files:
        if p.suffix == '.pdf':
            with fitz.open(p) as document:
                if not document.is_pdf or len(document) == 0:
                    raise RuntimeError(f'Invalid PDF: {p}')
    manifest = {'files':{str(p.relative_to(HERE)):digest(p) for p in sorted(files)},
        'pdf_text_outside_page':outside, 'deployment':'local supplement only'}
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    target = HERE.parent/'followup_dossier.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(files)+[HERE/'manifest.json']:
            z.write(p,'followup/'+str(p.relative_to(HERE)))
    with zipfile.ZipFile(target) as z:
        if z.testzip():
            raise RuntimeError('archive CRC failure')
        for rel,value in manifest['files'].items():
            if hashlib.sha256(z.read('followup/'+rel)).hexdigest()!=value:
                raise RuntimeError(f'archive hash mismatch {rel}')
    print(json.dumps({'archive':str(target),'bytes':target.stat().st_size,
        'files':len(files)+1,'archive_hashes_verified':True},indent=2))


if __name__=='__main__':
    main()
