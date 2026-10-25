"""Cloud pre-deploy helper (branch `cloud`): wait until DATABASE_URL accepts connections and print the
real error while it doesn't. psycopg_pool's PoolTimeout hides it. The password is never printed.

    python -m app.wait_for_db && python -m app.seed
"""
import os
import socket
import sys
import time
from urllib.parse import urlsplit

import psycopg

ATTEMPTS = 12
PAUSE_S = 10


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL is not set", flush=True)
        return 1
    u = urlsplit(url)
    print(f"database: user={u.username} host={u.hostname} port={u.port or 5432} db={u.path.lstrip('/')}"
          f" query={u.query or '-'}", flush=True)
    for i in range(1, ATTEMPTS + 1):
        try:
            addrs = sorted({a[4][0] for a in socket.getaddrinfo(u.hostname, u.port or 5432)})
            print(f"attempt {i}/{ATTEMPTS}: {u.hostname} resolves to {', '.join(addrs)}", flush=True)
            with psycopg.connect(url, connect_timeout=10) as conn:
                version = conn.execute("show server_version").fetchone()[0]
            print(f"database ok: PostgreSQL {version}", flush=True)
            return 0
        except Exception as e:  # print the real reason: DNS, refused, auth, SSL, pg_hba ...
            print(f"attempt {i}/{ATTEMPTS} failed: {type(e).__name__}: {str(e).strip()[:400]}", flush=True)
        time.sleep(PAUSE_S)
    return 1


if __name__ == "__main__":
    sys.exit(main())
