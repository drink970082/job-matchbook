// Discovered Jobs is one funnel (#158): a posting is in exactly one stage.
//   closed        - closed at its source (source_state='closed'), whatever else holds;
//                   before every other stage
//   other         - moved on from `new` (applied, expired, failed, a legacy scored/notified row)
//   otherwise the posting's effective status (#226): the operator's override if one
//   exists, else the stored verdict:
//   keep          - the default queue ("Postings for you")
//   skip          - triage, or the operator's "Not interested", says skip
//   discarded     - a hard requirement discarded it
//   pending       - still waiting for a stage
//   not_evaluated - left the evaluation window unfinished
// `removed` rows are in no stage. `all` lists every stage. The status rule is the MCP's
// (read_repository._STATUS_SQL); both sides are pinned by
// worker/tests/fixtures/effective-status-cases.json.
export const JOB_STAGES = ['keep', 'skip', 'discarded', 'pending', 'not_evaluated', 'other', 'closed'] as const
export type JobStage = (typeof JOB_STAGES)[number]
export type JobStageFilter = JobStage | 'all'
