Yes — this is a **very solvable problem without OCR or an LLM being the primary extractor**, especially because your PDF is vector-based.

The key issue is that the PDF does **not actually store the table as logical rows/cells**. It stores individual text fragments at `(x, y)` coordinates. Camelot is trying to infer the table, but it is treating every visual line inside the Description cell as a separate table row.

For your particular PDF, I would approach it as a **2-stage problem**:

> **PDF text + coordinates → reconstruct logical rows → clean/validate table**

rather than:

> PDF → Camelot → Excel

---

# 1. First understand what is actually happening

Visually, you have:

| Description                                                                  | Quantity TD | Quantity SD | Price | Market Value TD | ... |
| ---------------------------------------------------------------------------- | ----------: | ----------: | ----: | --------------: | --- |
| SIX FLAGS ENTERTAINMENT<br>CORPORATION<br>CMN<br>CUSIP: 83001C108            |       2,031 |           0 | 48.19 |       97,873.89 | ... |
| SOHO HOUSE & CO INC<br>CMN CLASS A<br>CUSIP: 586001109<br>ISIN: US5860011098 |       4,201 |       4,201 |  7.45 |       31,297.45 | ... |

But internally, the PDF is more like:

```text
SIX FLAGS ENTERTAINMENT     x=...
CORPORATION                  x=...
CMN                          x=...
CUSIP: 83001C108             x=...

2,031                        x=quantity
0                            x=quantity
48.19                        x=price
97,873.89                    x=market value
```

Each line has a different Y coordinate.

Camelot sees:

```text
row 1 = SIX FLAGS ENTERTAINMENT
row 2 = CORPORATION
row 3 = CMN
row 4 = CUSIP...
row 5 = 2,031 ...
```

when semantically you want:

```text
row 1 =
Description = "SIX FLAGS ENTERTAINMENT\nCORPORATION\nCMN\nCUSIP: 83001C108"
Quantity TD = 2031
Quantity SD = 0
Price = 48.19
...
```

So **row reconstruction** is the central problem.

---

# 2. Approaches you can take

I would divide the possible solutions into 6 approaches.

## Approach A — Tune Camelot

You can experiment with:

* `lattice`
* `stream`
* `flavor`
* `row_tol`
* `column_tol`
* `line_scale`
* `edge_tol`
* `shift_text`
* `copy_text`
* `split_text`
* `strip_text`
* table bounding boxes
* manually specifying column coordinates

### Advantage

Very easy because you're already using Camelot.

### Problem

It probably won't completely solve your case.

Why?

Because your problem isn't primarily:

> "Where is the table?"

It's:

> "Which multiple visual text lines belong to the same logical row?"

Camelot can improve this, but you'll probably end up writing substantial post-processing anyway.

---

# 3. Approach B — Camelot + custom row reconstruction

This is probably the **easiest improvement to your current implementation**.

Instead of accepting Camelot's dataframe directly:

```python
tables = camelot.read_pdf(...)
df = tables[0].df
```

you process the extracted rows.

For example:

```text
SIX FLAGS ENTERTAINMENT
CORPORATION
CMN
CUSIP: 83001C108
```

could be detected as four consecutive rows where:

```text
Quantity TD = empty
Quantity SD = empty
Price = empty
Market Value = empty
```

Then when the next row contains:

```text
2031 | 0 | 48.19 | 97873.89
```

you know that the preceding four description lines belong to that numerical row.

So:

```text
SIX FLAGS ENTERTAINMENT
CORPORATION
CMN
CUSIP: 83001C108
```

becomes one Description cell.

This works particularly well for your document because the **numeric columns provide strong row anchors**.

---

# 4. Approach C — PyMuPDF / pdfplumber + coordinates

### This is the approach I would seriously consider for production.

Instead of asking Camelot to infer the entire table, directly extract the PDF's words along with their bounding boxes.

For example with PyMuPDF:

```python
page.get_text("words")
```

gives information approximately like:

```text
[
    ("SIX", x0, y0, x1, y1, ...),
    ("FLAGS", x0, y0, x1, y1, ...),
    ("ENTERTAINMENT", x0, y0, x1, y1, ...),
    ...
]
```

You can then reconstruct the table yourself.

### Step 1 — Identify column boundaries

From your PDF you can determine approximately:

```text
Description       x = 30–250
Quantity TD       x = 250–330
Quantity SD       x = 330–400
Price             x = 400–480
Market Value TD   x = 480–600
Market Value SD   x = 600–730
...
```

