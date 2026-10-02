"""Which K9X HIL instance this is (HIL_PROFILE).

public    hil.k9x.ai. The example applications' tasks (EOC, DAS, Continuum,
          Process Studio AP), demo/admin logins shown. Deciding is allowed: no
          example application consumes the replies, so a decision changes
          nothing outside this HIL.
internal  LAN only, for K9-AIF Framework Administrators: K9X Sentinel's
          Security tasks, decided by the framework admin.

The two register disjoint topics, so a task only ever lands in one of them.
"""

import os

PROFILE = os.getenv("HIL_PROFILE", "public").strip().lower()
