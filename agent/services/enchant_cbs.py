"""Enchant API service for CBS support tickets (read-only).

Identity: Ross Calvert (r.calvert@cbsnw.uk) on the cbsnw Enchant helpdesk.
This service is scoped exclusively to CBS.
"""

import logging
import os

from agent.services.enchant_base import EnchantBaseService

logger = logging.getLogger("agent.enchant_cbs")


class EnchantCBSService(EnchantBaseService):
    def __init__(self):
        super().__init__(
            api_key=os.getenv("ENCHANT_CBS_API_KEY", ""),
            site=os.getenv("ENCHANT_CBS_SITE", ""),
            user_id=os.getenv("ENCHANT_CBS_USER_ID", ""),
            label="CBS",
        )
