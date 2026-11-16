import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, BrainCircuit, CheckCircle2, Cpu, Database, GitCompare, Layers, Menu, Radar, Radio, ShieldCheck, Sparkles, Target, Wand2, X } from 'lucide-react'
import HeroSim from './HeroSim'
import TwinCompare from './TwinCompare'
import './landing.css'

const Logo = ({ size = 28 }: { size?: number }) => (
  <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true"><path d="M4 18h12c7 0 9 7 12 11" stroke="#2ad4c3" strokeWidth="3.5" fill="none" strokeLinecap="round" /><path d="M4 32h18" stroke="#2ad4c3" strokeWidth="3.5" fill="none" strokeLinecap="round" /><path d="M4 46h12c7 0 9-7 12-11" stroke="#2ad4c3" strokeWidth="3.5" fill="none" strokeLinecap="round" /><ellipse cx="43" cy="32" rx="12" ry="15" stroke="#6f69ff" strokeWidth="5" fill="none" /></svg>
)

const NAV = [['how', 'How it works'], ['twin', 'Digital Twin'], ['adaptive', 'Adaptive Intelligence'], ['workflow', 'Workflow'], ['architecture', 'Architecture']] as const

/** Fades sections in as they enter the viewport. Content stays visible without JS or with reduced motion. */
function useReveal() {
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>('.lz [data-reveal]')
    if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) { els.forEach(e => e.classList.add('is-in')); return }
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target) } }), { threshold: 0.12, rootMargin: '0px 0px -40px 0px' })
    els.forEach(e => io.observe(e))
    return () => io.disconnect()
  }, [])
}

function useActiveSection() {
  const [active, setActive] = useState('')
  useEffect(() => {
    const els = NAV.map(([id]) => document.getElementById(id)).filter(Boolean) as HTMLElement[]
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) setActive(e.target.id) }), { rootMargin: '-45% 0px -50% 0px' })
    els.forEach(e => io.observe(e))
    return () => io.disconnect()
  }, [])
  return active
}

