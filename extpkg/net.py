"""HTTP helpers with retries, plus hashing and GitHub Actions annotations."""

import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

USER_AGENT = "armbian-external/1"
RETRIES = 4


class FetchError(RuntimeError):
    pass


def _request(url, headers=None, method="GET"):
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    return urllib.request.Request(url, headers=hdrs, method=method)


def _with_retry(fn, url):
    delay = 2
    for attempt in range(1, RETRIES + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            # 4xx other than 429 will not get better on retry.
            if 400 <= e.code < 500 and e.code != 429:
                raise FetchError(f"HTTP {e.code} for {url}") from e
            err = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            err = e
        if attempt < RETRIES:
            time.sleep(delay)
            delay *= 2
    raise FetchError(f"{url}: {err}")


def get_bytes(url, headers=None, timeout=60):
    def go():
        with urllib.request.urlopen(_request(url, headers), timeout=timeout) as r:
            return r.read()

    return _with_retry(go, url)


def get_json(url, headers=None):
    return json.loads(get_bytes(url, headers))


def download(url, dest, headers=None, timeout=300):
    """Download to dest atomically. Return (sha256, size)."""
    tmp = dest + ".part"

    def go():
        h = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(_request(url, headers), timeout=timeout) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
                f.write(chunk)
        return h.hexdigest(), size

    try:
        digest, size = _with_retry(go, url)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    os.replace(tmp, dest)
    return digest, size


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def github_headers():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    hdrs = {"Accept": "application/vnd.github+json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return hdrs


# --- logging -----------------------------------------------------------------

def log(msg):
    print(msg, file=sys.stderr, flush=True)


def warn(msg):
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "warning: "
    log(prefix + msg)


def error(msg):
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else "error: "
    log(prefix + msg)


def summary(markdown):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(markdown + "\n")


def have(cmd):
    return shutil.which(cmd) is not None
