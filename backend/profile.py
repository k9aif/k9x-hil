"""Which K9X HIL instance this is (HIL_PROFILE).

public    hil.k9x.ai. Receives the example applications' tasks (EOC, DAS,
          Continuum, Process Studio AP). Visitors can view everything, but no
          one (admin included) can act on a task. Tasks close only by their
          queue's TTL (expire/reject/escalate), which keeps the list short.
internal  LAN only, for K9-AIF Framework Administrators: K9X Sentinel's
          Security tasks, decided by the framework admin.

The two register disjoint topics, so a task only ever lands in one of them.
"""

import os

PROFILE = os.getenv("HIL_PROFILE", "public").strip().lower()
READ_ONLY = PROFILE != "internal"
