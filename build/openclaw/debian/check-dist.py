"""Check an npm tarball against dist.integrity and dist.shasum of the registry metadata."""
import base64
import hashlib
import json
import sys

meta, tgz = sys.argv[1], sys.argv[2]
with open(meta) as f:
    dist = json.load(f)["dist"]
with open(tgz, "rb") as f:
    data = f.read()
algo, _, want = dist["integrity"].partition("-")
if algo != "sha512":
    sys.exit(f"{tgz}: integrity uses {algo}, not sha512")
if base64.b64encode(hashlib.sha512(data).digest()).decode() != want:
    sys.exit(f"{tgz}: SHA-512 does not match dist.integrity")
if hashlib.sha1(data).hexdigest() != dist["shasum"]:
    sys.exit(f"{tgz}: SHA-1 does not match dist.shasum")
print(f"{tgz}: dist.integrity and dist.shasum match")
