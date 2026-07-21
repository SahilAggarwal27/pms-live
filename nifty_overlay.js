// Nifty comparison overlay - adds Nifty MoM/YoY to year cards + month rows
// Runs after main dashboard renders. Reads niftyMonthReturn/niftyValue from backtest data.
(function(){
  const originalRender = window.renderYearHistory;
  if(!originalRender)return;

  window.renderYearHistory = function(){
    const div=document.getElementById("yearHistory");
    let months=[];let tagCls='real-tag';let tagText='REALISTIC';
    const view=window.historyView||'honest';
    if(view==='honest'&&window.honestBT){months=(honestBT.monthlyJournal||[]).map(m=>({...m,source:'honest'}));tagCls='honest-tag';tagText='HONEST'}
    else if(view==='realistic'&&window.realBT){months=(realBT.monthlyJournal||[]).map(m=>({...m,source:'real'}));tagCls='real-tag';tagText='REALISTIC'}
    else if(view==='raw'&&window.rawBT){months=(rawBT.monthlyJournal||[]).map(m=>({...m,source:'raw'}));tagCls='bt-tag2';tagText='RAW'}
    else if(view==='live'&&window.liveState){months=(liveState.monthlyJournal||[]).map(m=>({...m,source:'live'}));tagCls='live-tag';tagText='LIVE'}
    if(months.length===0){div.innerHTML='<div class="empty">No data. Trigger workflow.</div>';return}

    const allMonths=months.slice().sort((a,b)=>a.month.localeCompare(b.month));
    const byYear={};
    months.forEach(m=>{const y=m.month.slice(0,4);if(!byYear[y])byYear[y]=[];byYear[y].push(m)});
    const years=Object.keys(byYear).sort().reverse();

    div.innerHTML=years.map(y=>{
      const ms=byYear[y].sort((a,b)=>a.month.localeCompare(b.month));
      const startNav=ms[0].nav;const endNav=ms[ms.length-1].nav;
      const yrRet=((endNav/startNav)-1)*100;
      // Nifty year-on-year
      const startNifty=ms[0].niftyValue;const endNifty=ms[ms.length-1].niftyValue;
      const niftyYr=(startNifty&&endNifty)?((endNifty/startNifty)-1)*100:null;
      const alphaYr=niftyYr!==null?yrRet-niftyYr:null;
      const lastMoM=ms[ms.length-1].monthReturn;
      const tb=ms.reduce((a,m)=>a+(m.bought||[]).length,0);
      const ts=ms.reduce((a,m)=>a+(m.sold||[]).length,0);
      const tw=ms.reduce((a,m)=>a+(m.winsThisMonth||0),0);
      const tl=ms.reduce((a,m)=>a+(m.lossesThisMonth||0),0);

      let statsHtml="<span>"+ms.length+" months</span>";
      statsHtml+="<span style='color:#94a3b8;font-size:10px'>YoY:</span><span class='"+(yrRet>=0?'green':'red')+"' style='font-weight:700'>"+(yrRet>=0?'+':'')+yrRet.toFixed(1)+"%</span>";
      if(niftyYr!==null){
        statsHtml+="<span style='color:#94a3b8;font-size:10px'>Nifty:</span><span class='"+(niftyYr>=0?'green':'red')+"' style='font-weight:600'>"+(niftyYr>=0?'+':'')+niftyYr.toFixed(1)+"%</span>";
        statsHtml+="<span style='color:#94a3b8;font-size:10px'>Alpha:</span><span class='"+(alphaYr>=0?'green':'red')+"' style='font-weight:700'>"+(alphaYr>=0?'+':'')+alphaYr.toFixed(1)+"%</span>";
      }
      statsHtml+="<span style='color:#94a3b8;font-size:10px'>Last MoM:</span><span class='"+(lastMoM>=0?'green':'red')+"' style='font-weight:700'>"+(lastMoM>=0?'+':'')+lastMoM.toFixed(1)+"%</span>";
      statsHtml+="<span>End ₹"+(endNav/10000000).toFixed(3)+"Cr</span><span>"+tb+"B·"+ts+"S</span><span>W/L "+tw+"/"+tl+"</span>";

      const yearBody=ms.slice().reverse().map((m,mi)=>{
        const mc=m.monthReturn>=0?'var(--green)':'var(--red)';
        const monthIdx=allMonths.findIndex(x=>x.month===m.month);
        const prevYearMonth=allMonths[monthIdx-12];
        const yoy=prevYearMonth?((m.nav/prevYearMonth.nav)-1)*100:null;
        const niftyMoM=m.niftyMonthReturn;
        const regBadge=m.regimeCostBuy!==undefined?" <span class='muted' style='font-size:10px'>· Costs "+m.regimeCostBuy+"%/"+m.regimeCostSell+"%</span>":'';

        let hdr="<b>"+m.month+"</b> · ₹"+m.navCr.toFixed(3)+"Cr · <span style='color:"+mc+"'>"+(m.monthReturn>=0?'+':'')+m.monthReturn+"% MoM</span>";
        if(niftyMoM!==undefined&&niftyMoM!==null){
          hdr+=" · <span style='color:#94a3b8;font-size:10px'>Nifty:</span> <span style='color:"+(niftyMoM>=0?'var(--green)':'var(--red)')+";font-size:11px'>"+(niftyMoM>=0?'+':'')+niftyMoM.toFixed(2)+"%</span>";
          const monthAlpha=m.monthReturn-niftyMoM;
          hdr+=" <span style='color:#94a3b8;font-size:10px'>α:</span><span style='color:"+(monthAlpha>=0?'var(--green)':'var(--red)')+";font-weight:700;font-size:11px'>"+(monthAlpha>=0?'+':'')+monthAlpha.toFixed(1)+"%</span>";
        }
        if(yoy!==null){
          hdr+=" · <span style='color:"+(yoy>=0?'var(--green)':'var(--red)')+"'>"+(yoy>=0?'+':'')+yoy.toFixed(1)+"% YoY</span>";
        }
        hdr+=" · Total "+(m.totalReturn>=0?'+':'')+m.totalReturn+"%"+regBadge;

        let out="<div class='month-item'><div class='month-header'><div>"+hdr+"</div><div style='font-size:11px'>Holdings "+m.holdingsCount+" · Cash ₹"+(m.cash/100000).toFixed(1)+"L</div></div>";
        if((m.bought||[]).length){out+="<div style='margin-top:3px'><b class='green'>BOUGHT ("+m.bought.length+"):</b> "+m.bought.map(t=>"<span class='tag tag-buy'>"+t+"</span>").join('')+"</div>"}
        if((m.sold||[]).length){out+="<div style='margin-top:3px'><b class='red'>SOLD ("+m.sold.length+"):</b> "+m.sold.map(t=>"<span class='tag tag-sell'>"+t+"</span>").join('')+" <span class='muted' style='font-size:10px'>· W "+(m.winsThisMonth||0)+" L "+(m.lossesThisMonth||0)+"</span></div>"}
        if((m.held||[]).length){out+="<div style='margin-top:3px'><b class='muted'>HELD ("+m.held.length+"):</b> "+m.held.slice(0,15).map(t=>"<span class='tag tag-hold'>"+t+"</span>").join('')+(m.held.length>15?" <span class='muted'>+"+(m.held.length-15)+"</span>":'')+"</div>"}
        out+="</div>";
        return out;
      }).join('');

      return "<div class='year-card'><div class='year-header' onclick='toggleYear(\""+y+"\")'><div><div class='year-title'>"+y+" <span class='"+tagCls+"'>"+tagText+"</span></div><div class='year-stats'>"+statsHtml+"</div></div><div class='expand-icon'>▶</div></div><div class='year-body' id='yb_"+y+"'>"+yearBody+"</div></div>";
    }).join('');
  };

  // Re-render after overlay loaded
  if(typeof renderYearHistory==='function')renderYearHistory();
  console.log("Nifty overlay v1 loaded ✓");
})();
