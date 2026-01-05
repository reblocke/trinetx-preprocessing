"""CSV splitting utilities."""

from __future__ import annotations

import csv
from pathlib import Path

DEFAULT_SUFFIX_WIDTH = 4


def split_csv(
    in_path: Path,
    out_dir: Path,
    lines_per_chunk: int,
    prefix: str | None = None,
) -> list[Path]:
    """Split a CSV into multiple chunk files.

    Args:
        in_path: Path to the source CSV file.
        out_dir: Directory to write chunked outputs.
        lines_per_chunk: Number of data rows per chunk.
        prefix: Optional output filename prefix (defaults to input stem).

    Returns:
        List of paths for the chunk files written in order.

    Raises:
        FileNotFoundError: If the input path does not exist.
        ValueError: If the input CSV is empty or lines_per_chunk is invalid.
    """

    input_path = Path(in_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")
    if lines_per_chunk <= 0:
        raise ValueError("lines_per_chunk must be a positive integer.")

    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_prefix = prefix or input_path.stem

    output_paths: list[Path] = []
    output_handle = None
    writer: csv.writer | None = None
    rows_in_chunk = 0

    def open_chunk(index: int, header: list[str]) -> None:
        nonlocal output_handle, writer, rows_in_chunk
        if output_handle is not None:
            output_handle.close()
        chunk_name = f"{chunk_prefix}{str(index).zfill(DEFAULT_SUFFIX_WIDTH)}.csv"
        chunk_path = output_dir / chunk_name
        output_handle = chunk_path.open("w", encoding="utf-8", newline="")
        writer = csv.writer(output_handle)
        writer.writerow(header)
        rows_in_chunk = 0
        output_paths.append(chunk_path)

    try:
        with input_path.open("r", encoding="utf-8", newline="") as input_handle:
            reader = csv.reader(input_handle)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise ValueError(f"Input CSV is empty: {input_path}") from exc

            chunk_index = 1
            open_chunk(chunk_index, header)

            for row in reader:
                if rows_in_chunk >= lines_per_chunk:
                    chunk_index += 1
                    open_chunk(chunk_index, header)
                writer.writerow(row)
                rows_in_chunk += 1
    finally:
        if output_handle is not None:
            output_handle.close()

    return output_paths
