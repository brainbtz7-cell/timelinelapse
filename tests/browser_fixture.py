"""Run the actual UI with a synthetic getDisplayMedia source. Not an OS capture test."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app

FIXTURE=r'''
// Test-only source: no screen, microphone, or camera permissions are requested.
const fixtureCanvas=document.createElement('canvas');fixtureCanvas.width=1920;fixtureCanvas.height=1080;
const fixtureCtx=fixtureCanvas.getContext('2d');let fixtureTick=0;
function fixturePaint(){
 const c=fixtureCtx,t=fixtureTick++;
 c.fillStyle='#232b26';c.fillRect(0,0,1920,1080);
 c.fillStyle='#c9e991';c.font='34px sans-serif';c.fillText('SYNTHETIC TEST WINDOW — NO SCREEN IS CAPTURED',50,65);
 c.fillStyle='#52664f';c.fillRect(40,110,1840,350);
 c.fillStyle='#e2ecd7';c.font='24px sans-serif';c.fillText('Preview / fixture only',75,170);
 for(let row=0;row<5;row++){
  const y=535+row*91;c.fillStyle='#303c33';c.fillRect(0,y,1920,85);
  c.fillStyle='#a7c491';c.font='22px sans-serif';c.fillText(row<3?'V'+(3-row):'A'+(row-2),25,y+45);
  for(let i=0;i<Math.min(15,1+(t%16));i++){
   c.fillStyle=['#607c8d','#7e6a91','#628c6e','#7f9c69','#698786'][row];
   c.fillRect(100+i*118,y+7,109,70);
   c.fillStyle='#eef5e5';c.font='16px sans-serif';c.fillText('Clip '+i,107+i*118,y+30);
  }
 }
}
fixturePaint();setInterval(fixturePaint,500);
navigator.mediaDevices.getDisplayMedia=async()=>fixtureCanvas.captureStream(5);
document.getElementById('chooseSource').querySelector('strong').textContent='Elegir ventana de prueba';
document.getElementById('sourceStatus').textContent='TEST: fuente sintética. No se captura ninguna ventana real.';
'''


class FixtureHandler(app.Handler):
    def do_GET(self):
        if self.path in ('/','/index.html'):
            body=(app.ROOT/'web/index.html').read_text().replace('</body>','<script src="/fixture.js" defer></script></body>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        elif self.path=='/fixture.js':
            body=FIXTURE.encode();self.send_response(200);self.send_header('Content-Type','application/javascript');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        else:super().do_GET()


if __name__=='__main__':
    app.DATA=app.ROOT/'.timelinelapse'/'browser-fixture';app.DATA.mkdir(parents=True,exist_ok=True)
    server=app.ThreadingHTTPServer(('127.0.0.1',8766),FixtureHandler)
    print('Synthetic capture fixture: http://127.0.0.1:8766',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.POOL.shutdown(wait=True)
