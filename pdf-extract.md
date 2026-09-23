Yes — I agree with you. For your use case, **the extraction pipeline should not know anything about the business/domain of the PDF**.

So I would remove:

* hardcoded header aliases
* hardcoded junk-row names
* hardcoded column names
* hardcoded assumptions like `Description` being column 0
* hardcoded financial formulas
* hardcoded security/CUSIP/ISIN logic

Instead, the pipeline should reason from **table structure, cell spans, data types, repetition, geometry, and statistical patterns**.

Also, I would change the previous design slightly: **save every intermediate optimization stage**, so you can inspect exactly where an error is introduced.

Docling's current table model actually gives us useful structural information such as `row_span`, `col_span`, `row_section`, `column_header`, and cell coordinates. That is much more valuable for a generic solution than hardcoded semantic rules. ([Docling Project][1])

---

# Proposed completely generic pipeline

```text
PDF
 │
 ├── page 1..N
 │
 ▼
Parallel page chunks
 │
 ▼
┌─────────────────────────────────────┐
│ 01_docling_raw                      │
│                                     │
│ Docling JSON                        │
│ Table cell spans                    │
│ Bounding boxes                      │
│ Header/section metadata             │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 02_table_html                       │
│                                     │
│ HTML with rowspan / colspan         │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 03_raw_dataframe                    │
│                                     │
│ Pandas representation               │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 04_header_structure                 │
│                                     │
│ Generic multi-row header merging    │
│ Based on structure, not names       │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 05_row_structure                    │
│                                     │
│ Generic row classification           │
│ Numeric/text density                │
│ span information                    │
│ section information                 │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 06_cleaned                          │
│                                     │
│ Structural rows removed             │
│ Multiline rows reconstructed        │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 07_normalized                       │
│                                     │
│ Whitespace                          │
│ Numbers                             │
│ Duplicate columns                  │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 08_chunk_outputs                    │
│                                     │
│ Ordered chunk results               │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 09_continuation_merge               │
│                                     │
│ Generic adjacent-table matching     │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│ 10_final                            │
│                                     │
│ Final Excel                         │
└─────────────────────────────────────┘
```

This also lets you answer the most important debugging question:

> **At which optimization stage did the extraction become wrong?**

---

# Updated code

Below is the revised generic version.

## `generic_pdf_table_pipeline.py`

