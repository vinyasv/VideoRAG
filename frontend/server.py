#!/usr/bin/env python3
import http.server
import socketserver
import os
from pathlib import Path

class RangeHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            return super().send_head()
        
        try:
            f = open(path, 'rb')
        except OSError:
            return None
        
        fs = os.fstat(f.fileno())
        size = fs.st_size
        
        range_header = self.headers.get('Range')
        if range_header:
            range_match = range_header.replace('bytes=', '').split('-')
            start = int(range_match[0]) if range_match[0] else 0
            end = int(range_match[1]) if len(range_match) > 1 and range_match[1] else size - 1
            
            if start >= size:
                self.send_error(416, "Requested Range Not Satisfiable")
                return None
            
            self.send_response(206)
            self.send_header('Content-type', self.guess_type(path))
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(end - start + 1))
            self.end_headers()
            
            f.seek(start)
            return f
        else:
            self.send_response(200)
            self.send_header('Content-type', self.guess_type(path))
            self.send_header('Content-Length', str(size))
            self.end_headers()
            return f

PORT = 3000
os.chdir(Path(__file__).parent)

with socketserver.TCPServer(("", PORT), RangeHTTPRequestHandler) as httpd:
    print(f"Serving at http://localhost:{PORT}")
    httpd.serve_forever()

