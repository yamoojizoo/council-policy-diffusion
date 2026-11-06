const { chromium } = require('playwright'); const fs=require('fs');
const OUT='/home/claude/final/demo2/frames'; fs.rmSync(OUT,{recursive:true,force:true}); fs.mkdirSync(OUT,{recursive:true});
(async () => {
  const b = await chromium.launch({args:['--disable-gpu-vsync','--force-device-scale-factor=1']});
  const p = await b.newPage({viewport:{width:1920,height:1080}});
  await p.goto('file:///home/claude/final/demo2/stage.html'); await p.waitForTimeout(2500);
  const fr = p.frames().find(f=>f.url().includes('dash.html'));
  await fr.addStyleTag({content:'.nav{position:static!important} ::-webkit-scrollbar{display:none}'});
  const cdp = await p.context().newCDPSession(p); const frames=[]; let n=0;
  cdp.on('Page.screencastFrame', async ev => { const f=`${OUT}/f${String(n++).padStart(6,'0')}.jpg`; fs.writeFileSync(f, Buffer.from(ev.data,'base64')); frames.push([f, ev.metadata.timestamp]); try{await cdp.send('Page.screencastFrameAck',{sessionId:ev.sessionId});}catch(e){} });
  const W=ms=>p.waitForTimeout(ms); const S=(fn,...a)=>p.evaluate(fn,...a);
  const rect=async (sel,pad=0)=>fr.evaluate(([s,pad])=>{const e=typeof s==='string'?document.querySelector(s):null;if(!e)return null;const r=e.getBoundingClientRect();return {x:r.left-pad,y:r.top-pad,w:r.width+2*pad,h:r.height+2*pad};},[sel,pad]);
  const scrollTo=async (sel,off=40)=>{await fr.evaluate(([s,off])=>{const e=document.querySelector(s);if(e)window.scrollTo({top:e.getBoundingClientRect().top+scrollY-off,behavior:'smooth'});},[sel,off]);await W(1300);};
  const settle=async()=>{for(let i=0;i<30;i++){const a=await fr.evaluate(()=>scrollY);await W(120);const b2=await fr.evaluate(()=>scrollY);if(a===b2)break;}};
  const hl=async (sel,label,pad=6)=>{await settle();const r=await rect(sel,pad);await S(([r,l])=>hl(r,l),[r,label]);};
  const hlOff=()=>S(()=>hl(null));
  const start=Date.now()/1000;
  await cdp.send('Page.startScreencast',{format:'jpeg',quality:90,maxWidth:1920,maxHeight:1080,everyNthFrame:1});
  // ---- 인트로
  await S(()=>card('<div class="mid">지방에서 먼저 시작된 정책은</div><div class="big">어디로 번져 갈까요?</div>')); await W(3600);
  await S(()=>card('<div class="row"><div><b>17</b><span>광역의회</span></div><div><b>9,886</b><span>회의록</span></div><div><b>311만</b><span>발언</span></div></div><div class="mid">사람이 다 읽을 수 없는 양입니다</div>')); await W(3800);
  await S(()=>card('<div class="mid">그리고, 먼저 논의했다고</div><div class="big">따라 했다고 할 수는 없습니다</div>')); await W(3800);
  await S(()=>card('<div class="sm">팀 ripple · 2026 DATA·AI 분석 경진대회</div><div class="big">확인된 만큼만 말하는<br>정책 확산 지도</div>',true)); await W(3800);
  await S(()=>cardOff());
  // ---- 1. 목적 선택
  await S(()=>{win(true);copy('목적별 시작 화면','누가 쓰느냐에 따라<br>첫 화면이 달라집니다','국회 입법 지원, 지방의회 정책 준비, 행정 동향 파악, 연구·취재. <b>목적을 고르면 그 일에 필요한 화면이 먼저</b> 열립니다.','같은 데이터라도 묻는 질문이 다르기 때문입니다.')}); await W(2600);
  await hl('#entry .entry-in button, #entry button','입법 검토'); await W(2600); await hlOff();
  await fr.evaluate(()=>choose('nat')); await W(900);
  // ---- 2. 입법 검토 신호
  await S(()=>copy('국회·입법 지원','여러 지역으로 번지는 조례,<br>법률이 필요하다는 신호','<b>조례로 다룬 의회 수 · 최근 6개월 확산 속도 · 법률 대응 요구 발언</b>을 한 줄에 놓고 입법 검토 순서를 정합니다.','지방에서 반복되는 의제를 일찍 포착하면 입법 검토 시점을 앞당길 수 있습니다.')); await W(1500);
  await fr.evaluate(()=>window.scrollTo({top:430,behavior:'smooth'})); await W(1400);
  await hl('#v-for .sig, #v-for .row, #v-for section .panel','입법 검토 신호'); await W(4200); await hlOff();
  // ---- 3. 개요 지도
  await fr.evaluate(()=>{go('overview');window.scrollTo(0,0);}); await W(600);
  await S(()=>copy('개요','정책이 번지는 길을<br>지도 위에서','의제가 처음 나온 의회부터 <b>월별로 번지는 과정을 재생</b>하고, 다음에 다룰 가능성이 큰 의회를 <b>점선으로 예측</b>합니다.','지역 간 흐름을 한눈에: 어디서 시작해 어디까지 왔는지.')); await W(1200);
  await hl('.hero .map, .hero svg, .hero','확산 재생'); await W(6500); await hlOff();
  // ---- 4. 깔때기
  await scrollTo('.funnel',140);
  await S(()=>copy('분석 깔때기','311만 개의 발언에서<br>결정적 근거 3건까지','단계마다 기준을 통과한 것만 남깁니다. 이슈 후보 2,158 → 여러 의회 928 → 신규 의제 158 → <b>다른 지역을 근거로 든 도입 3건</b>.','근거가 약하면 \'확산 경로\'라고 부르지 않습니다.')); await W(1200);
  await hl('.funnel','근거로 좁혀 가기'); await W(5000); await hlOff();
  // ---- 5. 의제 상세 (빠른 이동)
  await fr.evaluate(()=>{window.scrollTo(0,0);palOpen();}); await W(800);
  await S(()=>copy('빠른 이동 Ctrl+K','찾고 싶은 의제로<br>한 번에','의제·의회·화면 이름을 입력하면 바로 이동합니다. 회의록 <b>원문 검색</b>도 같은 자리에서.','')); await W(900);
  await fr.type('#palq','산단',{delay:220}); await W(1300); await fr.press('#palq','Enter'); await W(1200);
  await S(()=>copy('의제 상세','언제, 어디서, 누가<br>처음 말했는지','산단 근로자 지원: 2024.4 울산에서 처음 관측된 뒤 <b>11개 의회</b>로. 확산 단계, 월별 지도, 누적 채택 곡선과 근거 유형을 함께 봅니다.','모든 판단에 회의록명 · 회의일자 · 발언자 · 원문이 붙습니다.')); await W(800);
  await fr.evaluate(()=>{document.querySelectorAll('#detail .pbtn').forEach(b=>b.click());}); await W(1500);
  await fr.evaluate(()=>window.scrollTo({top:520,behavior:'smooth'})); await W(4800);
  // ---- 6. 판정 근거
  await fr.evaluate(()=>{[...document.querySelectorAll('#detail .more')].forEach(b=>{if(/나머지/.test(b.textContent))b.click();});}); await W(500);
  await scrollTo('#detail .ref.explicit',150);
  await S(()=>copy('판정 근거','\'따라 했다\'고 말하려면<br>다섯 가지를 확인합니다','<b>시간적 선행 · 대상 일치 · 선례 단서어 · 도입 시점 180일 · 공식 입법 맥락.</b> 원문에서 지명은 파랑, 단서어는 주황으로 강조합니다.','Campbell의 인과 조건을 판정 규칙으로 옮겼습니다. 후속 의회 1,128곳 중 이 기준을 넘은 곳은 3곳뿐입니다.')); await W(1000);
  await hl('#detail .ref.explicit','결정적 증거'); await W(6500); await hlOff();
  // ---- 7. 정책 공백
  await fr.evaluate(()=>{go('assemblies',{asm:'전남'});}); await W(900);
  await scrollTo('.gap, #v-assemblies .panel:nth-of-type(2)',120);
  await fr.evaluate(()=>{const h=[...document.querySelectorAll('#v-assemblies h3')].find(x=>x.textContent.includes('아직 다루지'));if(h)window.scrollTo({top:h.getBoundingClientRect().top+scrollY-140,behavior:'smooth'});}); await W(1300);
  await S(()=>copy('의회별 화면','우리 의회가<br>아직 다루지 않은 것','이웃 의회는 이미 논의했지만 우리는 아직인 의제를, <b>다음에 다룰 가능성 순</b>으로 보여 줍니다.','정책지원관·전문위원이 다른 지역의 선행 논의를 바로 참고 자료로 씁니다.')); await W(1000);
  const gapSel=await fr.evaluate(()=>{const h=[...document.querySelectorAll('#v-assemblies h3')].find(x=>x.textContent.includes('아직 다루지'));if(!h)return null;const p=h.closest('.panel');p.id='gapPanel';return '#gapPanel';});
  if(gapSel){await hl(gapSel,'정책 공백');} await W(5200); await hlOff();
  // ---- 8. 사후 검증
  await fr.evaluate(()=>go('model')); await W(800);
  await fr.evaluate(()=>{const h=[...document.querySelectorAll('#v-model h3')].find(x=>x.textContent.includes('보지 않은'));const p=h.closest('.panel');p.id='postPanel';window.scrollTo({top:p.getBoundingClientRect().top+scrollY-180,behavior:'smooth'});}); await W(1300);
  await S(()=>copy('사후 검증','예측은<br>실제로 맞았습니다','2025.9.30까지만 보고 처음부터 다시 예측한 뒤, 모델이 <b>보지 않은 이후 92일</b>과 대조했습니다.','\'높음\' 예측의 18.4%가 실제로 논의를 시작했습니다. 평균 9.6%의 1.9배, ROC-AUC 0.663.')); await W(1000);
  await hl('#postPanel','모델이 보지 않은 기간'); await W(5200); await hlOff();
  // ---- 아웃트로
  await S(()=>{hideCopy();win(false);}); await W(600);
  await S(()=>{card(`<div class="mid">2025.9.30 예측 등급별, 이후 92일 실제 논의 비율</div><div class="tier">
   <div class="r"><span>높음</span><div class="bar"><i data-w="92%" style="background:#c55a11"></i><span class="avg"></span></div><span>18.4%</span></div>
   <div class="r"><span>보통</span><div class="bar"><i data-w="69.5%" style="background:#2e5c99"></i><span class="avg"></span></div><span>13.9%</span></div>
   <div class="r"><span>낮음</span><div class="bar"><i data-w="35.5%" style="background:#aab3c0"></i><span class="avg"></span></div><span>7.1%</span></div></div>
   <div class="sm">검은 선: 전체 평균 9.6%</div>`,true);setTimeout(bars,900);}); await W(5200);
  await S(()=>card('<div class="big">근거로 확인한 만큼만.</div><div class="mid">모든 판단에 원문을 붙였습니다</div>')); await W(3600);
  await S(()=>card('<div class="mid">상용 AI API 없이</div><div class="big">일반 PC에서, 더블클릭 한 번</div><div class="sm">약 30분 · 새 회의록이 들어오면 스스로 갱신</div>')); await W(3800);
  await S(()=>card('<div class="big">확인된 만큼만 말하는<br>정책 확산 지도</div><div class="sm">팀 ripple · 국회도서관 정책지정 문제 · 2026 DATA·AI 분석 경진대회</div>',true)); await W(4200);
  await S(()=>card('<div></div>')); await W(1200);
  const end=Date.now()/1000; await cdp.send('Page.stopScreencast'); await W(300);
  // concat 목록 (프레임 타임스탬프로 길이 계산)
  let L=''; for(let i=0;i<frames.length;i++){const d=(i+1<frames.length?frames[i+1][1]:frames[i][1]+0.5)-frames[i][1]; L+=`file '${frames[i][0]}'\nduration ${Math.max(0.001,d).toFixed(4)}\n`;}
  L+=`file '${frames[frames.length-1][0]}'\n`;
  fs.writeFileSync('/home/claude/final/demo2/list.txt',L);
  console.log('frames',frames.length,'span',(frames[frames.length-1][1]-frames[0][1]).toFixed(1),'fps',(frames.length/(frames[frames.length-1][1]-frames[0][1])).toFixed(1));
  await b.close();
})();
