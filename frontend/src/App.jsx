import React, { useState, useEffect, useRef, useCallback } from 'react'
import { RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer,
         LineChart, Line, Tooltip, ReferenceLine, AreaChart, Area } from 'recharts'
import ReactMarkdown from 'react-markdown'

// ── CONFIG ──────────────────────────────────────────────────────────────────
// Use empty string so all /api/* calls go through the Vite dev proxy to the backend
const API     = import.meta.env.VITE_API_URL || ''
const WS_URL  = import.meta.env.VITE_WS_URL || `ws://${window.location.hostname}:8081`
// Services are auto-discovered from Splunk — no hardcoding here.
// Whatever service names exist in index=main will appear on the dashboard.

// ── UTILS ─────────────────────────────────────────────────────────────────────
const rc  = l => ({LOW:'#10B981',MEDIUM:'#F59E0B',HIGH:'#EF4444',CRITICAL:'#EF4444',
                    SILENT:'#8B5CF6',UNKNOWN:'#94A3B8'}[l]||'#94A3B8')
const rbg = l => ({LOW:'rgba(16, 185, 129, 0.05)',MEDIUM:'rgba(245, 158, 11, 0.05)',
                   HIGH:'rgba(239, 68, 68, 0.08)',CRITICAL:'rgba(239, 68, 68, 0.15)',
                   SILENT:'rgba(139, 92, 246, 0.08)',UNKNOWN:'transparent'}[l]||'transparent')
const fmtUSD = n => n>=1000000?`$${(n/1000000).toFixed(1)}M`:n>=1000?`$${(n/1000).toFixed(0)}K`:`$${n}`
const elapsed = t => { const m=Math.floor((Date.now()-new Date(t))/60000); return m<1?'just now':`${m}m ago` }

async function api(path, opts={}) {
  try { const r=await fetch(`${API}${path}`, opts); return r.ok?r.json():null }
  catch { return null }
}

// ── ERROR BOUNDARY ───────────────────────────────────────────────────────────
class ErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state={error:null} }
  static getDerivedStateFromError(e) { return {error:e} }
  componentDidCatch(e,i) { console.error('PreCog panel error:',e,i) }
  render() {
    if (this.state.error) return (
      <div style={{padding:20,color:'var(--muted)',fontSize:11,textAlign:'center'}}>
        <div style={{marginBottom:8,fontSize:18}}>⚠️</div>
        Panel error — <button onClick={()=>this.setState({error:null})}
          style={{background:'none',border:'none',color:'var(--cyan)',textDecoration:'underline'}}>
          retry
        </button>
      </div>
    )
    return this.props.children
  }
}

// ── COPY HOOK ─────────────────────────────────────────────────────────────────
function useCopy() {
  const [ok,set]=useState(false)
  const copy = t => { navigator.clipboard.writeText(t).then(()=>{set(true);setTimeout(()=>set(false),2000)}) }
  return [ok,copy]
}

// ── TYPEWRITER TEXT (RCA) ─────────────────────────────────────────────────────
function TypewriterText({text, speed=15, onComplete}) {
  const [displayed, setDisplayed] = useState('')
  useEffect(() => {
    setDisplayed('')
    if (!text) return
    let i = 0
    const timer = setInterval(() => {
      setDisplayed(text.substring(0, i+1))
      i++
      if (i >= text.length) { clearInterval(timer); onComplete?.() }
    }, speed)
    return () => clearInterval(timer)
  }, [text, speed])
  return <span style={{whiteSpace:'pre-wrap'}}>{displayed}</span>
}

// ── ANIMATED RISK ORB ────────────────────────────────────────────────────────
function RiskOrb({level, score, size=56, animate=true}) {
  const color = rc(level)
  const isHigh = ['HIGH','CRITICAL'].includes(level)
  const r=24, circ=2*Math.PI*r
  return (
    <div style={{position:'relative',width:size,height:size,flexShrink:0}}>
      {isHigh && <div style={{position:'absolute',inset:-6,borderRadius:'50%',
        background:color+'1a',animation:'ripple 2.2s ease-out infinite'}}/>}
      <svg viewBox="0 0 56 56" width={size} height={size} style={{overflow:'visible'}}>
        <circle cx="28" cy="28" r={r} fill="none" stroke="var(--border)" strokeWidth="3.5"/>
        <circle cx="28" cy="28" r={r} fill="none" stroke={color} strokeWidth="3.5"
          strokeDasharray={`${(score/100)*circ} ${circ}`}
          strokeLinecap="round" transform="rotate(-90 28 28)"
          style={{
            filter:`drop-shadow(0 0 5px ${color}99)`,
            animation: animate ? 'countUp .9s ease-out' : 'none',
            transition: 'stroke-dasharray 0.5s ease-out, stroke 0.5s ease-out, filter 0.5s ease-out'
          }}/>
        {level==='SILENT'
          ? <text x="28" y="33" textAnchor="middle" fontSize="14">👻</text>
          : <text x="28" y="33" textAnchor="middle" fill={color}
              style={{fontSize:12,fontFamily:'var(--font-mono)',fontWeight:700, transition: 'fill 0.5s ease-out'}}>
              {score}
            </text>}
      </svg>
    </div>
  )
}

