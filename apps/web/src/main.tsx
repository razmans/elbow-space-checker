import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { CoachState, TrainState } from '../../../contracts/observation';
import './style.css';
import { History } from './History';

const sourceLabels = { simulation: 'Simulated data', recorded_video: 'Recorded video', rtsp: 'Live RTSP' };

const labels = { green: 'Room to spare', yellow: 'Filling up', red: 'Crowded', unknown: 'Unknown' };

function sourceDescription(coach: CoachState) {
  if (coach.source_status === 'error') return coach.source_message ?? 'Video analysis unavailable';
  if (coach.source_status === 'ended') return 'Replay finished · no current reading';
  if (coach.source_status === 'connecting' || coach.source_status === 'reconnecting') return 'RTSP reconnecting · awaiting fresh frames';
  if (coach.source_status === 'loading') return 'Loading video source and local detector…';
  if (coach.availability === 'stale') return 'Stale · two update intervals elapsed';
  if (coach.availability !== 'fresh') return 'Waiting for the first valid observation';
  return coach.source === 'recorded_video'
    ? `Fresh in replay · every ${coach.interval_seconds}s of footage`
    : `Fresh · updates every ${coach.interval_seconds}s`;
}

function VerificationStatus({ coach }: { coach: CoachState }) {
  const check = coach.last_verification;
  if (!check) return coach.source === 'simulation' ? null : <div className="verification-note">Verification: {coach.last_observation?.verification.status === 'disabled' ? 'disabled' : 'awaiting first sample'}</div>;
  const applies = check.observation_id === coach.last_observation?.id;
  return <div className="verification-note" data-testid="verification">
    <strong>{check.status === 'pending' ? 'AI verification pending' : check.status === 'verified' ? check.disagreement ? 'AI disagreement recorded' : 'AI verification agrees' : 'AI verification unavailable'}</strong>
    {check.status === 'verified' && <span>Regular: {check.regular_passenger_count} · AI: {check.passenger_count}. {applies ? 'AI count used for this observation.' : 'Historical check; newer reading shown.'}</span>}
    {check.status === 'unavailable' && <span>{check.reason}. Regular estimate retained.</span>}
    <span>Sample {new Date(check.observed_at).toLocaleTimeString()}{check.completed_at ? ` · checked ${new Date(check.completed_at).toLocaleTimeString()}` : ''}</span>
  </div>;
}

function CoachCard({ coach }: { coach: CoachState }) {
  const observation = coach.last_observation;
  const fresh = coach.availability === 'fresh';
  return (
    <article className={`coach-card ${coach.status}`} data-testid={`coach-${coach.coach_id}`} data-status={coach.status} data-observation-id={observation?.id ?? ""} aria-live="polite">
      <div className="coach-top"><h3>{coach.coach_name}</h3><span className="source-tag">{sourceLabels[coach.source]}</span></div>
      <p className="coach-position">{coach.platform_zone} · Position {coach.position}</p>
      <div className="reading">
        <div><div className="percentage" data-testid="occupancy">{fresh ? `${coach.occupancy_percent}%` : '—'}</div><span className="reading-label">{fresh ? coach.source !== 'simulation' ? 'experimental occupancy estimate' : 'estimated occupancy' : 'occupancy unavailable'}</span></div>
        <div className="status-label"><span className="status-dot" />{labels[coach.status]}</div>
      </div>
      <div className="meter" aria-hidden="true"><div style={{ width: `${Math.min(coach.occupancy_percent ?? 0, 100)}%` }} /></div>
      <div className="coach-bottom">
        <span>{fresh ? `${coach.passenger_count} estimated passengers / ${coach.capacity} capacity` : `Configured capacity: ${coach.capacity}`}</span>
        <span>{observation ? <time dateTime={observation.observed_at}>{fresh ? 'Observed' : 'Last observed'} {new Date(observation.observed_at).toLocaleTimeString()}</time> : 'No observation received'}</span>
        {coach.source === 'recorded_video' && <span className="replay-detail">{observation?.media_position_seconds !== undefined ? `Sample at ${observation.media_position_seconds.toFixed(1)}s` : 'No sample yet'}{coach.duration_seconds !== null ? ` / ${coach.duration_seconds.toFixed(1)}s` : ''} · {coach.playback_speed}× replay</span>}
        <span className={`freshness ${fresh ? '' : 'notice'}`}>{sourceDescription(coach)}</span>
      </div>
      <VerificationStatus coach={coach} />
    </article>
  );
}

