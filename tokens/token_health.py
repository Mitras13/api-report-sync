"""
Cheap token liveness probe.

Usage:
    python token_health.py
    python token_health.py HK
    python token_health.py 54

This checks authentication without saving a report to raw_data/.
A network/server error is treated as inconclusive, not as an expired token.
"""
import sys
import jdatetime

from downloaders import INV_SAL_54, SCL_HK
from downloaders.downloader_core import call_api, load_token, AuthExpiredError

PROBES = {
    "HK": (SCL_HK, "cookie"),
    "54": (INV_SAL_54, "bearer"),
}


def check_token(company_code: str) -> bool:
    module, auth_mode = PROBES[company_code]
    now = jdatetime.datetime.now()
    token = load_token(company_code)
    params = module.build_params(now, now)

    try:
        call_api(
            module.URL,
            module.METHOD,
            params,
            token,
            auth_mode=auth_mode,
            json_body={} if auth_mode == "bearer" else None,
        )
        return True
    except AuthExpiredError:
        return False
    except Exception:
        # Cannot distinguish network/server failure from token failure here.
        return True


def check_all_tokens():
    status = {}
    for company_code in PROBES:
        ok = check_token(company_code)
        status[company_code] = ok
        if ok:
            print(f"🔑 token check: {company_code} OK")
        else:
            print(
                f"🚨 TOKEN EXPIRED for '{company_code}'. "
                f"Run: python refresh_token.py {company_code}"
            )
    return status


if __name__ == "__main__":
    if len(sys.argv) == 2:
        code = sys.argv[1]
        if code not in PROBES:
            print("Usage: python token_health.py [HK|54]")
            sys.exit(1)
        print(f"{code}: {'OK' if check_token(code) else 'EXPIRED'}")
    elif len(sys.argv) == 1:
        check_all_tokens()
    else:
        print("Usage: python token_health.py [HK|54]")
        sys.exit(1)
