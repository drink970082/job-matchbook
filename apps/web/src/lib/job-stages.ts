// Discovered Jobs is one funnel (#158): a posting is in exactly one stage.
//   rule_rejected   - a deterministic rule (location/internship/title/age) dropped it
//   screen_rejected - the hard-requirement screen disqualified it
//   jev_skip        - JEV (or the operator's override) says skip; hidden by default
//   unassessed      - still `new`, JEV has no current verdict (none, failed or stale)
//   keep            - still `new` and JEV (or the override) says keep: the default queue
//   other           - moved on (applied, expired, removed, a legacy scored/notified row)
// `all` lists every stage. JEV status is the MCP rule (read_repository._jev_status_sql);
// both sides are pinned by tests/fixtures/jev-status-cases.json.
export const JOB_STAGES = ['keep', 'jev_skip', 'unassessed', 'screen_rejected', 'rule_rejected', 'other'] as const
export type JobStage = (typeof JOB_STAGES)[number]
export type JobStageFilter = JobStage | 'all'
