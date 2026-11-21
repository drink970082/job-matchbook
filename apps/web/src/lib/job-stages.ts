// Discovered Jobs is one funnel (#158): a posting is in exactly one stage.
//   rule_rejected   - a deterministic screen rule (location/internship) dropped it
//   screen_rejected - the hard-requirement screen disqualified it, or a `discarded`
//                     row whose evidence triage cannot read (a legacy fit-pipeline
//                     screen discard)
//   jev_skip        - JEV (or the operator's override) says skip; hidden by default
//   unassessed      - still `new`, JEV has no current verdict (none, failed or stale)
//   keep            - still `new` and JEV (or the override) says keep: the default queue
//   other           - moved on (applied, expired, failed, a legacy scored/notified row)
//   closed          - closed at its source (source_state='closed'), whatever the above;
//                     before every other stage, so a closed posting is in no other stage
// `removed` rows are in no stage. `all` lists every stage. JEV status is the MCP rule (read_repository._jev_status_sql);
// both sides are pinned by tests/fixtures/jev-status-cases.json; the closed rule (MCP
// list_jobs `closed`) by tests/fixtures/closed-stage-cases.json.
export const JOB_STAGES = ['keep', 'jev_skip', 'unassessed', 'screen_rejected', 'rule_rejected', 'other', 'closed'] as const
export type JobStage = (typeof JOB_STAGES)[number]
export type JobStageFilter = JobStage | 'all'
