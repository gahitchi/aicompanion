import subprocess

ALLOWED = ["dir", "echo", "type"]

def run_command(cmd: str):

    base = cmd.split()[0]

    if base not in ALLOWED:
        return "Blocked command"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5
        )

        return result.stdout or result.stderr

    except Exception as e:
        return str(e)