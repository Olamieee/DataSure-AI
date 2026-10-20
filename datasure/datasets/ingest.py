"""Dataset ingestion: parsing CSV/TSV/Excel files with graceful error handling.

The goal is to give users *specific* validation errors rather than generic
failures, while never letting malformed input crash the service.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from ..storage import safe_extension


class DatasetParseError(ValueError):
    """Readable, user-facing error for dataset loading problems."""

    def __init__(self, message: str, *, hint: str | None = None):
        self.hint = hint
        super().__init__(message)


CSV_ENCODINGS_TO_TRY = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _pandas_exception_message(exc: Exception, ext: str) -> str:
    detail = str(exc).replace("\n", " ").strip()
    first_line = detail.split(":", 1)[0][:200] if ":" in detail else detail[:200]
    if ext in {".xlsx", ".xls"}:
        hint = "The file may be corrupted or protected. Try re-saving it from Excel"
    else:
        hint = "The file may have an unexpected layout. Try opening it in a text editor"
    return f"Could not parse the file ({first_line}). {hint} and upload it again."


def load_dataframe(path: Path, extension: str, max_rows: int, max_columns: int) -> pd.DataFrame:
    """Load a dataset file into a DataFrame, enforcing guards and clear errors."""
    if not path.exists():
        raise DatasetParseError("The stored dataset file could not be found.")

    size_ok = path.stat().st_size > 0
    if not size_ok:
        raise DatasetParseError("The uploaded file is empty (0 bytes).", hint="Export a non-empty file.")

    try:
        if extension in {".csv", ".tsv"}:
            df = _load_csv(path, delimiter="\t" if extension == ".tsv" else None)
        elif extension in {".xlsx", ".xls"}:
            try:
                df = pd.read_excel(path, engine="openpyxl" if extension == ".xlsx" else "xlrd")
            except Exception as exc:  # openpyxl raises several unrelated types
                raise DatasetParseError(_pandas_exception_message(exc, extension)) from exc
        else:
            raise DatasetParseError(f"Unsupported file type '{extension}'.")
    except DatasetParseError:
        raise
    except pd.errors.EmptyDataError as exc:
        raise DatasetParseError("The file contains no data rows.") from exc
    except pd.errors.ParserError as exc:
        raise DatasetParseError(_pandas_exception_message(exc, extension)) from exc
    except UnicodeDecodeError as exc:
        raise DatasetParseError(
            "The file uses an text encoding that could not be read.",
            hint="Re-save the file as UTF-8 encoded CSV.",
        ) from exc

    _validate_shape(df, max_rows, max_columns)
    df.columns = _clean_column_names(df.columns)
    return df


def _load_csv(path: Path, delimiter: str | None = None) -> pd.DataFrame:
    read_kwargs: dict = {"skip_blank_lines": True}
    if delimiter is not None:
        read_kwargs["sep"] = delimiter
    last_error: Exception | None = None
    for encoding in CSV_ENCODINGS_TO_TRY:
        try:
            df = pd.read_csv(path, encoding=encoding, **read_kwargs)
            _validate_shape(df, _huge, _huge)
            if df.shape[1] <= 1 and delimiter is None:
                # Single column often means the wrong delimiter; try auto-sniff.
                sniffed = pd.read_csv(path, encoding=encoding, sep=None, engine="python",
                                      skip_blank_lines=True)
                if sniffed.shape[1] > 1:
                    return sniffed
            return df
        except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
            last_error = exc
            continue
    raise DatasetParseError(_pandas_exception_message(last_error or ValueError("unknown"), ".csv"))


_huge = 10**9  # sentinel meaning "no row/column limit inline"


def _validate_shape(df: pd.DataFrame, max_rows: int, max_columns: int) -> None:
    rows, columns = df.shape
    if rows == 0 or columns == 0:
        raise DatasetParseError("The dataset has no data rows or columns.")
    if rows > max_rows:
        raise DatasetParseError(
            f"The dataset has {rows:,} rows, exceeding the platform limit of {max_rows:,}."
        )
    if columns > max_columns:
        raise DatasetParseError(
            f"The dataset has {columns:,} columns, exceeding the platform limit of {max_columns:,}."
        )


def _clean_column_names(columns) -> list[str]:
    """Normalise column headers: strip whitespace, fill unnamed/duplicate names."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for idx, col in enumerate(columns):
        name = str(col).strip()
        if not name or name.lower().startswith("unnamed"):
            name = f"column_{idx + 1}"
        base = name
        suffix = 2
        while name.lower() in seen:
            name = f"{base}_{suffix}"
            suffix += 1
        seen.add(name.lower())
        cleaned.append(name)
    return cleaned


def parse_uploaded_dataset(
    file_storage,
    allowed_extensions: set[str],
    instance_path: str,
    user_id: int,
    max_rows: int,
    max_columns: int,
):
    """Validate, persist, hash and parse a freshly uploaded file.

    Returns:
        (df, storage_filename, extension, sha256, row_count, column_count)
    Raises:
        DatasetParseError with a user-facing message on failure.
    """
    from ..storage import (
        generate_storage_filename,
        sha256_of_file,
        user_upload_dir,
    )

    client_filename = file_storage.filename or ""
    try:
        extension = safe_extension(client_filename, allowed_extensions)
    except ValueError as exc:
        raise DatasetParseError(str(exc)) from exc

    upload_dir = user_upload_dir(instance_path, user_id)
    storage_filename = generate_storage_filename(extension)
    destination = upload_dir / storage_filename

    file_storage.save(destination)
    try:
        sha256 = sha256_of_file(destination)
        df = load_dataframe(destination, extension, max_rows, max_columns)
    except DatasetParseError:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:  # unexpected - surface as friendly message
        destination.unlink(missing_ok=True)
        raise DatasetParseError(
            "An unexpected error occurred while processing the file.", hint=str(exc)[:200]
        ) from exc

    return df, storage_filename, extension, sha256, int(df.shape[0]), int(df.shape[1])


def dataset_preview(df: pd.DataFrame, limit: int = 25) -> list[list]:
    """Small preview matrix (headers + up to `limit` rows) as plain Python types."""
    import math

    head = df.head(limit)
    records: list[list] = [list(df.columns)]
    for row in head.itertuples(index=False, name=None):
        values = []
        for value in row:
            if value is None or value is pd.NA or (
                isinstance(value, float) and math.isnan(value)
            ):
                values.append(None)
            elif isinstance(value, bytes):
                values.append(value.decode("utf-8", "replace"))
            elif isinstance(value, pd.Timestamp):
                values.append(value.isoformat())
            else:
                values.append(value)
        records.append(values)
    return records


def dataframe_schema(df: pd.DataFrame) -> list[dict]:
    """Schema summary: per-column pandas dtype and inferred practical kind."""
    schema = []
    for column in df.columns:
        series = df[column]
        pandas_dtype = str(series.dtype)
        if pd.api.types.is_numeric_dtype(series):
            kind = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series):
            kind = "datetime"
        elif pd.api.types.is_bool_dtype(series):
            kind = "boolean"
        else:
            non_null = int(series.notna().sum())
            unique = int(series.nunique(dropna=True))
            kind = (
                "identifier"
                if non_null > 4 and unique == non_null
                else "categorical"
            )
        schema.append(
            {
                "name": str(column),
                "dtype": pandas_dtype,
                "kind": kind,
            }
        )
    return schema
