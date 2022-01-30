# The following code is based on cli/pawls/preprocessors/pdfplumber.py
# in https://github.com/allenai/pawls, copyright Allen Institute for
# Artificial Intelligence and PAWLS contributors, licensed under the
# Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0).

import pdfplumber
import pandas as pd


def preprocess_with_pdfplumber(pdf_path):
    # For PAWLS export, this aims to replicate process_pdfplumber() in
    # https://github.com/allenai/pawls cli/pawls/preprocessors/pdfplumber.py
    # If that implementation changes, this code should be updated to match.

    pdf = pdfplumber.open(pdf_path)

    page_dicts = []
    for page_idx, page in enumerate(pdf.pages):
        page_dicts.append({
            'page': {
                'width': float(page.width),
                'height': float(page.height),
                'index': page_idx,
            },
            'tokens': get_word_tokens(page)
        })
    return page_dicts


def get_word_tokens(page):
    # For PAWLS export, this aims to replicate obtain_word_tokens() in
    # https://github.com/allenai/pawls cli/pawls/preprocessors/pdfplumber.py
    # If that implementation changes, this code should be updated to match.
    words = page.extract_words(
        x_tolerance=1.5,
        y_tolerance=3,
        keep_blank_chars=False,
        use_text_flow=True,
        horizontal_ltr=True,
        vertical_ttb=True,
        extra_attrs=["fontname", "size"],
    )
    if len(words) == 0:
        return []

    df = pd.DataFrame(words)

    # Avoid boxes outside the page
    df[["x0", "x1"]] = (
        df[["x0", "x1"]].clip(
            lower=0, upper=int(page.width)).astype("float")
    )
    df[["top", "bottom"]] = (
        df[["top", "bottom"]].clip(
            lower=0, upper=int(page.height)).astype("float")
    )

    df["height"] = df["bottom"] - df["top"]
    df["width"] = df["x1"] - df["x0"]

    tokens = df.apply(row_to_token_dict, axis=1).tolist()
    return tokens


def row_to_token_dict(row):
    return {
        'text': row["text"],
        'x': row["x0"],
        'y': row["top"],
        'width': row["width"],
        'height': row["height"],
    }
