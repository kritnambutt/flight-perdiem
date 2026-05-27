"""
One-time Google Drive auth setup.

Run this once on each machine (Mac dev, Raspberry Pi) to grant Drive access
for kantaphajasuwan@airasia.com via gcloud. No GCP project permissions,
no service account, and no external sharing required.

Usage:
    python scripts/auth_drive.py

What it does:
    1. Runs: gcloud auth login --enable-gdrive-access --account=kantaphajasuwan@airasia.com
    2. Opens a browser — sign in as kantaphajasuwan@airasia.com and click Allow.
    3. Verifies the token works by fetching a known roster file from Drive.

After setup the engine calls `gcloud auth print-access-token` at runtime to
get a fresh token automatically — no manual refresh ever needed.
"""
import subprocess
import sys

ACCOUNT = "kantaphajasuwan@airasia.com"
TEST_FILE_ID = "1m_-KGc30xRNpRLROsY_9HOMcRcDBk467"   # Pansita Jansavang, MARCH 26 row 1


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def get_token() -> str | None:
    r = run(["gcloud", "auth", "print-access-token", f"--account={ACCOUNT}"])
    return r.stdout.strip() if r.returncode == 0 else None


def verify_token(token: str) -> bool:
    import urllib.request, urllib.error
    url = f"https://www.googleapis.com/drive/v3/files/{TEST_FILE_ID}?fields=name,mimeType"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            import json
            data = json.loads(resp.read())
            print(f"  Verified access to: {data.get('name')} ({data.get('mimeType')})")
            return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.reason}")
        return False


def main() -> None:
    print(f"Setting up Google Drive access for {ACCOUNT}")
    print()

    # Step 1: check if a working token already exists
    token = get_token()
    if token and verify_token(token):
        print()
        print("Already authenticated and Drive access confirmed.")
        print("No further action needed.")
        return

    # Step 2: run gcloud login with Drive scope
    print("Opening browser for Google sign-in...")
    print(f"Log in as: {ACCOUNT}")
    print()
    result = run([
        "gcloud", "auth", "login",
        "--enable-gdrive-access",
        f"--account={ACCOUNT}",
    ])
    if result.returncode != 0:
        print("ERROR: gcloud login failed.")
        print(result.stderr)
        sys.exit(1)

    # Step 3: verify
    token = get_token()
    if not token:
        print("ERROR: could not retrieve access token after login.")
        sys.exit(1)

    print("Verifying Drive access...")
    if verify_token(token):
        print()
        print("Setup complete. Drive access confirmed.")
        print(f"Token auto-refreshes via gcloud — no maintenance needed.")
    else:
        print()
        print("WARNING: login succeeded but Drive access was denied.")
        print("AirAsia may be blocking external Drive scope for this account.")
        print("Fallback: admin must upload roster images manually via the web UI.")
        sys.exit(1)


if __name__ == "__main__":
    main()
