#!/usr/bin/env python3
"""Roll a ConvAI agent back to a saved config snapshot.
Usage: python3 elevenlabs/rollback.py <snapshot.json> [agent_id]
Reads ELEVENLABS_API_KEY from ../.env. Sends conversation_config (tool_ids only)."""
import json,sys,os,urllib.request,re
snap=sys.argv[1]
agent=sys.argv[2] if len(sys.argv)>2 else "agent_1601kvz6xrrje8avnvdcchnsnwcf"
env=open(os.path.join(os.path.dirname(__file__),"..",".env")).read()
key=re.search(r'^ELEVENLABS_API_KEY=(.+)$',env,re.M).group(1).strip()
cc=json.load(open(snap))["conversation_config"]
# API rejects both tools + tool_ids; keep tool_ids only
cc.get("agent",{}).get("prompt",{}).pop("tools",None)
patch={"conversation_config":cc}
req=urllib.request.Request(f"https://api.elevenlabs.io/v1/convai/agents/{agent}",data=json.dumps(patch).encode(),method="PATCH",headers={"xi-api-key":key,"Content-Type":"application/json"})
urllib.request.urlopen(req); print("Rolled back to",os.path.basename(snap))
