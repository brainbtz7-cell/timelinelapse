"""Rebuild the illustrative demo. Development-only dependency: Pillow."""
from pathlib import Path
import json
import math
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT/'assets'/'demo'
FONT = str(ROOT/'assets'/'SpaceGrotesk.ttf')


def frame(step):
    image = Image.new('RGB',(1920,620),'#202321')
    d = ImageDraw.Draw(image)
    def label(x,y,t,size=15,color='#a3aca6'):
        d.text((x,y),t,font=ImageFont.truetype(FONT,size),fill=color)
    d.rectangle((0,0,1920,45),fill='#2a2f2b')
    label(24,12,'THE LONG WAY HOME',17,'#dae0d6')
    label(1410,14,'EDIT / ILLUSTRATIVE DEMO',12,'#86967f')
    label(1740,12,f'00:{int(step*2):02d}:00',16,'#c6d7a8')
    for x in range(230,1920,90):
        d.line((x,80,x,620),fill='#303631')
    for i in range(19):
        x=230+i*90
        label(x+4,60,f'00:{i*5//60:02d}:{i*5%60:02d}',11,'#778772')
        d.line((x,78,x,87),fill='#596950')
    rows=[('V3','Titles',88),('V2','B-roll',169),('V1','Main cut',250),('A1','Dialogue',349),('A2','Music',430),('A3','Atmosphere',511)]
    for track,name,y in rows:
        d.rectangle((0,y,213,y+76),fill='#292e29')
        d.line((0,y+77,1920,y+77),fill='#161c17',width=2)
        label(20,y+13,track,17,'#c0ceb5')
        label(65,y+15,name,13,'#83917a')
        label(20,y+46,'◇    M    S',11,'#6d7c66')
    def clip(start,duration,row,name,color,seed=0,audio=False):
        x=232+start*17.3;y=rows[row][2]+5;end=min(1915,x+duration*17.3)
        if end<=x:return
        d.rounded_rectangle((int(x),y,int(end),y+65),radius=3,fill=color)
        d.line((int(x)+1,y,int(end)-1,y),fill='#c3d4ba',width=1)
        # Caption clipping is intentional: real timeline labels disappear on tiny clips.
        maxchar=max(0,int((end-x-12)/8))
        label(int(x)+7,y+6,name[:maxchar],12,'#ebf0e8')
        if audio:
            center=y+45
            for p in range(int(x)+3,int(end)-2,3):
                a=2+abs(math.sin((p+seed)*.12)*math.cos((p-seed)*.031))*13
                d.line((p,center-a,p,center+a),fill='#a4c1a3')
        else:
            for p in range(int(x)+5,int(end)-12,38):
                d.rectangle((p,y+29,min(p+29,int(end)-4),y+58),fill='#20372b')
                d.polygon([(p,y+58),(p+12,y+36+(seed%5)),(min(p+29,int(end)-4),y+58)],fill='#7d9c80')
    # A rough cut grows, then shortens as the editor trims and adds layers.
    rough=min(12,max(0,step-1))
    durations=[10,7,9,8,7,8,10,6,8,7,5,9]
    if step>15:
        amount=min(1,(step-15)/12)
        durations=[v*(1-.28*amount) for v in durations]
    pos=0
    for i in range(rough):
        dur=durations[i]
        if step>40 and i==5:dur-=1.5
        clip(pos,dur,2,f'A7C_{i+1:04d}.MP4','#4e7182',i)
        if step>17:clip(pos+.1,max(.2,dur-.2),3,f'DIALOGUE_{i+1:02d}','#537267',i,True)
        pos+=dur
    if step>23:
        for i in range(min(7,step-23)):
            clip(6+i*10,3.5+(i%3),1,f'DETAIL_{i+1:02d}','#776181',i+3)
    if step>27:clip(0,max(1,pos-1),4,'MUSIC / distant mountains','#4c7150',5,True)
    if step>31:
        for i in range(min(9,step-31)):
            clip(i*8+.8,3+(i%2),5,f'FOLEY_{i+1:02d}','#5a756d',i+10,True)
    if step>37:clip(1,8,0,'THE LONG WAY HOME','#9b7a43',2)
    if step>42:clip(max(15,pos-8),7,0,'A FILM BY YOU','#9b7a43',3)
    head=232+((step*9)%90)*17.3
    d.line((int(head),80,int(head),610),fill='#d5b48b',width=2)
    d.polygon([(head-7,81),(head+7,81),(head,91)],fill='#d5b48b')
    return image


if __name__=='__main__':
    (DEST/'frames').mkdir(parents=True,exist_ok=True)
    frames=[]
    for i in range(48):
        name=f'{i:06d}.jpg';frame(i).save(DEST/'frames'/name,quality=88,subsampling=0)
        frames.append({'file':name,'elapsed':round(i/47*8280,3)})
    data={'id':'demo','title':'El arte de encontrar el corte','created':0,'interval':3,
          'elapsed':8280,'width':1920,'height':620,'frames':frames,'demo':True}
    (DEST/'session.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    print(f'Wrote {len(frames)} illustrative frames to {DEST}')
