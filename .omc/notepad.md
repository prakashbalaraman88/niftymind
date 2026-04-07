# Notepad
<!-- Auto-managed by OMC. Manual edits preserved in MANUAL section. -->

## Priority Context
<!-- ALWAYS loaded. Keep under 500 chars. Critical discoveries only. -->

## Working Memory
<!-- Session notes. Auto-pruned after 7 days. -->
### 2026-04-07 05:37
Session 2026-04-07: Major fixes applied during paper trading day.
- Fixed Fyers TBT WebSocket (on_open callback, subscribe params, token format)
- Created REST quotes poller as reliable tick fallback (NIFTY50-INDEX, NIFTYBANK-INDEX + futures)
- Fixed frontend: Notifications crash on web, agent ID mismatch, VIX as tick, change_pct
- Fixed DB logger: removed UUID id columns that didn't exist in Supabase tables
- Added trade status OPEN (was FILLED), manual close endpoint, open trade P&L display
- 9/12 agents now active (was 3/12). Volume Profile + Order Flow unlocked by futures data.
- Dhan depth feed still HTTP 400 — non-critical, Fyers provides data.


## MANUAL
<!-- User content. Never auto-pruned. -->