Then assign every text fragment to a column according to its X coordinate.

---

# 5. Then cluster text using Y coordinates

Suppose you extract:

```text
SIX FLAGS ENTERTAINMENT   y=100
CORPORATION               y=117
CMN                       y=134
CUSIP: 83001C108          y=151

2,031                     y=151
0                         y=151
48.19                     y=151
97,873.89                 y=151
```

This is extremely useful.

You can see:

```text
Description lines:

100
117
134
151
```

while the numeric values all occur at:

```text
151
```

Therefore:

### Logical row boundary = the Y position where numeric data occurs.

You can reconstruct:

```text
Description:
SIX FLAGS ENTERTAINMENT
CORPORATION
CMN
CUSIP: 83001C108

Quantity TD:
2031

Quantity SD:
0

Price:
48.19

Market Value:
97873.89
```

This is much more deterministic than asking an LLM to figure it out.

---

# 6. Even better: use numeric columns as row anchors

Your document has an excellent property.

Almost every real security row has something like:

```text
Quantity TD
Quantity SD
Price
Market Value TD
```

while these lines:

```text
SECURITY POSITIONS (Cont.)
COMMON STOCK (Cont.)
US Dollar (Exchange Rate: 1.00000000 USD) (Cont.)
```

don't have numeric values.

So you can define:

### A real data row

Something like:

```python
has_numeric_value(row)
```

where at least one of:

```text
Quantity TD
Quantity SD
Price
Market Value TD
```

contains a number.

Then:

```text
SIX FLAGS ENTERTAINMENT
CORPORATION
CMN
CUSIP: 83001C108
```

are accumulated until the numerical row appears.

---

# 7. This also solves your unwanted rows

You mentioned:

```text
SECURITY POSITIONS (Cont.)
COMMON STOCK (Cont.)
US Dollar (Exchange Rate: 1.00000000 USD) (Cont.)
```

These aren't actual holdings.

You can filter them using a combination of:

### Rule 1

If the row contains **no numerical table values**, don't create a security row.

### Rule 2

If the row doesn't have a valid identifier:

```text
CUSIP
ISIN
```

and doesn't have quantity/price/market value, ignore it.

### Rule 3

Keep known structural/header rows separately if needed.

For example:

```python
IGNORE_PATTERNS = [
    "SECURITY POSITIONS",
    "COMMON STOCK",
    "US Dollar (Exchange Rate"
]
```

But I wouldn't rely solely on hardcoded strings.

---

# 8. Approach D — pdfplumber

Another good option is:

```text
PDF
 ↓
pdfplumber
 ↓
words + coordinates
 ↓
custom table reconstruction
 ↓
pandas
 ↓
Excel
```

`pdfplumber` is particularly useful when you want access to:

* characters
* words
* bounding boxes
* lines
* rectangles
* table structures

It can also attempt table extraction.

But for **your particular document**, I would use pdfplumber primarily for its **coordinates**, rather than blindly trusting its table extractor.

---

# 9. Approach E — Tabula

You can also try:

```text
Tabula
```

especially if the PDF has clear table boundaries.

There are two broad strategies:

```text
Tabula lattice
Tabula stream
```

Similar to Camelot.

It can sometimes produce a better initial extraction than Camelot depending on the PDF generator.

But again, your multiline-description problem may remain.

I'd consider Tabula as a **baseline**, not necessarily the final solution.

---

# 10. Approach F — LLM-based reconstruction

This is where LLMs can be very useful — but **I wouldn't use an LLM for the initial extraction**.

For example:

```text
PDF
 ↓
PyMuPDF
 ↓
raw words + coordinates
 ↓
candidate table rows
 ↓
LLM
 ↓
normalized structured JSON
 ↓
Excel
```

You could give an LLM:

```json
{
  "description_lines": [
    "SIX FLAGS ENTERTAINMENT",
    "CORPORATION",
    "CMN",
    "CUSIP: 83001C108"
  ],
  "numeric_values": [
    "2031",
    "0",
    "48.19",
    "97873.89"
  ]
}
```

and ask it to return:

```json
{
  "description": "SIX FLAGS ENTERTAINMENT\nCORPORATION\nCMN\nCUSIP: 83001C108",
  "quantity_td": 2031,
  "quantity_sd": 0,
  "price": 48.19,
  "market_value_td": 97873.89
}
```

LLMs are particularly useful for **messy variations between different PDF layouts**.

But there's an important downside.

