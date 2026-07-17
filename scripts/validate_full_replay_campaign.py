"""兼容入口：历史五题现在只能产生集成 fixture 证据。"""

from __future__ import annotations

import warnings

from validate_integration_fixture_campaign import main


if __name__ == "__main__":
    warnings.warn(
        "该命令已降级为集成 fixture 校验，不能产生 full_replay_passed；"
        "请改用 validate_integration_fixture_campaign.py。",
        FutureWarning,
        stacklevel=1,
    )
    raise SystemExit(main())
