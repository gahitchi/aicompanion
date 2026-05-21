from pathlib import Path

BASE_DIR = Path.cwd()

def resolve(path: str):
    target = (BASE_DIR / path).resolve()

    if BASE_DIR not in target.parents and target != BASE_DIR:
        return None

    return target


def read_file(path: str):

    target = resolve(path)

    if not target:
        return "Blocked: outside project directory"

    if not target.exists():
        return "File not found"

    return target.read_text(encoding="utf-8")


def write_file(path: str, content: str):

    target = resolve(path)

    if not target:
        return "Blocked: outside project directory"

    target.parent.mkdir(parents=True, exist_ok=True)

    target.write_text(content, encoding="utf-8")

    return "OK"