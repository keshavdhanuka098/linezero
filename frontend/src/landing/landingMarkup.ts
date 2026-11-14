export const landingMarkup = `
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="sym" viewBox="0 0 64 64">
<path d="M4 18h12c7 0 9 7 12 11" stroke="#20D6C5" stroke-width="3.5" fill="none" stroke-linecap="round"/>
<path d="M4 32h18" stroke="#20D6C5" stroke-width="3.5" fill="none" stroke-linecap="round"/>
<path d="M4 46h12c7 0 9-7 12-11" stroke="#20D6C5" stroke-width="3.5" fill="none" stroke-linecap="round"/>
<ellipse cx="43" cy="32" rx="12" ry="15" stroke="#6B65FF" stroke-width="5" fill="none"/>
</symbol>
</svg>

<div id="loader" role="status" aria-label="Loading LineZero">
<svg class="lg" viewBox="0 0 64 64" aria-hidden="true">
<path class="lp" d="M4 18h12c7 0 9 7 12 11" stroke="#20D6C5" stroke-width="3.5" fill="none" stroke-linecap="round"/>
<path class="lp" d="M4 32h18" stroke="#20D6C5" stroke-width="3.5" fill="none" stroke-linecap="round"/>
<path class="lp" d="M4 46h12c7 0 9-7 12-11" stroke="#20D6C5" stroke-width="3.5" fill="none" stroke-linecap="round"/>
<ellipse id="lz" cx="43" cy="32" rx="12" ry="15" stroke="#6B65FF" stroke-width="5" fill="none"/>
</svg>
<div class="init">INITIALIZING LINEZERO</div>
<div class="lbls"><span>CONNECTING SYSTEMS</span><span>ANALYZING FLOW</span><span>CALIBRATING INTELLIGENCE</span></div>
<div class="bar"><i></i></div>
<div class="pct mono">0%</div>
</div>

<header id="hero">
<canvas id="scene" aria-hidden="true"></canvas>
<div class="shade"></div>
<nav>
<a class="brand" href="#hero" aria-label="LineZero home"><svg><use href="#sym"/></svg><span>LINEZERO</span></a>
<div class="links" id="links">
<a href="#ch1" data-c="1">Arrival</a><a href="#ch2" data-c="2">Congestion</a><a href="#ch3" data-c="3">Bottleneck</a><a href="#ch4" data-c="4">Insight</a><a href="/app/dashboard" data-launch class="launch-link">Open App</a>
<span class="status mono"><i class="dot"></i><b id="stx" style="font-weight:500">SYSTEMS NOMINAL</b></span>
</div>
<button id="burger" aria-label="Toggle menu" aria-expanded="false">☰</button>
</nav>
<div class="copy">
<p class="eyebrow">INTELLIGENT QUEUE OPERATIONS</p>
<h1 aria-label="Every queue has a breaking point."><span><i>EVERY QUEUE</i></span><span><i>HAS A BREAKING POINT.</i></span></h1>
<p class="sub">Predict congestion before it happens. Discover hidden bottlenecks. Transform waiting into intelligent operations.</p>
<div class="cta"><a class="btn p" href="#ch1">EXPLORE LINEZERO</a><a class="btn s" href="#ch4">DISCOVER THE SYSTEM</a><a class="btn t" href="/app/dashboard" data-launch>LAUNCH DASHBOARD →</a></div>
</div>
<div class="scroll mono">SCROLL<b></b></div>
</header>
<div id="tint"></div>
<main id="story">
<section class="ch" id="ch1" data-n="01 · ARRIVAL"><div class="stk"><div class="panel">
<p class="eyebrow">CHAPTER 01 · THE ARRIVAL</p>
<h2><span class="ln"><i>IT STARTS WITH</i></span><span class="ln"><i>A SINGLE ARRIVAL.</i></span></h2>
<p class="t">Every service system begins with incoming demand. But demand is never constant.</p>
<div class="hud mono">SIMULATED ARRIVALS<b id="arr">0</b></div>
</div></div></section>
<section class="ch" id="ch2" data-n="02 · CONGESTION"><div class="stk"><div class="panel">
<p class="eyebrow" style="color:#FF7A45">CHAPTER 02 · THE CONGESTION</p>
<h2><span class="ln"><i>DEMAND DOESN’T WAIT</i></span><span class="ln"><i>FOR CAPACITY.</i></span></h2>
<p class="t">When arrivals exceed service capacity, waiting becomes inevitable. Without prediction, organizations react only after congestion begins.</p>
<div class="hud mono">SIMULATED QUEUE PRESSURE<b id="arr2">0%</b></div>
</div></div></section>
<section class="ch" id="ch3" data-n="03 · BOTTLENECK"><div class="stk"><div class="panel">
<p class="eyebrow" style="color:#FF7A45">CHAPTER 03 · THE HIDDEN BOTTLENECK</p>
<h2><span class="ln"><i>THE BOTTLENECK ISN’T</i></span><span class="ln"><i>ALWAYS WHERE YOU EXPECT.</i></span></h2>
<p class="t">An inefficient system doesn’t always lack capacity. Sometimes, it simply allocates that capacity incorrectly.</p>
<div class="util mono" role="list" aria-label="Illustrative counter utilization">
<div role="listitem">C1<em><u style="width:38%"></u></em>38%</div><div role="listitem">C2<em><u style="width:46%"></u></em>46%</div><div class="hot" role="listitem">C3<em><u style="width:94%"></u></em>94%</div><div role="listitem">C4<em><u style="width:31%"></u></em>31%</div><div role="listitem">C5<em><u style="width:27%"></u></em>27%</div></div>
<p class="note mono">ILLUSTRATIVE FIGURES · NOT REAL MEASUREMENTS</p>
</div></div></section>
<section class="ch" id="ch4" data-n="04 · INSIGHT"><div class="stk"><div class="panel">
<p class="eyebrow">CHAPTER 04 · THE LINEZERO INSIGHT</p>
<h2><span class="ln"><i>WHAT IF YOU COULD SEE IT</i></span><span class="ln"><i>BEFORE IT HAPPENS?</i></span></h2>
<p class="t">LineZero turns operational data into predictions, insights and smarter decisions.</p>
<div class="cta"><a class="btn p" href="/app/dashboard" data-launch>LAUNCH DASHBOARD →</a><a class="btn s" href="#hero">BACK TO THE START</a></div>
</div></div></section>
</main>

`
