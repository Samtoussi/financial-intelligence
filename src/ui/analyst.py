"""Present completed, governed analyst text without generating new claims."""

from pathlib import Path
import re
from time import sleep as pause
from urllib.parse import urlsplit

import streamlit as st


ASSETS = Path(__file__).resolve().parents[2] / "assets"
ANALYST_AVATAR = str(ASSETS / "valentin_avatar.png")
THINKING_ART = ASSETS / "valentin_thinking.html"


def present_answer(answer: str) -> tuple[str, bool]:
    """Restyle known response fields; preserve unfamiliar prose verbatim.

    The original response remains the authority and is shown in details whenever
    technical fields are moved. Citation URLs are taken only from that response.
    """
    lines = []
    sources = {}
    details = False
    risk_analysis = False
    headings = {
        "Financial performance": "#### Financial performance",
        "SEC risk analysis": "#### Risks & business exposure",
        "SEC filing excerpts": "#### SEC filing excerpts",
    }
    if "Revenue: " in answer and "Financial performance" not in answer:
        lines.extend([headings["Financial performance"], ""])
    for line in answer.splitlines():
        if line in headings:
            lines.extend([headings[line], ""])
            risk_analysis |= line == "SEC risk analysis"
        elif line.startswith(("Chunk: ", "Accession: ", "Filed: ")):
            details = True
        elif line.startswith("Source: "):
            source = line.removeprefix("Source: ").strip()
            try:
                parsed = urlsplit(source)
            except ValueError:
                lines.append(line)
                continue
            if parsed.scheme in {"http", "https"} and parsed.netloc and not re.search(r"[\s<>\[\]()]", source):
                number = sources.setdefault(source, len(sources) + 1)
                label = "SEC filing" if parsed.hostname in {"sec.gov", "www.sec.gov"} else "Source"
                lines.extend([f"[{label} {number}]({source})", ""])
                details = True
            elif "SEC accession " in source:
                details = True
            else:
                lines.append(line)
        elif re.fullmatch(r".+ \([A-Z]+\), \d{4}", line) or line in {"MSFT", "CAT", "JPM"}:
            lines.extend([f"**{line}**", ""])
        elif line.startswith(("Revenue: ", "YoY growth: ", "Reporting period: ", "Filing: ")):
            label, value = line.split(": ", 1)
            lines.append(f"**{label}:** {value}  ")
        elif line.startswith("Source excerpt: "):
            lines.append(f"> {line.removeprefix('Source excerpt: ')}")
        elif risk_analysis and re.match(r"^\d+\. ", line):
            lines.extend(["", re.sub(r"^\d+\. ", "- ", line), ""])
        else:
            lines.append(line)
    if risk_analysis:
        lines.extend([
            "", "#### Interpreting growth implications",
            "These are AI explanations grounded in retrieved SEC excerpts, not direct quotations. "
            "They describe potential business exposure; this analysis does not quantify future "
            "growth or establish that a disclosed risk caused a revenue change.",
        ])
    return "\n".join(lines), details


def progressive_chunks(text: str):
    """Simulated reveal after validation; preserve links and bound added delay."""
    tokens = re.findall(r"\[[^\]]+\]\([^)]+\)\s*|\S+\s*|\s+", text)
    batch = max(1, (len(tokens) + 59) // 60)
    for index in range(0, len(tokens), batch):
        yield "".join(tokens[index:index + batch])
        pause(0.015)


def render_answer(answer: str, *, progressive: bool = False) -> None:
    body, details = present_answer(answer)
    if progressive:
        st.write_stream(progressive_chunks(body))
    else:
        st.markdown(body)
    if details:
        with st.expander("Sources & analysis details", expanded=False):
            st.caption("Original governed response, including source identifiers and filing metadata.")
            st.code(answer, language=None, wrap_lines=True)
