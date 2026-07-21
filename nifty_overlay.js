// Nifty overlay v2 — self-contained, fetches own data, uses MutationObserver
(function(){
  console.log("Nifty overlay v2 loading...");
  const state = {honestBT:null, realBT:null, rawBT:null, liveState:null};

  async function loadData(){
    const urls = {
      honestBT: "backtest_honest.json",
      realBT: "backtest_realistic.json",
      rawBT: "backtest_data.json",
      liveState: "data.json"
    };
    for(const [key,url] of Object.entries(urls)){
      try{
        const r = await fetch(url+"?t="+Date.now(),{cache:"no-store"});
        if(r.ok) state[key] = await r.json();
      }catch(e){console.warn("Failed",url,e)}
    }
    console.log("Nifty overlay data loaded:",
      "honest="+(state.honestBT?.monthlyJournal?.length||0),
      "real="+(state.realBT?.monthlyJournal?.length||0),
      "raw="+(state.rawBT?.monthlyJournal?.length||0),
      "live="+(state.liveState?.monthlyJournal?.length||0));
  }

  function currentView(){
    const activeTab = document.querySelector(".tab-btn.active");
    if(!activeTab) return "honest";
    const txt = activeTab.textContent.toLowerCase();
    if(txt.includes("honest")) return "honest";
    if(txt.includes("realistic")) return "realistic";
    if(txt.includes("raw")) return "raw";
    if(txt.includes("live")) return "live";
    return "honest";
  }

  function getSourceData(view){
    if(view==="honest") return state.honestBT;
    if(view==="realistic") return state.realBT;
    if(view==="raw") return state.rawBT;
    if(view==="live") return state.liveState;
    return state.honestBT;
  }

  function renderWithNifty(){
    const view = currentView();
    const src = getSourceData(view);
    if(!src || !src.monthlyJournal || src.monthlyJournal.length===0) return;

    const tagCls = view==="honest"?"honest-tag":view==="realistic"?"real-tag":view==="raw"?"bt-tag2":"live-tag";
    const tagText = view.toUpperCase();
    const div = document.getElementById("yearHistory");
    if(!div) return;

    const months = src.monthlyJournal.slice().map(m=>({...m}));
    const allMonths = months.slice().sort((a,b)=>a.month.localeCompare(b.month));

    // Check if nifty data present
    const hasNifty = months.some(m=>m.niftyMonthReturn!==undefined && m.niftyMonthReturn!==null);
    if(!hasNifty){
      console.warn("Nifty data not in "+view+" backtest — run nifty-enrich workflow");
    }

    const byYear = {};
    months.forEach(m=>{const y=m.month.slice(0,4);if(!byYear[y])byYear[y]=[];byYear[y].push(m)});
    const years = Object.keys(byYear).sort().reverse();

    div.innerHTML = years.map(y=>{
      const ms = byYear[y].sort((a,b)=>a.month.localeCompare(b.month));
      const startNav = ms[0].nav; const endNav = ms[ms.length-1].nav;
      const yrRet = ((endNav/startNav)-1)*100;
      const startNifty = ms[0].niftyValue; const endNifty = ms[ms.length-1].niftyValue;
      const niftyYr = (startNifty && endNifty) ? ((endNifty/startNifty)-1)*100 : null;
      const alphaYr = niftyYr!==null ? yrRet - niftyYr : null;
      const lastMoM = ms[ms.length-1].monthReturn;
      const tb = ms.reduce((a,m)=>a+(m.bought||[]).length,0);
      const ts = ms.reduce((a,m)=>a+(m.sold||[]).length,0);
      const tw = ms.reduce((a,m)=>a+(m.winsThisMonth||0),0);
      const tl = ms.reduce((a,m)=>a+(m.lossesThisMonth||0),0);

      let stats = "<span>"+ms.length+" months</span>";
      stats += "<span style='color:#94a3b8;font-size:10px'>YoY:</span><span class='"+(yrRet>=0?'green':'red')+"' style='font-weight:700'>"+(yrRet>=0?'+':'')+yrRet.toFixed(1)+"%</span>";
      if(niftyYr!==null){
        stats += "<span style='color:#94a3b8;font-size:10px'>Nifty:</span><span class='"+(niftyYr>=0?'green':'red')+"' style='font-weight:600'>"+(niftyYr>=0?'+':'')+niftyYr.toFixed(1)+"%</span>";
        stats += "<span style='color:#94a3b8;font-size:10px'>α:</span><span class='"+(alphaYr>=0?'green':'red')+"' style='font-weight:700'>"+(alphaYr>=0?'+':'')+alphaYr.toFixed(1)+"%</span>";
      }
      stats += "<span style='color:#94a3b8;font-size:10px'>Last MoM:</span><span class='"+(lastMoM>=0?'green':'red')+"' style='font-weight:700'>"+(lastMoM>=0?'+':'')+lastMoM.toFixed(1)+"%</span>";
      stats += "<span>End ₹"+(endNav/10000000).toFixed(3)+"Cr</span><span>"+tb+"B·"+ts+"S</span><span>W/L "+tw+"/"+tl+"</span>";

      const body = ms.slice().reverse().map(m=>{
        const mc = m.monthReturn>=0?'var(--green)':'var(--red)';
        const monthIdx = allMonths.findIndex(x=>x.month===m.month);
        const prevYr = allMonths[monthIdx-12];
        const yoy = prevYr ? ((m.nav/prevYr.nav)-1)*100 : null;
        const niftyMoM = m.niftyMonthReturn;
        const regBadge = m.regimeCostBuy!==undefined ? " <span class='muted' style='font-size:10px'>· Costs "+m.regimeCostBuy+"%/"+m.regimeCostSell+"%</span>" : "";

        let hdr = "<b>"+m.month+"</b> · ₹"+m.navCr.toFixed(3)+"Cr · <span style='color:"+mc+"'>"+(m.monthReturn>=0?'+':'')+m.monthReturn+"% MoM</span>";
        if(niftyMoM!==undefined && niftyMoM!==null){
          hdr += " · <span style='color:#94a3b8;font-size:10px'>Nifty:</span> <span style='color:"+(niftyMoM>=0?'var(--green)':'var(--red)')+";font-size:11px'>"+(niftyMoM>=0?'+':'')+niftyMoM.toFixed(2)+"%</span>";
          const monthAlpha = m.monthReturn - niftyMoM;
          hdr += " <span style='color:#94a3b8;font-size:10px'>α:</span><span style='color:"+(monthAlpha>=0?'var(--green)':'var(--red)')+";font-weight:700;font-size:11px'>"+(monthAlpha>=0?'+':'')+monthAlpha.toFixed(1)+"%</span>";
        }
        if(yoy!==null){
          hdr += " · <span style='color:"+(yoy>=0?'var(--green)':'var(--red)')+"'>"+(yoy>=0?'+':'')+yoy.toFixed(1)+"% YoY</span>";
        }
        hdr += " · Total "+(m.totalReturn>=0?'+':'')+m.totalReturn+"%" + regBadge;

        let out = "<div class='month-item'><div class='month-header'><div>"+hdr+"</div><div style='font-size:11px'>Holdings "+m.holdingsCount+" · Cash ₹"+(m.cash/100000).toFixed(1)+"L</div></div>";
        if((m.bought||[]).length){out += "<div style='margin-top:3px'><b class='green'>BOUGHT ("+m.bought.length+"):</b> "+m.bought.map(t=>"<span class='tag tag-buy'>"+t+"</span>").join('')+"</div>"}
        if((m.sold||[]).length){out += "<div style='margin-top:3px'><b class='red'>SOLD ("+m.sold.length+"):</b> "+m.sold.map(t=>"<span class='tag tag-sell'>"+t+"</span>").join('')+" <span class='muted' style='font-size:10px'>· W "+(m.winsThisMonth||0)+" L "+(m.lossesThisMonth||0)+"</span></div>"}
        if((m.held||[]).length){out += "<div style='margin-top:3px'><b class='muted'>HELD ("+m.held.length+"):</b> "+m.held.slice(0,15).map(t=>"<span class='tag tag-hold'>"+t+"</span>").join('')+(m.held.length>15?" <span class='muted'>+"+(m.held.length-15)+"</span>":'')+"</div>"}
        out += "</div>";
        return out;
      }).join('');

      return "<div class='year-card'><div class='year-header' onclick='toggleYear(\""+y+"\")'><div><div class='year-title'>"+y+" <span class='"+tagCls+"'>"+tagText+"</span></div><div class='year-stats'>"+stats+"</div></div><div class='expand-icon'>▶</div></div><div class='year-body' id='yb_"+y+"'>"+body+"</div></div>";
    }).join('');
    console.log("Nifty overlay: re-rendered "+view+" view with "+months.length+" months, nifty="+hasNifty);
  }

  // Watch for tab changes
  document.addEventListener("click", (e)=>{
    if(e.target && e.target.classList && e.target.classList.contains("tab-btn")){
      setTimeout(renderWithNifty, 100);
    }
  });

  // Initial load
  async function init(){
    await loadData();
    // Wait for main dashboard to finish rendering first
    setTimeout(renderWithNifty, 500);
    setTimeout(renderWithNifty, 2000);  // safety re-run
  }

  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
