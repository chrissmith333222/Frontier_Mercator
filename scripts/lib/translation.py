"""
scripts/lib/translation.py

Batch translation helper for non-English news sources (Infobae/Spanish,
Jeune Afrique/French). Chris wants the News & Social Signal tab to read
in English by default, with the original still available -- "provide
the news and social signals in English with the ability to see the
translation from the native language."

Uses the Anthropic API in ONE batched tool call per ingestion run (every
headline in the batch sent together, not one API call per headline) --
headlines are short and Claude is already a project dependency, so this
avoids adding a second translation vendor/API key just for this. This is
a local/backend-only helper, called from the normalize CLI scripts
opt-in via --translate (same pattern as GDELT's --enrich-headlines),
never from the deployed Streamlit app.

Usage (as a module):
    from scripts.lib.translation import translate_batch
    english_titles = translate_batch(spanish_titles, source_language="Spanish")
"""

import os
import sys
from dotenv import load_dotenv

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

_TRANSLATE_TOOL = {
    "name": "record_translations",
    "description": "Records the English translation for each numbered headline, in order.",
    "input_schema": {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One English translation per input headline, same order as given.",
            },
        },
        "required": ["translations"],
    },
}


def _get_client(api_key: str | None = None):
    if api_key is None:
        load_dotenv()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file -- never paste it into chat."
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def translate_batch(
    texts: list[str], source_language: str, model: str = DEFAULT_MODEL, client=None,
) -> list[str]:
    """Translates a list of short headlines/titles from `source_language`
    into English in a single API call, returning translations in the same
    order as `texts`. `client` is injectable for tests (a fake with a
    matching `.messages.create(...)` surface). Defensively pads/truncates
    if the model returns a mismatched count, rather than crashing the
    whole ingestion batch over one malformed response."""
    if not texts:
        return []
    if client is None:
        client = _get_client()

    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(texts))
    response = client.messages.create(
        model=model,
        max_tokens=4000,
        system=(
            f"Translate each numbered {source_language} headline into natural, concise English. "
            f"Preserve proper nouns, names, and numbers exactly. Return exactly one translation per "
            f"input headline, in the same order, via the record_translations tool."
        ),
        tools=[_TRANSLATE_TOOL],
        tool_choice={"type": "tool", "name": "record_translations"},
        messages=[{"role": "user", "content": numbered}],
    )
    tool_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
    if not tool_blocks:
        raise RuntimeError("No tool_use block in translation response")

    translations = tool_blocks[0].input.get("translations", [])
    if len(translations) < len(texts):
        print(
            f"WARNING: translation returned {len(translations)}/{len(texts)} items -- "
            f"falling back to the original text for the missing ones.",
            file=sys.stderr,
        )
        translations = translations + texts[len(translations):]
    elif len(translations) > len(texts):
        translations = translations[:len(texts)]
    return translations