function App() {
  const [received, setReceived] = useState<{ state: TrainState; at: number } | null>(null);
  const [connected, setConnected] = useState(false);
  const [clock, setClock] = useState(() => performance.now());

  useEffect(() => {
    let events: EventSource | null = null;
    function disconnect() {
      events?.close();
      events = null;
      setConnected(false);
    }
    function connect() {
      disconnect();
      events = new EventSource('/api/events');
      // A socket alone does not establish freshness: wait for the complete snapshot.
      events.onerror = () => setConnected(false);
      events.addEventListener('state', (event) => {
        const now = performance.now();
        setReceived({ state: JSON.parse((event as MessageEvent).data), at: now });
        setClock(now);
        setConnected(true);
      });
    }
    if (navigator.onLine) connect();
    window.addEventListener('offline', disconnect);
    window.addEventListener('online', connect);
    const timer = window.setInterval(() => setClock(performance.now()), 100);
    return () => {
      events?.close();
      window.clearInterval(timer);
      window.removeEventListener('offline', disconnect);
      window.removeEventListener('online', connect);
    };
  }, []);

  const state = received?.state;
  // Use server time plus elapsed browser time, avoiding client/server clock skew.
  // This expires readings even when the stream stops without sending an error.
  const now = state && received ? Date.parse(state.server_time) + Math.max(0, clock - received.at) : 0;
  const coaches = (state?.coaches ?? []).map((coach): CoachState => {
    if (coach.availability === 'fresh' && coach.stale_at && now >= Date.parse(coach.stale_at)) {
      return { ...coach, availability: 'stale', status: 'unknown', passenger_count: null, occupancy_percent: null };
    }
    return coach;
  });

  const hasVideo = coaches.some(coach => coach.source !== 'simulation');
  const hasRtsp = coaches.some(coach => coach.source === 'rtsp');

  return (
    <div className="page">
      <header>
        <a className="brand" href="/" aria-label="Elbow Room home"><span className="brand-mark">er.</span> Elbow Room</a>
        <span className="demo-pill">{hasRtsp ? 'LIVE VIDEO DEMO' : hasVideo ? 'RECORDED VIDEO DEMO' : 'SIMULATION DEMO'}</span>
      </header>
      <main>
        <div className="eyebrow">A LITTLE SPACE MAKES A DIFFERENCE</div>
        <h1>Find your<br /><span>elbow room.</span></h1>
        <p className="intro">A clearer picture of the space on board.<br />Compare coaches and their configured platform positions.</p>
        <section className="availability" aria-labelledby="availability-heading">
          <div className="section-heading">
            <h2 id="availability-heading">{state?.train_name ?? 'On board'}</h2>
            <span className="connection"><i className={connected ? 'online' : ''} />{connected ? 'Live connection' : received ? 'Reconnecting…' : 'Connecting to local service…'}</span>
          </div>
          {state && (
            <section className="platform" aria-label="Configured platform layout">
              <div className="platform-heading"><span>{state.platform_name}</span><span>{state.direction === 'left' ? '← Travel direction' : 'Travel direction →'}</span></div>
              <ol className="train-layout">
                {coaches.map(coach => (
                  <li key={coach.coach_id} className={`layout-coach ${coach.status}`} data-testid={`layout-${coach.coach_id}`}>
                    <span className="layout-name">{coach.coach_name}</span>
                    <strong>{coach.occupancy_percent === null ? 'Unknown' : `${coach.occupancy_percent}% · ${labels[coach.status]}`}</strong>
                    <span className="layout-zone">{coach.platform_zone}</span>
                    <span className="layout-source">{sourceLabels[coach.source]}</span>
                  </li>
                ))}
              </ol>
              <p>Configured stopping positions · sources labelled per coach · not live train tracking</p>
            </section>
          )}
          <div className="coach-grid">{coaches.map(coach => <CoachCard key={coach.coach_id} coach={coach} />)}</div>
          {!received && <p role="status" className="empty-state">Waiting for the train’s current state. No occupancy readings are available yet.</p>}
          {!connected && received && <p role="status" className="notice">Connection interrupted. Reconnecting automatically; old readings become unknown after two update intervals.</p>}
          <div className="legend"><span><i className="green-dot" />Below 30% · Room to spare</span><span><i className="yellow-dot" />30–80% · Filling up</span><span><i className="red-dot" />Above 80% · Crowded</span><span><i className="unknown-dot" />Unknown · No fresh reading</span></div>
        </section>
        <History coaches={state?.coaches ?? []} />
        <aside><span className="info-icon">i</span><div><strong>{hasVideo ? 'Video analysed and verified locally.' : 'A working demo, with simulated passengers.'}</strong><p>{hasVideo ? 'Video estimates count visible people with a baseline detector. Camera coverage and crowded-scene accuracy have not been validated. Sources are labelled per coach. Recorded footage is a replay; RTSP is a live feed. AI verification is a second estimate, not ground truth.' : 'No cameras are connected. Each coach has its own capacity, update interval and simulated readings.'} The platform layout is configured for demonstration; these readings are not boarding guidance.</p></div></aside>
      </main>
      <footer><span>ELBOW ROOM</span><span>Open source. More space for everyone.</span><span>LOCAL DEMO / {coaches.length} COACHES</span></footer>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
