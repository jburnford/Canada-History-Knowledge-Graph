#!/usr/bin/env python3
"""Preview the completed static site locally at its production path prefix."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from _config import REPO_ROOT
from _site_urls import BASE, local_path


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == '/':
            self.send_response(302)
            self.send_header('Location', BASE + '/')
            self.end_headers()
            return
        try:
            local_path(self.path)
        except ValueError:
            self.send_error(404)
            return
        super().do_GET()

    def translate_path(self, path):
        # The standard handler safely decodes names and removes dot segments;
        # local_path above rejects traversal and requires the production prefix.
        path = path[len(BASE):] if path.startswith(BASE + '/') else '/'
        return super().translate_path(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--site', type=Path, default=REPO_ROOT / 'data_quality/rdf_site')
    ap.add_argument('--port', type=int, default=8000)
    args = ap.parse_args()
    if not (args.site / 'data/build-manifest.json').is_file():
        ap.error('Build the RDF site first with make rdf-site')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(args.site.resolve())))
    print(f'Preview: http://127.0.0.1:{args.port}{BASE}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
