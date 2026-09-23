from __future__ import annotations

import os
import re
import json
import traceback

from pathlib import Path
from io import StringIO
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import fitz  # PyMuPDF

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
# CONFIG
# ============================================================

INPUT_PDF = "input.pdf"

OUTPUT_ROOT = Path(
    "extraction_output"
)

CHUNK_SIZE = 10

MAX_WORKERS = min(
    4,
    os.cpu_count() or 2
)

TABLE_MODE = TableFormerMode.ACCURATE

DO_CELL_MATCHING = False

DO_OCR = False

FORCE_BACKEND_TEXT = True


# ============================================================
# GENERIC GEOMETRY PARAMETERS
#
# These are geometry parameters, NOT PDF/business-specific
# hardcoded rules.
# ============================================================

MIN_HORIZONTAL_RULE_PAGE_RATIO = 0.35

MAX_HEADER_REGION_RATIO = 0.40

HEADER_BAND_FONT_MULTIPLIER = 8.0

BOLD_FLAG = 1 << 4


# ============================================================
# OUTPUT STAGES
# ============================================================

STAGES = {
    "01_docling_raw": "01_docling_raw",
    "02_table_html": "02_table_html",
    "03_raw_dataframe": "03_raw_dataframe",
    "04_header_structure": "04_header_structure",
    "05_visual_header": "05_visual_header",
    "06_row_structure": "06_row_structure",
    "07_multiline_merge": "07_multiline_merge",
    "08_normalized": "08_normalized",
    "09_ordered_chunks": "09_ordered_chunks",
    "10_continuation_merge": "10_continuation_merge",
    "11_final": "11_final",
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
# TEXT UTILITIES
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

    return clean_text(value).lower()


# ============================================================
# NUMBER DETECTION
# ============================================================

def is_numeric(value) -> bool:

    text = clean_text(value)

    if not text:
        return False

    candidate = (
        text
        .replace(",", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("¥", "")
    )

    negative = (
        candidate.startswith("(")
        and candidate.endswith(")")
    )

    candidate = candidate.strip("()")

    # Currency / short suffixes.
    candidate = re.sub(
        r"\s+[A-Za-z]{2,5}$",
        "",
        candidate
    )

    if negative:
        candidate = "-" + candidate

    return bool(
        re.fullmatch(
            r"-?\d+(?:\.\d+)?",
            candidate
        )
    )


def numeric_ratio(row) -> float:

    values = [
        v for v in row.values
        if clean_text(v)
    ]

    if not values:
        return 0.0

    numeric = sum(
        is_numeric(v)
        for v in values
    )

    return numeric / len(values)


def text_ratio(row) -> float:

    values = [
        v for v in row.values
        if clean_text(v)
    ]

    if not values:
        return 0.0

    text_values = sum(
        not is_numeric(v)
        for v in values
    )

    return text_values / len(values)


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
# HEADER STRUCTURE
# ============================================================

def flatten_multiindex_columns(
    df
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


def detect_header_rows(
    df
):

    candidates = []

    for index in range(
        min(len(df), 8)
    ):

        row = df.iloc[index]

        nr = numeric_ratio(row)
        tr = text_ratio(row)

        if (
            tr >= 0.50
            and nr <= 0.25
        ):

            candidates.append(
                index
            )

        elif nr > 0.25:

            break

    return candidates


def reconstruct_headers(
    df
):

    if df.empty:
        return df

    df = flatten_multiindex_columns(df)

    header_rows = (
        detect_header_rows(df)
    )

    if len(header_rows) <= 1:
        return df

    new_columns = []

    for column_index in range(
        len(df.columns)
    ):

        pieces = []

        existing = clean_text(
            df.columns[column_index]
        )

        if existing:
            pieces.append(existing)

        for row_index in header_rows:

            value = clean_text(
                df.iloc[
                    row_index,
                    column_index
                ]
            )

            if not value:
                continue

            if (
                not pieces
                or normalize_text(value)
                != normalize_text(pieces[-1])
            ):

                pieces.append(value)

        new_columns.append(
            " ".join(pieces)
        )

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
# DOCLING STRUCTURAL INFORMATION
# ============================================================

def get_table_cells(
    table
):

    try:

        return list(
            table.data.table_cells
        )

    except Exception:

        return []


def build_structural_signatures(
    table
):

    """
    Build generic signatures for rows that Docling
    explicitly considers:

        - column headers
        - row sections
        - row headers
        - large spanning cells

    No domain knowledge.
    """

    cells = get_table_cells(table)

    if not cells:
        return set()

    max_col = 0

    for cell in cells:

        max_col = max(
            max_col,
            int(
                getattr(
                    cell,
                    "end_col_offset_idx",
                    0
                )
            )
        )

    total_columns = max_col + 1

    signatures = set()

    rows = {}

    for cell in cells:

        start_row = int(
            getattr(
                cell,
                "start_row_offset_idx",
                0
            )
        )

        rows.setdefault(
            start_row,
            []
        ).append(cell)

    for row_index, row_cells in rows.items():

        texts = []

        protected = False

        for cell in row_cells:

            text = clean_text(
                getattr(
                    cell,
                    "text",
                    ""
                )
            )

            if text:
                texts.append(text)

            is_column_header = bool(
                getattr(
                    cell,
                    "column_header",
                    False
                )
            )

            is_row_section = bool(
                getattr(
                    cell,
                    "row_section",
                    False
                )
            )

            is_row_header = bool(
                getattr(
                    cell,
                    "row_header",
                    False
                )
            )

            col_span = int(
                getattr(
                    cell,
                    "col_span",
                    1
                )
            )

            # Generic structural evidence.
            if (
                is_column_header
                or is_row_section
                or is_row_header
            ):

                protected = True

            # A cell spanning most/all columns is
            # structurally more likely to be a section.
            if (
                total_columns > 1
                and
                col_span
                >=
                max(
                    2,
                    int(
                        total_columns * 0.60
                    )
                )
            ):

                protected = True

        if protected and texts:

            signature = normalize_text(
                " ".join(texts)
            )

            signatures.add(
                signature
            )

    return signatures


def dataframe_row_signature(
    row
):

    return normalize_text(
        " ".join(
            clean_text(v)
            for v in row.values
            if clean_text(v)
        )
    )


# ============================================================
# VISUAL HEADER DETECTION
# ============================================================

def bbox_to_top_left(
    bbox,
    page_height
):

    if bbox is None:
        return None

    try:

        l = float(bbox.l)
        r = float(bbox.r)
        t = float(bbox.t)
        b = float(bbox.b)

        origin = str(
            getattr(
                bbox,
                "coord_origin",
                "TOPLEFT"
            )
        )

        if "BOTTOMLEFT" in origin:

            t, b = (
                page_height - b,
                page_height - t
            )

        return (
            l,
            t,
            r,
            b
        )

    except Exception:

        return None


def get_table_bbox(
    table,
    page_height
):

    try:

        prov = table.prov

        if not prov:
            return None

        return bbox_to_top_left(
            prov[0].bbox,
            page_height
        )

    except Exception:

        return None


def get_column_boxes(
    table,
    page_height
):

    """
    Obtain column geometry directly from Docling.
    """

    try:

        boxes = (
            table.data
            .get_column_bounding_boxes(
                minimal=False
            )
        )

        result = {}

        for column_index, bbox in boxes.items():

            converted = bbox_to_top_left(
                bbox,
                page_height
            )

            if converted:

                result[
                    int(column_index)
                ] = converted

        return result

    except Exception:

        return {}


def get_bold_spans(
    page
):

    spans = []

    data = page.get_text(
        "dict"
    )

    for block in data.get(
        "blocks",
        []
    ):

        if "lines" not in block:
            continue

        for line in block[
            "lines"
        ]:

            for span in line[
                "spans"
            ]:

                text = clean_text(
                    span.get(
                        "text",
                        ""
                    )
                )

                if not text:
                    continue

                flags = int(
                    span.get(
                        "flags",
                        0
                    )
                )

                font = str(
                    span.get(
                        "font",
                        ""
                    )
                )

                is_bold = (
                    bool(
                        flags
                        & BOLD_FLAG
                    )
                    or
                    bool(
                        re.search(
                            r"bold|heavy|black",
                            font,
                            re.I
                        )
                    )
                )

                if not is_bold:
                    continue

                bbox = span.get(
                    "bbox"
                )

                if not bbox:
                    continue

                spans.append(
                    {
                        "text": text,
                        "bbox": bbox,
                        "size": float(
                            span.get(
                                "size",
                                0
                            )
                        ),
                    }
                )

    return spans


def get_horizontal_rules(
    page
):

    """
    Detect long horizontal vector lines.

    No semantic knowledge.
    """

    rules = []

    drawings = page.get_drawings()

    for drawing in drawings:

        width = float(
            drawing.get(
                "width",
                1
            )
        )

        for item in drawing.get(
            "items",
            []
        ):

            if not item:
                continue

            if item[0] != "l":
                continue

            try:

                p1 = item[1]
                p2 = item[2]

                x0 = min(
                    p1.x,
                    p2.x
                )

                x1 = max(
                    p1.x,
                    p2.x
                )

                y0 = min(
                    p1.y,
                    p2.y
                )

                y1 = max(
                    p1.y,
                    p2.y
                )

                if abs(y1 - y0) > 2:
                    continue

                if x1 - x0 < 20:
                    continue

                rules.append(
                    {
                        "x0": x0,
                        "x1": x1,
                        "y": (
                            y0 + y1
                        ) / 2,
                        "width": width,
                    }
                )

            except Exception:

                continue

    return rules


def overlap_ratio(
    a0,
    a1,
    b0,
    b1
):

    overlap = max(
        0,
        min(a1, b1)
        - max(a0, b0)
    )

    denom = max(
        1e-9,
        min(
            a1 - a0,
            b1 - b0
        )
    )

    return overlap / denom


def detect_visual_headers(
    pdf_path,
    page_number,
    table
):

    """
    Detect header text by combining:

        1. bold PDF text
        2. horizontal rules
        3. table bounding box
        4. Docling column geometry

    This is intentionally semantic-free.
    """

    try:

        with fitz.open(
            pdf_path
        ) as pdf:

            if page_number < 0:
                return {}

            if page_number >= len(pdf):
                return {}

            page = pdf[
                page_number
            ]

            page_height = page.rect.height

            table_bbox = (
                get_table_bbox(
                    table,
                    page_height
                )
            )

            column_boxes = (
                get_column_boxes(
                    table,
                    page_height
                )
            )

            if not column_boxes:
                return {}

            if table_bbox is None:

                table_bbox = (
                    0,
                    0,
                    page.rect.width,
                    page.rect.height
                )

            table_l, table_t, table_r, table_b = (
                table_bbox
            )

            table_width = (
                table_r - table_l
            )

            table_height = (
                table_b - table_t
            )

            if table_width <= 0:
                return {}

            bold_spans = (
                get_bold_spans(
                    page
                )
            )

            rules = (
                get_horizontal_rules(
                    page
                )
            )

            # Only long rules inside the table.
            candidate_rules = []

            for rule in rules:

                x_overlap = (
                    max(
                        0,
                        min(
                            rule["x1"],
                            table_r
                        )
                        -
                        max(
                            rule["x0"],
                            table_l
                        )
                    )
                )

                if (
                    x_overlap
                    <
                    table_width
                    *
                    MIN_HORIZONTAL_RULE_PAGE_RATIO
                ):
                    continue

                relative_y = (
                    rule["y"] - table_t
                ) / max(
                    table_height,
                    1
                )

                if (
                    relative_y
                    <
                    0
                    or
                    relative_y
                    >
                    MAX_HEADER_REGION_RATIO
                ):
                    continue

                candidate_rules.append(
                    rule
                )

            if not candidate_rules:
                return {}

            # Estimate typical font size.
            sizes = [
                s["size"]
                for s in bold_spans
                if s["size"] > 0
            ]

            median_size = (
                sorted(sizes)[
                    len(sizes) // 2
                ]
                if sizes
                else 8.0
            )

            header_band = (
                median_size
                *
                HEADER_BAND_FONT_MULTIPLIER
            )

            best = None
            best_score = -1

            for rule in candidate_rules:

                candidates = []

                for span in bold_spans:

                    x0, y0, x1, y1 = (
                        span["bbox"]
                    )

                    # Text must be above the rule.
                    if y1 > rule["y"] + 2:
                        continue

                    if (
                        rule["y"] - y1
                        >
                        header_band
                    ):
                        continue

                    # Text should overlap table.
                    if (
                        x1 < table_l
                        or
                        x0 > table_r
                    ):
                        continue

                    candidates.append(
                        span
                    )

                if not candidates:
                    continue

                character_count = sum(
                    len(
                        s["text"]
                    )
                    for s in candidates
                )

                x_min = min(
                    s["bbox"][0]
                    for s in candidates
                )

                x_max = max(
                    s["bbox"][2]
                    for s in candidates
                )

                coverage = (
                    max(
                        0,
                        x_max - x_min
                    )
                    /
                    max(
                        table_width,
                        1
                    )
                )

                # Generic score.
                score = (
                    character_count
                    *
                    max(
                        coverage,
                        0.1
                    )
                    *
                    max(
                        rule["x1"]
                        - rule["x0"],
                        1
                    )
                    /
                    max(
                        table_width,
                        1
                    )
                )

                if score > best_score:

                    best_score = score

                    best = (
                        rule,
                        candidates
                    )

            if best is None:
                return {}

            _, candidates = best

            result = {}

            # ------------------------------------------------
            # Map bold text to columns by geometry.
            # ------------------------------------------------

            for span in candidates:

                sx0, _, sx1, _ = (
                    span["bbox"]
                )

                text = span["text"]

                overlapping_columns = []

                for col_index, box in (
                    column_boxes.items()
                ):

                    cx0, _, cx1, _ = box

                    overlap = (
                        overlap_ratio(
                            sx0,
                            sx1,
                            cx0,
                            cx1
                        )
                    )

                    if overlap >= 0.15:

                        overlapping_columns.append(
                            col_index
                        )

                if not overlapping_columns:

                    center = (
                        sx0 + sx1
                    ) / 2

                    nearest = min(
                        column_boxes,
                        key=lambda c:
                        abs(
                            (
                                column_boxes[c][0]
                                +
                                column_boxes[c][2]
                            ) / 2
                            -
                            center
                        )
                    )

                    overlapping_columns = [
                        nearest
                    ]

                for col in (
                    overlapping_columns
                ):

                    result.setdefault(
                        col,
                        []
                    ).append(
                        (
                            span["bbox"][1],
                            text
                        )
                    )

            # Sort by vertical position and
            # concatenate header levels.
            for col in result:

                result[col] = (
                    " ".join(
                        text
                        for _, text
                        in sorted(
                            result[col],
                            key=lambda x:
                            x[0]
                        )
                    )
                )

            return result

    except Exception:

        return {}


# ============================================================
# APPLY VISUAL HEADER
# ============================================================

def apply_visual_headers(
    df,
    visual_headers
):

    if df.empty:
        return df

    if not visual_headers:
        return df

    output = df.copy()

    new_columns = []

    for index, existing in enumerate(
        output.columns
    ):

        visual = clean_text(
            visual_headers.get(
                index,
                ""
            )
        )

        existing = clean_text(
            existing
        )

        if visual:

            # Visual PDF structure gets priority.
            new_columns.append(
                visual
            )

        else:

            new_columns.append(
                existing
            )

    output.columns = (
        normalize_column_names(
            new_columns
        )
    )

    return output


# ============================================================
# ROW STRUCTURE
# ============================================================

def analyze_rows(
    df
):

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

    output["_row_type"] = (
        output.apply(
            lambda row:
            (
                "empty"
                if row["_nonempty_count"] == 0
                else
                "data"
                if row["_numeric_ratio"] >= 0.25
                else
                "text"
            ),
            axis=1
        )
    )

    return output


# ============================================================
# MULTILINE ROW MERGE
# ============================================================

def merge_multiline_rows(
    df,
    protected_signatures=None
):

    """
    Core fix for:

        DESCRIPTION TEXT
        DESCRIPTION CONTINUATION | 2,031

    ->

        DESCRIPTION TEXT DESCRIPTION CONTINUATION | 2,031

    Generic structural approach:

        - text-only row
        - followed by numeric/data row
        - same first occupied column
        - not a Docling structural/header row

    Also handles:

        data row
        continuation text row

    without knowing what the text means.
    """

    if df.empty:
        return df

    protected_signatures = (
        protected_signatures
        or set()
    )

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

    if working.empty:
        return working

    rows = [
        row.copy()
        for _, row
        in working.iterrows()
    ]

    result = []

    pending = []

    def first_nonempty_column(
        row
    ):

        for col in data_columns:

            if clean_text(
                row[col]
            ):

                return col

        return None

    def row_is_protected(
        row
    ):

        signature = (
            dataframe_row_signature(
                row
            )
        )

        return (
            signature
            in protected_signatures
        )

    def append_text(
        target,
        text,
        column
    ):

        current = clean_text(
            target[column]
        )

        text = clean_text(
            text
        )

        if not text:
            return

        if current:

            target[column] = (
                current
                + " "
                + text
            )

        else:

            target[column] = text

    i = 0

    while i < len(rows):

        row = rows[i]

        if row_is_protected(row):

            # Protected structural row.
            #
            # Never merge it into a data row.
            result.append(row)

            i += 1

            continue

        nonempty = [
            (
                col,
                clean_text(
                    row[col]
                )
            )
            for col in data_columns
            if clean_text(
                row[col]
            )
        ]

        numeric_values = [
            value
            for _, value in nonempty
            if is_numeric(value)
        ]

        # ----------------------------------------------------
        # Text-only row
        # ----------------------------------------------------

        if not numeric_values:

            first_col = (
                nonempty[0][0]
                if nonempty
                else None
            )

            # Check whether the next row is a data row.
            if i + 1 < len(rows):

                next_row = rows[i + 1]

                if not row_is_protected(
                    next_row
                ):

                    next_nonempty = [
                        (
                            col,
                            clean_text(
                                next_row[col]
                            )
                        )
                        for col in data_columns
                        if clean_text(
                            next_row[col]
                        )
                    ]

                    next_numeric = [
                        value
                        for _, value
                        in next_nonempty
                        if is_numeric(value)
                    ]

                    next_first_col = (
                        next_nonempty[0][0]
                        if next_nonempty
                        else None
                    )

                    # ----------------------------------------
                    # EXACT PATTERN FROM YOUR PDF
                    # ----------------------------------------

                    if (
                        next_numeric
                        and
                        first_col
                        == next_first_col
                    ):

                        text = " ".join(
                            value
                            for _, value
                            in nonempty
                        )

                        pending.append(
                            (
                                first_col,
                                text
                            )
                        )

                        i += 1

                        continue

            # ------------------------------------------------
            # Text-only row AFTER a data row.
            # ------------------------------------------------

            if result:

                previous = result[-1]

                previous_numeric = any(
                    is_numeric(
                        previous[col]
                    )
                    for col in data_columns
                    if clean_text(
                        previous[col]
                    )
                )

                previous_col = (
                    first_nonempty_column(
                        previous
                    )
                )

                if (
                    previous_numeric
                    and
                    first_col
                    ==
                    previous_col
                ):

                    text = " ".join(
                        value
                        for _, value
                        in nonempty
                    )

                    append_text(
                        previous,
                        text,
                        first_col
                    )

                    i += 1

                    continue

            # ------------------------------------------------
            # Ordinary text row.
            # ------------------------------------------------

            result.append(row)

            i += 1

            continue

        # ====================================================
        # DATA ROW
        # ====================================================

        current = row.copy()

        # Merge all pending preceding continuation text.
        for (
            pending_column,
            pending_text
        ) in pending:

            target_column = (
                first_nonempty_column(
                    current
                )
            )

            if target_column is None:
                target_column = (
                    pending_column
                )

            append_text(
                current,
                pending_text,
                target_column
            )

        pending = []

        result.append(
            current
        )

        i += 1

    # If anything remains pending, retain it rather
    # than silently dropping document content.
    for (
        pending_column,
        pending_text
    ) in pending:

        new_row = {
            col: ""
            for col in data_columns
        }

        new_row[
            pending_column
        ] = pending_text

        result.append(
            pd.Series(new_row)
        )

    return pd.DataFrame(
        result,
        columns=data_columns
    ).reset_index(
        drop=True
    )


# ============================================================
# NORMALIZATION
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
    df
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

    return (
        output
        .drop_duplicates()
        .reset_index(drop=True)
    )


# ============================================================
# DOCLING
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
# SAVE
# ============================================================

def save_dataframe(
    df,
    path
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
# PROCESS CHUNK
# ============================================================

def process_chunk(
    pdf_path,
    chunk_id,
    start_page,
    end_page,
    output_root
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
        # ====================================================

        raw_dir = (
            Path(output_root)
            / STAGES[
                "01_docling_raw"
            ]
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
            encoding="utf-8"
        ) as f:

            json.dump(
                raw_json,
                f,
                ensure_ascii=False,
                indent=2
            )

        # ====================================================
        # TABLES
        # ====================================================

        for table_id, table in enumerate(
            result.document.tables
        ):

            table_key = (
                f"table_{table_id:04d}"
            )

            # ------------------------------------------------
            # STAGE 02
            # ------------------------------------------------

            html = (
                table.export_to_html(
                    doc=result.document
                )
            )

            html_dir = (
                Path(output_root)
                / STAGES[
                    "02_table_html"
                ]
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
                encoding="utf-8"
            ) as f:

                f.write(html)

            # ------------------------------------------------
            # STAGE 03
            # ------------------------------------------------

            dataframes = pd.read_html(
                StringIO(html)
            )

            if not dataframes:
                continue

            df = dataframes[0]

            save_dataframe(
                df,
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
            # STRUCTURAL SIGNATURES
            # ------------------------------------------------

            protected_signatures = (
                build_structural_signatures(
                    table
                )
            )

            # ------------------------------------------------
            # STAGE 04
            # STRUCTURAL HEADER
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
            # PAGE NUMBER
            # ------------------------------------------------

            page_number = None

            try:

                if table.prov:

                    page_number = int(
                        table.prov[
                            0
                        ].page_no
                    )

                    # Docling provenance is commonly
                    # 1-based for PDF pages.
                    page_number -= 1

            except Exception:

                page_number = None

            # ------------------------------------------------
            # STAGE 05
            # VISUAL HEADER
            # ------------------------------------------------

            visual_headers = {}

            if page_number is not None:

                visual_headers = (
                    detect_visual_headers(
                        pdf_path,
                        page_number,
                        table
                    )
                )

            visual_df = (
                apply_visual_headers(
                    header_df,
                    visual_headers
                )
            )

            save_dataframe(
                visual_df,
                (
                    Path(output_root)
                    / STAGES[
                        "05_visual_header"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            # ------------------------------------------------
            # STAGE 06
            # ROW STRUCTURE
            # ------------------------------------------------

            analyzed = (
                analyze_rows(
                    visual_df
                )
            )

            save_dataframe(
                analyzed,
                (
                    Path(output_root)
                    / STAGES[
                        "06_row_structure"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            # ------------------------------------------------
            # STAGE 07
            # MULTILINE ROW MERGE
            # ------------------------------------------------

            merged_rows = (
                merge_multiline_rows(
                    analyzed,
                    protected_signatures
                )
            )

            save_dataframe(
                merged_rows,
                (
                    Path(output_root)
                    / STAGES[
                        "07_multiline_merge"
                    ]
                    / f"chunk_{chunk_id:05d}"
                    / f"{table_key}.csv"
                )
            )

            # ------------------------------------------------
            # STAGE 08
            # NORMALIZATION
            # ------------------------------------------------

            normalized = (
                normalize_dataframe(
                    merged_rows
                )
            )

            save_dataframe(
                normalized,
                (
                    Path(output_root)
                    / STAGES[
                        "08_normalized"
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
# PAGE / CHUNK MANAGEMENT
# ============================================================

def get_page_count(
    pdf_path
):

    with fitz.open(
        pdf_path
    ) as pdf:

        return len(pdf)


def create_chunks(
    total_pages,
    chunk_size
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
# ORDERING
# ============================================================

def save_table_collection(
    tables,
    stage_name
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

        filename = (
            f"table_{index:05d}"
            f"_pages_"
            f"{item['start_page']}-"
            f"{item['end_page']}.csv"
        )

        item["df"].to_csv(
            stage_dir / filename,
            index=False
        )


# ============================================================
# CONTINUATION TABLE MERGE
# ============================================================

def column_similarity(
    df1,
    df2
):

    c1 = {
        normalize_text(c)
        for c in df1.columns
    }

    c2 = {
        normalize_text(c)
        for c in df2.columns
    }

    if not c1 or not c2:
        return 0

    return (
        len(c1 & c2)
        /
        len(c1 | c2)
    )


def merge_continuations(
    tables
):

    if not tables:
        return []

    merged = []

    for item in tables:

        if not merged:

            merged.append(
                {
                    **item
                }
            )

            continue

        previous = merged[-1]

        similarity = (
            column_similarity(
                previous["df"],
                item["df"]
            )
        )

        if (
            similarity >= 0.80
            and
            item["start_page"]
            <=
            previous["end_page"] + 1
        ):

            previous["df"] = pd.concat(
                [
                    previous["df"],
                    item["df"]
                ],
                ignore_index=True,
                sort=False
            )

            previous["end_page"] = (
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
# FINAL EXCEL
# ============================================================

def export_final_excel(
    tables
):

    final_dir = (
        OUTPUT_ROOT
        / STAGES["11_final"]
    )

    final_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output = (
        final_dir
        / "final_extracted_tables.xlsx"
    )

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        all_tables = []

        for index, item in enumerate(
            tables
        ):

            df = item["df"]

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

            all_tables.append(
                annotated
            )

        if all_tables:

            combined = pd.concat(
                all_tables,
                ignore_index=True,
                sort=False
            )

            combined.to_excel(
                writer,
                sheet_name="ALL_TABLES",
                index=False
            )

    return output


# ============================================================
# MAIN
# ============================================================

def main():

    create_stage_directories()

    pdf_path = (
        Path(INPUT_PDF)
        .resolve()
    )

    total_pages = (
        get_page_count(
            pdf_path
        )
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
                str(OUTPUT_ROOT)
            )

            futures[future] = chunk_id

        for future in as_completed(
            futures
        ):

            chunk_id = futures[
                future
            ]

            try:

                result = (
                    future.result()
                )

                results.append(
                    result
                )

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
    # ORDER CHUNKS
    # ========================================================

    results = sorted(
        results,
        key=lambda x: (
            x["start_page"],
            x["chunk_id"]
        )
    )

    # ========================================================
    # COLLECT TABLES
    # ========================================================

    tables = []

    for result in results:

        if result["error"]:

            print(
                f"\nERROR:"
                f" {result['error']}"
            )

        tables.extend(
            result["tables"]
        )

    tables = sorted(
        tables,
        key=lambda x: (
            x["start_page"],
            x["chunk_id"],
            x["table_id"]
        )
    )

    # ========================================================
    # STAGE 09
    # ========================================================

    save_table_collection(
        tables,
        "09_ordered_chunks"
    )

    # ========================================================
    # STAGE 10
    # ========================================================

    merged_tables = (
        merge_continuations(
            tables
        )
    )

    save_table_collection(
        merged_tables,
        "10_continuation_merge"
    )

    # ========================================================
    # STAGE 11
    # ========================================================

    final_file = (
        export_final_excel(
            merged_tables
        )
    )

    print()
    print(
        "======================================"
    )
    print(
        "EXTRACTION COMPLETE"
    )
    print(
        "======================================"
    )

    print(
        f"Final file:"
        f" {final_file}"
    )

    print(
        f"Intermediate:"
        f" {OUTPUT_ROOT.resolve()}"
    )


if __name__ == "__main__":

    main()
