'use strict';
const $ = (id) => document.getElementById(id);
const state = {token:'',session:null,stream:null,crop:null,recording:false,paused:false,busy:false,
  elapsedBefore:0,started:0,index:0,playing:false,playStart:0,skipped:0,lastFingerprint:null,worker:null,upload:null};
const captureCanvas = document.createElement('canvas');
const fingerprintCanvas = document.createElement('canvas');
fingerprintCanvas.width=128; fingerprintCanvas.height=48;
const fingerprintContext = fingerprintCanvas.getContext('2d',{willReadFrequently:true});
let toastTimer, playRAF, currentCrop, dragStart;

function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('toast').hidden=true;},7000);}
async function api(path,options={}){
  const response=await fetch(path,{...options,headers:{'X-TimelineLapse-Token':state.token,...options.headers}});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'No se pudo completar la operación.');return data;
}
function post(path,body){return api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
function shortTime(seconds){seconds=Math.max(0,Math.floor(seconds||0));const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;return h?`${h}h ${String(m).padStart(2,'0')}m`:m?`${m}m ${String(s).padStart(2,'0')}s`:`${s}s`;}
function clock(seconds){return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;}
function elapsed(){return state.elapsedBefore+(state.recording&&!state.paused?(performance.now()-state.started)/1000:0);}
function frameURL(frame){return `/frames/${state.session.id}/${frame.file}`;}
function stopPlayback(){state.playing=false;cancelAnimationFrame(playRAF);$('playButton').textContent='▶';$('playButton').setAttribute('aria-label','Reproducir timelapse');}
function showFrame(index){
  const frames=state.session?.frames||[];state.index=Math.max(0,Math.min(frames.length-1,Math.round(index)));
  if(frames.length){$('frameImage').src=frameURL(frames[state.index]);$('frameImage').hidden=false;}else{$('frameImage').removeAttribute('src');$('frameImage').hidden=true;}
  $('emptyState').hidden=Boolean(frames.length);
  $('scrubber').max=Math.max(0,frames.length-1);$('scrubber').value=state.index;
  $('frameCounter').textContent=`CAPTURA ${String(frames.length?state.index+1:0).padStart(2,'0')} / ${String(frames.length).padStart(2,'0')}`;
  const duration=Number($('duration').value);$('playTime').textContent=clock(frames.length?state.index/frames.length*duration:0);$('playDuration').textContent=clock(duration);
}
function updateStats(){
  const frames=state.session?.frames||[];
  $('captureStat').textContent=frames.length;$('skippedStat').textContent=state.session?.demo?'—':state.skipped;
  $('elapsedStat').textContent=shortTime(state.recording?elapsed():state.session?.elapsed);
  $('lengthStat').innerHTML=`${Number($('duration').value)}<span>s</span>`;
  $('previewTitle').textContent=$('sessionTitle').value||'Mi edición';
  $('sessionBadge').textContent=state.recording?(state.paused?'EN PAUSA':'● GRABANDO'):state.session?.demo?'DEMO ILUSTRATIVA':'SESIÓN GUARDADA';
  $('sessionBadge').classList.toggle('recording',state.recording&&!state.paused);
  $('liveState').textContent=state.recording?(state.paused?'EN PAUSA':'EN VIVO'):'VISTA PREVIA';$('liveState').classList.toggle('live',state.recording);
  $('imageDisclaimer').textContent=state.session?.demo?'Demo simulada · no es una sesión tuya':'Capturas reales · guardadas en tu equipo';
  $('recordActions').hidden=!state.recording;$('recordButton').hidden=state.recording;
  $('recordButton').disabled=!state.stream||!state.crop;
  $('pauseButton').textContent=state.paused?'Continuar ▶':'Pausar Ⅱ';
  $('chooseSource').disabled=state.recording;$('recrop').hidden=!state.stream||state.recording;
  $('interval').disabled=state.recording;$('sessionSelect').disabled=state.recording;$('demoButton').disabled=state.recording;
  $('exportButton').disabled=frames.length<2||Boolean(state.exporting)||state.recording;
  $('backupLink').hidden=!state.session||state.session.demo||!frames.length;
  $('backupLink').href=state.session&&!state.session.demo?`/backup/${state.session.id}`:'#';
  document.body.classList.toggle('is-recording',state.recording);
}
async function loadSession(id,autoplay=false){
  stopPlayback();state.session=await api(`/api/sessions/${id}`);state.skipped=state.session.skipped||0;
  $('sessionTitle').value=state.session.title;$('sessionSelect').value=id;showFrame(0);updateStats();
  $('downloadLink').hidden=true;$('exportStatus').textContent='Sin marca de agua. Las capturas quedan en tu equipo.';
  if(autoplay)play();
}
async function refreshSessions(){
  const sessions=await api('/api/sessions');const select=$('sessionSelect');const selected=state.session?.id||'demo';
  select.replaceChildren(new Option('Demo incluida','demo'));
  for(const session of sessions){select.append(new Option(`${session.title} · ${session.count} capturas`,session.id));}
  select.value=selected;
}
function play(){
  if(!state.session?.frames.length)return;
  if(state.playing){stopPlayback();return;}
  const frames=state.session.frames.length;const duration=Number($('duration').value)*1000;
  if(state.index>=frames-1)state.index=0;
  state.playing=true;state.playStart=performance.now()-(state.index/frames*duration);
  $('playButton').textContent='Ⅱ';$('playButton').setAttribute('aria-label','Pausar timelapse');
  const animate=(now)=>{if(!state.playing)return;const p=(now-state.playStart)/duration;
    if(p>=1){showFrame(frames-1);stopPlayback();return;}
    const next=Math.floor(p*frames);if(next!==state.index)showFrame(next);playRAF=requestAnimationFrame(animate);};
  playRAF=requestAnimationFrame(animate);
}
function releaseSource(){
  if(state.stream){state.stream.getTracks().forEach(track=>track.stop());state.stream=null;}
  $('sourceVideo').srcObject=null;state.crop=null;$('sourceStatus').textContent='Elegí DaVinci y recortá la zona de pistas.';updateStats();
}
async function chooseSource(){
  if(!navigator.mediaDevices?.getDisplayMedia){toast('La captura de ventanas requiere Chrome o Edge de escritorio en localhost.');return;}
  try{
    const stream=await navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'window',frameRate:5,cursor:'never'},audio:false,
      preferCurrentTab:false,selfBrowserSurface:'exclude',surfaceSwitching:'exclude'});
    releaseSource();state.stream=stream;
    const video=$('sourceVideo');video.srcObject=stream;await video.play();
    stream.getVideoTracks()[0].addEventListener('ended',async()=>{
      if(state.recording)await stopRecording(false);releaseSource();toast('Se detuvo la pantalla compartida. Las capturas guardadas siguen disponibles.');
    });
    stream.getVideoTracks()[0].addEventListener('mute',()=>{if(state.recording&&!state.paused){pauseRecording();toast('La ventana dejó de enviar imagen. La captura quedó en pausa.');}});
    if(!video.videoWidth)await new Promise(resolve=>video.addEventListener('loadedmetadata',resolve,{once:true}));
    openCrop();
  }catch(error){if(error.name==='NotAllowedError'||error.name==='AbortError'){toast('No se compartió ninguna ventana. Podés volver a elegirla cuando quieras.');}else{toast(`No se pudo compartir la ventana: ${error.message}`);}}
}
function openCrop(){
  if(!state.stream)return;
  currentCrop=state.crop?{...state.crop}:{x:0,y:.47,w:1,h:.49};
  $('cropDialog').showModal();requestAnimationFrame(drawCrop);
}
function drawCrop(){
  const r=$('sourceVideo').getBoundingClientRect(),v=$('sourceVideo');const c=currentCrop;
  Object.assign($('cropSelection').style,{left:`${c.x*r.width}px`,top:`${c.y*r.height}px`,width:`${c.w*r.width}px`,height:`${c.h*r.height}px`});
  $('cropDimensions').textContent=`${Math.round(c.w*v.videoWidth)} × ${Math.round(c.h*v.videoHeight)} px`;
  $('confirmCrop').disabled=c.w*v.videoWidth<32||c.h*v.videoHeight<32;
}
function cropPoint(event){const r=$('sourceVideo').getBoundingClientRect();return {x:Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))};}
$('cropArea').addEventListener('pointerdown',(event)=>{dragStart=cropPoint(event);$('cropArea').setPointerCapture(event.pointerId);currentCrop={...dragStart,w:0,h:0};drawCrop();});
$('cropArea').addEventListener('pointermove',(event)=>{if(!dragStart)return;const p=cropPoint(event);currentCrop={x:Math.min(dragStart.x,p.x),y:Math.min(dragStart.y,p.y),w:Math.abs(p.x-dragStart.x),h:Math.abs(p.y-dragStart.y)};drawCrop();});
$('cropArea').addEventListener('pointerup',()=>{dragStart=null;});
$('cropArea').addEventListener('pointercancel',()=>{dragStart=null;});
$('fullCrop').onclick=()=>{currentCrop={x:0,y:0,w:1,h:1};drawCrop();};
$('confirmCrop').onclick=()=>{
  state.crop={...currentCrop};$('cropDialog').close();
  const v=$('sourceVideo'),w=Math.round(state.crop.w*v.videoWidth),h=Math.round(state.crop.h*v.videoHeight);
  $('sourceStatus').textContent=`Recorte listo · ${w} × ${h} px. Podés empezar a grabar.`;updateStats();
};
$('closeCrop').onclick=()=>{$('cropDialog').close();if(!state.crop)releaseSource();};
$('cropDialog').addEventListener('cancel',()=>{if(!state.crop)releaseSource();});
window.addEventListener('resize',()=>{if($('cropDialog').open)drawCrop();});

