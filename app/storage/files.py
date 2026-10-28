"""Server-named originals with atomic replacement on the local filesystem."""
import os
from pathlib import Path
import tempfile
from uuid import UUID


def save_original_pdf(pdf_bytes: bytes, receipt_id: str, *, data_dir: Path) -> str:
    identifier = str(UUID(receipt_id))
    if identifier != receipt_id:
        raise ValueError("Receipt ID must be a canonical server UUID")
    root = data_dir.resolve()
    directory = root / "originals"
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Original directory escapes DATA_DIR")
    target = directory / f"{identifier}.pdf"
    if target.is_symlink():
        raise FileExistsError("Refusing to replace a symbolic link")
    if target.exists():
        if target.read_bytes() != pdf_bytes:
            raise FileExistsError("Refusing to overwrite an existing original")
        return f"originals/{identifier}.pdf"
    descriptor, name = tempfile.mkstemp(dir=directory, prefix=f".{identifier}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(pdf_bytes)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        if os.name != "nt":
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return f"originals/{identifier}.pdf"