If you're processing thousands/millions of pages, LLM cost and latency become unnecessary.

---

# 11. Approach G — Vision LLM

Another option is:

```text
PDF page
 ↓
image
 ↓
GPT/Gemini/Claude vision
 ↓
structured table
```

For example:

```text
"Extract this table into JSON"
```

This can work surprisingly well.

But I would **not make this your primary solution** for this dataset.

Problems:

* expensive
* slower
* harder to guarantee numerical accuracy
* harder to reproduce deterministically
* token/image costs
* potential hallucination
* difficult validation

For financial statements, deterministic extraction + validation is preferable.

---

# 12. Approach H — Document AI services

You could also use services such as:

* AWS Textract
* Azure Document Intelligence
* Google Document AI
* specialized table extraction APIs

Architecture:

```text
PDF
 ↓
Document AI
 ↓
Tables
 ↓
Post-processing
 ↓
Excel
```

These can be very good when PDFs vary significantly.

But if your PDFs are consistently vector-based like this one, they're probably **overkill**.

---

# 13. Approach I — Train/custom table extraction model

If you have a **large number of different PDF templates**, you could eventually build:

```text
PDF
 ↓
layout detection
 ↓
row detection
 ↓
column detection
 ↓
semantic classification
 ↓
structured table
```

using models such as:

* LayoutLM
* Table Transformer
* Detectron-based layout models
* PaddleOCR/Paddle structure
* DocTR
* custom object detection

But I wouldn't start here.

You don't appear to have a difficult OCR problem.

You have a **layout reconstruction problem**.

---

# What I would recommend for YOUR PDF

I'd rank the architectures roughly like this:

| Approach                  |    Accuracy potential |        Cost | Complexity | My take |
| ------------------------- | --------------------: | ----------: | ---------: | ------- |
| Camelot only              |                Medium |    Very low |   Very low | ❌       |
| Camelot + post-processing |                  High |    Very low |        Low | ⭐⭐⭐⭐    |
| PyMuPDF + coordinates     |             Very high |    Very low |     Medium | ⭐⭐⭐⭐⭐   |
| pdfplumber + coordinates  |             Very high |    Very low |     Medium | ⭐⭐⭐⭐    |
| Tabula + post-processing  |           Medium/High |    Very low |        Low | ⭐⭐⭐     |
| LLM after extraction      |             Very high |      Medium |     Medium | ⭐⭐⭐⭐    |
| Vision LLM                |                  High |        High | Low/Medium | ⭐⭐      |
| AWS/Azure/GCP Document AI |                  High | Medium/High |     Medium | ⭐⭐⭐     |
| Custom ML model           | Potentially very high |        High |  Very high | ⭐       |

---

# The most cost-efficient approaches

I'd divide them into three levels.

## 🥇 Cheapest: Camelot + deterministic post-processing

Keep what you already have.

```text
PDF
 ↓
Camelot
 ↓
raw dataframe
 ↓
detect numerical anchor rows
 ↓
merge description rows
 ↓
remove structural rows
 ↓
Excel
```

This is probably enough if **all PDFs have the same/similar layout**.

---

# 🥈 Best cost/accuracy: PyMuPDF + coordinates

This is the one I'd personally build if you're going to process a lot of these PDFs.

```text
                   ┌── Description text
                   │
PDF → PyMuPDF → coordinates
                   │
                   ├── Quantity TD
                   ├── Quantity SD
                   ├── Price
                   ├── Market Value
                   │
                   ↓
             Row reconstruction
                   ↓
             Validation
                   ↓
                Pandas
                   ↓
                Excel
```

No API.

No LLM.

No OCR.

Essentially **zero per-page inference cost**.

---

# 🥉 Hybrid: deterministic extraction + LLM fallback

This is probably the best **production architecture** if you expect many different PDF formats.

```text
                    PDF
                     │
                     ▼
              Vector extraction
              PyMuPDF/Camelot
                     │
                     ▼
             Deterministic parser
                     │
          ┌──────────┴──────────┐
          │                     │
       confident            uncertain
          │                     │
          ▼                     ▼
        Excel                  LLM
                                │
                                ▼
                            normalized
                                │
                                ▼
                              Excel
```

This is much better than:

```text
PDF → LLM
```

because perhaps **95–99%** of pages could be handled deterministically, and only problematic pages go to the LLM.

---

# One particularly important trick for your data

Your financial table contains a very useful validation relationship.

For example:

```text
Quantity = 2,031
Price = 48.19
```

Then:

