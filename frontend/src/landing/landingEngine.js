import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import Lenis from 'lenis'

let THREE = null

export function mountLanding(opts) {
  window.gsap = gsap; window.ScrollTrigger = ScrollTrigger; window.Lenis = Lenis

var destroyed=false,cleanups=[];
var RM=matchMedia('(prefers-reduced-motion:reduce)').matches;
var S=window.LZ={active:.35,spd:1,cong:0,dim:0,bal:0,cz:0,cy:0,ry:0};
var MOBILE=innerWidth<820||/Mobi|Android/i.test(navigator.userAgent);
var $=function(s,r){return (r||document).querySelector(s)};
var loader=$('#loader'),bar=$('.bar i'),pct=$('.pct');
var tasks={dom:false,fonts:false,three:false,scene:false},shown={v:0},listeners=[],raf=0,ro;

function done(k){tasks[k]=true;var n=0,t=0;for(var i in tasks){t++;if(tasks[i])n++}
gsap.to(shown,{v:n/t,duration:.5,ease:'power2.out',onUpdate:function(){bar.style.transform='scaleX('+shown.v+')';pct.textContent=Math.round(shown.v*100)+'%'}});
if(n===t)ready=true;check()}
var ready=false,minTime=false;
function check(){if(ready&&minTime)exit()}

var burger=$('#burger'),links=$('#links');
burger.onclick=function(){var o=links.classList.toggle('open');burger.setAttribute('aria-expanded',o)};
links.addEventListener('click',function(e){if(e.target.tagName==='A')links.classList.remove('open')});

var lps=document.querySelectorAll('.lp'),lz=$('#lz');
gsap.set(lz,{opacity:0,transformOrigin:'50% 50%',scale:.4});
if(opts&&opts.skipLoader){minTime=true;loader.style.display='none'}
if(RM){minTime=true;gsap.set('.init',{opacity:1});}
else if(!(opts&&opts.skipLoader)){
var from=[{x:-60,y:-40},{x:-80,y:0},{x:-60,y:40}];
lps.forEach(function(p,i){var L=p.getTotalLength();gsap.set(p,{strokeDasharray:L,strokeDashoffset:L,x:from[i].x,y:from[i].y,opacity:.9})});
var tl=gsap.timeline({onComplete:function(){minTime=true;check()}});cleanups.push(function(){tl.kill()});
lps.forEach(function(p,i){tl.to(p,{strokeDashoffset:0,x:from[i].x*.4,y:from[i].y*.4,duration:.7,ease:'power2.out'},i*.15)});
tl.to(lps,{x:0,y:0,duration:.6,ease:'power3.inOut'},.9)
.to(lz,{opacity:1,scale:1,duration:.6,ease:'back.out(1.6)'},1.2)
.to('.init',{opacity:1,duration:.4},1.5)
.to('.lbls span',{opacity:1,duration:.3,stagger:{each:.5},yoyo:true,repeat:1,repeatDelay:.1},1.5);
tl.to({}, {duration:.2});
}
function exit(){
if(exit.d)return;exit.d=1;
var t=gsap.timeline({onComplete:function(){loader.style.display='none';window.ScrollTrigger&&ScrollTrigger.refresh();heroIn()}});
t.to(loader,{opacity:0,duration:RM?.2:.6,ease:'power2.inOut'});
}
function heroIn(){
if(RM)return;
gsap.from('h1 i',{yPercent:110,duration:1,ease:'power4.out',stagger:.12});
gsap.from('.eyebrow,.sub,.cta,.scroll',{opacity:0,y:20,duration:.8,stagger:.1,delay:.3,ease:'power2.out'});
gsap.from('nav',{opacity:0,y:-16,duration:.8,ease:'power2.out'});
}

function story(){
if(!window.ScrollTrigger){return}
gsap.registerPlugin(ScrollTrigger);
var K=innerWidth<1100?.5:1,lenis=null,tk,chs=gsap.utils.toArray('.ch'),nav=$('nav'),stx=$('#stx'),al=document.querySelectorAll('.links a[data-c]');
function setCh(i){stx.textContent=i?chs[i-1].dataset.n:'SYSTEMS NOMINAL';al.forEach(function(a){a.classList.toggle('on',+a.dataset.c===i)})}
if(!RM&&window.Lenis){lenis=new Lenis({lerp:.1});lenis.on('scroll',ScrollTrigger.update);tk=function(t){lenis.raf(t*1000)};gsap.ticker.add(tk);gsap.ticker.lagSmoothing(0)}
document.querySelectorAll('a[href^="#"]').forEach(function(a){a.addEventListener('click',function(e){var el=$(a.getAttribute('href'));if(!el)return;e.preventDefault();if(lenis)lenis.scrollTo(el);else el.scrollIntoView()})});
ScrollTrigger.create({start:80,end:'max',onToggle:function(s){nav.classList.toggle('solid',s.isActive)}});
ScrollTrigger.create({trigger:'#hero',start:'top top',end:'bottom 50%',onToggle:function(s){if(s.isActive)setCh(0)}});
chs.forEach(function(c,i){ScrollTrigger.create({trigger:c,start:'top 50%',end:'bottom 50%',onToggle:function(s){if(s.isActive)setCh(i+1)}})});
cleanups.push(function(){if(tk)gsap.ticker.remove(tk);if(lenis)lenis.destroy();ScrollTrigger.getAll().forEach(function(s){s.kill()});gsap.globalTimeline.clear()});
if(RM){S.active=.7;S.bal=1;$('#arr').textContent='168';$('#arr2').textContent='0%';return}
gsap.to('.copy',{opacity:0,y:-40,ease:'none',scrollTrigger:{trigger:'#hero',start:'top top',end:'70% top',scrub:true}});
chs.forEach(function(c){var q=gsap.utils.selector(c),st={trigger:c,start:'top 55%'};
gsap.from(q('.ln i'),{yPercent:110,duration:.9,ease:'power4.out',stagger:.1,scrollTrigger:st});
gsap.from(q('.eyebrow,.t,.hud,.util,.note,.btn'),{opacity:0,y:18,duration:.8,stagger:.1,delay:.2,ease:'power2.out',scrollTrigger:st})});
gsap.from('.util u',{scaleX:0,transformOrigin:'left',duration:1,stagger:.1,ease:'power3.out',scrollTrigger:{trigger:'#ch3',start:'top 40%'}});
var tl=gsap.timeline({defaults:{ease:'power1.inOut'},scrollTrigger:{trigger:'#story',start:'top top',end:'bottom bottom',scrub:.8}});
tl.to(S,{active:.6,cz:-3*K,ry:.25*K,duration:1},0)
.to(S,{active:1,spd:.35,cong:1,cz:-6*K,cy:1.2*K,ry:-.2*K,duration:1},1)
.to('#tint',{'--tc':'#3a1b14',duration:1},1)
.to(S,{dim:1,cz:-9*K,cy:-.4*K,ry:0,duration:1},2)
.to(S,{bal:1,dim:0,spd:1,active:.8,cz:0,cy:0,ry:0,duration:1},3)
.to('#tint',{'--tc':'#0d2d2f',duration:1},3);
tl.eventCallback('onUpdate',function(){$('#arr').textContent=Math.round(S.active*240);$('#arr2').textContent=Math.round(S.cong*(1-S.bal)*100)+'%'});
}
done('dom');story();
(document.fonts&&document.fonts.ready?document.fonts.ready:Promise.resolve()).then(function(){done('fonts')});

import('three').then(function(m){if(destroyed)return;THREE=m;done('three');try{buildScene()}catch(e){console.warn('3D unavailable',e)}done('scene')}).catch(function(){done('three');done('scene')});

function buildScene(){
var cv=$('#scene'),T=THREE;if(!cv)return;
var r=new T.WebGLRenderer({canvas:cv,antialias:!MOBILE,alpha:true,powerPreference:'high-performance'});
r.setPixelRatio(Math.min(devicePixelRatio,MOBILE?1.5:2));
var sc=new T.Scene(),cam=new T.PerspectiveCamera(45,1,.1,100);
var VIO=new T.Color('#6B65FF'),TEAL=new T.Color('#20D6C5'),DIM=new T.Color('#2a3558'),WARN=new T.Color('#FF7A45');
var root=new T.Group();sc.add(root);

var N=MOBILE?5:7,lanes=[],nodes=[],lines=[],BASEZ=19;
for(var i=0;i<N;i++){
var k=(i-(N-1)/2),y=k*1.5,z=k*-.9;
var c=new T.CatmullRomCurve3([
new T.Vector3(-17,y*1.2,z*1.4),new T.Vector3(-9,y*.9,z),new T.Vector3(-3,y*.25,z*.25),
new T.Vector3(0,0,0),new T.Vector3(3.5,y*.3,z*.3),new T.Vector3(9,y*.9,z),new T.Vector3(11,y,z)]);
lanes.push(c);
var g=new T.BufferGeometry().setFromPoints(c.getPoints(120));
var ln=new T.Line(g,new T.LineBasicMaterial({color:i%2?VIO:TEAL,transparent:true,opacity:.28}));lines.push(ln);root.add(ln);
var m=new T.Mesh(new T.BoxGeometry(.7,.7,.7),new T.MeshBasicMaterial({color:DIM}));
m.position.copy(c.getPoint(1));m.userData.glow=0;root.add(m);nodes.push(m);
var e=new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry(1,1,1)),new T.LineBasicMaterial({color:VIO}));
e.position.copy(m.position);root.add(e);
}
var core=new T.Group();
core.add(new T.LineSegments(new T.EdgesGeometry(new T.IcosahedronGeometry(2.1,1)),new T.LineBasicMaterial({color:VIO,transparent:true,opacity:.85})));
var inner=new T.Mesh(new T.OctahedronGeometry(.8),new T.MeshBasicMaterial({color:TEAL,wireframe:true}));
core.add(inner);root.add(core);
var ring=new T.Mesh(new T.TorusGeometry(3.2,.015,8,96),new T.MeshBasicMaterial({color:TEAL,transparent:true,opacity:.5}));
ring.rotation.x=Math.PI/2.4;root.add(ring);