function fingerprint(){
  fingerprintContext.drawImage(captureCanvas,0,0,128,48);
  const rgba=fingerprintContext.getImageData(0,0,128,48).data,gray=new Uint8Array(128*48);
  for(let i=0;i<gray.length;i++)gray[i]=Math.round((rgba[4*i]+rgba[4*i+1]+rgba[4*i+2])/3);
  return gray;
}
function difference(a,b){let sum=0;for(let i=0;i<a.length;i++)sum+=Math.abs(a[i]-b[i]);return sum/a.length/255;}
async function captureFrame(force=false){
  if(state.busy||!state.recording||state.paused||!state.stream)return;
  const video=$('sourceVideo');if(video.readyState<2||!video.videoWidth)return;
  state.busy=true;
  try{
    const c=state.crop,context=captureCanvas.getContext('2d');
    context.drawImage(video,c.x*video.videoWidth,c.y*video.videoHeight,c.w*video.videoWidth,c.h*video.videoHeight,0,0,captureCanvas.width,captureCanvas.height);
    const current=fingerprint();
    if(!force&&$('skipSimilar').checked&&state.lastFingerprint&&difference(current,state.lastFingerprint)<.0015){state.skipped++;updateStats();return;}
    const image=await new Promise((resolve,reject)=>captureCanvas.toBlob(blob=>blob?resolve(blob):reject(new Error('No se pudo crear la captura.')),'image/jpeg',.91));
    const at=elapsed();const key=state.session.id;
    const data=await api(`/api/sessions/${key}/frame`,{method:'POST',headers:{'Content-Type':'image/jpeg','X-Elapsed':String(at)},body:image});
    state.lastFingerprint=current;state.session.frames.push({file:`${String(data.count-1).padStart(6,'0')}.jpg`,elapsed:at});state.session.elapsed=at;
    showFrame(state.session.frames.length-1);updateStats();
  }catch(error){if(state.recording){state.elapsedBefore=elapsed();state.paused=true;updateStats();}toast(`Captura en pausa: ${error.message}`);}
  finally{state.busy=false;}
}
function startTicker(interval){
  // A worker keeps expensive UI work from delaying captures. Browsers/OS may still suspend background pages.
  const script=`let timer;onmessage=e=>{clearInterval(timer);if(e.data)timer=setInterval(()=>postMessage('tick'),e.data)}`;
  const url=URL.createObjectURL(new Blob([script],{type:'text/javascript'}));state.worker=new Worker(url);URL.revokeObjectURL(url);
  state.worker.onmessage=()=>{if(state.recording&&!state.paused&&!state.busy){state.upload=captureFrame();updateStats();}};
  state.worker.postMessage(interval*1000);
}
async function startRecording(){
  if(!state.stream||!state.crop)return;
  try{
    stopPlayback();const video=$('sourceVideo'),c=state.crop;
    const scale=Math.min(1,3840/(c.w*video.videoWidth),2160/(c.h*video.videoHeight));
    captureCanvas.width=Math.max(32,Math.round(c.w*video.videoWidth*scale));captureCanvas.height=Math.max(32,Math.round(c.h*video.videoHeight*scale));
    state.session=await post('/api/sessions',{title:$('sessionTitle').value,interval:Number($('interval').value)});
    state.recording=true;state.paused=false;state.skipped=0;state.elapsedBefore=0;state.started=performance.now();state.lastFingerprint=null;
    $('downloadLink').hidden=true;$('exportStatus').textContent='Finalizá la grabación para exportar tu timelapse.';
    showFrame(0);updateStats();await refreshSessions();state.upload=captureFrame(true);await state.upload;startTicker(Number($('interval').value));
    toast('Grabando. Volvé a DaVinci y editá con la timeline visible.');
  }catch(error){state.recording=false;updateStats();toast(error.message);}
}
function pauseRecording(){
  if(!state.recording)return;
  if(!state.paused){state.elapsedBefore=elapsed();state.paused=true;}else{state.started=performance.now();state.paused=false;state.upload=captureFrame(true);}
  updateStats();
}
async function stopRecording(release=true){
  if(!state.recording)return;
  state.worker?.terminate();state.worker=null;
  if(state.upload)await state.upload;
  if(!state.paused&&release){state.upload=captureFrame(true);await state.upload;}
  state.elapsedBefore=elapsed();state.paused=true;
  try{state.session=await post(`/api/sessions/${state.session.id}/finish`,{elapsed:state.elapsedBefore,title:$('sessionTitle').value,skipped:state.skipped});}
  catch(error){toast(`Las capturas se guardaron, pero no se pudo cerrar la sesión: ${error.message}`);}
  state.recording=false;state.paused=false;
  if(release)releaseSource();updateStats();await refreshSessions();toast('Sesión guardada. Ya podés reproducirla y exportar.');
}
async function exportVideo(){
  state.exporting=true;updateStats();$('downloadLink').hidden=true;
  try{
    const job=await post('/api/render',{session:state.session.id,title:$('sessionTitle').value,duration:Number($('duration').value),hold:1,format:$('format').value,titles:true});
    let done=false;
    while(!done){await new Promise(resolve=>setTimeout(resolve,800));const data=await api(`/api/jobs/${job.id}`);
      $('exportStatus').textContent=data.status==='queued'?'Esperando turno…':`Creando tu MP4… ${data.progress||0}%`;
      if(data.status==='error')throw new Error(data.error);
      if(data.status==='ready'){done=true;$('downloadLink').href=data.download;$('downloadLink').download='timelinelapse.mp4';$('downloadLink').hidden=false;
        $('exportStatus').textContent=`Listo · ${(data.size/1024/1024).toFixed(1)} MB · ${Number($('duration').value)+1}s con pausa final.`;toast('Tu timelapse está listo para descargar.');}
    }
  }catch(error){$('exportStatus').textContent=error.message;toast(error.message);}
  finally{state.exporting=false;updateStats();}
}
$('chooseSource').onclick=chooseSource;$('recrop').onclick=openCrop;$('recordButton').onclick=startRecording;
$('pauseButton').onclick=pauseRecording;$('stopButton').onclick=()=>stopRecording();
$('playButton').onclick=play;$('scrubber').oninput=()=>{stopPlayback();showFrame(Number($('scrubber').value));};
$('demoButton').onclick=()=>loadSession('demo',true).catch(error=>toast(error.message));
$('sessionSelect').onchange=()=>loadSession($('sessionSelect').value).catch(error=>toast(error.message));
$('sessionTitle').oninput=updateStats;$('duration').onchange=()=>{stopPlayback();showFrame(state.index);updateStats();};
$('exportButton').onclick=exportVideo;$('helpButton').onclick=()=>$('helpDialog').showModal();$('closeHelp').onclick=()=>$('helpDialog').close();
$('fullscreen').onclick=()=>{if(document.fullscreenElement)document.exitFullscreen();else $('previewArt').requestFullscreen?.();};
document.addEventListener('keydown',event=>{if(event.code==='Space'&&!['INPUT','SELECT','TEXTAREA','BUTTON'].includes(document.activeElement.tagName)&&!document.querySelector('dialog[open]')){event.preventDefault();play();}});
window.addEventListener('beforeunload',event=>{if(state.recording||state.exporting){event.preventDefault();event.returnValue='';}});
async function init(){
  try{const config=await api('/api/config');state.token=config.token;await refreshSessions();await loadSession('demo');
    if(!config.ffmpeg){$('exportStatus').textContent='Falta FFmpeg para exportar. Podés grabar y guardar capturas igualmente.';}
  }catch(error){toast(`No se pudo iniciar: ${error.message}. Abrí esta app con python3 app.py.`);}
}
init();