export default function Landing() {
  const [menu, setMenu] = useState(false)
  const [scrolled, setScrolled] = useState(false)
  const active = useActiveSection()
  const root = useRef<HTMLDivElement>(null)
  useReveal()
  useEffect(() => { document.title = 'LineZero · Queue intelligence for service operations' }, [])
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8)
    on(); window.addEventListener('scroll', on, { passive: true }); return () => window.removeEventListener('scroll', on)
  }, [])
  useEffect(() => {
    if (!menu) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenu(false) }
    document.addEventListener('keydown', k); return () => document.removeEventListener('keydown', k)
  }, [menu])

  return (
    <div className="lz" ref={root}>
      <a className="lz-skip" href="#main">Skip to content</a>
      <header className={`lz-nav ${scrolled || menu ? 'solid' : ''}`}>
        <div className="lz-wrap lz-nav-in">
          <a className="lz-brand" href="#top" aria-label="LineZero home"><Logo /><span>LineZero</span></a>
          <nav className={`lz-links ${menu ? 'open' : ''}`} aria-label="Sections">
            {NAV.map(([id, label]) => <a key={id} href={`#${id}`} className={active === id ? 'on' : ''} onClick={() => setMenu(false)}>{label}</a>)}
            <Link to="/app/dashboard" className="lz-btn p sm lz-mob-cta">Open application</Link>
          </nav>
          <Link to="/app/dashboard" className="lz-btn p sm lz-desk-cta">Open application <ArrowRight size={14} /></Link>
          <button className="lz-burger" onClick={() => setMenu(m => !m)} aria-label={menu ? 'Close menu' : 'Open menu'} aria-expanded={menu}>{menu ? <X size={18} /> : <Menu size={18} />}</button>
        </div>
      </header>

      <main id="main">
        {/* Hero */}
        <section className="lz-hero" id="top">
          <div className="lz-wrap lz-hero-in">
            <div className="lz-hero-copy">
              <p className="lz-pill"><i />Queue intelligence for service operations</p>
              <h1>Every queue has a breaking point. See it before your customers do.</h1>
              <p className="lz-lead">LineZero monitors live queues, forecasts congestion, stress-tests changes in a digital twin and proposes interventions for your team to approve. Every number is labelled as observed, simulated or predicted.</p>
              <div className="lz-cta">
                <Link to="/app/dashboard" className="lz-btn p lg">Open the application <ArrowRight size={16} /></Link>
                <a href="#how" className="lz-btn lg">Explore capabilities</a>
              </div>
              <ul className="lz-facts">
                <li><CheckCircle2 size={15} />Works offline in your browser with synthetic demo data</li>
                <li><CheckCircle2 size={15} />Connect the FastAPI backend for the Digital Twin and Adaptive Intelligence</li>
              </ul>
            </div>
            <div className="lz-hero-vis"><HeroSim /></div>
          </div>
        </section>

        {/* How it works */}
        <section className="lz-sec" id="how">
          <div className="lz-wrap">
            <div className="lz-head" data-reveal>
              <p className="lz-eyebrow">How LineZero works</p>
              <h2>From a live queue to a decision you can defend</h2>
              <p>Five stages, each backed by an engine in the codebase. LineZero detects, simulates and recommends. People decide and act.</p>
            </div>
            <ol className="lz-steps" data-reveal>
              {([
                [Radio, 'Observe', 'Queues, counters and customers are tracked live. Analytics show demand, waiting and service patterns, and a statistical engine flags bottlenecks.', 'Live Monitor · Analytics · Bottlenecks'],
                [Sparkles, 'Predict', 'A transparent waiting-time baseline, plus a 5, 15, 30 and 60 minute forecast from many simulation replications started at the current queue state.', 'Dashboard · Digital Twin'],
                [Cpu, 'Simulate', 'Ask what-if questions and inject failures, surges and slow service. Scenarios run on identical random seeds so differences are paired, not noise.', 'Simulator · Digital Twin'],
                [Wand2, 'Intervene', 'Candidate interventions are simulated, costed and ranked against doing nothing. An operator approves; the operator carries the change out.', 'Interventions · Self-healing'],
                [BrainCircuit, 'Learn', 'The twin recalibrates from observed data behind a validation gate, watches for drift, and compares expected against observed outcomes.', 'Adaptive · Outcomes'],
              ] as const).map(([Icon, t, d, where], i) => (
                <li key={t}><span className="lz-step-n">{i + 1}</span><Icon size={20} className="lz-ic" /><h3>{t}</h3><p>{d}</p><small>{where}</small></li>
              ))}
            </ol>
          </div>
        </section>

        {/* Digital twin */}
        <section className="lz-sec alt" id="twin">
          <div className="lz-wrap lz-split">
            <div data-reveal>
              <p className="lz-eyebrow">Digital Twin</p>
              <h2>Test the fix in simulation, not on your customers</h2>
              <p className="lz-sub">The twin starts from the queue’s real current state and projects it forward. It is read-only: it never writes to a real queue.</p>
              <ul className="lz-list">
                {([
                  [Radio, 'Live twin and forecast', 'Animated floor view built from database state, with queue, wait and utilization forecasts.'],
                  [Cpu, 'What-if and chaos', 'Six presets plus counter failures, outages, surges, slow service and staff shortages.'],
                  [ShieldCheck, 'Self-healing', 'Manual, assisted or automatic recovery plans, ranked by simulation.'],
                  [GitCompare, 'Compare', 'Two to five scenarios on shared seeds with paired differences and 95% intervals.'],
                  [Layers, 'Explain', 'Deterministic explanations grounded in the numbers on screen.'],
                ] as const).map(([Icon, t, d]) => <li key={t}><Icon size={18} /><div><b>{t}</b><span>{d}</span></div></li>)}
              </ul>
            </div>
            <div data-reveal><TwinCompare /><p className="lz-cap">Computed live in your browser by LineZero’s simulation engine. Parameters are illustrative.</p></div>
          </div>
        </section>

        {/* Adaptive Intelligence */}
        <section className="lz-sec" id="adaptive">
          <div className="lz-wrap">
            <div className="lz-head" data-reveal>
              <p className="lz-eyebrow">Adaptive Intelligence</p>
              <h2>A decision-support loop that shows its working</h2>
              <p>Predict. Understand. Intervene. Learn. Every score lists its inputs and formula, and no accuracy figure is claimed that was not computed from the data on screen.</p>
            </div>
            <div className="lz-cards" data-reveal>
              {([
                [Target, 'Calibration', 'Learns arrival and service rates per queue and counter with a chronological split. A candidate becomes a version only if it predicts held-out waits better. Versions are append-only and reversible.'],
                [Radar, 'Drift detection', 'Compares a reference window with a recent one using an exact Poisson test, a KS test and a Welch test, with Bonferroni correction and a practical-effect threshold.'],
                [ShieldCheck, 'Risk radar', 'Seven risk categories scored from observed data and the twin’s forecast, with severity bands, a confidence value and an explanation for each score.'],
                [Wand2, 'Interventions', 'Open reserve counters, assist staff, divert arrivals or change the assignment rule. Each is simulated against a baseline, costed and ranked for approval.'],
              ] as const).map(([Icon, t, d]) => <article key={t} className="lz-card"><Icon size={20} className="lz-ic" /><h3>{t}</h3><p>{d}</p></article>)}
            </div>
            <div className="lz-prov" data-reveal>
              <span>Every figure is tagged</span>
              <i className="chip ok">Observed</i><i className="chip demo">Synthetic</i><i className="chip vio">Simulated</i><i className="chip warn">Predicted</i><i className="chip">Explanation</i>
            </div>
          </div>
        </section>

        {/* Workflow */}
        <section className="lz-sec alt" id="workflow">
          <div className="lz-wrap">
            <div className="lz-head" data-reveal>
              <p className="lz-eyebrow">Simulation and intervention workflow</p>
              <h2>Nothing changes until a person approves it</h2>
              <p>LineZero never executes an intervention. Approving records a decision; an intervention counts as applied only when you confirm you carried it out.</p>
            </div>
            <ol className="lz-flow" data-reveal>
              {([['Detect', 'A risk is scored from observed data'], ['Explain', 'Inputs, formula and confidence are shown'], ['Propose', 'Candidates are simulated against a baseline'], ['Approve', 'An operator accepts or rejects'], ['Apply', 'People make the change and confirm it'], ['Learn', 'Expected vs observed outcome is recorded']] as const).map(([t, d], i) => (
                <li key={t} className={t === 'Approve' || t === 'Apply' ? 'human' : ''}><span>{i + 1}</span><b>{t}</b><small>{d}</small></li>
              ))}
            </ol>
            <p className="lz-legend-line" data-reveal><i className="human" />Steps performed by people &nbsp;·&nbsp; <i />Steps computed by LineZero</p>
          </div>
        </section>

        {/* Architecture */}
        <section className="lz-sec" id="architecture">
          <div className="lz-wrap">
            <div className="lz-head" data-reveal>
              <p className="lz-eyebrow">Technical architecture</p>
              <h2>Pure engines behind a thin API</h2>
              <p>Engines are pure functions of their inputs. Services own database access and routes stay thin. The frontend also ships an offline demo engine.</p>
            </div>
            <div className="lz-arch" data-reveal>
              <div className="lz-layer"><h3>Frontend</h3><p>React, TypeScript, Vite</p><ul><li>React Router, Zustand</li><li>Recharts, lucide-react</li><li>Browser demo engine (offline)</li></ul></div>
              <div className="lz-arrow" aria-hidden="true">HTTP /api/v1</div>
              <div className="lz-layer"><h3>API</h3><p>FastAPI, Pydantic v2</p><ul><li>Thin routes</li><li>Services: database access and orchestration</li><li>Optional Gemini rewording of explanations</li></ul></div>
              <div className="lz-arrow" aria-hidden="true">calls</div>
              <div className="lz-layer hl"><h3>Engines</h3><p>Pure computation</p><ul><li>SimPy discrete-event simulation</li><li>Prediction, optimization, bottleneck</li><li>Twin forecast, recovery, scenarios</li><li>Calibration, drift, risk, interventions</li></ul></div>
              <div className="lz-arrow" aria-hidden="true">SQLAlchemy</div>
              <div className="lz-layer"><h3>Data</h3><p>SQLite or PostgreSQL</p><ul><li>Alembic migrations</li><li>Versioned calibration, audit trail</li><li><Database size={13} /> Synthetic data is always flagged</li></ul></div>
            </div>
          </div>
        </section>

        {/* Final CTA */}
        <section className="lz-sec cta">
          <div className="lz-wrap lz-final" data-reveal>
            <h2>See where your queue breaks</h2>
            <p>Open the application with synthetic demo data in seconds. No account needed and nothing to install.</p>
            <div className="lz-cta c"><Link to="/app/dashboard" className="lz-btn p lg">Open the application <ArrowRight size={16} /></Link><Link to="/app/simulator" className="lz-btn lg">Try the simulator</Link></div>
          </div>
        </section>
      </main>

      <footer className="lz-foot">
        <div className="lz-wrap lz-foot-in">
          <div><a className="lz-brand" href="#top"><Logo /><span>LineZero</span></a><p>Queue intelligence for service operations. Predict. Simulate. Optimize. Recover.</p></div>
          <nav aria-label="Application"><b>Application</b><Link to="/app/dashboard">Dashboard</Link><Link to="/app/simulator">Simulator</Link><Link to="/app/digital-twin">Digital Twin</Link><Link to="/app/adaptive-intelligence">Adaptive Intelligence</Link></nav>
          <nav aria-label="Product"><b>Product</b><a href="#how">How it works</a><a href="#twin">Digital Twin</a><a href="#adaptive">Adaptive Intelligence</a><a href="#architecture">Architecture</a></nav>
        </div>
        <div className="lz-wrap lz-foot-note">Demo data is synthetic. LineZero proposes; people decide and act.</div>
      </footer>
    </div>
  )
}
