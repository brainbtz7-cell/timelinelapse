import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
import io

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_data=app.DATA
        app.DATA.mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=app.ROOT/'.timelinelapse',prefix='test-')
        app.DATA=Path(cls.temp.name)
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.jpeg=(app.ROOT/'assets/demo/frames/000001.jpg').read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()
        app.DATA=cls.original_data
        cls.temp.cleanup()

    def request(self,path,method='GET',body=None,headers=None):
        con=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=15)
        con.request(method,path,body=body,headers=headers or {})
        response=con.getresponse();data=response.read();status=response.status;h=dict(response.getheaders());con.close()
        return status,data,h

    def create(self):
        return app.new_session('Test cut',1)

    def test_real_jpeg_and_session_persist_after_reload(self):
        data=self.create()
        self.assertEqual(app.jpeg_size(self.jpeg),(1920,620))
        self.assertEqual(app.add_frame(data['id'],self.jpeg,.1),1)
        saved=app.session(data['id'])
        self.assertEqual(saved['frames'],[{'file':'000000.jpg','elapsed':.1}])
        self.assertEqual((app.folder_for(data['id'])/'frames/000000.jpg').read_bytes(),self.jpeg)

    def test_invalid_and_out_of_order_frames_are_rejected(self):
        data=self.create()
        with self.assertRaises(ValueError):app.add_frame(data['id'],b'not a JPEG',0)
        app.add_frame(data['id'],self.jpeg,5)
        with self.assertRaises(ValueError):app.add_frame(data['id'],self.jpeg,4)
        self.assertEqual(len(app.session(data['id'])['frames']),1)

    def test_bad_session_cannot_escape_storage(self):
        for key in ['../assets','a'*23,'a'*24+'/../','demo/../']:
            with self.assertRaises(ValueError):app.folder_for(key)

    def test_demo_is_read_only(self):
        with self.assertRaises(ValueError):app.add_frame('demo',self.jpeg,9000)

    def test_write_requires_session_token_and_same_origin(self):
        body=json.dumps({'title':'test','interval':1})
        status,_,_=self.request('/api/sessions','POST',body,{'Content-Type':'application/json'})
        self.assertEqual(status,403)
        status,_,_=self.request('/api/sessions','POST',body,{'X-TimelineLapse-Token':app.TOKEN,'Origin':'https://example.com'})
        self.assertEqual(status,403)

    def test_unknown_host_is_rejected(self):
        status,_,_=self.request('/api/config',headers={'Host':'attacker.example'})
        self.assertEqual(status,421)

    def test_http_capture_finish_and_backup(self):
        headers={'X-TimelineLapse-Token':app.TOKEN,'Content-Type':'application/json'}
        status,body,_=self.request('/api/sessions','POST',json.dumps({'title':'A cut','interval':3}),headers)
        self.assertEqual(status,201);key=json.loads(body)['id']
        status,body,_=self.request(f'/api/sessions/{key}/frame','POST',self.jpeg,
                                  {'X-TimelineLapse-Token':app.TOKEN,'Content-Type':'image/jpeg','X-Elapsed':'4'})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['count'],1)
        status,body,_=self.request(f'/api/sessions/{key}/finish','POST',json.dumps({'elapsed':20,'title':'Finished','skipped':7}),headers)
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['elapsed'],20)
        self.assertEqual(json.loads(body)['skipped'],7)
        status,body,h=self.request(f'/backup/{key}')
        self.assertEqual(status,200)
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertEqual(set(z.namelist()),{'session.json','frames/000000.jpg'})
            self.assertEqual(json.loads(z.read('session.json'))['title'],'Finished')

    def test_video_ranges_and_invalid_range(self):
        status,body,h=self.request('/assets/demo/frames/000001.jpg',headers={'Range':'bytes=10-29'})
        self.assertEqual(status,206);self.assertEqual(body,self.jpeg[10:30]);self.assertIn('Content-Range',h)
        status,body,_=self.request('/assets/demo/frames/000001.jpg',headers={'Range':'bytes=99999999-'})
        self.assertEqual(status,416);self.assertEqual(body,b'')

    def test_reject_nan_duration(self):
        with self.assertRaises(ValueError):app.number(float('nan'),2,120)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg required')
    def test_export_duration_geometry_and_last_frame(self):
        data=self.create();app.add_frame(data['id'],self.jpeg,0)
        last=(app.ROOT/'assets/demo/frames/000047.jpg').read_bytes()
        app.add_frame(data['id'],last,20)
        for fmt,expected in [('native',(1920,620)),('portrait',(1080,1920)),('landscape',(1920,1080))]:
            with self.subTest(format=fmt):
                out=app.render(data['id'],{'format':fmt,'duration':2,'hold':1,'title':"The cut: 100% 'yours'"},app.DATA/f'out-{fmt}')
                info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(out)]))
                video=info['streams'][0]
                self.assertEqual((video['width'],video['height']),expected)
                self.assertAlmostEqual(float(info['format']['duration']),3,places=1)
                self.assertEqual(video['pix_fmt'],'yuv420p')
                self.assertFalse(any(s['codec_type']=='audio' for s in info['streams']))
        out=app.DATA/'out-native/timelinelapse.mp4'
        def tiny_at(seconds):
            return subprocess.check_output(['ffmpeg','-v','error','-ss',str(seconds),'-i',str(out),'-frames:v','1','-vf','scale=32:12,format=gray','-f','rawvideo','-'])
        # A hold must retain the final capture, rather than flashing back to the first.
        def mean_difference(a,b):return sum(abs(x-y) for x,y in zip(a,b))/len(a)
        # Lossy H.264 may change individual pixel values slightly between frames.
        self.assertLess(mean_difference(tiny_at(1.5),tiny_at(2.5)),.75)
        self.assertGreater(mean_difference(tiny_at(0),tiny_at(2.5)),2)


if __name__=='__main__':unittest.main()
