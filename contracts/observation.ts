export interface Verification {
  status: 'disabled' | 'not_due' | 'pending' | 'verified' | 'unavailable' | 'not_recorded';
  model?: string;
  passenger_count?: number;
  sample_counts?: number[];
  completed_at?: string;
  reason?: string;
  disagreement?: boolean;
}

/** Successful observation retaining the regular count and any verifier override. */
export interface Observation {
  id: number;
  coach_id: string;
  coach_name: string;
  source: 'simulation' | 'recorded_video' | 'rtsp';
  observed_at: string;
  passenger_count: number;
  regular_passenger_count: number;
  verification: Verification;
  capacity: number;
  occupancy_percent: number;
  status: 'green' | 'yellow' | 'red';
  interval_seconds: number;
  media_position_seconds?: number;
  media_window_start_seconds?: number;
  sample_counts?: number[];
  detector?: string;
  playback_speed?: number;
}

/** Live state is distinct from the timestamp-preserving last observation. */
export interface CoachState {
  coach_id: string;
  coach_name: string;
  source: 'simulation' | 'recorded_video' | 'rtsp';
  capacity: number;
  interval_seconds: number;
  position: number;
  platform_zone: string;
  availability: 'fresh' | 'stale' | 'unavailable';
  status: Observation['status'] | 'unknown';
  passenger_count: number | null;
  occupancy_percent: number | null;
  stale_at: string | null;
  last_observation: Observation | null;
  playback_speed: number;
  source_status: 'running' | 'loading' | 'playing' | 'ended' | 'error' | 'connecting' | 'reconnecting' | 'live';
  source_message: string | null;
  duration_seconds: number | null;
  last_verification: (Verification & { observation_id: number; observed_at: string; regular_passenger_count: number }) | null;
}

/** GET /api/state and every `state` SSE event contain a complete snapshot. */
export interface TrainState {
  server_time: string;
  train_name: string;
  platform_name: string;
  direction: 'left' | 'right';
  coaches: CoachState[];
}

/** Cursor-paginated persisted history, newest observation ID first. */
export interface HistoryPage {
  items: Observation[];
  next_before: number | null;
}
