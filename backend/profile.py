"""Which K9X HIL instance this is (HIL_PROFILE).

public    hil.k9x.ai. A read-only window: it consumes the same task topics
          (its own consumer group) so visitors see real traffic, but it never
          decides and never publishes. No task actions for anyone (admin
          included), no TTL expiry replies, no reply outbox, no dead-letter
          publishing. Decisions come only from the internal instance, so a
          public copy never resumes a waiting application.
internal  LAN only. Decides: actions, TTL expiry, replies, DLQ.
"""

import os

PROFILE = os.getenv("HIL_PROFILE", "public").strip().lower()
READ_ONLY = PROFILE != "internal"
