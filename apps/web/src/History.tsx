import { useEffect, useState } from 'react';
import type { CoachState, HistoryPage, Verification } from '../../../contracts/observation';

const sources = { simulation: 'Simulated data', recorded_video: 'Recorded video', rtsp: 'Live RTSP' };
const colours = { green: 'Green', yellow: 'Yellow', red: 'Red' };

function Timestamp({ value }: { value?: string }) {
  return value ? <time dateTime={value} title={value}>{new Date(value).toLocaleString()}</time> : <>—</>;
}

function verificationLabel(check: Verification) {
  if (check.status === 'verified') return check.disagreement ? 'Disagreement · AI used' : 'Agrees · AI used';
  return { disabled: 'Disabled', not_due: 'Not due', pending: 'Pending', unavailable: 'Unavailable · regular retained', not_recorded: 'Not recorded' }[check.status];
}

export function History({ coaches }: { coaches: CoachState[] }) {
  const [coach, setCoach] = useState('');
  const [cursors, setCursors] = useState<(number | null)[]>([null]);
  const [page, setPage] = useState<HistoryPage | null>(null);
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const before = cursors[cursors.length - 1];

  useEffect(() => {
    let disposed = false;
    let timer: number;
    const controller = new AbortController();
    setPage(null);
    setError(false);
    async function load() {
      const query = new URLSearchParams({ limit: '20' });
      if (coach) query.set('coach_id', coach);
      if (before !== null) query.set('before', String(before));
      try {
        const response = await fetch(`/api/history?${query}`, { signal: controller.signal });
        if (!response.ok) throw new Error('History unavailable');
        const result: HistoryPage = await response.json();
        if (!disposed) { setPage(result); setError(false); }
      } catch {
        if (!disposed) setError(true);
      } finally {
        if (!disposed) timer = window.setTimeout(load, 5000);
      }
    }
    void load();
    return () => { disposed = true; controller.abort(); window.clearTimeout(timer); };
  }, [coach, before, refresh]);

  return <section className="history" aria-labelledby="history-heading">
    <div className="section-heading"><h2 id="history-heading">Observation history</h2><button onClick={() => setRefresh(value => value + 1)}>Refresh history</button></div>
    <p className="history-description">Saved estimates, newest received first. Historical colours describe the observation, not current availability. Times are shown in your local timezone.</p>
    <div className="history-controls">
      <label htmlFor="history-coach">Coach</label>
      <select id="history-coach" value={coach} onChange={event => { setCoach(event.target.value); setCursors([null]); }}>
        <option value="">All coaches</option>
        {coaches.map(item => <option key={item.coach_id} value={item.coach_id}>{item.coach_name}</option>)}
      </select>
      <span>Checks update automatically every 5 seconds.</span>
    </div>
    {error && <p role="alert">History could not be refreshed. {page ? 'Showing the last loaded records. ' : ''}Retrying automatically.</p>}
    {!page && !error && <p role="status">Loading history…</p>}
    {page?.items.length === 0 && <p role="status">No observations saved for this selection.</p>}
    {!!page?.items.length && <div className="history-scroll" role="region" aria-label="Saved observations" tabIndex={0}>
      <table>
        <caption>Original and verified estimates · {page.items.length} records on this page</caption>
        <thead><tr><th scope="col">Coach / source</th><th scope="col">Observed at</th><th scope="col">Original count</th><th scope="col">AI count</th><th scope="col">Effective occupancy</th><th scope="col">Verification</th><th scope="col">Verification completed at</th></tr></thead>
        <tbody>{page.items.map(row => <tr key={row.id} data-testid={`history-${row.id}`}>
          <td><strong>{row.coach_name}</strong><small>{sources[row.source]}</small><small>Observation #{row.id}</small>{row.media_position_seconds !== undefined && <small>Replay at {row.media_position_seconds.toFixed(1)}s</small>}</td>
          <td><Timestamp value={row.observed_at} /></td>
          <td>{row.regular_passenger_count}</td>
          <td>{row.verification.status === 'verified' ? row.verification.passenger_count : '—'}</td>
          <td><strong className={`history-colour ${row.status}`}>{row.occupancy_percent}% · {colours[row.status]}</strong><small>{row.passenger_count} / {row.capacity} capacity</small></td>
          <td>{verificationLabel(row.verification)}{row.verification.reason && <small>{row.verification.reason}</small>}{row.verification.model && <small>Model: {row.verification.model}</small>}</td>
          <td><Timestamp value={row.verification.completed_at} /></td>
        </tr>)}</tbody>
      </table>
    </div>}
    <nav className="history-pagination" aria-label="History pages">
      <button disabled={cursors.length === 1} onClick={() => setCursors([null])}>Latest</button>
      <button disabled={cursors.length === 1} onClick={() => setCursors(values => values.slice(0, -1))}>Newer</button>
      <span>Page {cursors.length}</span>
      <button disabled={!page?.next_before || error} onClick={() => { if (page?.next_before) setCursors(values => [...values, page.next_before]); }}>Older</button>
    </nav>
  </section>;
}