```text
2031 × 48.19 ≈ 97,873.89
```

And indeed:

```text
2,031 × 48.19 = 97,873.89
```

That gives you an excellent **row-confidence check**.

For every extracted row:

```python
expected = quantity_td * price
actual = market_value_td

abs(expected - actual) < tolerance
```

If true:

```text
HIGH CONFIDENCE
```

If false:

```text
REVIEW / RECONSTRUCT
```

This is extremely valuable for financial PDFs.

You can similarly validate:

```text
Quantity SD × Price ≈ Market Value SD
```

For example:

```text
4,201 × 7.45 = 31,297.45
```

Exactly matching your PDF.

---

# You can make the parser almost deterministic

For your particular page, I'd implement something like:

```text
1. Extract every word with x/y coordinates

2. Determine column boundaries

3. Group words into visual lines using Y coordinates

4. Identify lines containing numeric table values

5. Treat these as "row anchors"

6. Everything in Description above the anchor
   and after the previous anchor
   belongs to this security

7. Concatenate those description lines

8. Ignore lines that:
      - have no numeric values
      - aren't associated with a security row
      - are known section/header rows

9. Extract CUSIP / ISIN

10. Validate:
      quantity × price ≈ market value

11. Export to Excel
```

For your sample, it would transform:

```text
SIX FLAGS ENTERTAINMENT
CORPORATION
CMN
CUSIP: 83001C108
2031
0
48.19
97873.89
```

into:

| Description                                                       | Qty TD | Qty SD | Price | Market Value TD |
| ----------------------------------------------------------------- | -----: | -----: | ----: | --------------: |
| SIX FLAGS ENTERTAINMENT<br>CORPORATION<br>CMN<br>CUSIP: 83001C108 |  2,031 |      0 | 48.19 |       97,873.89 |

And:

```text
SOHO HOUSE & CO INC
CMN CLASS A
CUSIP: 586001109
ISIN: US5860011098
4201
4201
7.45
31297.45
```

becomes:

| Description                                                                  | Qty TD | Qty SD | Price | Market Value TD |
| ---------------------------------------------------------------------------- | -----: | -----: | ----: | --------------: |
| SOHO HOUSE & CO INC<br>CMN CLASS A<br>CUSIP: 586001109<br>ISIN: US5860011098 |  4,201 |  4,201 |  7.45 |       31,297.45 |

---

# What I would NOT do

I wouldn't start with:

```text
PDF → OCR → LLM → Excel
```

because your PDF is vector-based.

That introduces an unnecessary OCR error layer.

I also wouldn't start with:

```text
PDF → Vision LLM → Excel
```

because you're dealing with **financial numerical data**, where deterministic extraction + arithmetic validation gives you much better control.

---

# My recommended architecture

Given the exact problem you've shown, I'd build:

```text
                    VECTOR PDF
                        │
                        ▼
                   PyMuPDF
                        │
                words + bbox
                        │
                        ▼
              Detect table region
                        │
                        ▼
             Detect column boundaries
                        │
                        ▼
              Group by Y coordinates
                        │
                        ▼
          Detect numeric/security rows
                        │
                        ▼
        Merge multiline DESCRIPTION
                        │
                        ▼
             Remove non-data rows
                        │
                        ▼
              Extract CUSIP / ISIN
                        │
                        ▼
                 DATA VALIDATION
              qty × price ≈ value
                        │
               ┌────────┴────────┐
               │                 │
            PASS              FAIL
               │                 │
               ▼                 ▼
             Excel         LLM fallback
```

### Cost

For the normal path:

**essentially ₹0/API-call cost per page.**

The only computation is local Python.

And if you later discover that 1–5% of PDFs have unusual layouts, you can send **only those pages** to an LLM.

---

## One more important point

Before changing libraries, I'd actually try to **solve your current Camelot output programmatically**.

Because your screenshot suggests Camelot has already extracted almost all the required information correctly. The problem is primarily that the **logical row structure has been lost**.

So we may not need to throw Camelot away at all.

The next useful step would be to take **the actual Camelot dataframe/Excel output from this page** and build the row-reconstruction algorithm against it. We can make it automatically produce:

```text
Description | Quantity TD | Quantity SD | Price | Market Value TD | ...
```

with the multiline descriptions merged and the unwanted `SECURITY POSITIONS`, `COMMON STOCK`, `US Dollar...` rows removed.

That would also let us test whether **Camelot + post-processing is sufficient**, before moving to PyMuPDF.