```python
from __future__ import annotations

import os
import re
import json
import shutil
import traceback

from pathlib import Path
from io import StringIO
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_PDF = "input.pdf"

OUTPUT_ROOT = Path("extraction_output")

CHUNK_SIZE = 10

MAX_WORKERS = min(
    4,
    os.cpu_count() or 2
)

# ------------------------------------------------------------
# Docling configuration
# ------------------------------------------------------------

TABLE_MODE = TableFormerMode.ACCURATE

DO_CELL_MATCHING = False

DO_OCR = False

FORCE_BACKEND_TEXT = True


# ============================================================
# STAGE DIRECTORIES
# ============================================================

STAGES = {
    "01_docling_raw": "01_docling_raw",
    "02_table_html": "02_table_html",
    "03_raw_dataframe": "03_raw_dataframe",
    "04_header_structure": "04_header_structure",
    "05_row_structure": "05_row_structure",
    "06_cleaned": "06_cleaned",
    "07_normalized": "07_normalized",
    "08_ordered_chunks": "08_ordered_chunks",
    "09_continuation_merge": "09_continuation_merge",
    "10_final": "10_final",
}


def create_stage_directories():

    for directory in STAGES.values():

        (
            OUTPUT_ROOT / directory
        ).mkdir(
            parents=True,
            exist_ok=True
        )


# ============================================================
# GENERIC TEXT UTILITIES
# ============================================================

def clean_text(value) -> str:

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value)

    text = text.replace(
        "\xa0",
        " "
    )

    text = text.replace(
        "\n",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_text(value) -> str:

    text = clean_text(value)

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# GENERIC DATA-TYPE DETECTION
# ============================================================

def is_numeric(value) -> bool:

    if value is None:
        return False

    text = clean_text(value)

    if not text:
        return False

    # Remove common formatting without assuming
    # what the business meaning is.
    candidate = (
        text
        .replace(",", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("¥", "")
    )

    # Parentheses commonly represent negative numbers.
    candidate = candidate.strip("()")

    # Remove a trailing currency/token if present.
    candidate = re.sub(
        r"\s+[A-Za-z]{2,5}$",
        "",
        candidate
    )

    return bool(
        re.fullmatch(
            r"-?\d+(?:\.\d+)?",
            candidate
        )
    )


def numeric_ratio(row) -> float:

    values = list(row.values)

    nonempty = [
        v
        for v in values
        if clean_text(v)
    ]

    if not nonempty:
        return 0.0

    numeric = sum(
        is_numeric(v)
        for v in nonempty
    )

    return numeric / len(nonempty)


def text_ratio(row) -> float:

    values = list(row.values)

    nonempty = [
        v
        for v in values
        if clean_text(v)
    ]

    if not nonempty:
        return 0.0

    text_values = sum(
        not is_numeric(v)
        for v in nonempty
    )

    return text_values / len(nonempty)


# ============================================================
# COLUMN NORMALIZATION
# ============================================================

def normalize_column_names(
    columns
):

    output = []

    used = {}

    for column in columns:

        name = clean_text(column)

        if not name:
            name = "unnamed"

        # Generic normalization only.
        name = re.sub(
            r"\s+",
            " ",
            name
        )

        name = name.strip()

        base = name

        if base not in used:

            used[base] = 0
            output.append(base)

        else:

            used[base] += 1

            output.append(
                f"{base}_{used[base]}"
            )

    return output


# ============================================================
# MULTI-LEVEL HEADER RECONSTRUCTION
# ============================================================

def flatten_multiindex_columns(
    df: pd.DataFrame
):

    if not isinstance(
        df.columns,
        pd.MultiIndex
    ):

        df.columns = (
            normalize_column_names(
                df.columns
            )
        )

        return df

    flattened = []

    for levels in df.columns:

        parts = []

        previous = None

        for level in levels:

            text = clean_text(level)

            if not text:
                continue

            # Prevent:
            #
            # QUANTITY | QUANTITY
            #
            # becoming:
            #
            # QUANTITY QUANTITY
            #
            if (
                previous is not None
                and normalize_text(previous)
                == normalize_text(text)
            ):
                continue

            parts.append(text)

            previous = text

        flattened.append(
            " ".join(parts)
        )

    df.columns = (
        normalize_column_names(
            flattened
        )
    )

    return df


# ============================================================
# GENERIC HEADER ROW DETECTION
# ============================================================

def detect_header_rows(
    df: pd.DataFrame
):

    """
    Detect leading rows that look like headers.

    No knowledge of column names is required.

    Header candidates generally have:

        - high text density
        - low numeric density
        - occur before the first data-like row
    """

    if df.empty:
        return [], df

    candidate_indices = []

    for index in range(
        min(len(df), 8)
    ):

        row = df.iloc[index]

        nr = numeric_ratio(row)
        tr = text_ratio(row)

        # Generic statistical criterion.
        #
        # Text-heavy + almost no numeric values.
        if (
            tr >= 0.50
            and nr <= 0.25
        ):

            candidate_indices.append(
                index
            )

        else:

            # Stop once we reach the first
            # data-like row.
            if nr > 0.25:
                break

    return candidate_indices, df


def reconstruct_headers(
    df: pd.DataFrame
):

    if df.empty:
        return df

    df = flatten_multiindex_columns(df)

    header_rows, _ = detect_header_rows(df)

    if not header_rows:
        return df

    # We only use rows as additional header
    # information when there is more than
    # one candidate row.
    #
    # This prevents ordinary single-row tables
    # from being unnecessarily modified.
    if len(header_rows) <= 1:

        return df

    new_columns = []

    for column_index in range(
        len(df.columns)
    ):

        pieces = []

        # Existing column name.
        existing = clean_text(
            df.columns[column_index]
        )

        if existing:
            pieces.append(existing)

        # Header-row values.
        for row_index in header_rows:

            value = clean_text(
                df.iloc[
                    row_index,
                    column_index
                ]
            )

            if not value:
                continue

            if not pieces:

                pieces.append(value)

            elif (
                normalize_text(value)
                != normalize_text(
                    pieces[-1]
                )
            ):

                pieces.append(value)

        new_columns.append(
            " ".join(pieces)
        )

    # Remove the header rows from body.
    df = df.drop(
        index=header_rows
    ).reset_index(
        drop=True
    )

    df.columns = (
        normalize_column_names(
            new_columns
        )
    )

    return df


# ============================================================
# GENERIC ROW STRUCTURE ANALYSIS
# ============================================================

def analyze_rows(
    df: pd.DataFrame
):

    """
    Add generic structural metadata.

    This does NOT know anything about the domain.

    Features:

        numeric_ratio
        text_ratio
        nonempty_count
        row_type
    """

    if df.empty:
        return df

    output = df.copy()

    output["_numeric_ratio"] = (
        output.apply(
            numeric_ratio,
            axis=1
        )
    )

    output["_text_ratio"] = (
        output.apply(
            text_ratio,
            axis=1
        )
    )

    output["_nonempty_count"] = (
        output.apply(
            lambda row:
            sum(
                bool(clean_text(v))
                for v in row.values
            ),
            axis=1
        )
    )

    row_types = []

    for _, row in output.iterrows():

        nr = row["_numeric_ratio"]
        tr = row["_text_ratio"]
        ne = row["_nonempty_count"]

        if ne == 0:

            row_type = "empty"

        elif nr >= 0.50:

            row_type = "data"

        elif tr >= 0.75:

            row_type = "text"

        else:

            row_type = "mixed"

        row_types.append(
            row_type
        )

    output["_row_type"] = row_types

    return output


# ============================================================
# GENERIC STRUCTURAL ROW REMOVAL
# ============================================================

def remove_structural_rows(
    df: pd.DataFrame
):

    """
    Remove rows that are statistically structural.

    No business-specific text matching.

    Rules:

        1. Completely empty rows -> remove

        2. Text-only rows before any data ->
           retained temporarily because they may
           be multiline descriptions.

        3. Text-only rows after data:
           treated as possible continuation text.

    """

    if df.empty:
        return df

    metadata_columns = {
        "_numeric_ratio",
        "_text_ratio",
        "_nonempty_count",
        "_row_type",
    }

    data_columns = [
        c
        for c in df.columns
        if c not in metadata_columns
    ]

    working = df[
        data_columns
    ].copy()

    result = []

    pending_text = []

    for _, row in working.iterrows():

        values = list(row.values)

        nonempty = [
            v
            for v in values
            if clean_text(v)
        ]

        if not nonempty:
            continue

        numeric_count = sum(
            is_numeric(v)
            for v in nonempty
        )

        # ----------------------------------------------------
        # Data row
        # ----------------------------------------------------

        if numeric_count > 0:

            if pending_text:

                # Put preceding text into the
                # first non-empty textual cell.
                #
                # This is positional rather than
                # semantic.
                first_text_column = None

                for col in data_columns:

                    if clean_text(
                        row[col]
                    ):

                        first_text_column = col
                        break

                if first_text_column is None:

                    first_text_column = (
                        data_columns[0]
                    )

                prefix = "\n".join(
                    pending_text
                )

                current = clean_text(
                    row[
                        first_text_column
                    ]
                )

                row[
                    first_text_column
                ] = (
                    prefix
                    + (
                        "\n" + current
                        if current
                        else ""
                    )
                )

                pending_text = []

            result.append(row)

        # ----------------------------------------------------
        # Text-only row
        # ----------------------------------------------------

        else:

            text = " ".join(
                clean_text(v)
                for v in nonempty
            )

            pending_text.append(
                text
            )

    return pd.DataFrame(
        result,
        columns=data_columns
    ).reset_index(
        drop=True
    )


# ============================================================
# GENERIC NUMBER NORMALIZATION
# ============================================================

def normalize_number(
    value
):

    if not is_numeric(value):
        return value

    text = clean_text(value)

    negative = (
        text.startswith("(")
        and text.endswith(")")
    )

    text = (
        text
        .replace(",", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("¥", "")
    )

    text = text.strip("()")

    text = re.sub(
        r"\s+[A-Za-z]{2,5}$",
        "",
        text
    )

    try:

        number = float(text)

        if negative:
            number *= -1

        return number

    except Exception:

        return value


def normalize_dataframe(
    df: pd.DataFrame
):

    if df.empty:
        return df

    output = df.copy()

    output.columns = (
        normalize_column_names(
            output.columns
        )
    )

    for column in output.columns:

        output[column] = (
            output[column]
            .map(normalize_number)
        )

    return output


# ============================================================
# GENERIC DUPLICATE ROW REMOVAL
# ============================================================

def remove_duplicate_rows(
    df: pd.DataFrame
):

    if df.empty:
        return df

    return (
        df
        .drop_duplicates()
        .reset_index(drop=True)
    )


# ============================================================
# DOC LING CONVERTER
# ============================================================

def create_converter():

    pipeline_options = (
        PdfPipelineOptions(
            do_table_structure=True,
            do_ocr=DO_OCR,
            force_backend_text=(
                FORCE_BACKEND_TEXT
            ),
        )
    )

    pipeline_options.table_structure_options = (
        TableStructureOptions(
            mode=TABLE_MODE,
            do_cell_matching=(
                DO_CELL_MATCHING
            ),
        )
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF:
            PdfFormatOption(
                pipeline_options=(
                    pipeline_options
                )
            )
        }
    )


# ============================================================
# SAVE DATAFRAME
# ============================================================

def save_dataframe(
    df: pd.DataFrame,
    path: Path
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_csv(
        path,
        index=False
    )


# ============================================================
# PROCESS ONE CHUNK
# ============================================================

def process_chunk(
    pdf_path: str,
    chunk_id: int,
    start_page: int,
    end_page: int,
    output_root: str,
):

    try:

        converter = create_converter()

        result = converter.convert(
            pdf_path,
            page_range=(
                start_page,
                end_page
            )
        )

        chunk_results = []

        # ====================================================
        # STAGE 01
        # RAW DOCLING
        # ====================================================

        raw_dir = (
            Path(output_root)
            / STAGES["01_docling_raw"]
            / f"chunk_{chunk_id:05d}"
        )

        raw_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        raw_json = (
            result.document
            .export_to_dict()
        )

        with open(
            raw_dir / "document.json",
            "w",
            encoding="utf-8",
        ) as fp:

            json.dump(
                raw_json,
                fp,
                ensure_ascii=False,
                indent=2,
            )

        # ====================================================
        # PROCESS TABLES
        # ====================================================

        for table_id, table in enumerate(
            result.document.tables
        ):

            table_key = (
                f"table_{table_id:04d}"
            )

            # ------------------------------------------------
            # STAGE 02
            # HTML
            # ------------------------------------------------

            html = (
                table.export_to_html(
                    doc=result.document
                )
            )

            html_dir = (
                Path(output_root)
                / STAGES["02_table_html"]
                / f"chunk_{chunk_id:05d}"
            )

            html_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            with open(
                html_dir
                / f"{table_key}.html",
                "w",
                encoding="utf-8",
            ) as fp:

                fp.write(html)

            # ------------------------------------------------
            # STAGE 03
            # RAW DATAFRAME
            # ------------------------------------------------

            dataframes = pd.read_html(
                StringIO(html)
            )

            if not dataframes:
                continue

            df = dataframes[0]

            raw_df = df.copy()

            save_dataframe(
                raw_df,
                (
                    Path(output_root)
                    / STAGES[
                        "03_raw_dataframe"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            # ------------------------------------------------
            # STAGE 04
            # HEADER STRUCTURE
            # ------------------------------------------------

            header_df = (
                reconstruct_headers(
                    df.copy()
                )
            )

            save_dataframe(
                header_df,
                (
                    Path(output_root)
                    / STAGES[
                        "04_header_structure"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            # ------------------------------------------------
            # STAGE 05
            # ROW STRUCTURE
            # ------------------------------------------------

            row_analysis = (
                analyze_rows(
                    header_df.copy()
                )
            )

            save_dataframe(
                row_analysis,
                (
                    Path(output_root)
                    / STAGES[
                        "05_row_structure"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            # ------------------------------------------------
            # STAGE 06
            # CLEANED
            # ------------------------------------------------

            cleaned = (
                remove_structural_rows(
                    row_analysis
                )
            )

            save_dataframe(
                cleaned,
                (
                    Path(output_root)
                    / STAGES[
                        "06_cleaned"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            # ------------------------------------------------
            # STAGE 07
            # NORMALIZED
            # ------------------------------------------------

            normalized = (
                normalize_dataframe(
                    cleaned
                )
            )

            normalized = (
                remove_duplicate_rows(
                    normalized
                )
            )

            save_dataframe(
                normalized,
                (
                    Path(output_root)
                    / STAGES[
                        "07_normalized"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            chunk_results.append(
                {
                    "chunk_id": chunk_id,
                    "table_id": table_id,
                    "start_page": start_page,
                    "end_page": end_page,
                    "df": normalized,
                }
            )

        return {
            "chunk_id": chunk_id,
            "start_page": start_page,
            "end_page": end_page,
            "tables": chunk_results,
            "error": None,
        }

    except Exception as exc:

        return {
            "chunk_id": chunk_id,
            "start_page": start_page,
            "end_page": end_page,
            "tables": [],
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}\n"
                f"{traceback.format_exc()}"
            ),
        }


# ============================================================
# PAGE COUNT
# ============================================================

def get_page_count(
    pdf_path: str
):

    import fitz

    with fitz.open(pdf_path) as pdf:

        return len(pdf)


# ============================================================
# CHUNK CREATION
# ============================================================

def create_chunks(
    total_pages: int,
    chunk_size: int
):

    chunks = []

    chunk_id = 0

    for start in range(
        1,
        total_pages + 1,
        chunk_size
    ):

        end = min(
            start + chunk_size - 1,
            total_pages
        )

        chunks.append(
            (
                chunk_id,
                start,
                end
            )
        )

        chunk_id += 1

    return chunks


# ============================================================
# ORDER CHUNK RESULTS
# ============================================================

def order_results(
    results
):

    return sorted(
        results,
        key=lambda x: (
            x["start_page"],
            x["chunk_id"]
        )
    )


# ============================================================
# GENERIC TABLE SIMILARITY
# ============================================================

def column_similarity(
    df1,
    df2
):

    cols1 = [
        normalize_text(c)
        for c in df1.columns
    ]

    cols2 = [
        normalize_text(c)
        for c in df2.columns
    ]

    if not cols1 or not cols2:
        return 0.0

    intersection = len(
        set(cols1)
        & set(cols2)
    )

    union = len(
        set(cols1)
        | set(cols2)
    )

    if union == 0:
        return 0.0

    return intersection / union


# ============================================================
# GENERIC CONTINUATION MERGE
# ============================================================

def merge_continuations(
    tables
):

    if not tables:
        return []

    merged = []

    for item in tables:

        current = item["df"]

        if not merged:

            merged.append(
                {
                    **item
                }
            )

            continue

        previous = merged[-1]

        previous_df = (
            previous["df"]
        )

        # ----------------------------------------------------
        # Only adjacent chunks/tables are considered.
        # ----------------------------------------------------

        similarity = (
            column_similarity(
                previous_df,
                current
            )
        )

        # ----------------------------------------------------
        # Generic schema similarity.
        #
        # No domain names.
        # ----------------------------------------------------

        if (
            similarity >= 0.80
            and
            item["start_page"]
            <=
            previous["end_page"] + 1
        ):

            merged_df = pd.concat(
                [
                    previous_df,
                    current
                ],
                ignore_index=True,
                sort=False
            )

            merged[
                -1
            ]["df"] = merged_df

            merged[
                -1
            ]["end_page"] = (
                item["end_page"]
            )

        else:

            merged.append(
                {
                    **item
                }
            )

    return merged


# ============================================================
# SAVE ORDERED TABLES
# ============================================================

def save_table_collection(
    tables,
    stage_name: str
):

    stage_dir = (
        OUTPUT_ROOT
        / STAGES[stage_name]
    )

    stage_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    for index, item in enumerate(
        tables
    ):

        df = item["df"]

        filename = (
            f"table_{index:05d}"
            f"_pages_"
            f"{item['start_page']}-"
            f"{item['end_page']}.csv"
        )

        df.to_csv(
            stage_dir / filename,
            index=False
        )


# ============================================================
# EXPORT FINAL EXCEL
# ============================================================

def export_final_excel(
    tables
):

    final_dir = (
        OUTPUT_ROOT
        / STAGES["10_final"]
    )

    final_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_excel = (
        final_dir
        / "final_extracted_tables.xlsx"
    )

    with pd.ExcelWriter(
        output_excel,
        engine="openpyxl"
    ) as writer:

        combined = []

        for index, item in enumerate(
            tables
        ):

            df = item["df"].copy()

            if df.empty:
                continue

            sheet_name = (
                f"Table_{index + 1}"
            )[:31]

            df.to_excel(
                writer,
                sheet_name=sheet_name,
                index=False
            )

            annotated = df.copy()

            annotated.insert(
                0,
                "_source_end_page",
                item["end_page"]
            )

            annotated.insert(
                0,
                "_source_start_page",
                item["start_page"]
            )

            annotated.insert(
                0,
                "_table_id",
                index + 1
            )

            combined.append(
                annotated
            )

        if combined:

            all_tables = pd.concat(
                combined,
                ignore_index=True,
                sort=False
            )

            all_tables.to_excel(
                writer,
                sheet_name="ALL_TABLES",
                index=False
            )

    return output_excel


# ============================================================
# MAIN
# ============================================================

def main():

    create_stage_directories()

    pdf_path = (
        Path(INPUT_PDF)
        .resolve()
    )

    total_pages = get_page_count(
        pdf_path
    )

    print(
        f"PDF: {pdf_path}"
    )

    print(
        f"Pages: {total_pages}"
    )

    print(
        f"Workers: {MAX_WORKERS}"
    )

    print(
        f"Chunk size: {CHUNK_SIZE}"
    )

    print(
        f"Cell matching: "
        f"{DO_CELL_MATCHING}"
    )

    print(
        f"Native backend text: "
        f"{FORCE_BACKEND_TEXT}"
    )

    chunks = create_chunks(
        total_pages,
        CHUNK_SIZE
    )

    # ========================================================
    # PARALLEL PROCESSING
    # ========================================================

    results = []

    with ProcessPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for (
            chunk_id,
            start_page,
            end_page
        ) in chunks:

            future = executor.submit(
                process_chunk,
                str(pdf_path),
                chunk_id,
                start_page,
                end_page,
                str(OUTPUT_ROOT),
            )

            futures[future] = chunk_id

        for future in as_completed(
            futures
        ):

            chunk_id = futures[future]

            try:

                result = future.result()

                results.append(result)

                print(
                    f"Completed chunk "
                    f"{chunk_id}"
                )

            except Exception as exc:

                print(
                    f"Chunk {chunk_id} failed:"
                    f" {exc}"
                )

    # ========================================================
    # ORDER RESULTS
    # ========================================================

    results = order_results(
        results
    )

    # ========================================================
    # COLLECT TABLES
    # ========================================================

    tables = []

    for result in results:

        if result["error"]:

            print(
                f"\nERROR in chunk "
                f"{result['chunk_id']}"
            )

            print(
                result["error"]
            )

        tables.extend(
            result["tables"]
        )

    # ========================================================
    # STAGE 08
    # ORDERED CHUNKS
    # ========================================================

    tables = sorted(
        tables,
        key=lambda x: (
            x["start_page"],
            x["chunk_id"],
            x["table_id"],
        )
    )

    save_table_collection(
        tables,
        "08_ordered_chunks"
    )

    # ========================================================
    # STAGE 09
    # CONTINUATION MERGING
    # ========================================================

    merged_tables = (
        merge_continuations(
            tables
        )
    )

    save_table_collection(
        merged_tables,
        "09_continuation_merge"
    )

    # ========================================================
    # STAGE 10
    # FINAL
    # ========================================================

    final_excel = (
        export_final_excel(
            merged_tables
        )
    )

    print()
    print(
        "===================================="
    )
    print(
        "EXTRACTION COMPLETE"
    )
    print(
        "===================================="
    )

    print(
        f"Final Excel:"
        f" {final_excel}"
    )

    print(
        f"Intermediate outputs:"
        f" {OUTPUT_ROOT.resolve()}"
    )


if __name__ == "__main__":

    main()
```

