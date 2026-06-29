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
