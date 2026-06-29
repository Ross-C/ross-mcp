# Sophie (ElevenLabs PA) — Config Change Log

Config snapshots live in `elevenlabs/backups/` (git-versioned = our rollback history).
**To roll back:** `python3 elevenlabs/rollback.py elevenlabs/backups/<snapshot>.json`

## 20260629-134536 — voice-agent refinement (human-likeness + usefulness)
Rollback to previous: `python3 elevenlabs/rollback.py sophie-before-20260629-133943.json` (in backups/)
- temperature 0.0 -> 0.5; stability 0.85 -> 0.6; speed 1.05 -> 1.0; max_tokens -1 -> 250
- first_message "Hey Ross..." -> "" (varied greetings); text_normalisation_type -> elevenlabs; turn_timeout 3.0 -> 2.0
- Removed the disabled `local-weather` tool (42 -> 41) and its prompt dependency
- Prompt: added WORK & TASKS + DAILY BRIEF sections; spoken-style rules (no markdown, money in words); broadened confirm-before-action to tasks/deploy-bill/tickets
- NOT applied: enable_parallel_tool_calls (rejected for this agent — revisit)
- Snapshots: before=`sophie-before-20260629-133943.json`, after=`sophie-after-20260629-134536.json`

## 20260629-141001 — revert empty first_message (startup latency)
- first_message restored to "Hey Ross, what can I do for you?" so the greeting is spoken instantly (empty first_message made the LLM generate it first, causing a long delay before she talks). All other refinements kept.

## 20260629-141444 — revert text normalisation to system_prompt (latency)
- text_normalisation_type elevenlabs -> system_prompt to drop a per-reply processing step (Ross felt responses were a touch slower). The "speak money/refs in words, no markdown" rule is already in the prompt, so spoken correctness is kept.

## 20260629-141851 — silence handling: snappy turns, no quick "still there"
- Kept turn_timeout 2.0s (fast replies). Added prompt rule: stay silent on normal pauses; only after a long silence give ONE brief check-in; let the 30s silence_end_call_timeout end an abandoned call.

## 20260629-142043 — slightly friendlier
- Added a warmth/persona line to the system prompt; warmer fixed greeting ("Hey Ross, good to hear from you! What can I do for you?"); nudged TTS style up a touch if supported.

## 20260629-142210 — fix "short and moody"
- Prompt: added WARMTH FIRST rule (brief but friendly/upbeat, never curt/flat). Voice model eleven_flash_v2 -> eleven_turbo_v2_5 (warmer, more expressive). Rollback if too slow: restore a previous snapshot.

## 20260629-142255 — fix "short and moody" (re-applied; prior entry did not apply due to a script error)
- Prompt: added WARMTH FIRST rule (brief but friendly/upbeat, never curt/flat). Voice model eleven_flash_v2 -> eleven_turbo_v2_5 (warmer, more expressive). If she now feels too slow, roll back to a flash snapshot.