// ── SPARKLINE ─────────────────────────────────────────────────────────────────
function Sparkline({data, color}) {
  if (!data?.length) return null
  return (
    <ResponsiveContainer width="100%" height={32}>
      <AreaChart data={data} margin={{top:2,right:0,bottom:2,left:0}}>
        <defs>
          <linearGradient id={`sg-${color?.replace('#','')}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor={color} stopOpacity={0.25}/>
            <stop offset="95%" stopColor={color} stopOpacity={0}/>
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="risk" stroke={color} strokeWidth={1.5}
          fill={`url(#sg-${color?.replace('#','')})`} dot={false} isAnimationActive={false}/>
      </AreaChart>
    </ResponsiveContainer>
  )
}

// ── BADGE ────────────────────────────────────────────────────────────────────
function Bdg({text,color,bg}) {
  return <span style={{fontSize:9,fontWeight:700,letterSpacing:'0.05em',padding:'3px 8px',
    borderRadius:12,color:color||'#94A3B8',background:bg||`${color}1a`||'#edeeef',
    border:`1px solid ${color}33`||'#e1e3e4',textTransform:'uppercase',
    flexShrink:0}}>{text}</span>
}

// ── SERVICE CARD ──────────────────────────────────────────────────────────────
function ServiceCard({svc, sparkline, onClick, active}) {
  const color = rc(svc.risk_level)
  const isHigh = ['HIGH','CRITICAL','SILENT'].includes(svc.risk_level)
  return (
    <div 
      draggable={true}
      onDragStart={(e) => {
        e.dataTransfer.setData('application/json', JSON.stringify(svc))
      }}
      onClick={onClick} className={`bg-white border p-6 cursor-pointer transition-all duration-300 ${active ? '-translate-y-1 shadow-lg' : 'hover:-translate-y-1'}`} style={{
      borderColor: active ? color : '#e1e3e4'
    }}>
      <div style={{display:'flex',alignItems:'center',gap:14,marginBottom:10}}>
        <RiskOrb level={svc.risk_level} score={svc.risk_score} size={50}/>
        <div style={{flex:1,minWidth:0}}>
          <div className="text-[16px] font-medium text-on-surface whitespace-nowrap overflow-hidden text-ellipsis mb-1">
            {svc.service}
          </div>
          <div style={{display:'flex',gap:6,flexWrap:'wrap',alignItems:'center'}}>
            <Bdg text={svc.risk_level} color={color}/>
            {svc.traditional_alert_fired===false && svc.risk_level!=='LOW' && (
              <Bdg text="INVISIBLE TO SPLUNK" color="#F59E0B"/>
            )}
          </div>
        </div>
      </div>
      <Sparkline data={sparkline} color={color}/>
      <div className="text-[14px] text-on-surface-variant mt-4 leading-relaxed line-clamp-2">
        {svc.summary}
      </div>
    </div>
  )
}

// ── SIGNAL TIMELINE (Why Now?) ────────────────────────────────────────────────
function SignalTimeline({timeline}) {
  if (!timeline?.length) return <div className="text-[11px] text-on-surface-variant italic">No timeline data</div>
  return (
    <div>
      {timeline.map((item,i) => {
        const color = item.risk>60?'#EF4444':item.risk>30?'#F59E0B':'#10B981'
        return (
          <div key={i} className=" flex gap-3" style={{animationDelay:`${i*0.06}s`}}>
            <div className="flex flex-col items-center shrink-0">
              <div className="w-[9px] h-[9px]  mt-1 shrink-0" style={{background:color,boxShadow:`0 0 7px ${color}88`}}/>
              {i<timeline.length-1&&<div className="w-[1px] flex-1 bg-surface-container min-h-[20px]"/>}
            </div>
            <div className="pb-3">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[9px] text-on-surface-variant">{item.time}</span>
                <span className="text-[10px] font-bold" style={{color}}>{item.risk}/100</span>
              </div>
              <div className="text-[11px] text-on-surface font-semibold mb-1">{item.trigger}</div>
              <div className="text-[10px] text-on-surface-variant leading-relaxed">{item.detail}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── BLAST RADIUS (TOPOLOGY GRAPH) ──────────────────────────────────────────────
function BlastRadius({blast}) {
  if (!blast?.affected_services?.length) return (
    <div className="text-[11px] text-on-surface-variant italic">No cascade risk detected</div>
  )
  const nodes = blast.affected_services
  return (
    <div>
      <div className="px-2 py-5 bg-white  border border-surface-container overflow-x-auto">
        <svg width="100%" height={Math.max(200, nodes.length * 60)} style={{minWidth:400}}>
          <defs>
            <linearGradient id="flowLine" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="#EF4444" stopOpacity="0.8"/>
              <stop offset="100%" stopColor="#F59E0B" stopOpacity="0.8"/>
            </linearGradient>
            <filter id="glow">
              <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
              <feMerge>
                <feMergeNode in="coloredBlur"/>
                <feMergeNode in="SourceGraphic"/>
              </feMerge>
            </filter>
          </defs>
          
          {/* Origin Node */}
          <g transform="translate(40, 100)">
            <circle r="30" fill="#EF44441a" stroke="#EF4444" strokeWidth="2" filter="url(#glow)"/>
            <text y="-40" fill="#EF4444" fontSize="10" fontWeight="700" textAnchor="middle">ORIGIN</text>
            <text y="4" fill="#191c1d" fontSize="11" fontWeight="700" textAnchor="middle">{blast.origin_service.substring(0,10)}...</text>
          </g>

          {/* Links and Downstream Nodes */}
          {nodes.map((s, i) => {
            const prob = s.failure_probability
            const color = prob>0.7?'#EF4444':prob>0.4?'#F59E0B':'#10B981'
            const yPos = 40 + (i * 60)
            return (
              <g key={i} className="" style={{animationDelay:`${i*0.08}s`}}>
                {/* Animated Path */}
                <path d={`M 70 100 C 150 100, 150 ${yPos}, 220 ${yPos}`} 
                  fill="none" stroke="url(#flowLine)" strokeWidth="2" 
                  strokeDasharray="5,5"/>
                <circle cx="220" cy={yPos} r="4" fill={color} filter="url(#glow)">
                  <animate attributeName="r" values="3;6;3" dur="1.5s" repeatCount="indefinite"/>
                </circle>
                {/* Node Box */}
                <g transform={`translate(230, ${yPos - 20})`}>
                  <rect width="140" height="40" rx="4" fill="#f8f9fa" stroke={color} strokeWidth="1" filter="url(#glow)"/>
                  <text x="10" y="16" fill="#191c1d" fontSize="11" fontWeight="700">{s.service.substring(0,16)}</text>
                  <text x="10" y="30" fill="#444748" fontSize="9">{s.impact_type?.replace(/_/g,' ')}</text>
                  <text x="130" y="23" fill={color} fontSize="12" fontWeight="800" textAnchor="end">{Math.round(prob*100)}%</text>
                </g>
              </g>
            )
          })}
        </svg>
      </div>

      {blast.customer_facing_features_at_risk?.length>0 && (
        <div className="mt-2 p-2.5 bg-error-container bg-opacity-30 border border-error-container rounded text-error">
          <div className="text-[10px] font-bold mb-1 tracking-widest uppercase">
            CUSTOMER FEATURES AT RISK
          </div>
          {blast.customer_facing_features_at_risk.map((f,i)=>(
            <div key={i} className="text-[10px] text-on-surface-variant py-0.5">· {f}</div>
          ))}
        </div>
      )}
      {blast.data_integrity_risks?.length>0 && (
        <div className="mt-2 p-2.5 bg-orange-100 bg-opacity-50 border border-orange-200 rounded text-orange-600">
          <div className="text-[10px] font-bold mb-1 tracking-widest uppercase">
            DATA INTEGRITY RISKS
          </div>
          {blast.data_integrity_risks.map((r,i)=>(
            <div key={i} className="text-[10px] text-on-surface-variant py-0.5">⚠ {r}</div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── FATIGUE PANEL ─────────────────────────────────────────────────────────────
function FatiguePanel({fatigue}) {
  if (!fatigue) return null
  const color = fatigue.fatigue_score>=75?'#EF4444':fatigue.fatigue_score>=55?'#F59E0B':'#10B981'
  const segs = [
    {label:'Alert load (6h)',val:Math.min(100,fatigue.alerts_last_6h*25)},
    {label:'Sleep debt',    val:Math.min(100,fatigue.hours_since_last_sleep_window*5)},
    {label:'Oncall streak', val:Math.min(100,fatigue.consecutive_oncall_days*15)},
  ]
  return (
    <div>
      <div className="flex items-center gap-4 mb-4">
        <div className="relative w-[60px] h-[60px] shrink-0">
          <svg viewBox="0 0 60 60" width={60} height={60}>
            <circle cx="30" cy="30" r="26" fill="none" stroke="#edeeef" strokeWidth="5"/>
            <circle cx="30" cy="30" r="26" fill="none" stroke={color} strokeWidth="5"
              strokeDasharray={`${(fatigue.fatigue_score/100)*163.4} 163.4`}
              strokeLinecap="round" transform="rotate(-90 30 30)"
              style={{filter:`drop-shadow(0 0 5px ${color}88)`,
                animation:'countUp .9s ease-out'}}/>
            <text x="30" y="35" textAnchor="middle" fill={color}
              className="text-[13px] font-bold">
              {fatigue.fatigue_score}
            </text>
          </svg>
        </div>
        <div>
          <div className="text-[14px] font-bold text-on-surface mb-1">
            {fatigue.engineer_name}
          </div>
          <Bdg text={fatigue.fatigue_level} color={color}/>
          <div className="text-[11px] text-on-surface-variant mt-1.5 leading-relaxed">
            {fatigue.hours_since_last_sleep_window.toFixed(1)}h awake
            · {fatigue.alerts_last_6h} alerts tonight
            · {fatigue.consecutive_oncall_days}d streak
          </div>
        </div>
      </div>
      {segs.map((seg,i)=>(
        <div key={i} className="mb-2" title={seg.label === 'Alert load (6h)' ? 'Number of alerts received in the last 6 hours' : seg.label === 'Sleep debt' ? 'Hours since the last 8-hour sleep window' : 'Consecutive days on-call without a break'}>
          <div className="flex justify-between mb-1">
            <span className="text-[10px] text-on-surface-variant">{seg.label}</span>
            <span className="text-[10px]" style={{color}}>{seg.val}%</span>
          </div>
          <div className="h-1 bg-surface-container ">
            <div className="h-full  transition-all duration-700" style={{width:`${seg.val}%`,background:color,boxShadow:`0 0 5px ${color}55`}}/>
          </div>
        </div>
      ))}
      <div className="mt-4 p-3 rounded bg-opacity-10 border text-[11px] text-on-surface leading-relaxed" style={{backgroundColor:`${color}1a`,borderColor:`${color}33`}}>
        {fatigue.recommendation}
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className="text-[11px] text-on-surface-variant">Delivery method:</span>
        <Bdg text={fatigue.alert_delivery_method?.replace('_',' ')} color={color}/>
      </div>
    </div>
  )
}

// ── REGRET TRACKER ────────────────────────────────────────────────────────────
function RegretTracker({regret}) {
  if (!regret) return (
    <div className="text-[11px] text-on-surface-variant italic">No recent deployment detected in observation window</div>
  )
  const color = regret.regret_score>=70?'#EF4444':regret.regret_score>=40?'#F59E0B':'#10B981'
  return (
    <div>
      <div className="flex justify-between items-start mb-4">
        <div>
          <div className="text-[11px] text-on-surface-variant mb-1">{regret.deployment_id}</div>
          <div className="text-[11px] text-on-surface-variant">
            Deployed {regret.deployment_time} · {regret.minutes_since_deploy}min ago
          </div>
        </div>
        <div className="text-right">
          <div className="text-[32px] font-black" style={{color,filter:`drop-shadow(0 0 14px ${color}77)`,animation:'countUp .9s ease-out'}}>
            {regret.regret_score}%
          </div>
          <div className="text-[9px] text-on-surface-variant tracking-widest uppercase">REGRET SCORE</div>
        </div>
      </div>
      <div className="mb-4">
        <ResponsiveContainer width="100%" height={56}>
          <AreaChart data={regret.regret_trajectory} margin={{top:4,right:0,bottom:0,left:0}}>
            <defs>
              <linearGradient id="rg" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor={color} stopOpacity={0.3}/>
                <stop offset="95%" stopColor={color} stopOpacity={0}/>
              </linearGradient>
            </defs>
            <Area type="monotone" dataKey="score" stroke={color} strokeWidth={2.5}
              fill="url(#rg)" dot={{fill:color,r:3,strokeWidth:0}}/>
            <ReferenceLine y={70} stroke="#EF444455" strokeDasharray="3 3"/>
            <Tooltip contentStyle={{background:'#fff',border:'1px solid #edeeef',
              fontSize:11,padding:'4px 8px'}}
              formatter={v=>[`${v}% regret`,'']} labelFormatter={v=>`T+${v}min`}/>
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        {[
          {label:'Rollback cost',val:`${regret.cost_of_rollback_minutes}min`,color:'#10B981'},
          {label:'Incident cost',val:`${regret.cost_of_waiting_minutes}min`,color:'#EF4444'},
        ].map((item,i)=>(
          <div key={i} className="p-3 bg-surface-bright rounded text-center border border-surface-container">
            <div className="text-[20px] font-black" style={{color:item.color}}>{item.val}</div>
            <div className="text-[10px] text-on-surface-variant">{item.label}</div>
          </div>
        ))}
      </div>
      <div className="p-3 bg-opacity-10 border rounded text-[11px] text-on-surface leading-relaxed" style={{backgroundColor:`${color}1a`,borderColor:`${color}33`}}>
        {regret.recommendation}
      </div>
    </div>
  )
}

// ── TRIBAL KNOWLEDGE ──────────────────────────────────────────────────────────
function TribalPanel({tribal}) {
  if (!tribal?.items?.length) return (
    <div className="text-[11px] text-on-surface-variant italic">No matching knowledge found for current signal pattern</div>
  )
  return (
    <div>
      {tribal.items.map((item,i)=>(
        <div key={i} className=" mb-3 p-3 rounded" style={{
          backgroundColor:!item.author_still_at_company?'#8B5CF608':'#f8f9fa',
          border:`1px solid ${!item.author_still_at_company?'#8B5CF633':'#edeeef'}`,
          animationDelay:`${i*0.08}s`}}>
          <div className="flex justify-between mb-2 gap-2">
            <div className="flex items-center gap-2">
              <div className="w-[22px] h-[22px]  shrink-0 flex items-center justify-center text-[11px] font-bold text-on-surface" style={{
                backgroundColor:!item.author_still_at_company?'#8B5CF633':'#edeeef'
              }}>
                {item.author[0]}
              </div>
              <span className="text-[11px] font-bold">{item.author}</span>
              {!item.author_still_at_company&&<Bdg text="LEFT COMPANY" color="#8B5CF6"/>}
            </div>
            <div className="flex gap-1.5 items-center shrink-0">
              <Bdg text={item.source}/>
              <span className="text-[9px] text-on-surface-variant">{item.date}</span>
            </div>
          </div>
          <div className="text-[10px] text-on-surface leading-relaxed italic pl-2.5" style={{
            borderLeft:`2px solid ${!item.author_still_at_company?'#8B5CF655':'#edeeef'}`
          }}>
            "{item.content}"
          </div>
        </div>
      ))}
      {tribal.key_insight&&(
        <div className="p-3 rounded text-[11px] leading-relaxed font-semibold border" style={{backgroundColor:'#8B5CF60a', borderColor:'#8B5CF633', color:'#8B5CF6'}}>
          ⚡ {tribal.key_insight}
        </div>
      )}
    </div>
  )
}

// ── SILENT INCIDENTS ──────────────────────────────────────────────────────────
function SilentPanel({incidents}) {
  if (!incidents?.length) return (
    <div className="text-[11px] text-on-surface-variant italic">No silent incidents detected for this service</div>
  )
  return incidents.map((si,i)=>(
    <div key={i} className="p-3  mb-3 border" style={{backgroundColor:'#8B5CF608', borderColor:'#8B5CF633'}}>
      <div className="flex justify-between mb-2">
        <div>
          <div className="text-[12px] font-bold mb-1" style={{color:'#8B5CF6'}}>{si.incident_type}</div>
          <Bdg text="ZERO ALERTS FIRED" color="#8B5CF6"/>
        </div>
        <div className="text-right">
          <div className="text-[26px] font-black" style={{color:'#8B5CF6'}}>{si.duration_days}d</div>
          <div className="text-[9px] text-on-surface-variant">UNDETECTED</div>
        </div>
      </div>
      <div className="mb-2.5">
        {si.evidence.map((e,j)=>(
          <div key={j} className="text-[10px] text-on-surface-variant py-1 border-b border-surface-container flex gap-1.5">
            <span className="shrink-0" style={{color:'#8B5CF6'}}>·</span>{e}
          </div>
        ))}
      </div>
      <div className="flex justify-between items-center mb-2">
        <span className="text-[10px] text-on-surface-variant">Estimated revenue impact</span>
        <span className="text-[18px] font-black" style={{color:'#8B5CF6'}}>
          ~{fmtUSD(si.estimated_revenue_impact_usd)}
        </span>
      </div>
      <div className="text-[10px] text-on-surface-variant leading-relaxed p-2.5  bg-surface-bright">
        <span className="text-on-surface font-semibold">Root cause: </span>{si.root_cause_hypothesis}
      </div>
    </div>
  ))
}

// ── COST ESTIMATE ─────────────────────────────────────────────────────────────
// ── COST ESTIMATE ─────────────────────────────────────────────────────────────
function CostPanel({cost}) {
  if (!cost?.total_cost_usd) return (
    <div className="text-[11px] text-on-surface-variant italic">Risk score below cost estimation threshold</div>
  )
  
  // Mock time-series data for the chart
  const bleedData = Array.from({length:10}, (_,i) => ({
    time: `T+${i*10}m`,
    loss: i===0?0: Math.floor(cost.total_cost_usd * Math.pow((i/9), 2))
  }))

  return (
    <div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        {[
          {label:'Revenue at risk',   val:fmtUSD(cost.revenue_at_risk_usd),    color:'#EF4444'},
          {label:'Engineering cost',  val:fmtUSD(cost.engineering_cost_usd),   color:'#F59E0B'},
          {label:'Customers affected',val:cost.customers_affected?.toLocaleString()+'',color:'#06B6D4'},
          {label:'Est. downtime',     val:`~${cost.downtime_minutes_estimate}min`,color:'#444748'},
        ].map((item,i)=>(
          <div key={i} className="p-2.5 bg-surface-bright rounded border border-surface-container">
            <div className="text-[18px] font-black" style={{color:item.color}}>{item.val}</div>
            <div className="text-[9px] text-on-surface-variant mt-0.5">{item.label}</div>
          </div>
        ))}
      </div>

      <div className="mb-4 p-2.5 bg-white  border border-surface-container">
        <div className="text-[9px] text-on-surface-variant mb-2 tracking-widest uppercase font-bold">Cumulative Revenue Bleed Projection</div>
        <ResponsiveContainer width="100%" height={100}>
          <AreaChart data={bleedData}>
            <defs>
              <linearGradient id="bleed" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#EF4444" stopOpacity={0.4}/>
                <stop offset="95%" stopColor="#EF4444" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <Area type="monotone" dataKey="loss" stroke="#EF4444" fill="url(#bleed)" />
            <Tooltip contentStyle={{background:'#fff',border:'1px solid #edeeef',fontSize:10}}
                     formatter={v=>[fmtUSD(v),'Loss']} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="p-3 bg-error-container bg-opacity-30 border border-error-container rounded mb-3">
        <div className="flex justify-between items-center">
          <span className="text-[11px] text-on-surface font-semibold">Total cost of inaction</span>
          <span className="text-[22px] font-black text-error">
            {fmtUSD(cost.total_cost_usd)}
          </span>
        </div>
      </div>
      <div className="p-3 bg-green-100 bg-opacity-50 border border-green-200 rounded">
        <div className="flex justify-between items-center">
          <span className="text-[11px] text-on-surface font-semibold">PreCog estimated saving</span>
          <span className="text-[22px] font-black text-green-600">
            ~{fmtUSD(cost.precog_estimated_saving_usd)}
          </span>
        </div>
        <div className="text-[9px] text-on-surface-variant mt-1">
          Based on early detection enabling rollback vs full incident resolution
        </div>
      </div>
    </div>
  )
}

// ── SLACK BRIEF (CHATOPS MOCK) ────────────────────────────────────────────────
function BriefPanel({brief, service}) {
  const [ok,copy]=useCopy()
  const [isAck, setAck] = useState(false)
  const [showTerminal, setShowTerminal] = useState(false)
  
  if (!brief) return null
  return (
    <div>
      <div className="bg-white border border-surface-container  p-4 mb-4 " style={{fontFamily:'-apple-system,BlinkMacSystemFont,sans-serif'}}>
        <div className="flex gap-3">
          <div className="w-9 h-9 rounded bg-primary-container bg-opacity-30 text-primary flex items-center justify-center text-[18px] shrink-0 border border-primary-container">
            👁️
          </div>
          <div>
            <div className="flex items-baseline gap-2 mb-1">
              <span className="text-[15px] font-black text-on-surface">PreCog AI</span>
              <span className="text-[12px] text-on-surface-variant font-medium bg-surface-container px-1.5 ">APP</span>
              <span className="text-[12px] text-on-surface-variant">Just now</span>
            </div>
            <div className="text-[14px] text-on-surface leading-relaxed whitespace-pre-wrap break-words max-w-[80ch]">
              {brief}
            </div>
            <div className="flex gap-2 mt-3">
              <button onClick={()=>setAck(true)} className={`px-3 py-1.5 border rounded text-[13px] font-bold transition-colors ${isAck ? 'bg-green-100 text-green-700 border-green-300' : 'bg-surface-bright border-surface-container text-on-surface hover:bg-surface-container'}`}>
                {isAck ? '✓ Acknowledged' : '👀 Acknowledge'}
              </button>
              <button onClick={()=>setShowTerminal(true)} className="px-3 py-1.5 bg-green-600 border-none rounded text-white text-[13px] font-bold hover:bg-green-700 transition-colors shadow-sm">
                🔄 Initiate Rollback
              </button>
            </div>
          </div>
        </div>
      </div>
      <button onClick={()=>{copy(brief); showToast('Slack brief copied to clipboard!')}} className={`w-full p-2.5 rounded text-[11px] font-bold tracking-widest uppercase transition-all duration-200 ${ok ? 'bg-green-100 border border-green-500 text-green-600' : 'bg-white border border-surface-container text-on-surface hover:bg-surface-bright'}`}>
        {ok?'✓ COPIED TO CLIPBOARD':'COPY SLACK BRIEF'}
      </button>
      
      {showTerminal && <TerminalModal service={service} onClose={()=>setShowTerminal(false)} />}
    </div>
  )
}

// ── NASA REAL DATA PANEL ──────────────────────────────────────────────────────
// ── NASA PANEL ─────────────────────────────────────────────────────────────────
function NasaPanel({data}) {
  if (!data) return (
    <div className="text-[11px] text-on-surface-variant italic p-2">
      Loading NASA analysis...
    </div>
  )
  const {findings, summary} = data
  return (
    <div>
      <div className="p-3 bg-blue-50 bg-opacity-50 border border-blue-200  mb-3.5">
        <div className="text-[10px] text-blue-600 font-bold mb-1 tracking-widest uppercase">
          REAL DATA — NASA C-MAPSS TURBOFAN ENGINE DATASET
        </div>
        <div className="text-[11px] text-on-surface leading-relaxed mb-1.5">
          {summary?.headline}
        </div>
        <div className="text-[11px] font-bold text-cyan-600 leading-relaxed">
          {summary?.demo_line}
        </div>
        <div className="text-[9px] text-on-surface-variant mt-1.5">
          Source: A. Saxena & K. Goebel (2008). NASA Prognostics Data Repository. Public domain.
        </div>
      </div>
      <div className="text-[10px] text-on-surface-variant mb-2 tracking-widest uppercase font-semibold">
        Top findings — engines traditional monitoring missed:
      </div>
      {findings?.slice(0,5).map((f,i)=>(
        <div key={i} className=" mb-2 p-2.5 bg-white border border-surface-container rounded " style={{animationDelay:`${i*0.07}s`}}>
          <div className="flex justify-between mb-1.5">
            <span className="text-[11px] font-bold">Engine #{f.engine_id}</span>
            <Bdg text={`${f.silent_period_cycles} cycles missed`} color="#F59E0B"/>
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            {[
              {label:'Total cycles',val:f.total_cycles},
              {label:'PreCog detects',val:`Cycle ${f.precog_detection_cycle}`},
              {label:'Alert fires',val:f.traditional_alert_cycle?`Cycle ${f.traditional_alert_cycle}`:'Never'},
            ].map((item,j)=>(
              <div key={j} className="text-center p-1 bg-surface-bright  border border-surface-container">
                <div className="text-[11px] font-bold text-cyan-600">{item.val}</div>
                <div className="text-[8px] text-on-surface-variant">{item.label}</div>
              </div>
            ))}
          </div>
          <div className="mt-1.5 h-1 bg-surface-container ">
            <div className="h-full  bg-cyan-500 shadow-sm" style={{width:`${(f.precog_detection_cycle/f.total_cycles)*100}%`}}/>
          </div>
          <div className="text-[9px] text-on-surface-variant mt-1">
            PreCog detects at {f.pct_failure_already_progressed}% degradation — before any threshold crossed
          </div>
        </div>
      ))}
    </div>
  )
}

// ── BENCHMARK PANEL ───────────────────────────────────────────────────────────
function BenchmarkPanel({benchmark}) {
  if (!benchmark) return (
    <div className="text-[11px] text-on-surface-variant italic">Loading benchmarks...</div>
  )
  return (
    <div>
      <div className="p-2.5 bg-green-50 bg-opacity-50 border border-green-200 rounded mb-3.5">
        <div className="text-[10px] text-on-surface-variant mb-1 font-semibold tracking-widest uppercase">KEY INSIGHT</div>
        <div className="text-[11px] text-on-surface leading-relaxed font-semibold">
          {benchmark.headline_stat?.text}
        </div>
        <div className="text-[9px] text-on-surface-variant mt-1">
          Source: {benchmark.headline_stat?.source}
        </div>
      </div>
      {benchmark.vs_industry?.map((item,i)=>(
        <div key={i} className=" mb-2.5 p-2.5 bg-white border border-surface-container rounded " style={{animationDelay:`${i*0.06}s`}}>
          <div className="text-[10px] font-bold text-on-surface mb-2">{item.metric}</div>
          <div className="grid grid-cols-2 gap-2 mb-1.5">
            <div className="p-1.5 bg-surface-bright rounded border border-surface-container text-center">
              <div className="text-[11px] text-on-surface-variant mb-0.5">Industry avg</div>
              <div className="text-[12px] font-bold text-error">{item.industry}</div>
            </div>
            <div className="p-1.5 bg-green-50 bg-opacity-50 border border-green-200 rounded text-center">
              <div className="text-[11px] text-on-surface-variant mb-0.5">PreCog</div>
              <div className="text-[11px] font-bold text-green-600">{item.precog}</div>
            </div>
          </div>
          <div className="text-[9px] text-on-surface-variant">Source: {item.source}</div>
        </div>
      ))}
      <div className="p-2.5 bg-white border border-surface-container rounded ">
        <div className="text-[10px] text-on-surface-variant mb-1.5 tracking-widest uppercase font-semibold">YOUR METRICS vs INDUSTRY</div>
        {benchmark.your_metrics&&Object.entries(benchmark.your_metrics).map(([k,v],i)=>(
          <div key={i} className="flex justify-between py-1 border-b border-surface-container last:border-0">
            <span className="text-[10px] text-on-surface-variant">{k.replace(/_/g,' ')}</span>
            <span className="text-[10px] text-on-surface font-semibold">{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── COMPARE PANEL ─────────────────────────────────────────────────────────────
function ComparePanel({prediction}) {
  const p = prediction?.prediction;
  return (
    <div className="">
      <div className="text-[11px] text-on-surface mb-3.5 leading-relaxed">
        Head-to-head comparison of how this incident is handled today versus with PreCog.
      </div>
      
      <div className="grid grid-cols-2 gap-3">
        {/* TRADITIONAL */}
        <div className="p-3.5 bg-surface-bright border border-surface-container ">
          <div className="text-[10px] font-bold text-on-surface-variant tracking-widest uppercase mb-3">TRADITIONAL MONITORING</div>
          
          <div className="flex flex-col gap-3">
            <div className="p-2 bg-white rounded border border-surface-container shadow-sm">
              <div className="text-[9px] text-on-surface-variant mb-1">Current Status</div>
              <div className={`text-[11px] font-bold ${p?.would_traditional_alert_catch ? 'text-error' : 'text-green-600'}`}>
                {p?.would_traditional_alert_catch ? 'Alerts firing. Incident opened.' : 'No alerts firing. Dashboards green.'}
              </div>
            </div>
            <div className="p-2 bg-white rounded border border-surface-container shadow-sm">
              <div className="text-[9px] text-on-surface-variant mb-1">Lead Time to Incident</div>
              <div className="text-[11px] font-bold text-error">0 minutes (reactive only)</div>
            </div>
            <div className="p-2 bg-white rounded border border-surface-container shadow-sm">
              <div className="text-[9px] text-on-surface-variant mb-1">Resolution Cost</div>
              <div className="text-[11px] font-bold text-on-surface">$100,000+ (Outage & War Room)</div>
            </div>
            <div className="p-2.5 border-l-2 border-error bg-error-container bg-opacity-10 mt-2 ">
              <div className="text-[10px] font-bold text-error">OUTCOME: FULL INCIDENT</div>
              <div className="text-[9px] text-on-surface mt-1">Alerts fire only after customer impact begins.</div>
            </div>
          </div>
        </div>
        
        {/* PRECOG */}
        <div className="p-3.5 bg-green-50 bg-opacity-30 border border-green-200 ">
          <div className="text-[10px] font-bold text-green-600 tracking-widest uppercase mb-3">PRECOG AI</div>
          
          <div className="flex flex-col gap-3">
            <div className="p-2 bg-white rounded border border-surface-container shadow-sm">
              <div className="text-[9px] text-on-surface-variant mb-1">Current Status</div>
              <div className="text-[11px] font-bold text-error">Risk {p?.risk_score||81}/100 — {p?.risk_level||'HIGH'}</div>
            </div>
            <div className="p-2 bg-white rounded border border-surface-container shadow-sm">
              <div className="text-[9px] text-on-surface-variant mb-1">Lead Time to Incident</div>
              <div className="text-[11px] font-bold text-cyan-600">{p?.estimated_time_to_incident || '35-60 min'}</div>
            </div>
            <div className="p-2 bg-white rounded border border-surface-container shadow-sm">
              <div className="text-[9px] text-on-surface-variant mb-1">Resolution Cost</div>
              <div className="text-[11px] font-bold text-green-600">~0 downtime (8 min rollback)</div>
            </div>
            <div className="p-2.5 border-l-2 border-green-500 bg-green-100 bg-opacity-50 mt-2 ">
              <div className="text-[10px] font-bold text-green-700">OUTCOME: INCIDENT PREVENTED</div>
              <div className="text-[9px] text-on-surface mt-1">Proactive rollback before any customer impact.</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── TRACE PANEL (Splunk MCP & NIM) ────────────────────────────────────────────
function TracePanel({prediction}) {
  const p = prediction?.prediction;
  return (
    <div className="">
      <div className="text-[11px] text-on-surface mb-3.5 leading-relaxed">
        Real-time model tracing. Splunk MCP queries executed and NVIDIA NIM inferences.
      </div>
      
      <div className="mb-4">
        <div className="text-[10px] font-bold text-orange-500 tracking-widest uppercase mb-2">SPLUNK MCP QUERIES</div>
        <div className="p-3 bg-white border border-surface-container  font-mono ">
          {p?.trace_queries?.map((q, i) => (
            <React.Fragment key={i}>
              <div className="text-[9px] text-on-surface-variant mb-1">Query {i+1}</div>
              <div className="text-[10px] text-cyan-600 mb-2.5 leading-relaxed bg-surface-bright p-1.5 rounded break-all">
                {q}
              </div>
            </React.Fragment>
          )) || (
            <>
              <div className="text-[9px] text-on-surface-variant mb-1">Query 1: Network Latency</div>
              <div className="text-[10px] text-cyan-600 mb-2.5 leading-relaxed bg-surface-bright p-1.5 rounded break-all">
                search index=main sourcetype=aws:cloudtrail service="{prediction?.service}" | stats avg(latency) as avg_lat by bin(5m) | eval drift=(avg_lat - 42)
              </div>
            </>
          )}
        </div>
      </div>

      <div>
        <div className="text-[10px] font-bold text-green-600 tracking-widest uppercase mb-2">NVIDIA NIM INFERENCE ({p?.model_used || 'moonshotai/kimi-k2-instruct'})</div>
        <div className="p-3 bg-green-50 bg-opacity-30 border border-green-200  font-mono">
          <div className="text-[9px] text-on-surface-variant mb-1">Prompt Context Sent</div>
          <div className="text-[10px] text-on-surface-variant mb-2.5 leading-relaxed bg-white p-1.5 rounded border border-surface-container break-all">
            {p?.trace_prompt || `"Analyze these disconnected signals from Splunk, GitHub, and Jira for ${prediction?.service}. Predict system failure probability."`}
          </div>
          <div className="text-[9px] text-on-surface-variant mb-1">Model Response</div>
          <div className="text-[10px] text-green-700 leading-relaxed bg-white p-1.5 rounded border border-surface-container">
            &gt; Risk assessment complete. Identified pattern.
            <br/>&gt; Confidence: {p?.confidence||92}%
            <br/>&gt; Time to failure: {p?.estimated_time_to_incident||'35-60 min'}
            <br/>&gt; Recommended action: {p?.recommended_action||'Initiate immediate rollback'}
          </div>
        </div>
      </div>
    </div>
  )
}


// ── TABS CONFIG ───────────────────────────────────────────────────────────────
const TABS = [
  {id:'overview',  label:'Overview'},
  {id:'compare',   label:'Vs Splunk'},
  {id:'whynow',   label:'Why Now?'},
  {id:'blast',    label:'Blast Radius'},
  {id:'fatigue',  label:'Fatigue'},
  {id:'regret',   label:'Regret Score'},
  {id:'tribal',   label:'Tribal Knowledge'},
  {id:'silent',   label:'Silent Incidents'},
  {id:'trace',    label:'AI Trace'},

  {id:'benchmark',label:'vs Industry'},
  {id:'cost',     label:'Cost Estimate'},
  {id:'brief',    label:'Slack Brief'},
]

// ── CONFIDENCE DECAY TIMER ──────────────────────────────────────────────────
function ConfidenceDecayTimer({ confidence }) {
  const [elapsed, setElapsed] = useState(0)
  
  useEffect(() => {
    const timer = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(timer)
  }, [])
  
  const mins = Math.floor(elapsed / 60)
  const status = mins < 10 ? 'FRESH' : mins < 20 ? 'AGING' : 'STALE'
  const color = status === 'FRESH' ? '#10B981' : status === 'AGING' ? '#F59E0B' : '#EF4444'
  
  return (
    <div style={{display:'flex', alignItems:'center', gap:'6px'}}>
      <Bdg text={`${confidence}% confidence`}/>
      <Bdg text={`${status} (${Math.floor(elapsed/60)}:${(elapsed%60).toString().padStart(2,'0')})`} color={color}/>
    </div>
  )
}

// ── DYNAMIC WIDGET PANEL ──────────────────────────────────────────────────────
function DynamicWidgetPanel({ widget }) {
  if (!widget) return null;
  const dataString = typeof widget.data === 'object' ? JSON.stringify(widget.data, null, 2) : widget.data;
  
  return (
    <div className="">
      <div className="text-[10px] font-bold tracking-widest uppercase mb-3 text-cyan-600">
        AI GENERATED COMPONENT
      </div>
      <div className="p-4 bg-surface-bright border border-surface-container ">
        <div className="text-[14px] font-bold mb-4">{widget.title}</div>
        <div className="text-[11px] font-mono whitespace-pre-wrap bg-surface-container-low p-3 rounded text-on-surface">
          {dataString}
        </div>
      </div>
    </div>
  )
}

// ── DETAIL PANEL ──────────────────────────────────────────────────────────────
function DetailPanel({prediction, brief, cost, nasa, benchmark, onClose}) {
  const [tab, setTab] = useState('overview')
  if (!prediction) return null
  const p = prediction.prediction
  const color = rc(p?.risk_level)

  const dynamicTabs = (p?.dynamic_widgets || []).map((w, i) => ({
    id: `dyn_${i}`,
    label: w.title,
    widgetData: w
  }))
  const activeTabs = [...TABS, ...dynamicTabs]

  return (
    <div className="flex flex-col h-full bg-white border-l border-surface-container">

      {/* Header */}
      <div className="p-4 bg-surface-bright border-b border-surface-container shrink-0">
        <div className="flex justify-between items-start mb-2">
          <div>
            <div className="text-[16px] font-black text-on-surface mb-1.5">{prediction.service}</div>
            <div className="flex gap-1.5 flex-wrap">
              <Bdg text={p?.risk_level} color={color}/>
              <ConfidenceDecayTimer confidence={p?.confidence} />
              {!p?.would_traditional_alert_catch&&(
                <Bdg text="INVISIBLE TO TRADITIONAL MONITORING" color="#F59E0B"/>
              )}
            </div>
          </div>
          <button onClick={onClose} className="bg-transparent border-none text-on-surface-variant text-[24px] p-1 leading-none transition-colors hover:text-on-surface">×</button>
        </div>
        {p?.estimated_time_to_incident && p.estimated_time_to_incident!=='N/A' && (
          <div className="px-2.5 py-1.5 rounded flex items-center gap-2 mt-2 border" style={{backgroundColor:`${color}1a`,borderColor:`${color}33`}}>
            <span className="text-[10px] text-on-surface-variant">⏱ Incident in:</span>
            <span className="text-[11px] font-bold" style={{color}}>{p.estimated_time_to_incident}</span>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex overflow-x-auto border-b border-surface-container shrink-0 bg-surface-bright hide-scrollbar">
        {activeTabs.map(t=>(
          <button key={t.id} onClick={()=>setTab(t.id)} className={`px-3 py-2 border-none bg-transparent text-[10px] font-bold tracking-widest uppercase whitespace-nowrap transition-all duration-150 border-b-2`} style={{
            color:tab===t.id?color:(t.id.startsWith('dyn_')?'#0284c7':'#94A3B8'),
            borderBottomColor:tab===t.id?color:'transparent',
            backgroundColor:tab===t.id?'#ffffff':'transparent',
            ...(t.id==='nasa'?{color:tab===t.id?'#3B82F6':'#94A3B8'}:{}),
          }}>{t.label}</button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        <ErrorBoundary>
          {tab==='overview' && (
            <div className="flex flex-col gap-4">
              <div className="flex items-start gap-4">
                <RiskOrb level={p?.risk_level} score={p?.risk_score} size={72}/>
                <div className="flex-1">
                  <div className="text-[10px] font-bold text-primary mb-1.5 tracking-widest uppercase">
                    GENERATIVE RCA SUMMARY
                  </div>
                  <div className="text-[12px] text-on-surface leading-relaxed p-2.5 bg-primary-container bg-opacity-30 border border-primary-container  border-l-4 border-l-primary">
                    <TypewriterText text={p?.explanation || "Analyzing signal correlation..."} speed={8} />
                  </div>
                </div>
              </div>
              <div>
                <div className="text-[10px] text-on-surface-variant mb-2 tracking-widest uppercase font-semibold">
                  Key Signals
                </div>
                {p?.key_signals?.map((s,i)=>(
                  <div key={i} className=" flex gap-2 py-1.5 border-b border-surface-container text-[11px] text-on-surface" style={{animationDelay:`${i*0.05}s`}}>
                    <span className="shrink-0" style={{color}}>·</span>{s}
                  </div>
                ))}
              </div>
              {p?.recommended_action&&(
                <div className="p-3  border" style={{backgroundColor:`${color}1a`,borderColor:`${color}33`}}>
                  <div className="text-[9px] text-on-surface-variant mb-1 uppercase tracking-widest font-semibold">Recommended Action</div>
                  <div className="text-[12px] text-on-surface font-semibold leading-relaxed">
                    {p.recommended_action}
                  </div>
                </div>
              )}
              <div className="flex gap-1.5 flex-wrap mt-2">
                <Bdg text={`Model: ${p?.model_used?.split('/').pop()||'AI'}`}/>
                <Bdg text={p?.would_traditional_alert_catch?'Alert would fire':'Traditional alert blind'}
                  color={p?.would_traditional_alert_catch?'#10B981':'#F59E0B'}/>
              </div>
            </div>
          )}
          {tab==='compare'   && <ComparePanel prediction={prediction}/>}
          {tab==='whynow'    && <SignalTimeline timeline={prediction.why_now}/>}
          {tab==='blast'     && <BlastRadius blast={prediction.blast_radius}/>}
          {tab==='fatigue'   && <FatiguePanel fatigue={prediction.fatigue}/>}
          {tab==='regret'    && <RegretTracker regret={prediction.regret}/>}
          {tab==='tribal'    && <TribalPanel tribal={prediction.tribal_knowledge}/>}
          {tab==='silent'    && <SilentPanel incidents={prediction.silent_incidents}/>}
          {tab==='trace'     && <TracePanel prediction={prediction}/>}
          {tab==='nasa'      && <NasaPanel data={nasa}/>}
          {tab==='benchmark' && <BenchmarkPanel benchmark={benchmark}/>}
          {tab==='cost'      && <CostPanel cost={cost}/>}
          {tab==='brief'     && <BriefPanel brief={brief}/>}
          {tab.startsWith('dyn_') && <DynamicWidgetPanel widget={activeTabs.find(t=>t.id===tab)?.widgetData}/>}
        </ErrorBoundary>
      </div>
    </div>
  )
}

// ── WS HOOK ───────────────────────────────────────────────────────────────────
function useWebSocket(onMessage) {
  const ws = useRef(null)
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    let retryTimer = null
    const connect = () => {
      try {
        ws.current = new WebSocket(`${WS_URL}/ws/dashboard`)
        ws.current.onopen    = () => setConnected(true)
        ws.current.onclose   = () => { setConnected(false); retryTimer=setTimeout(connect,15000) }
        ws.current.onerror   = () => ws.current?.close()
        ws.current.onmessage = e => { try { onMessage(JSON.parse(e.data)) } catch{} }
      } catch { retryTimer = setTimeout(connect, 15000) }
    }
    connect()
    return () => { ws.current?.close(); clearTimeout(retryTimer) }
  }, [])

  return connected
}

// ── LIVE EVENT LOG ─────────────────────────────────────────────────────────────
// Removed EventLogStream since it relied on mock static data and was purely for visual presentation.

// ── ANIMATED STAT ─────────────────────────────────────────────────────────────
function AnimatedStat({targetVal, prefix='', suffix='', duration=1500, color}) {
  const [val, setVal] = useState(0)
  
  useEffect(() => {
    if (typeof targetVal !== 'number') return
    let start = null
    const step = timestamp => {
      if (!start) start = timestamp
      const progress = Math.min((timestamp - start) / duration, 1)
      setVal(Math.floor(progress * targetVal))
      if (progress < 1) window.requestAnimationFrame(step)
    }
    window.requestAnimationFrame(step)
  }, [targetVal, duration])

  const displayVal = typeof targetVal === 'number' ? val : targetVal
  return <span className="text-[15px] font-black" style={{color, fontFamily:'var(--font-head)'}}>{prefix}{displayVal}{suffix}</span>
}

// ── CHATBOT OVERLAY ────────────────────────────────────────────────────────────
function ChatbotOverlay({selected}) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([{role:'ai', text:"How can I help you investigate the current signals?"}])
  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const [attachedContext, setAttachedContext] = useState([])

  const handleSend = async () => {
    if(!input.trim()) return
    const userMsg = input
    const newMessages = [...messages, {role:'user', text:userMsg}]
    setMessages(newMessages)
    setInput('')
    setIsTyping(true)

    // Pass the attached context OR current prediction context
    const predCtx = attachedContext.length > 0 ? attachedContext : (window.__precog_prediction?.prediction || null)
    const res = await api('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userMsg,
        service: attachedContext.length > 0 ? attachedContext.map(s=>s.service).join(', ') : (selected || "recommendations-engine"),
        history: newMessages,
        prediction_context: predCtx
      })
    })

    setIsTyping(false)
    if (res?.reply) {
      setMessages(prev => [...prev, {role:'ai', text: res.reply}])
    } else {
      setMessages(prev => [...prev, {role:'ai', text: "I'm having trouble connecting to the neural net."}])
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragActive(false)
    try {
      const data = JSON.parse(e.dataTransfer.getData('application/json'))
      if (data && data.service) {
        setAttachedContext(prev => {
          if (!prev) prev = [];
          if (prev.find(p => p.service === data.service)) return prev;
          return [...prev, data].slice(-10);
        })
        setOpen(true) // Ensure it opens if they dropped it onto the closed button
      }
    } catch(err) {}
  }
  const handleDragOver = (e) => { e.preventDefault(); setDragActive(true) }
  const handleDragLeave = () => setDragActive(false)

  return (
    <div 
      onDrop={handleDrop} 
      onDragOver={handleDragOver} 
      onDragLeave={handleDragLeave}
      className="fixed bottom-0 right-5 z-[999]"
    >
      <button onClick={()=>setOpen(!open)} className="absolute bottom-5 right-0 w-12 h-12 bg-primary text-white border-none shadow-none text-[24px] flex items-center justify-center transition-transform hover:scale-105 active:scale-95">
        {open?'×':'💬'}
      </button>

      {open && (
        <div className={`absolute bottom-20 right-0 w-[450px] h-[600px] bg-white border ${dragActive ? 'border-primary border-4' : 'border-surface-container'} shadow-2xl flex flex-col overflow-hidden`}>
          <div className="bg-primary p-3 text-white font-bold text-[12px] flex justify-between items-center">
            <span>PreCog AI Assistant</span>
            <div className="flex gap-1 overflow-x-hidden">
              {attachedContext?.map(ctx => (
                <span key={ctx.service} className="bg-primary-dark px-2 py-0.5 border border-white border-opacity-30 whitespace-nowrap">{ctx.service}</span>
              ))}
            </div>
          </div>
          <div className="flex-1 p-3 overflow-y-auto flex flex-col gap-2.5 hide-scrollbar relative">
            {messages.map((m,i) => (
              <div key={i} className={`p-3 max-w-[85%] text-[13px] leading-relaxed markdown-body ${m.role === 'user' ? 'self-end bg-surface-container text-on-surface' : 'self-start bg-surface-bright border border-surface-container text-on-surface [&_p]:mb-1 [&_ul]:list-disc [&_ul]:ml-3'}`}>
                {m.role === 'ai' ? <ReactMarkdown>{m.text}</ReactMarkdown> : m.text}
              </div>
            ))}
            {isTyping && (
              <div className="text-[13px] text-on-surface-variant flex items-center gap-2 p-2">
                <span className="material-symbols-outlined animate-spin text-[16px]">sync</span>
                Gathering telemetry & analyzing...
              </div>
            )}
            {dragActive && (
              <div className="absolute inset-0 bg-primary bg-opacity-10 flex items-center justify-center pointer-events-none">
                <div className="bg-white border-2 border-primary border-dashed p-4 font-bold text-primary">
                  Drop Service to Inject Context
                </div>
              </div>
            )}
          </div>
          <div className="p-3 border-t border-surface-container flex flex-col gap-2 bg-surface-bright">
            {attachedContext?.length > 0 && (
               <div className="flex flex-wrap items-center gap-2 bg-secondary-container text-on-secondary-container px-3 py-1.5 text-[11px] font-bold border border-outline-variant">
                 <span className="opacity-70 uppercase">Context ({attachedContext.length}/10):</span>
                 {attachedContext.map(ctx => (
                   <span key={ctx.service} className="bg-white border border-surface-container px-1.5 flex items-center gap-1">
                     {ctx.service}
                     <button onClick={()=>setAttachedContext(prev=>prev.filter(p=>p.service!==ctx.service))} className="hover:text-error text-[12px] font-black">×</button>
                   </span>
                 ))}
                 <button onClick={()=>setAttachedContext([])} className="ml-auto hover:underline text-error uppercase">Clear</button>
               </div>
            )}
            <div className="flex gap-1.5">
              <input type="text" value={input} onChange={e=>setInput(e.target.value)}
                onKeyDown={e=>e.key==='Enter'&&handleSend()}
                placeholder="Ask anything..." className="flex-1 bg-white border border-surface-container text-on-surface p-2.5 text-[13px] outline-none focus:border-primary transition-colors"/>
              <button onClick={handleSend} className="bg-primary border-none text-white px-5 font-bold hover:bg-primary-dark transition-colors text-[13px]">Send</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function AnimatedNumber({ value, duration=500, prefix='', suffix='', color='' }) {
  const [val, setVal] = useState(0)
  const targetVal = value
  useEffect(() => {
    if (typeof targetVal !== 'number') return
    let startTimestamp = null
    const startVal = val
    const step = (timestamp) => {
      if (!startTimestamp) startTimestamp = timestamp
      const progress = Math.min((timestamp - startTimestamp) / duration, 1)
      setVal(Math.floor(progress * (targetVal - startVal) + startVal))
      if (progress < 1) window.requestAnimationFrame(step)
    }
    window.requestAnimationFrame(step)
  }, [targetVal, duration])

  const displayVal = typeof targetVal === 'number' ? val : targetVal
  return <span className="text-[15px] font-black" style={{color, fontFamily:'var(--font-head)'}}>{prefix}{displayVal}{suffix}</span>
}

// ── TOAST MOCK ────────────────────────────────────────────────────────────────
export function showToast(msg) {
  const el = document.createElement('div')
  el.className = 'fixed top-28 right-10 bg-surface-bright border border-surface-container shadow-lg text-on-surface text-[12px] px-4 py-3  z-[9999]  flex items-center gap-2 font-bold'
  el.innerHTML = `<span>⚡</span> ${msg}`
  document.body.appendChild(el)
  setTimeout(() => {
    el.style.opacity = '0'
    el.style.transition = 'opacity 0.5s'
    setTimeout(() => el.remove(), 500)
  }, 2500)
}

// ── TERMINAL MODAL ────────────────────────────────────────────────────────────
export function TerminalModal({ service, onClose }) {
  const [output, setOutput] = useState('')
  useEffect(() => {
    const lines = [
      `$ kubectl config use-context production-cluster`,
      `Switched to context "production-cluster".`,
      `$ kubectl rollout undo deployment ${service} -n production`,
      `deployment.apps/${service} rolled back`,
      `$ kubectl rollout status deployment ${service} -n production`,
      `Waiting for deployment "${service}" rollout to finish: 1 out of 5 new replicas have been updated...`,
      `Waiting for deployment "${service}" rollout to finish: 3 out of 5 new replicas have been updated...`,
      `Waiting for deployment "${service}" rollout to finish: 5 out of 5 new replicas have been updated...`,
      `deployment "${service}" successfully rolled out`
    ]
    let i = 0
    const int = setInterval(() => {
      setOutput(prev => prev + (prev?'\n':'') + lines[i])
      i++
      if (i >= lines.length) clearInterval(int)
    }, 800)
    return () => clearInterval(int)
  }, [service])
  
  return (
    <div className="fixed inset-0 bg-black bg-opacity-60 z-[9999] flex items-center justify-center p-4">
      <div className="w-full max-w-2xl bg-[#0c0e11]  shadow-2xl overflow-hidden border border-[#181b21] flex flex-col">
        <div className="bg-[#181b21] px-4 py-2 flex items-center justify-between border-b border-[#2a2e37]">
          <div className="flex gap-2">
            <div className="w-3 h-3  bg-red-500"></div>
            <div className="w-3 h-3  bg-yellow-500"></div>
            <div className="w-3 h-3  bg-green-500"></div>
          </div>
          <div className="text-[11px] text-[#94a3b8] font-mono tracking-wider">production-cluster — bash</div>
          <button onClick={onClose} className="text-[#94a3b8] hover:text-white border-none bg-transparent">×</button>
        </div>
        <div className="p-4 font-mono text-[12px] text-[#10b981] whitespace-pre-wrap leading-relaxed h-[300px] overflow-y-auto">
          {output}
          <span className="animate-pulse">_</span>
        </div>
        <div className="bg-[#181b21] px-4 py-3 flex justify-end">
          <button onClick={onClose} className="px-4 py-1.5 bg-white text-black font-bold rounded text-[11px] uppercase tracking-widest hover:bg-gray-200 transition-colors">Close</button>
        </div>
      </div>
    </div>
  )
}


// ── PAGE: SETTINGS ────────────────────────────────────────────────────────────
function SettingsPage() {
  const [cfg, setCfg] = useState({
    url: '', token: '', index: 'main',
    service_field: 'service', cpu_field: 'cpu_pct', mem_field: 'mem_pct',
    error_rate_field: 'error_rate', level_field: 'level', message_field: 'message',
    mcp_polling_interval: 2, ai_response_speed: 'balanced', ai_model: 'meta/llama-3.3-70b-instruct'
  })
  const [introspect, setIntrospect] = useState(null)
  const [connStatus, setConnStatus] = useState(null)  // null | 'ok' | 'fail'
  const [connMsg, setConnMsg]       = useState('')
  const [saving, setSaving]         = useState(false)
  const [testing, setTesting]       = useState(false)
  const [scanning, setScanning]     = useState(false)

  // Load current config on mount
  useEffect(() => {
    api('/api/config').then(d => {
      if (d) setCfg(prev => ({
        ...prev,
        url:              d.url || prev.url,
        index:            d.index || prev.index,
        service_field:    d.service_field || prev.service_field,
        cpu_field:        d.cpu_field || prev.cpu_field,
        mem_field:        d.mem_field || prev.mem_field,
        error_rate_field: d.error_rate_field || prev.error_rate_field,
        level_field:      d.level_field || prev.level_field,
        message_field:    d.message_field || prev.message_field,
        mcp_polling_interval: d.mcp_polling_interval || prev.mcp_polling_interval,
        ai_response_speed: d.ai_response_speed || prev.ai_response_speed,
        ai_model: d.ai_model || prev.ai_model,
      }))
    })
  }, [])
  const save = async () => {
    setSaving(true)
    const payload = Object.fromEntries(Object.entries(cfg).filter(([,v]) => v))
    const r = await api('/api/configure', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    })
    setSaving(false)
    if (r?.status === 'updated') {
      showToast('✅ Config saved — dashboard reloading with your data')
    } else {
      showToast('⚠️ Save failed')
    }
  }

  return (
    <div className="p-[40px] flex-1 overflow-y-auto max-w-3xl">
      <h2 className="text-[24px] font-black text-on-surface mb-2">Settings</h2>
      <p className="text-[14px] text-on-surface-variant mb-8 leading-relaxed">
        Configure the AI response engine and the polling frequency.
      </p>

      {/* AI & MCP Configuration */}
      <div className="bg-white border border-surface-container p-6 mb-5">
        <h3 className="text-[13px] font-bold text-on-surface mb-5 border-b border-surface-container pb-3 uppercase tracking-widest">
          🧠 AI & Polling Engine
        </h3>
        
        <div className="mb-4">
          <label className="block text-[11px] font-bold text-on-surface-variant mb-1 uppercase tracking-widest">MCP Data Pull Interval (seconds)</label>
          <input type="number" min="1" value={cfg.mcp_polling_interval||2}
            onChange={e => setCfg(p => ({...p, mcp_polling_interval: parseInt(e.target.value)}))}
            className="w-full p-2.5 bg-surface-bright border border-surface-container text-[13px] text-on-surface focus:outline-none focus:border-primary transition-colors font-mono"/>
        </div>

        <div className="mb-4">
          <label className="block text-[11px] font-bold text-on-surface-variant mb-1 uppercase tracking-widest">AI Response Speed</label>
          <select value={cfg.ai_response_speed||'balanced'}
            onChange={e => setCfg(p => ({...p, ai_response_speed: e.target.value}))}
            className="w-full p-2.5 bg-surface-bright border border-surface-container text-[13px] text-on-surface focus:outline-none focus:border-primary transition-colors font-mono">
            <option value="fast">Fast (Lower latency, concise)</option>
            <option value="balanced">Balanced (Standard latency & depth)</option>
            <option value="comprehensive">Comprehensive (Deep analysis)</option>
          </select>
        </div>

        <div className="mb-4">
          <label className="block text-[11px] font-bold text-on-surface-variant mb-1 uppercase tracking-widest">NVIDIA NIM Free Endpoint Model</label>
          <select value={cfg.ai_model||'meta/llama-3.3-70b-instruct'}
            onChange={e => setCfg(p => ({...p, ai_model: e.target.value}))}
            className="w-full p-2.5 bg-surface-bright border border-surface-container text-[13px] text-on-surface focus:outline-none focus:border-primary transition-colors font-mono">
            <option value="meta/llama-3.3-70b-instruct">meta/llama-3.3-70b-instruct (Default)</option>
            <option value="deepseek-ai/deepseek-v4-flash">deepseek-ai/deepseek-v4-flash (Thinking 🧠)</option>
            <option value="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning">nvidia/nemotron-3-nano-omni-30b-a3b-reasoning (Thinking 🧠)</option>
            <option value="google/gemma-4-31b-it">google/gemma-4-31b-it (Thinking 🧠)</option>
            <option value="stepfun-ai/step-3.7-flash">stepfun-ai/step-3.7-flash</option>
          </select>
        </div>
      </div>



      {/* Save */}
      <button onClick={save} disabled={saving}
        className="w-full py-3.5 bg-primary text-white  font-black text-[14px] uppercase tracking-widest hover:opacity-90 active:scale-[0.99] transition-all disabled:opacity-50 shadow-lg">
        {saving ? 'Saving...' : '💾 Save & Apply Configuration'}
      </button>

      <p className="text-[11px] text-on-surface-variant mt-4 text-center leading-relaxed">
        Saving instantly reloads the dashboard with your data. No restart needed.
      </p>
    </div>
  )
}




// ── PAGE: FINANCIAL IMPACT ──────────────────────────────────────────────────────
function FinancialImpactPage({services, totalCost, savings}) {
  return (
    <div className="p-[40px] flex-1 overflow-y-auto max-w-5xl">
      <h2 className="text-[24px] font-black text-on-surface mb-2 uppercase tracking-tight">Cost Estimate & Exposure</h2>
      <p className="text-[14px] text-on-surface-variant mb-8 leading-relaxed max-w-2xl">
        Live calculation of financial risk based on signal anomalies. Services with high risk scores increase potential downtime costs.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-[24px] mb-[40px]">
        <div className="bg-white border border-error-container p-8 relative overflow-hidden group">
          <div className="absolute top-0 right-0 w-32 h-32 bg-error-container opacity-20 -mr-10 -mt-10 transition-transform group-hover:scale-110"></div>
          <span className="text-[13px] font-bold text-error uppercase tracking-widest relative z-10">Total Exposure Risk</span>
          <div className="text-[64px] font-light mt-4 text-error relative z-10 font-mono tracking-tighter">
            ${(totalCost/1000).toFixed(1)}k
          </div>
          <p className="text-[12px] text-on-surface-variant mt-4 max-w-xs relative z-10">Calculated sum of SLA penalties and downtime costs across all at-risk endpoints.</p>
        </div>

        <div className="bg-white border border-[#10B981] p-8 relative overflow-hidden group">
          <div className="absolute top-0 right-0 w-32 h-32 bg-green-50 opacity-50 -mr-10 -mt-10 transition-transform group-hover:scale-110"></div>
          <span className="text-[13px] font-bold text-[#10B981] uppercase tracking-widest relative z-10">Projected PreCog Savings</span>
          <div className="text-[64px] font-light mt-4 text-[#10B981] relative z-10 font-mono tracking-tighter">
            ${(savings/1000).toFixed(1)}k
          </div>
          <p className="text-[12px] text-on-surface-variant mt-4 max-w-xs relative z-10">Estimated capital preserved by intercepting critical anomalies before structural failure.</p>
        </div>
      </div>

      <h3 className="text-[16px] font-black text-on-surface mb-4 uppercase tracking-widest border-b border-surface-container pb-2">Service Breakdown</h3>
      <div className="bg-white border border-surface-container overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-surface-variant text-[11px] uppercase tracking-widest text-on-surface-variant">
              <th className="p-4 font-bold border-b border-surface-container">Target Service</th>
              <th className="p-4 font-bold border-b border-surface-container">Current Risk Score</th>
              <th className="p-4 font-bold border-b border-surface-container">Exposure Vector</th>
            </tr>
          </thead>
          <tbody>
            {services.map((s,i) => (
              <tr key={i} className="border-b border-surface-container hover:bg-surface-bright transition-colors">
                <td className="p-4 text-[13px] font-bold">{s.service}</td>
                <td className="p-4">
                  <span className={`px-2 py-1 text-[11px] font-bold ${s.risk_score>80?'bg-error text-white':s.risk_score>50?'bg-[#F59E0B] text-white':'bg-[#10B981] text-white'}`}>
                    {s.risk_score}/100
                  </span>
                </td>
                <td className="p-4 text-[13px] font-mono opacity-80">
                  {s.risk_score>80 ? '$94,000.00' : s.risk_score>50 ? '$12,500.00' : '$0.00'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── MAIN APP ──────────────────────────────────────────────────────────────────
export default function App() {
  const [page,        setPage]        = useState('dashboard')
  const [services,    setServices]    = useState([])
  const [sparklines,  setSparklines]  = useState({})
  const [selected,    setSelected]    = useState(null)
  const [prediction,  setPrediction]  = useState(null)
  const [brief,       setBrief]       = useState(null)
  const [cost,        setCost]        = useState(null)
  const [benchmark,   setBenchmark]   = useState(null)
  const [accuracy,    setAccuracy]    = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [detailLoad,  setDetailLoad]  = useState(false)
  const [aiUpgrading, setAiUpgrading] = useState(false)  // true while full AI is loading in bg
  const [lastUpdated, setLastUpdated] = useState(null)
  const [wsConnected, setWsConn]      = useState(false)
  const [simulationActive, setSimulationActive] = useState(false)
  const [notifOpen, setNotifOpen]     = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const aiPollRef = useRef(null)  // ref to cancel background polling when service changes

  // Re-fetch cost whenever risk score changes (dynamic update)
  useEffect(() => {
    if (prediction?.prediction?.risk_score != null && selected) {
      api(`/api/cost/${selected}?risk_score=${prediction.prediction.risk_score}`).then(d => { if (d) setCost(d) })
    }
  }, [prediction?.prediction?.risk_score, selected])

  const simulateIncident = async () => {
    await api('/api/demo/trigger_incident', {method: 'POST'});
    setSimulationActive(true);
    showToast("Incident Simulation Triggered!");
    loadDashboard();
  }
  const resetSimulation = async () => {
    await api('/api/demo/reset', {method: 'POST'});
    setSimulationActive(false);
    showToast("Simulation Reset!");
    loadDashboard();
  }

  // WebSocket live updates
  const wsConn = useWebSocket(useCallback(data => {
    if (data.type === 'dashboard_update') {
      setServices(data.services)
      setLastUpdated(new Date())
      setWsConn(true)
    }
  }, []))

  // Initial load
  const loadDashboard = useCallback(async () => {
    setLoading(true)
    const [dash, sparks, acc] = await Promise.all([
      api('/api/dashboard'),
      api('/api/sparklines'),
      api('/api/accuracy'),
    ])
    if (dash?.services) setServices(dash.services)
    if (sparks) setSparklines(sparks)
    if (acc) setAccuracy(acc)
    setLastUpdated(new Date())
    setLoading(false)
  }, [])

  useEffect(() => { loadDashboard() }, [loadDashboard])


  const selectService = async svc => {
    if (selected === svc.service) { setSelected(null); setPrediction(null); return }

    // Cancel any previous background poll
    if (aiPollRef.current) { clearTimeout(aiPollRef.current); aiPollRef.current = null }

    setSelected(svc.service)
    setPrediction(null); setBrief(null); setCost(null); setBenchmark(null)
    setDetailLoad(true)
    setAiUpgrading(false)

    const svcName = svc.service

    // ── STEP 1: INSTANT (< 500ms) ──────────────────────────────────────────
    // Get instant response — from cache or fast rule-based signal scan
    const instant = await api(`/api/instant/${svcName}`)
    if (!instant) { setDetailLoad(false); return }

    // Build a FullPrediction-shaped object from the instant response
    const instantPred = {
      service: svcName,
      timestamp: instant.timestamp,
      prediction: {
        risk_score: instant.risk_score,
        risk_level: instant.risk_level,
        confidence: instant.confidence,
        explanation: instant.explanation,
        key_signals: instant.key_signals || [],
        recommended_action: instant.recommended_action,
        would_traditional_alert_catch: instant.would_traditional_alert_catch,
        model_used: instant.model_used,
        dynamic_widgets: instant.dynamic_widgets || [],
      },
      why_now: instant.why_now || [],
      blast_radius: instant.blast_radius,
      fatigue: instant.fatigue,
      regret: instant.regret,
      tribal_knowledge: instant.tribal_knowledge,
      silent_incidents: instant.silent_incidents || [],
    }

    setPrediction(instantPred)
    window.__precog_prediction = instantPred
    setDetailLoad(false)  // Panel shows immediately!

    // Load cost & benchmarks in parallel (fast, no LLM)
    api(`/api/cost/${svcName}?risk_score=${instant.risk_score}`).then(d => { if (d) setCost(d) })
    api(`/api/benchmarks/${svcName}`).then(d => { if (d) setBenchmark(d) })

    // ── STEP 2: BACKGROUND AI UPGRADE ──────────────────────────────────────
    // If instant result was from cache with full AI, we're done. Otherwise poll for full prediction.
    if (!instant.computing) {
      // Already have full cached AI prediction — load brief and done
      api(`/api/brief/${svcName}`).then(d => { if (d) setBrief(d.brief) })
      return
    }

    // Show subtle "AI computing" indicator
    setAiUpgrading(true)

    // Poll for the full AI prediction (it's computing in background on the server)
    const pollForFullPrediction = async (attempt = 0, svcAtClick = svcName) => {
      // Stop if user has switched to another service
      if (selected !== svcAtClick && attempt > 0) return

      const full = await api(`/api/instant/${svcAtClick}`)  // returns from cache once ready
      if (full && !full.computing) {
        // Full AI prediction is now cached — upgrade the panel
        const fullPred = {
          service: svcAtClick,
          timestamp: full.timestamp,
          prediction: {
            risk_score: full.risk_score,
            risk_level: full.risk_level,
            confidence: full.confidence,
            explanation: full.explanation,
            key_signals: full.key_signals || [],
            recommended_action: full.recommended_action,
            would_traditional_alert_catch: full.would_traditional_alert_catch,
            model_used: full.model_used,
            dynamic_widgets: full.dynamic_widgets || [],
          },
          why_now: full.why_now || [],
          blast_radius: full.blast_radius,
          fatigue: full.fatigue,
          regret: full.regret,
          tribal_knowledge: full.tribal_knowledge,
          silent_incidents: full.silent_incidents || [],
        }
        setPrediction(fullPred)
        window.__precog_prediction = fullPred
        setAiUpgrading(false)
        // Also fetch brief now that we have full prediction
        api(`/api/brief/${svcAtClick}`).then(d => { if (d) setBrief(d.brief) })
        // Update cost with real risk score
        api(`/api/cost/${svcAtClick}?risk_score=${full.risk_score}`).then(d => { if (d) setCost(d) })
      } else if (attempt < 20) {
        // Try again in 5 seconds (max ~100 seconds total polling)
        aiPollRef.current = setTimeout(() => pollForFullPrediction(attempt + 1, svcAtClick), 5000)
      } else {
        setAiUpgrading(false)  // Give up after 100s
      }
    }
    aiPollRef.current = setTimeout(() => pollForFullPrediction(0, svcName), 5000)
  }

  const highRisk = services.filter(s=>['HIGH','CRITICAL'].includes(s.risk_level)).length
  const healthy = services.filter(s=>['LOW','NORMAL'].includes(s.risk_level)).length
  const atRisk = services.filter(s=>['MEDIUM','HIGH','CRITICAL'].includes(s.risk_level)).length
  const silent = services.filter(s=>s.risk_level==='SILENT').length
  const totalCost = services.reduce((sum,s)=>sum+(s.risk_score>50?94000:0),0)
  const savings = services.reduce((sum,s)=>sum+(s.risk_score>80?94000:0),0)

  return (
    <div className="bg-white text-on-surface min-h-screen font-body-sm">

      {/* TOP NAV */}
      <header className="bg-surface-lowest border-b border-surface-container flex justify-between items-center px-[40px] w-full fixed top-0 z-50 h-24">
        <div className="flex items-center gap-12">
          <div className="text-[32px] tracking-tighter font-black text-on-surface flex items-center">
            <div className="w-3 h-3 bg-primary mr-3"></div>
            PRECOG
          </div>
        </div>
        <div className="flex items-center gap-8">
          <span className="text-[12px] uppercase text-on-surface-variant font-bold tracking-widest flex items-center gap-2">
            <span className={`w-1.5 h-1.5 ${wsConn?'bg-green-500':'bg-secondary-fixed-dim'}`}></span>
            {wsConn?'LIVE STREAM':'POLLING'}
          </span>

          <div className="flex gap-4 relative">
            <button className="material-symbols-outlined text-on-surface-variant cursor-pointer hover:text-primary transition-colors"
              onClick={()=>{setNotifOpen(!notifOpen); setProfileOpen(false)}}>notifications</button>
            {notifOpen && (
              <div className="absolute right-10 top-8 w-64 bg-white border border-surface-container shadow-lg z-50 p-2">
                <div className="text-[12px] font-bold text-on-surface-variant p-2 border-b border-surface-container mb-2 uppercase">Notifications</div>
                <div className="p-2 text-[14px] text-on-surface hover:bg-surface-variant cursor-pointer">Neural Net Active</div>
                <div className="p-2 text-[14px] text-on-surface hover:bg-surface-variant cursor-pointer">Live Stream Connected</div>
              </div>
            )}
            <button className="material-symbols-outlined text-on-surface-variant cursor-pointer hover:text-primary transition-colors"
              onClick={()=>{setProfileOpen(!profileOpen); setNotifOpen(false)}}>account_circle</button>
            {profileOpen && (
              <div className="absolute right-0 top-8 w-48 bg-white border border-surface-container shadow-lg z-50 p-2">
                <div className="text-[12px] font-bold text-on-surface-variant p-2 border-b border-surface-container mb-2 uppercase">Admin</div>
                <div className="p-2 text-[14px] text-on-surface hover:bg-surface-variant cursor-pointer" onClick={()=>setPage('settings')}>Settings</div>
                <div className="p-2 text-[14px] text-error hover:bg-surface-variant cursor-pointer">Sign Out</div>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* SIDE NAV */}
      <aside className="fixed left-0 bottom-0 w-64 bg-surface-container-low border-r border-surface-container-highest flex flex-col p-4 z-40 hidden md:flex top-24">
        <div className="mb-8 p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-surface-container-highest overflow-hidden">
              <img alt="Admin" className="w-full h-full object-cover"
                src="https://lh3.googleusercontent.com/aida-public/AB6AXuCz8ubQBHOOdZ5nSg_KRsNFefsTLNmmtwYyfbUID_pKuPr4vXv-D16vGmVaaffGTnNCJVB4wL4A_XyNiL_QPYvbwflpk_--cqPhkKj8zBLSQetP7XRJWneE46k14JMLP-n5H8K5WLpZ84KwAPcsimoyz6J5VpOyEZa9kARGcW4KB5OunfEY4nT7FQRwacAhXXkbWtmCGlDo4PZrGorClBC2qAeuA0lA-_rNNz5r1xVG1eqyA7ap9zw9vA7_3yqjfFidlm2rjxNOVYA" />
            </div>
            <div>
              <p className="text-[20px] font-medium text-on-surface leading-tight">Admin</p>
              <p className="text-[14px] text-on-surface-variant opacity-70">Neural Net Active</p>
            </div>
          </div>
        </div>
        <nav className="flex flex-col gap-1 flex-1">
          <a className={`flex items-center gap-3 px-4 py-3 font-medium transition-all duration-300 ${page==='dashboard'?'bg-primary text-white':'text-on-surface-variant hover:bg-surface-container'}`}
            href="#" onClick={e=>{e.preventDefault(); setPage('dashboard');}}>
            <span className="material-symbols-outlined">dashboard</span>
            <span className="text-[14px]">Overview</span>
          </a>
          <a className={`flex items-center gap-3 px-4 py-3 font-medium transition-all duration-300 ${page==='financialimpact'?'bg-primary text-white':'text-on-surface-variant hover:bg-surface-container'}`}
            href="#" onClick={e=>{e.preventDefault(); setPage('financialimpact');}}>
            <span className="material-symbols-outlined">payments</span>
            <span className="text-[14px]">Cost Estimate</span>
          </a>
          <a className={`flex items-center gap-3 px-4 py-3 font-medium transition-all duration-300 ${page==='settings'?'bg-primary text-white':'text-on-surface-variant hover:bg-surface-container'}`}
            href="#" onClick={e=>{e.preventDefault(); setPage('settings');}}>
            <span className="material-symbols-outlined">settings</span>
            <span className="text-[14px]">Settings</span>
          </a>
        </nav>
      </aside>

      {/* MAIN */}
      <main className="md:pl-64 min-h-screen flex flex-col pt-24">
        <div className="flex-1 flex flex-col md:flex-row">
          {page === 'settings' && <SettingsPage />}
          {page === 'financialimpact' && <FinancialImpactPage services={services} totalCost={totalCost} savings={savings} />}
          {page === 'dashboard' && (
          <div className="flex-1 p-[40px] flex flex-col h-[calc(100vh-6rem)] overflow-hidden">
            <section className="grid grid-cols-1 md:grid-cols-4 gap-[24px] mb-[24px] flex-shrink-0">
              <div className="bg-white border border-surface-container p-6">
                <span className="text-[12px] uppercase font-bold text-on-surface-variant tracking-widest opacity-60">Monitored</span>
                <div className="text-[48px] font-light mt-2 text-on-surface"><AnimatedStat targetVal={services.length} color="currentColor"/></div>
              </div>
              <div className="bg-white border border-surface-container p-6">
                <span className="text-[12px] uppercase font-bold text-[#EF4444] tracking-widest opacity-80">High Risk</span>
                <div className="text-[48px] font-light mt-2 text-[#EF4444]"><AnimatedStat targetVal={highRisk} color="currentColor"/></div>
              </div>
              <div className="bg-white border border-surface-container p-6">
                <span className="text-[12px] uppercase font-bold text-[#10B981] tracking-widest opacity-80">Healthy</span>
                <div className="text-[48px] font-light mt-2 text-[#10B981]"><AnimatedStat targetVal={healthy} color="currentColor"/></div>
              </div>
              <div className="bg-white border border-surface-container p-6">
                <span className="text-[12px] uppercase font-bold text-[#F59E0B] tracking-widest opacity-80">At Risk</span>
                <div className="text-[48px] font-light mt-2 text-[#F59E0B]"><AnimatedStat targetVal={atRisk} color="currentColor"/></div>
              </div>
            </section>
            {loading ? (
              <section className="flex-1 flex flex-col items-center justify-center text-center -mt-16">
                <div style={{position:'relative',width:96,height:96,marginBottom:32}}>
                  <div style={{position:'absolute',inset:0,border:'2px solid #e2e8f0',borderRadius:'50%'}}></div>
                  <div className="animate-spin" style={{position:'absolute',inset:0,border:'2px solid',borderColor:'var(--color-primary) transparent transparent transparent',borderRadius:'50%'}}></div>
                </div>
                <h1 className="text-[48px] font-light text-primary tracking-tight">Initializing Precog Neural Net...</h1>
                <p className="mt-4 text-[16px] text-on-surface-variant max-w-md opacity-60">
                  Synthesizing global signal streams and preparing predictive risk modeling.
                </p>
                <div className="mt-12 w-full max-w-2xl h-px bg-gradient-to-r from-transparent via-surface-container to-transparent"></div>
              </section>
            ) : (
              <div className="flex-1 flex overflow-hidden gap-[24px]">
                <div className={`transition-all duration-300 overflow-y-auto w-full grid gap-[16px] align-content-start pb-10 ${selected?'grid-cols-1 md:w-[350px] flex-shrink-0':'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'}`}>
                  {services.map(svc=>(
                    <ErrorBoundary key={svc.service}>
                      <ServiceCard svc={svc} sparkline={sparklines[svc.service]}
                        onClick={()=>selectService(svc)} active={selected===svc.service}/>
                    </ErrorBoundary>
                  ))}
                </div>
                {selected&&(
                  <div className="flex-1 overflow-y-auto bg-white border border-surface-container relative">
                    {detailLoad
                      ? <div className="flex items-center justify-center h-full text-on-surface-variant flex-col gap-3">
                          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                          <span className="text-[12px] uppercase tracking-widest font-bold opacity-60">Reading signals...</span>
                        </div>
                      : <ErrorBoundary>
                          {aiUpgrading && (
                            <div className="absolute top-3 right-12 z-10 flex items-center gap-1.5 bg-[#F59E0B] text-white text-[10px] font-black uppercase tracking-widest px-2 py-1 shadow pointer-events-none">
                              <span className="w-2 h-2 bg-white rounded-full animate-pulse inline-block"></span>
                              AI Upgrading...
                            </div>
                          )}
                          <DetailPanel prediction={prediction} brief={brief} cost={cost}
                            nasa={nasa} benchmark={benchmark}
                            onClose={()=>{
                              setSelected(null); setPrediction(null); setAiUpgrading(false)
                              if(aiPollRef.current){clearTimeout(aiPollRef.current); aiPollRef.current=null}
                            }}/>
                        </ErrorBoundary>
                    }
                  </div>
                )}
              </div>
            )}
          </div>
          )}
        </div>
      </main>

      <ChatbotOverlay selected={selected} />
    </div>
  )
}