---

# What changed from the previous version

## 1. Completely removed domain knowledge

There is now **zero knowledge** of:

```text
Description
Quantity
Price
Market Value
CUSIP
ISIN
Security
Stock
Currency
```

The parser doesn't know what any of those things mean.

It only knows:

```text
text
numeric
empty
row
column
span
header
data
```

That's what we want.

---

# 2. Header reconstruction is structural

Instead of:

```python
HEADER_ALIASES = {...}
```

we look at:

```text
text density
numeric density
row position
existing MultiIndex
repeated header values
```

For example, this:

```text
             QUANTITY        QUANTITY
             TD              SD
DESCRIPTION
```

can become:

```text
DESCRIPTION
QUANTITY TD
QUANTITY SD
```

without knowing what `QUANTITY` means.

---

# 3. Junk rows are no longer identified by names

Instead of:

```python
JUNK_PATTERNS = [...]
```

the algorithm uses the structure.

For example:

```text
SECURITY POSITIONS
COMMON STOCK
US Dollar
Exchange Rate
```

are detected as:

```text
text-heavy
numeric ratio ≈ 0
```

while:

```text
ABC COMPANY
1,000
25.32
25,320
```

is:

```text
numeric ratio > 0
```

So the latter becomes a data row.

---

# 4. More importantly: we can use Docling's structural metadata