var P=MOBILE?90:220,inst=new T.InstancedMesh(new T.SphereGeometry(.07,6,6),new T.MeshBasicMaterial({color:0xffffff}),P);
var st=[],o=new T.Object3D(),pos=new T.Vector3();
for(var j=0;j<P;j++){st.push({l:j%N,t:Math.random(),v:.035+Math.random()*.05,last:0});inst.setColorAt(j,j%3?TEAL:VIO)}
root.add(inst);
root.position.x=innerWidth>820?2.5:0;
var HOT=Math.floor(N/2),LOAD=[];
function weights(){var sk=S.cong*(1-S.bal),w=[],s=0,i,d;for(i=0;i<N;i++){d=Math.abs(i-HOT);w[i]=1+((d===0?4:d===1?1.6:.35)-1)*sk;s+=w[i]}for(i=0;i<N;i++){w[i]/=s;LOAD[i]=w[i]*N}return w}
function pick(){var w=weights(),r=Math.random();for(var i=0;i<N;i++){r-=w[i];if(r<=0)return i}return N-1}

function size(){var w=cv.clientWidth,h=cv.clientHeight;r.setSize(w,h,false);cam.aspect=w/h;
BASEZ=w/h<1?30:19;cam.updateProjectionMatrix();root.position.x=w>820?2.5:0;root.position.y=w<=820?3:0}
size();ro=new ResizeObserver(size);ro.observe(cv);

