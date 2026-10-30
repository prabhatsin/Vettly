
# This is used to run the all three containers , ...redis , postgres and livekit server 
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent

result = subprocess.run(["docker", "compose", "up", "-d", "--wait"], cwd=root)
if result.returncode != 0:
    sys.exit("docker compose failed: is Docker running?")

subprocess.run(["docker", "compose", "ps"], cwd=root)