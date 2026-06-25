"""Enchant API service for RCSC support tickets (read-only).

Identity: Ross Calvert (r.calvert@rcsc.uk) on the rcsc Enchant helpdesk.
This service is scoped exclusively to RCSC.
"""

import logging
import os

from agent.services.enchant_base import EnchantBaseService

logger = logging.getLogger("agent.enchant_rcsc")


class EnchantRCSCService(EnchantBaseService):
    def __init__(self):
        super().__init__(
            api_key=os.getenv("ENCHANT_RCSC_API_KEY", ""),
            site=os.getenv("ENCHANT_RCSC_SITE", ""),
            user_id=os.getenv("ENCHANT_RCSC_USER_ID", ""),
            label="RCSC",
        )