var px=0,py=0,tx=0,ty=0,clock=new T.Clock(),vis=true;
function mv(e){tx=e.clientX/innerWidth-.5;ty=e.clientY/innerHeight-.5}
if(!MOBILE&&!RM){addEventListener('pointermove',mv);listeners.push(['pointermove',mv])}
function vc(){vis=!document.hidden;if(vis&&!raf)raf=requestAnimationFrame(frame)}
document.addEventListener('visibilitychange',vc);listeners.push(['visibilitychange',vc,document]);

function frame(){
if(!vis||destroyed){raf=0;return}
var d=Math.min(clock.getDelta(),.05),t=clock.elapsedTime,sp=RM?0:1;
inst.count=Math.max(1,Math.floor(P*S.active));weights();
for(var j=0;j<inst.count;j++){var p=st[j];var prev=p.t;p.t+=p.v*d*sp*8*S.spd*(p.l===HOT?1-S.cong*(1-S.bal)*.55:1);
if(p.t>=1){p.t-=1;p.l=pick();}
if(prev<.97&&p.t>=.97||(p.t>.97&&p.last===0)){} 
lanes[p.l].getPoint(p.t,pos);
if(p.t>.93&&p.t<.99)nodes[p.l].userData.glow=1;
var sc2=.8+Math.sin(p.t*Math.PI)*.8;
o.position.copy(pos);o.scale.setScalar(sc2);o.updateMatrix();inst.setMatrixAt(j,o.matrix)}
inst.instanceMatrix.needsUpdate=true;
for(var n=0;n<nodes.length;n++){var u=nodes[n],ov=Math.min(1,Math.max(0,(LOAD[n]-1.15)/1.8)),lm=lines[n].material;u.userData.glow*=.94;
u.material.color.copy(DIM).lerp(TEAL,u.userData.glow).lerp(WARN,ov*.9).multiplyScalar(n===HOT?1:1-S.dim*.55);
u.scale.setScalar(1+u.userData.glow*.35+ov*.5*(1+Math.sin(t*6)*.15));
lm.color.copy(n%2?VIO:TEAL).lerp(WARN,ov);lm.opacity=n===HOT&&S.dim>0?.6:(.18+S.active*.2+ov*.35)*(1-(n===HOT?0:S.dim*.7))}
core.rotation.y=t*.15*sp;core.rotation.x=t*.08*sp;inner.rotation.y=-t*.4*sp;ring.rotation.z=t*.1*sp;
px+=(tx-px)*.05;py+=(ty-py)*.05;
root.rotation.y=S.ry;cam.position.z=BASEZ+S.cz;cam.position.x=px*3+Math.sin(t*.12)*(RM?0:1.2);cam.position.y=-py*2+1.5+S.cy+Math.sin(t*.1)*(RM?0:.5);
cam.lookAt(root.position.x*.4,0,0);
r.render(sc,cam);
raf=RM?0:requestAnimationFrame(frame)}
raf=requestAnimationFrame(frame);

cleanups.push(function(){cancelAnimationFrame(raf);raf=0;ro&&ro.disconnect();
listeners.forEach(function(l){(l[2]||window).removeEventListener(l[0],l[1])});r.dispose()});
}

  return function cleanup() {
    destroyed = true
    cleanups.forEach(function (fn) { try { fn() } catch (e) { } })
    cleanups = []
    
  }
}
