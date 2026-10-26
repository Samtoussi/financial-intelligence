
import json
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from src.analytics.financials import get_annual_financials
from src.analytics.financial_summary import format_financial_summaries
from src.ai.financial_intent import requires_financial_evidence
from src.retrieval.search_filings import search_filings

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

MODEL = "gpt-5-mini"
MAX_TOOL_ROUNDS = 3


@dataclass
class AnalysisResult:
    answer: str
    financial_evidence: list[dict]
    financial_summary: str = ""
    financial_tool_attempted: bool = False
    financial_evidence_required: bool = False
    document_evidence: list[dict] = field(default_factory=list)


TOOLS = [
    {
        "type": "function",
        "name": "get_annual_financials",
        "description": (
            "Get governed annual revenue and year-over-year growth "
            "from the local dbt Gold layer. This is the authoritative "
            "source for financial figures. Fiscal year refers to "
            "the calendar year when the reporting period ends."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "enum": ["MSFT", "CAT", "JPM"],
                },
                "fiscal_year": {"type": "integer"},
            },
            "required": ["ticker", "fiscal_year"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_filings",
        "description": (
            "Search locally indexed SEC 10-K filing passages "
            "for qualitative evidence such as business risks "
            "and management commentary. Do not use this tool "
            "to retrieve or verify revenue or growth figures. "
            "Results include filing section, source URL, "
            "chunk ID, and passage text. Search relevance "
            "does not guarantee evidential support."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Short search terms likely to occur "
                        "in a financial filing."
                    ),
                },
                "ticker": {
                    "type": "string",
                    "enum": ["MSFT", "CAT", "JPM"],
                },
                "limit": {
                    "type": "integer",
                    "enum": [1, 2, 3],
                },
            },
            "required": ["query", "ticker", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


INSTRUCTIONS = """
You are a financial analyst using governed SEC-derived data.

Financial data rules:
- Always use get_annual_financials for revenue and growth figures.
- This tool is the authoritative source for these metrics.
- Never invent revenue or growth values.
- Never calculate your own growth percentages.
- Respect the is_comparable field.
- If growth is unavailable or non-comparable, explain why.
- Distinguish financial reporting periods from SEC filing dates.
- Treat source_concept as an XBRL concept identifier.
- Do not invent accounting-standard labels.

Document retrieval rules:
- Use search_filings only for qualitative evidence, such as
  business risks and management commentary.
- Do not search filing text to verify or recalculate financial
  figures already returned by get_annual_financials.
- Search results are excerpts, not complete filings.
- Lexical relevance does not guarantee evidential support.
- Only make claims supported by retrieved passage text.
- Cite document claims with source URLs and chunk IDs.
- Do not imply that risks caused revenue changes unless
  the evidence explicitly establishes that relationship.

Tool usage rules:
- Use the minimum number of tool calls necessary.
- Multiple independent tools may be called in the same round.
- Once sufficient evidence has been retrieved, answer without
  making unnecessary additional tool calls.
- If evidence is missing or insufficient, say so clearly.

Answer style:
- Keep answers concise, factual, and readable.
- Clearly separate financial metrics from qualitative risks.
"""


def execute_tool(name: str, arguments: str):
    args = json.loads(arguments)

    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be an object")

    if name == "get_annual_financials":
        if set(args) != {"ticker", "fiscal_year"}:
            raise ValueError("Invalid financial tool arguments")

        ticker = args["ticker"]
        year = args["fiscal_year"]

        if ticker not in {"MSFT", "CAT", "JPM"}:
            raise ValueError("Unsupported ticker")

        if type(year) is not int or not 2000 <= year <= 2030:
            raise ValueError("Invalid fiscal year")

        return get_annual_financials(
            ticker=ticker,
            fiscal_year=year,
        )

    if name == "search_filings":
        if set(args) != {"query", "ticker", "limit"}:
            raise ValueError("Invalid search tool arguments")

        query = args["query"]
        ticker = args["ticker"]
        limit = args["limit"]

        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 100
        ):
            raise ValueError("Invalid search query")

        if ticker not in {"MSFT", "CAT", "JPM"}:
            raise ValueError("Unsupported ticker")

        if type(limit) is not int or limit not in {1, 2, 3}:
            raise ValueError("Invalid search limit")

        results = search_filings(
            query=query,
            ticker=ticker,
            limit=limit,
        )

        return [
            {
                "chunk_id": item["chunk_id"],
                "ticker": item["ticker"],
                "item": item["item"],
                "source_url": item["source_url"],
                "text": item["text"],
            }
            for item in results
        ]

    raise ValueError(f"Unsupported tool: {name}")


