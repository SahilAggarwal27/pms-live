// Simple Mode overlay — one-click toggle between Pitch view (Honest only) and Detail view (all)
(function(){
  const KEY = "pms_simple_mode";
  const CSS = `
    <style id="simpleModeCSS">
      body.simple-mode #rawHero,
      body.simple-mode #realHero,
      body.simple-mode #customHero,
      body.simple-mode .regime-panel,
      body.simple-mode .cost-panel { display: none !important; }
      body.simple-mode .hero-row { grid-template-columns: 1fr !important; max-width: 800px; margin: 0 auto 14px !important; }
      body.simple-mode #honestHero { transform: scale(1.02); }
      #simpleModeBtn {
        position: sticky; top: 8px; z-index: 100;
        display: flex; align-items: center; gap: 10px;
        background: linear-gradient(135deg, #064e3b, #059669);
        border: 2px solid #10b981;
        border-radius: 12px;
        padding: 12px 20px;
        margin-bottom: 14px;
        cursor: pointer;
        transition: transform 0.15s;
      }
      #simpleModeBtn:hover { transform: translateY(-1px); }
      #simpleModeBtn .label { font-size: 14px; font-weight: 800; color: white; }
      #simpleModeBtn .subtitle { font-size: 11px; color: #a7f3d0; margin-left: auto; }
      #simpleModeBtn .icon { font-size: 20px; }
      body:not(.simple-mode) #simpleModeBtn {
        background: linear-gradient(135deg, #1e293b, #334155);
        border-color: #64748b;
      }
      body:not(.simple-mode) #simpleModeBtn .label { color: #cbd5e1; }
      body:not(.simple-mode) #simpleModeBtn .subtitle { color: #94a3b8; }
    </style>
  `;
  document.head.insertAdjacentHTML("beforeend", CSS);

  function makeBtn(){
    // Insert button after H1 or at top of container
    const container = document.querySelector(".container");
    if(!container) return;
    if(document.getElementById("simpleModeBtn")) return;
    const btn = document.createElement("div");
    btn.id = "simpleModeBtn";
    btn.innerHTML = `
      <span class="icon">🏆</span>
      <span class="label" id="smLabel">SIMPLE MODE — Show only Honest + Fees</span>
      <span class="subtitle" id="smSub">Click to toggle · Pitch-ready view</span>
    `;
    // Insert after the first h1's parent div
    const firstBanner = document.getElementById("execBanner");
    if(firstBanner){
      firstBanner.parentNode.insertBefore(btn, firstBanner.nextSibling);
    } else {
      container.insertBefore(btn, container.firstChild.nextSibling);
    }
    btn.addEventListener("click", toggle);
  }

  function apply(){
    const on = localStorage.getItem(KEY) === "1";
    document.body.classList.toggle("simple-mode", on);
    const lbl = document.getElementById("smLabel");
    const sub = document.getElementById("smSub");
    if(lbl){
      lbl.textContent = on ? "🏆 SIMPLE MODE ON — Honest + Fees only (pitch view)" : "🎯 DETAIL MODE — All backtests visible";
    }
    if(sub){
      sub.textContent = on ? "Click to show all backtests (detail view)" : "Click for pitch-ready view";
    }
  }

  function toggle(){
    const cur = localStorage.getItem(KEY) === "1";
    localStorage.setItem(KEY, cur ? "0" : "1");
    apply();
  }

  function init(){
    makeBtn();
    apply();
  }

  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
  // Safety: re-add button if DOM re-renders
  setTimeout(init, 1000);
  console.log("Simple Mode overlay loaded ✓");
})();
