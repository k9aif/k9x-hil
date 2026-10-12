"""Which K9X HIL instance this is (HIL_PROFILE).

public    hil.k9x.ai. The example applications' tasks (EOC, DAS, Continuum,
          Process Studio AP); signs in on its landing page (demo login). Deciding
          is allowed and real for the demonstrations: DAS and Continuum consume
          the replies, so approving a DAS gate moves that DAS job on.
internal  LAN only, for K9-AIF Framework Administrators: K9X Sentinel's
          Security tasks, decided by the framework admin.
instance  A dedicated HIL for one project (HIL_INSTANCE=<name>, backend/instance.py):
          its own branding, queues, Jobs view and schema, e.g. DAS.

The two register disjoint topics, so a task only ever lands in one of them.
"""

import os

PROFILE = "instance" if os.getenv("HIL_INSTANCE", "").strip() else os.getenv("HIL_PROFILE", "public").strip().lower()