This is something I would actually take further.

Docling's table cells expose:

```text
row_span
col_span
start_row_offset_idx
end_row_offset_idx
start_col_offset_idx
end_col_offset_idx
column_header
row_header
row_section
bbox
```

according to the current Docling API. ([Docling Project][2])

That gives us an opportunity to identify something like:

```text
┌─────────────────────────────────────────┐
│         SECURITY POSITIONS              │
└─────────────────────────────────────────┘
```

because its cell might have:

```text
col_span = 8
```

whereas a normal description cell might have:

```text
col_span = 1
```

That is **far more generic** than searching for `"SECURITY POSITIONS"`.

---

# 5. I would actually make this our next improvement

The code above already saves:

```text
01_docling_raw
```

and that raw JSON contains the span information.

So the next iteration should use the actual Docling `TableData.table_cells` directly.

Something like:

```text
TableCell
│
├── row_span
├── col_span
├── start_row
├── end_row
├── start_col
├── end_col
├── column_header
├── row_header
├── row_section
└── text
```

Then we can construct a **generic structural representation**:

```text
               TABLE
                 │
       ┌─────────┴─────────┐
       │                   │
   HEADER CELLS        BODY CELLS
       │                   │
   colspan/rowspan     numeric/text
       │                   │
       ▼                   ▼
 reconstruct           classify
 headers               rows
```

