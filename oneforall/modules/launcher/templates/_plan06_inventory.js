/* PLAN-06 Inventory — drawer openers per module
 *
 * Module    | Entity type | Opener                        | Data source
 * ----------|------------|-------------------------------|--------------------------
 * ERM       | risk       | ermOpenRiskDrawer(id)         | fetches /erm/api/risks/{id}, fallback regCache
 * ORM       | event      | ormOpenEventDrawer(id)        | fetches /orm/api/events/{id}
 * GRID      | nc         | openNCDetail(ncid)            | fetches /grid/api/ncs/{ncid}
 * Sentinel  | ropa       | snOpenRopaDrawer(id)          | ropaCache (cache-only)
 * Sentinel  | dpia       | snOpenDpiaDrawer(id)          | dpiaCache (cache-only)
 * Sentinel  | breach     | snOpenModal('breach', item)   | cache — needs full item, opens modal
 * Sentinel  | dsr        | snOpenModal('dsr', item)      | cache — needs full item, opens modal
 * BCM       | plan       | bcmOpenModal('plan', item)    | planCache (cache, needs item object)
 * BCM       | incident   | bcmOpenModal('incident', item)| incCache (cache, needs item object)
 * Evidence  | item       | openDetail(eid)               | evCache (cache, needs check)
 * ARIA      | —          | SPA router (separate pages)   | — (uses per-page routes, not a single SPA)
 *
 * Fetch-based openers (ERM, ORM, GRID): id is used in API fetch URL → deep link works directly.
 * Cache-based openers (Sentinel, BCM): the boot handler must wait for cache to populate,
 *   then look up by id. If cache miss after retries, silently fail.
 * Modal-only (breach, dsr): open a new-record form. Deep links can't open specifics
 *   without significant refactor — show the module page with a toast instead.
 * ARIA: uses separate pages, not a single SPA. Deep link lands on dashboard page.
 */