def analyze(question: str) -> AnalysisResult:
    if not question.strip():
        raise ValueError("Question cannot be empty")

    client = OpenAI(timeout=90.0, max_retries=0)

    financial_evidence = []
    document_evidence = []
    financial_tool_attempted = False
    financial_evidence_required = requires_financial_evidence(
        question
    )

    response = client.responses.create(
        model=MODEL,
        instructions=INSTRUCTIONS,
        input=question,
        tools=TOOLS,
        tool_choice="required",
        max_output_tokens=1000,
    )

    for round_number in range(MAX_TOOL_ROUNDS):
        if response.status != "completed":
            print("\n[DEBUG] Response status:", response.status)
            print(
                "[DEBUG] Incomplete details:",
                response.incomplete_details,
            )
            print("[DEBUG] Token usage:", response.usage)
            print("[DEBUG] Output items:", len(response.output))

            raise RuntimeError(
                f"Model response incomplete: {response.status}"
            )

        calls = [
            item
            for item in response.output
            if item.type == "function_call"
        ]

        if not calls:
            if not response.output_text:
                raise RuntimeError("Model returned no answer")

            return AnalysisResult(
                answer=response.output_text,
                financial_evidence=financial_evidence,
                financial_summary=format_financial_summaries(
                    financial_evidence
                ),
                financial_tool_attempted=financial_tool_attempted,
                financial_evidence_required=financial_evidence_required,
                document_evidence=document_evidence,
            )

        print(
            f"\n[TOOL ROUND {round_number + 1}] "
            f"{len(calls)} call(s)"
        )

        tool_outputs = []

        for call in calls:
            print(
                f"[TOOL CALL] {call.name}: "
                f"{call.arguments}"
            )

            if call.name == "get_annual_financials":
                financial_tool_attempted = True

            try:
                result = execute_tool(
                    call.name,
                    call.arguments,
                )
            except (ValueError, KeyError, TypeError) as exc:
                result = {"error": str(exc)}

            if (
                call.name == "get_annual_financials"
                and isinstance(result, dict)
                and "error" not in result
                and result.get("ticker") is not None
                and result.get("fiscal_year") is not None
            ):
                financial_evidence.append(result.copy())

            if (
                call.name == "search_filings"
                and isinstance(result, list)
            ):
                for item in result:
                    if (
                        isinstance(item, dict)
                        and item.get("ticker")
                        and item.get("chunk_id")
                        and item.get("source_url")
                        and item.get("text")
                    ):
                        document_evidence.append(item.copy())

            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result, default=str),
                }
            )

        response = client.responses.create(
            model=MODEL,
            instructions=INSTRUCTIONS,
            previous_response_id=response.id,
            input=tool_outputs,
            tools=TOOLS,
            tool_choice=(
                "none"
                if round_number == MAX_TOOL_ROUNDS - 1
                else "auto"
            ),
            max_output_tokens=3000,
        )

    # The final response is generated after the last tool round.
    # It must be checked outside the loop, with no further tools allowed.
    if response.status != "completed":
        raise RuntimeError(
            f"Model response incomplete: {response.status}"
        )

    if any(item.type == "function_call" for item in response.output):
        raise RuntimeError(
            "Maximum tool rounds reached without a final answer"
        )

    if not response.output_text:
        raise RuntimeError("Model returned no answer")

    return AnalysisResult(
        answer=response.output_text,
        financial_evidence=financial_evidence,
        financial_summary=format_financial_summaries(financial_evidence),
        financial_tool_attempted=financial_tool_attempted,
        financial_evidence_required=financial_evidence_required,
        document_evidence=document_evidence,
    )


def ask_analyst(question: str) -> str:
    from src.ai.response_builder import build_user_response

    result = analyze(question)
    return build_user_response(result).text


if __name__ == "__main__":
    question = (
        "Compare Microsoft's and Caterpillar's revenue growth "
        "in 2025 and explain relevant risks from their latest "
        "indexed SEC filings. Cite your sources."
    )

    print("\nQUESTION:")
    print(question)

    print("\nAI ANSWER:")
    print(ask_analyst(question))