That would be considerably stronger than relying only on Pandas.

---

# Output structure

After running the code you'll get:

```text
extraction_output/
│
├── 01_docling_raw/
│   ├── chunk_00000/
│   │   └── document.json
│   ├── chunk_00001/
│   │   └── document.json
│   └── ...
│
├── 02_table_html/
│   ├── chunk_00000/
│   │   ├── table_0000.html
│   │   └── table_0001.html
│   └── ...
│
├── 03_raw_dataframe/
│   ├── chunk_00000/
│   │   ├── table_0000.csv
│   │   └── table_0001.csv
│   └── ...
│
├── 04_header_structure/
│   └── ...
│
├── 05_row_structure/
│   └── ...
│
├── 06_cleaned/
│   └── ...
│
├── 07_normalized/
│   └── ...
│
├── 08_ordered_chunks/
│   ├── table_00000_pages_1-10.csv
│   ├── table_00001_pages_11-20.csv
│   └── ...
│
├── 09_continuation_merge/
│   ├── table_00000_pages_1-20.csv
│   └── ...
│
└── 10_final/
    └── final_extracted_tables.xlsx
```

So you can literally open:

```text
03_raw_dataframe
```

and see what Docling/Pandas produced,

then:

```text
04_header_structure
```

and see what the header optimization changed,

then:

```text
05_row_structure
```

and see the generic classification,

then:

```text
06_cleaned
```

and see which rows disappeared,

then:

```text
07_normalized
```

and finally:

```text
10_final
```

---

## One important point about the current code

I **wouldn't consider this the final generic architecture yet**.

The weakest part is still:

```python
remove_structural_rows()
```

because a completely generic algorithm has a fundamental ambiguity:

```text
ABC COMPANY
INC
```

could be:

**A.** a section/title

or

**B.** a multiline description belonging to the next data row.

Without domain-specific rules, the strongest signal is **layout metadata**—especially `col_span`, `row_section`, bounding boxes, and whether the cells are marked as header/section cells. Docling exposes exactly those fields. ([Docling Project][2])

So I recommend our next version be:

**Docling `TableData` → structural cell graph → generic header/section detection → DataFrame**

rather than:

**Docling → Pandas → try to infer everything from strings.**

That will get us much closer to the genuinely **PDF/layout-agnostic extractor** you're looking for.

[1]: https://docling-project.github.io/docling/concepts/serialization/?utm_source=chatgpt.com "Serialization - Docling"
[2]: https://docling-project.github.io/docling/reference/docling_document/?utm_source=chatgpt.com "Docling Document - Docling"
